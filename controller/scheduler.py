"""Durable, single-owner timers. Missed or uncertain sends are never replayed."""
import hashlib
import json
import math
import re
import time

from .core import ControlError

COOL = {'action': 'climate', 'mode': 'cool', 'temperature': 24, 'fan': 'high'}
DRY = {'action': 'climate', 'mode': 'dry', 'temperature': 24, 'fan': 'auto'}
OFF = {'action': 'button', 'button': 'power-off'}
GRACE_SECONDS = 30


class Scheduler:
    def __init__(self, controller, clock=time.time):
        self.controller, self.clock = controller, clock
        self.lock = controller.lock
        with controller.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, kind TEXT NOT NULL,
                phase TEXT NOT NULL, payload TEXT NOT NULL, due_at REAL NOT NULL,
                created_at REAL NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL)''')
            db.execute("UPDATE schedules SET status='unknown', message=? WHERE status='running'",
                       ('服务曾中断，执行结果未确认；不会自动重发。',))
            # Startup never transmits, including recently overdue tasks.
            db.execute("UPDATE schedules SET status='missed', message=? WHERE status='pending' AND due_at<=?",
                       ('服务离线期间已到点，本次未补发。', clock()))

    def get(self, job_id):
        with self.controller.db() as db:
            row = db.execute('SELECT * FROM schedules WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise ControlError('找不到这条定时任务。', 404)
        return self.public(row)

    @staticmethod
    def public(row):
        job = dict(row)
        job.pop('fingerprint')
        job['payload'] = json.loads(job['payload'])
        return job

    def list(self):
        with self.controller.db() as db:
            rows = db.execute("SELECT * FROM schedules ORDER BY (status IN ('pending','running')) DESC, created_at DESC LIMIT 24").fetchall()
        return [self.public(row) for row in rows]

    def _update(self, job_id, status, message):
        with self.controller.db() as db:
            db.execute('UPDATE schedules SET status=?, message=? WHERE id=?', (status, message, job_id))

    def create(self, request_id, body):
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id or ''):
            raise ControlError('缺少有效的操作编号。', 400)
        if not isinstance(body, dict) or body.get('kind') not in ('timer', 'precool'):
            raise ControlError('不支持的定时任务。', 422)
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.lock:
            with self.controller.db() as db:
                old = db.execute('SELECT * FROM schedules WHERE id=?', (request_id,)).fetchone()
                if old:
                    if old['fingerprint'] != fingerprint:
                        raise ControlError('操作编号已用于另一条任务。', 409)
                    return self.public(old)
                active = db.execute("SELECT kind FROM schedules WHERE status IN ('pending','running')").fetchall()
            if len(active) >= 12:
                raise ControlError('最多保留 12 个待执行任务，请先取消不需要的任务。', 409)
            stamp, kind = self.clock(), body['kind']
            if kind == 'precool':
                if set(body) != {'kind'}:
                    raise ControlError('预制冷使用固定的两阶段设置。', 422)
                if any(row['kind'] == 'precool' for row in active):
                    raise ControlError('预制冷已经在进行中。', 409)
                if time.monotonic() < self.controller.cooldown_until:
                    raise ControlError('上一条指令刚发送，请等倒计时结束。', 429)
                payload, due, phase, status = COOL, stamp, 'cool', 'running'
            else:
                if set(body) != {'kind', 'due_at', 'payload'}:
                    raise ControlError('需要执行时间和开关机设定。', 422)
                due, payload = body['due_at'], body['payload']
                if type(due) not in (int, float) or not math.isfinite(due) or not stamp + 5 <= due <= stamp + 30 * 86400:
                    raise ControlError('请选择 5 秒后至 30 天内的执行时间。', 422)
                if not isinstance(payload, dict):
                    raise ControlError('定时任务只能设置开机或关机。', 422)
                if payload.get('action') == 'climate':
                    if set(payload) != set(COOL):
                        raise ControlError('开机设定格式不正确。', 422)
                    self.controller.climate(payload)
                elif payload != OFF:
                    raise ControlError('定时任务只能设置开机或关机。', 422)
                phase, status = 'timer', 'pending'
            with self.controller.db() as db:
                db.execute('INSERT INTO schedules VALUES (?,?,?,?,?,?,?,?,?)',
                           (request_id, fingerprint, kind, phase, json.dumps(payload), due, stamp, status,
                            '正在开始预制冷。' if kind == 'precool' else '等待执行。'))
            if kind == 'precool':
                self._run(self.get(request_id))
            return self.get(request_id)

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job['status'] == 'pending':
                self._update(job_id, 'cancelled', '已取消后续执行；空调保持当前设定。')
            return self.get(job_id)

    def _cancel_precool(self, message):
        with self.controller.db() as db:
            db.execute("UPDATE schedules SET status='cancelled', message=? WHERE kind='precool' AND status='pending'", (message,))

    def manual(self, request_id, payload):
        with self.lock:
            # A duplicate receipt must not cancel a newly started routine.
            with self.controller.db() as db:
                existing = db.execute('SELECT 1 FROM commands WHERE id=?', (request_id,)).fetchone()
            if not existing:
                if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id or ''):
                    raise ControlError('缺少有效的操作编号。', 400)
                self.controller.plan(payload, self.controller.state()['state'])
                if time.monotonic() < self.controller.cooldown_until:
                    raise ControlError('上一条指令刚发送，请等倒计时结束。', 429)
                # Persist the override before sending, even if the process then crashes.
                self._cancel_precool('手动控制已结束预制冷，后续除湿切换已取消。')
            return self.controller.execute(request_id, payload)

    def tick(self):
        with self.lock:
            stamp = self.clock()
            with self.controller.db() as db:
                db.execute("UPDATE schedules SET status='missed', message=? WHERE status='pending' AND due_at<?",
                           ('已错过执行时间，本次未补发。', stamp - GRACE_SECONDS))
                row = db.execute("SELECT * FROM schedules WHERE status='pending' AND due_at<=? ORDER BY due_at,created_at LIMIT 1", (stamp,)).fetchone()
            if row is None or time.monotonic() < self.controller.cooldown_until:
                return
            self._update(row['id'], 'running', '正在执行。')
            self._run(self.public(row))

    def _run(self, job):
        job_id = job['id']
        if job['kind'] == 'timer':
            self._cancel_precool('定时开关机已接管，后续预制冷切换已取消。')
        command_id = 'schedule_' + hashlib.sha256((job_id + ':' + job['phase']).encode()).hexdigest()
        try:
            result = self.controller.execute(command_id, job['payload'])
        except ControlError as exc:
            self._update(job_id, 'unknown' if exc.uncertain else 'failed', str(exc) + ' 不会自动重试。')
            return
        except Exception:
            self._update(job_id, 'unknown', '执行中断，结果未确认；不会自动重发。')
            return
        if result['status'] != 'sent':
            self._update(job_id, result['status'] if result['status'] in ('failed', 'unknown') else 'unknown',
                         result.get('message', '执行结果未确认。') + ' 不会自动重发。')
            if job['kind'] == 'timer' and result['status'] == 'unknown':
                self._cancel_precool('定时控制结果未确认，已取消后续预制冷切换。')
            return
        if job['kind'] == 'precool' and job['phase'] == 'cool':
            with self.controller.db() as db:
                db.execute("UPDATE schedules SET phase='dry', payload=?, due_at=?, status='pending', message=? WHERE id=?",
                           (json.dumps(DRY), self.clock() + 600, '制冷 24°C 大风指令已发送，10 分钟后切换除湿。', job_id))
        else:
            self._update(job_id, 'completed', '除湿 24°C 指令已发送。' if job['kind'] == 'precool' else '定时指令已发送。')
            if job['kind'] == 'timer':
                self._cancel_precool('定时开关机已执行，后续预制冷切换已取消。')
