"""Timers run against fake serial only; wall-clock progression is explicit."""
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from controller.core import Controller, ControlError
from controller.scheduler import Scheduler, COOL, DRY, OFF
from test_controller import FakeBoard, login, setup


@pytest.fixture
def scheduled(tmp_path):
    board = FakeBoard()
    controller = Controller(tmp_path, board)
    clock = [time.time()]
    scheduler = Scheduler(controller, clock=lambda: clock[0])
    return scheduler, controller, board, clock


def create(scheduler, payload=OFF, delay=60, request_id=None):
    return scheduler.create(request_id or str(uuid.uuid4()),
                            {'kind': 'timer', 'due_at': scheduler.clock() + delay, 'payload': payload})


def advance(fixture, seconds):
    scheduler, controller, _, clock = fixture
    clock[0] += seconds
    controller.cooldown_until = 0
    scheduler.tick()


@pytest.mark.parametrize('payload', [OFF, COOL, DRY])
def test_timer_due_once_and_frozen_payload(scheduled, payload):
    scheduler, controller, board, clock = scheduled
    payload = dict(payload)
    job = create(scheduler, payload)
    payload['temperature'] = 30
    assert not board.calls
    scheduler.tick()
    assert not board.calls
    advance(scheduled, 60)
    assert len(board.calls) == 1
    assert scheduler.get(job['id'])['status'] == 'completed'
    scheduler.tick()
    assert len(board.calls) == 1
    if job['payload']['action'] == 'climate':
        assert controller.state()['state']['temperature'] == 24


def test_precool_two_stages_and_idempotency(scheduled):
    scheduler, _, board, clock = scheduled
    job_id = str(uuid.uuid4())
    job = scheduler.create(job_id, {'kind': 'precool'})
    assert board.calls == ['SEND 1 B23F40']
    assert job['phase'] == 'dry' and job['due_at'] == clock[0] + 600
    assert scheduler.create(job_id, {'kind': 'precool'}) == job
    advance(scheduled, 599)
    assert len(board.calls) == 1
    advance(scheduled, 1)
    assert board.calls == ['SEND 1 B23F40', 'SEND 2 B21F44']
    assert scheduler.get(job_id)['status'] == 'completed'
    advance(scheduled, 600)
    assert len(board.calls) == 2


def test_precool_countdown_starts_after_successful_send(scheduled):
    scheduler, _, board, clock = scheduled
    send = board.send
    def delayed(command, seq):
        clock[0] += 3
        return send(command, seq)
    board.send = delayed
    start = clock[0]
    job = scheduler.create(str(uuid.uuid4()), {'kind': 'precool'})
    assert job['due_at'] == start + 603


def test_cancel_survives_restart_and_never_sends(scheduled):
    scheduler, controller, board, clock = scheduled
    job = create(scheduler)
    scheduler.cancel(job['id'])
    restored = Scheduler(controller, lambda: clock[0])
    clock[0] += 60
    restored.tick()
    assert restored.get(job['id'])['status'] == 'cancelled'
    assert not board.calls


def test_future_task_survives_restart_but_overdue_does_not(scheduled):
    scheduler, controller, board, clock = scheduled
    future = create(scheduler, delay=120)
    missed = create(scheduler, delay=60)
    clock[0] += 60
    restored = Scheduler(controller, lambda: clock[0])
    restored.tick()
    assert not board.calls
    assert restored.get(missed['id'])['status'] == 'missed'
    assert restored.get(future['id'])['status'] == 'pending'
    clock[0] += 60
    restored.tick()
    assert len(board.calls) == 1


def test_sleep_gap_marks_missed_without_catchup(scheduled):
    scheduler, _, board, _ = scheduled
    job = create(scheduler)
    advance(scheduled, 91)
    assert scheduler.get(job['id'])['status'] == 'missed'
    assert not board.calls


@pytest.mark.parametrize('stage', ['cool', 'dry'])
def test_uncertain_precool_stage_never_retried(scheduled, stage):
    scheduler, controller, board, clock = scheduled
    if stage == 'cool':
        board.error = ControlError('lost receipt', 503, uncertain=True)
    job = scheduler.create(str(uuid.uuid4()), {'kind': 'precool'})
    if stage == 'dry':
        board.error = ControlError('lost receipt', 503, uncertain=True)
        advance(scheduled, 600)
    calls = list(board.calls)
    board.error = None
    restored = Scheduler(controller, lambda: clock[0])
    clock[0] += 600
    controller.cooldown_until = 0
    restored.tick()
    assert restored.get(job['id'])['status'] == 'unknown'
    assert board.calls == calls


def test_claimed_job_not_replayed_after_crash(scheduled):
    scheduler, controller, board, clock = scheduled
    job = create(scheduler)
    scheduler._update(job['id'], 'running', 'claimed')
    clock[0] += 60
    restored = Scheduler(controller, lambda: clock[0])
    restored.tick()
    assert restored.get(job['id'])['status'] == 'unknown'
    assert not board.calls


