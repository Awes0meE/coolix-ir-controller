"""Single-owner serial control, durable command receipts, and estimated state."""
import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from coolix_states import encode

COMMAND_INTERVAL_SECONDS = 2.0


class ControlError(Exception):
    def __init__(self, message, status=409, uncertain=False):
        super().__init__(message)
        self.status, self.uncertain = status, uncertain


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


class SerialBoard:
    def __init__(self, port, expected_tag):
        self.port, self.expected_tag = port, expected_tag
        self.handle = None
        self.lock = threading.RLock()
        self.info = {'online': False, 'last_seq': 0, 'error': '正在连接控制器'}

    def _status_line(self, line):
        if not line.startswith('STATUS '):
            return False
        fields = dict(re.findall(r'(\w+)=([^ ]+)', line))
        if fields.get('catalog') != self.expected_tag:
            raise ControlError('UNO 按键目录与服务不一致，请重新上传对应程序。', 503)
        self.info = {'online': True, 'last_seq': int(fields.get('last_seq', '0')),
                     'uptime_ms': int(fields.get('uptime_ms', '0')),
                     'catalog': fields['catalog'], 'd3': fields.get('D3'),
                     'min_interval_ms': int(fields['min_interval_ms']) if 'min_interval_ms' in fields else None,
                     'error': None}
        return True

    def _read(self):
        return self.handle.readline().decode('ascii', errors='replace').strip()

    def _close(self, message):
        if self.handle:
            try:
                self.handle.close()
            except Exception:
                pass
        self.handle = None
        self.info.update(online=False, error=message)

    def connect(self):
        with self.lock:
            if self.handle is not None:
                return
            import serial
            try:
                self.handle = serial.Serial(self.port, 115200, timeout=.15, write_timeout=1, exclusive=True)
                # Opening the UNO can reset it. Boot never transmits; only query status.
                time.sleep(2)
                self.handle.reset_input_buffer()
                self.handle.write(b'STATUS\n')
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if self._status_line(self._read()):
                        return
                raise RuntimeError('No matching UNO status')
            except Exception:
                self._close('控制器离线，请检查 Mac 与 UNO 的 USB 连接。')
                raise ControlError(self.info['error'], 503)

    def status(self):
        with self.lock:
            try:
                self.connect()
                self.handle.write(b'STATUS\n')
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if self._status_line(self._read()):
                        return dict(self.info)
                raise RuntimeError('Status timeout')
            except Exception:
                self._close('控制器离线，请检查 Mac 与 UNO 的 USB 连接。')
                return dict(self.info)

    def send(self, command, sequence):
        with self.lock:
            self.connect()
            attempted = False
            lines, done = [], False
            try:
                attempted = True  # A partial OS write may already reach the board.
                self.handle.write((command + '\n').encode('ascii'))
                self.handle.flush()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    line = self._read()
                    if not line:
                        continue
                    lines.append(line)
                    if line.startswith('REJECTED'):
                        raise ControlError('控制器拒绝本次指令，请稍后再操作。', 409)
                    if line.startswith('BOOT '):
                        raise RuntimeError('Board reset during transmission')
                    if line == f'TX_DONE seq={sequence}':
                        done = True
                    if self._status_line(line) and done and self.info['last_seq'] == sequence and self.info['d3'] == 'LOW':
                        return {'sequence': sequence, 'lines': lines, 'board': dict(self.info)}
                raise RuntimeError('No complete transmission receipt')
            except ControlError:
                raise
            except Exception:
                self._close('连接中断，无法确认这次发送结果。')
                raise ControlError('发送结果未确认，请先观察空调；系统不会自动重发。', 503, uncertain=attempted)


