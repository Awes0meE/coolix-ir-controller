"""Exercise the HTTP-to-serial boundary without emitting infrared."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from controller.core import Controller, ControlError
from controller.server import create_app

ORIGIN = 'http://127.0.0.1:8768'
TARGET = {'action': 'climate', 'mode': 'cool', 'temperature': 24, 'fan': 'high'}


class FakeBoard:
    def __init__(self):
        self.info = {'online': True, 'last_seq': 0, 'd3': 'LOW'}
        self.calls = []
        self.error = None

    def connect(self):
        pass

    def send(self, command, sequence):
        self.calls.append(command)
        if self.error:
            raise self.error
        self.info['last_seq'] = sequence
        return {'sequence': sequence}


@pytest.fixture
def setup(tmp_path):
    board = FakeBoard()
    app = create_app(tmp_path, board, 'TEST-ONLY-CODE', monitor=False)
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        yield client, board, app.state.controller


def login(client):
    response = client.post('/api/login', json={'code': 'TEST-ONLY-CODE'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    return {'X-CSRF-Token': response.json()['csrf'], 'X-Request-ID': str(uuid.uuid4())}


def test_auth_origin_csrf_prevent_transmission(setup):
    client, board, _ = setup
    assert client.get('/api/state').status_code == 401
    assert client.post('/api/command', json=TARGET).status_code == 401
    headers = login(client)
    assert client.post('/api/command', json=TARGET).status_code == 403
    assert client.post('/api/command', headers={**headers, 'Origin': 'https://attacker.invalid'}, json=TARGET).status_code == 403
    assert client.get('/api/state', headers={'Host': 'attacker.invalid'}).status_code == 400
    assert not board.calls


def test_one_click_one_transmission_and_durable_receipt(setup):
    client, board, controller = setup
    headers = login(client)
    first = client.post('/api/command', headers=headers, json=TARGET)
    assert first.status_code == 200
    assert first.json()['status'] == 'sent'
    assert board.calls == ['SEND 1 B23F40']
    assert client.post('/api/command', headers=headers, json=TARGET).json() == first.json()
    assert len(board.calls) == 1
    assert client.post('/api/command', headers=headers, json={**TARGET, 'temperature': 25}).status_code == 409
    assert client.post('/api/command', headers={**headers, 'X-Request-ID': str(uuid.uuid4())}, json=TARGET).status_code == 429
    restarted = Controller(controller.data_dir, board)
    assert restarted.execute(headers['X-Request-ID'], TARGET)['status'] == 'sent'
    assert len(board.calls) == 1


@pytest.mark.parametrize('change', [{'temperature': 31}, {'temperature': True}, {'mode': 'dry'}, {'mode': 'fan'}, {'fan': 'auto'}])
def test_invalid_climate_cannot_transmit(setup, change):
    client, board, _ = setup
    assert client.post('/api/command', headers=login(client), json={**TARGET, **change}).status_code == 422
    assert not board.calls


def test_ambiguous_write_is_never_retried(setup):
    client, board, controller = setup
    headers = login(client)
    board.error = ControlError('Serial disconnected', 503, uncertain=True)
    assert client.post('/api/command', headers=headers, json=TARGET).json()['status'] == 'unknown'
    restarted = Controller(controller.data_dir, board)
    assert restarted.execute(headers['X-Request-ID'], TARGET)['status'] == 'unknown'
    assert len(board.calls) == 1
    assert restarted.state()['state']['confidence'] == 'unknown'


def test_pending_after_crash_not_replayed(setup):
    _, board, controller = setup
    with controller.db() as db:
        db.execute('INSERT INTO commands VALUES (?,?,?,?,?,?)', ('a'*20, 'fingerprint', 'date', 'command', 'pending', '{}'))
        state = controller.state()['state']
        state['confidence'] = 'sent'
        db.execute("UPDATE meta SET value=? WHERE key='state'", (json.dumps(state),))
    restored = Controller(controller.data_dir, board)
    assert restored.state()['history'][0]['status'] == 'unknown'
    assert restored.state()['state']['confidence'] == 'unknown'
    assert not board.calls


def test_captured_sleep_applies_recorded_state(setup):
    client, board, _ = setup
    result = client.post('/api/command', headers=login(client), json={'action': 'button', 'button': 'sleep-first-sample'}).json()
    assert board.calls == ['PRESS 1 5']
    assert result['state']['temperature'] == 25
    assert result['state']['fan'] == 'breeze'
    assert result['state']['sleep'] is None


def test_login_throttle_and_logout(setup):
    client, board, _ = setup
    headers = login(client)
    assert client.post('/api/logout', headers=headers, json={}).status_code == 200
    assert client.get('/api/state').status_code == 401
    for _ in range(5):
        assert client.post('/api/login', json={'code': 'wrong'}).status_code == 401
    assert client.post('/api/login', json={'code': 'wrong'}).status_code == 429
    assert not board.calls