def test_manual_override_cancels_dry_stage_before_send(scheduled):
    scheduler, controller, board, _ = scheduled
    job = scheduler.create(str(uuid.uuid4()), {'kind': 'precool'})
    controller.cooldown_until = 0
    original = board.send
    def check_cancelled(command, seq):
        assert scheduler.get(job['id'])['status'] == 'cancelled'
        return original(command, seq)
    board.send = check_cancelled
    scheduler.manual(str(uuid.uuid4()), OFF)
    advance(scheduled, 600)
    assert len(board.calls) == 2
    assert controller.state()['state']['power'] is False


def test_invalid_manual_or_duplicate_does_not_cancel_new_precool(scheduled):
    scheduler, controller, board, _ = scheduled
    old_id = str(uuid.uuid4())
    scheduler.manual(old_id, OFF)
    controller.cooldown_until = 0
    job = scheduler.create(str(uuid.uuid4()), {'kind': 'precool'})
    scheduler.manual(old_id, OFF)
    with pytest.raises(ControlError):
        scheduler.manual(str(uuid.uuid4()), {'action': 'invalid'})
    assert scheduler.get(job['id'])['status'] == 'pending'
    assert len(board.calls) == 2


def test_timer_override_cancels_precool(scheduled):
    scheduler, _, board, _ = scheduled
    job = scheduler.create(str(uuid.uuid4()), {'kind': 'precool'})
    create(scheduler)
    advance(scheduled, 60)
    advance(scheduled, 540)
    assert scheduler.get(job['id'])['status'] == 'cancelled'
    assert len(board.calls) == 2


def test_due_timers_respect_send_cooldown(scheduled):
    scheduler, controller, board, clock = scheduled
    a, b = create(scheduler), create(scheduler)
    clock[0] += 60
    scheduler.tick()
    scheduler.tick()
    assert len(board.calls) == 1
    controller.cooldown_until = 0
    scheduler.tick()
    assert len(board.calls) == 2


def test_concurrent_precool_clicks_only_send_once(scheduled):
    scheduler, _, board, _ = scheduled
    def click(_):
        try:
            return scheduler.create(str(uuid.uuid4()), {'kind': 'precool'})['status']
        except ControlError as e:
            return e.status
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(click, range(4)))
    assert results.count('pending') == 1
    assert results.count(409) == 3
    assert len(board.calls) == 1


def test_offline_task_fails_once_without_queued_send(scheduled):
    scheduler, controller, board, _ = scheduled
    def offline():
        raise ControlError('offline', 503)
    board.connect = offline
    job = create(scheduler)
    advance(scheduled, 60)
    assert scheduler.get(job['id'])['status'] == 'failed'
    board.connect = lambda: None
    advance(scheduled, 1)
    assert not board.calls


@pytest.mark.parametrize('change', [
    {'due_at': True}, {'due_at': float('nan')}, {'due_at': float('inf')},
    {'due_at': 0}, {'due_at': 10**12}, {'payload': []},
    {'payload': {'action': 'button', 'button': 'turbo'}},
    {'payload': {**DRY, 'fan': 'high'}},
])
def test_invalid_timer_never_persists_or_transmits(scheduled, change):
    scheduler, _, board, clock = scheduled
    body = {'kind': 'timer', 'due_at': clock[0] + 60, 'payload': OFF, **change}
    with pytest.raises(ControlError):
        scheduler.create(str(uuid.uuid4()), body)
    assert not scheduler.list() and not board.calls


def test_schedule_auth_csrf_origin_idempotency_and_cancel(setup):
    client, board, controller = setup
    body = {'kind': 'timer', 'due_at': time.time() + 60, 'payload': OFF}
    assert client.post('/api/schedules', json=body).status_code == 401
    assert client.post('/api/schedules/missing/cancel', json={}).status_code == 401
    headers = login(client)
    assert client.post('/api/schedules', json=body).status_code == 403
    assert client.post('/api/schedules', headers={**headers, 'Origin':'https://invalid.example'}, json=body).status_code == 403
    first = client.post('/api/schedules', headers=headers, json=body)
    assert first.status_code == 200
    assert client.post('/api/schedules', headers=headers, json=body).json() == first.json()
    assert client.post('/api/schedules', headers=headers, json={**body, 'payload': COOL}).status_code == 409
    url = '/api/schedules/' + first.json()['id'] + '/cancel'
    assert client.post(url, json={}).status_code == 403
    assert client.post(url, headers=headers, json={}).json()['status'] == 'cancelled'
    assert client.get('/api/state').json()['schedules'][0]['status'] == 'cancelled'
    assert not board.calls