class Controller:
    def __init__(self, data_dir, board):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.data_dir / 'controller.sqlite3'
        self.board = board
        self.lock = threading.RLock()
        self.cooldown_until = 0.0
        self.index = json.loads((ROOT / 'captures/york-replay-index.json').read_text())
        self.buttons = {b['id']: b for b in self.index['buttons']}
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    created TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
            ''')
            interrupted = db.execute("UPDATE commands SET status='unknown', response=? WHERE status='pending'",
                       (json.dumps({'status': 'unknown', 'message': '服务重启，先前发送结果未确认；不会自动重试。'}, ensure_ascii=False),))
            if interrupted.rowcount:
                row = db.execute("SELECT value FROM meta WHERE key='state'").fetchone()
                if row:
                    state = json.loads(row[0])
                    state['confidence'] = 'unknown'
                    db.execute("UPDATE meta SET value=? WHERE key='state'", (json.dumps(state),))
            if not db.execute("SELECT 1 FROM meta WHERE key='state'").fetchone():
                seed = {'power': None, 'mode': 'cool', 'temperature': 24, 'fan': 'high',
                        'sleep': None, 'silence': None, 'turbo': None, 'led': None,
                        'horizontal_swing': None, 'vertical_steps': 0,
                        'last_sent_at': None, 'confidence': 'unknown', 'last_action': '尚未通过网页发送'}
                db.execute('INSERT INTO meta VALUES (?,?)', ('state', json.dumps(seed, ensure_ascii=False)))
        self.db_path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self):
        with self.db() as db:
            state = json.loads(db.execute("SELECT value FROM meta WHERE key='state'").fetchone()[0])
            history = [dict(r) for r in db.execute('SELECT id,created,label,status FROM commands ORDER BY rowid DESC LIMIT 8')]
        return {'state': state, 'board': dict(self.board.info), 'history': history,
                'cooldown_ms': max(0, int((self.cooldown_until - time.monotonic()) * 1000)),
                'state_note': '显示的是已发送设定，空调没有状态回传；使用原遥控器后可能不同步。'}

    @staticmethod
    def climate(payload):
        mode, temperature, fan = payload.get('mode'), payload.get('temperature'), payload.get('fan')
        if mode not in ('auto', 'cool', 'dry', 'heat', 'fan') or fan not in ('breeze', 'low', 'medium', 'high', 'auto'):
            raise ControlError('模式或风量无效。', 422)
        if mode in ('auto', 'dry') and fan != 'auto':
            raise ControlError('AUTO 和 DRY 模式的风量由空调决定。', 422)
        if mode not in ('auto', 'dry') and fan == 'auto':
            raise ControlError('请选择微风、低风、中风或大风。', 422)
        if mode == 'fan':
            if temperature is not None:
                raise ControlError('送风模式没有设定温度。', 422)
        elif type(temperature) is not int or not 17 <= temperature <= 30:
            raise ControlError('温度范围为 17–30°C。', 422)
        code = encode(mode, temperature, 'auto' if fan == 'breeze' else fan)
        return code, {'power': True, 'mode': mode, 'temperature': temperature, 'fan': fan}

    def plan(self, payload, previous):
        kind = payload.get('action')
        if kind == 'climate':
            code, update = self.climate(payload)
            modes = {'auto': '自动', 'cool': '制冷', 'dry': '除湿', 'heat': '制热', 'fan': '送风'}
            fans = {'auto': '风量自动', 'breeze': '微风', 'low': '低风', 'medium': '中风', 'high': '大风'}
            label = ' · '.join(filter(None, (modes[update['mode']], f"{update['temperature']}°C" if update['temperature'] is not None else None, fans[update['fan']])))
            update['sleep'] = None
            return f'SEND {{seq}} {code:06X}', update, label
        name = payload.get('button')
        if kind != 'button' or not isinstance(name, str) or name not in self.buttons:
            raise ControlError('不支持的按键。', 422)
        labels = {'vertical-step': '上下扇叶移动一档', 'horizontal-swing': '左右 Swing',
                  'led': '切换灯光与提示音', 'turbo': 'Turbo', 'sleep-first-sample': 'Sleep 开启样本 · 制冷 25°C 微风',
                  'sleep-second-sample': 'Sleep 取消样本 · 制冷 25°C 微风',
                  'silence-first-sample': 'Silence 开启', 'silence-second-code': 'Silence 关闭',
                  'follow-me-ion-long': 'Follow Me / ION 长按', 'power-off': '关机',
                  'power-on-sample': '开机样本 · 制冷 25°C 微风'}
        update = {}
        if name == 'power-off':
            update['power'] = False
        elif name in ('sleep-first-sample', 'sleep-second-sample', 'power-on-sample'):
            update = {'power': True, 'mode': 'cool', 'temperature': 25, 'fan': 'breeze', 'sleep': None}
        elif name.startswith('silence-'):
            update['silence'] = 'on' if name == 'silence-first-sample' else 'off'
        elif name == 'vertical-step':
            update['vertical_steps'] = previous.get('vertical_steps', 0) + 1
        elif name in ('led', 'turbo', 'horizontal-swing'):
            update[{'horizontal-swing': 'horizontal_swing'}.get(name, name)] = None
        return f"PRESS {{seq}} {self.buttons[name]['index']}", update, labels[name]

    def execute(self, request_id, payload):
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id or ''):
            raise ControlError('缺少有效的操作编号。', 400)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.lock:
            with self.db() as db:
                old = db.execute('SELECT * FROM commands WHERE id=?', (request_id,)).fetchone()
                if old:
                    if old['fingerprint'] != fingerprint:
                        raise ControlError('操作编号已用于另一条指令。', 409)
                    return json.loads(old['response'])
                previous = json.loads(db.execute("SELECT value FROM meta WHERE key='state'").fetchone()[0])
            command, update, label = self.plan(payload, previous)
            if time.monotonic() < self.cooldown_until:
                raise ControlError('上一条指令刚发送，请等倒计时结束。', 429)
            self.board.connect()
            with self.db() as db:
                row = db.execute("SELECT value FROM meta WHERE key='sequence'").fetchone()
                sequence = max(int(row[0]) if row else 0, self.board.info.get('last_seq', 0)) + 1
                if sequence > 0xFFFFFFFF:
                    raise ControlError('控制序号已达上限，需要维护。', 503)
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('sequence', str(sequence)))
                db.execute('INSERT INTO commands VALUES (?,?,?,?,?,?)',
                           (request_id, fingerprint, now(), label, 'pending', json.dumps({'status': 'pending', 'message': '正在发送，请勿重复操作。'}, ensure_ascii=False)))
            try:
                receipt = self.board.send(command.format(seq=sequence), sequence)
                previous.update(update)
                previous.update(last_sent_at=now(), confidence='sent', last_action=label)
                result = {'status': 'sent', 'message': '指令已发送', 'label': label, 'sequence': sequence, 'state': previous}
                status = 'sent'
                self.cooldown_until = time.monotonic() + COMMAND_INTERVAL_SECONDS
            except ControlError as exc:
                status = 'unknown' if exc.uncertain else 'failed'
                result = {'status': status, 'message': str(exc), 'label': label, 'sequence': sequence}
                if exc.uncertain:
                    previous['confidence'] = 'unknown'
                self.cooldown_until = time.monotonic() + COMMAND_INTERVAL_SECONDS
            with self.db() as db:
                db.execute('UPDATE commands SET status=?,response=? WHERE id=?', (status, json.dumps(result, ensure_ascii=False), request_id))
                db.execute("UPDATE meta SET value=? WHERE key='state'", (json.dumps(previous, ensure_ascii=False),))
            return result
