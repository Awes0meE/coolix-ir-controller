"""Private HTTP interface for the USB IR controller; no command runs on startup."""
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import ROOT, Controller, ControlError, SerialBoard

COOKIE = 'ir_controller_session'


def create_app(data_dir=None, board=None, access_code=None, monitor=True):
    data_dir = Path(data_dir or os.environ.get('IR_DATA_DIR', ROOT / '.runtime/controller'))
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    origin = os.environ.get('IR_PUBLIC_ORIGIN', 'http://127.0.0.1:8768').rstrip('/')
    origins = {origin, 'http://127.0.0.1:8768', 'http://localhost:8768'}
    allowed_hosts = {urlsplit(o).hostname for o in origins}
    index = json.loads((ROOT / 'captures/york-replay-index.json').read_text())
    board = board or SerialBoard(os.environ.get('IR_SERIAL_PORT', ''), index['catalog_tag'])
    controller = Controller(data_dir, board)
    credentials = data_dir / 'credentials.json'
    if not credentials.exists():
        code = access_code or '-'.join(''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(4)) for _ in range(3))
        salt = secrets.token_bytes(16)
        config = {'salt': salt.hex(), 'hash': hashlib.pbkdf2_hmac('sha256', code.encode(), salt, 260000).hex()}
        credentials.write_text(json.dumps(config))
        credentials.chmod(0o600)
        code_path = data_dir / 'access-code.txt'
        code_path.write_text(code + '\n')
        code_path.chmod(0o600)
    config = json.loads(credentials.read_text())
    stop = threading.Event()
    auth_lock = threading.Lock()
    attempts = {}

    def watch():
        while not stop.is_set():
            board.status()
            stop.wait(4)

    @asynccontextmanager
    async def lifespan(app):
        worker = None
        if monitor:
            worker = threading.Thread(target=watch, daemon=True, name='ir-board-status')
            worker.start()
        yield
        stop.set()
        if worker:
            worker.join(timeout=5)
        if hasattr(board, '_close'):
            board._close('服务已停止')

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.controller = controller
    app.state.origins = origins

    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.hostname not in allowed_hosts:
            return JSONResponse({'message': 'Host not allowed'}, status_code=400)
        if request.method not in ('GET', 'HEAD', 'POST'):
            return JSONResponse({'message': 'Method not allowed'}, status_code=405)
        if request.method == 'POST':
            if request.headers.get('origin') not in origins:
                return JSONResponse({'message': '来源验证失败，请从控制页重新操作。'}, status_code=403)
            if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                return JSONResponse({'message': '需要 JSON 请求。'}, status_code=415)
            if len(await request.body()) > 8192:
                return JSONResponse({'message': '请求过大。'}, status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def session(request, mutate=False):
        token = request.cookies.get(COOKIE, '')
        digest = hashlib.sha256(token.encode()).hexdigest()
        with controller.db() as db:
            row = db.execute('SELECT csrf,expires FROM sessions WHERE token_hash=?', (digest,)).fetchone()
        if not token or not row or row['expires'] < time.time():
            raise ControlError('请先解锁控制器。', 401)
        if mutate and not hmac.compare_digest(request.headers.get('x-csrf-token', ''), row['csrf']):
            raise ControlError('会话校验失败，请刷新页面。', 403)
        return row, digest

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return JSONResponse({'message': str(exc), 'uncertain': exc.uncertain}, status_code=exc.status)

    @app.get('/health')
    def health():
        return {'service': 'ir-controller', 'status': 'ok'}

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'controller/static/index.html')

    @app.get('/api/session')
    def get_session(request: Request):
        row, _ = session(request)
        return {'authenticated': True, 'csrf': row['csrf']}

    @app.post('/api/login')
    async def login(request: Request):
        client = request.headers.get('cf-connecting-ip') or request.client.host
        stamp = time.monotonic()
        with auth_lock:
            for key in list(attempts):
                attempts[key] = [t for t in attempts[key] if stamp - t < 60]
                if not attempts[key]:
                    del attempts[key]
            if len(attempts.get(client, [])) >= 5 or sum(map(len, attempts.values())) >= 30:
                return JSONResponse({'message': '尝试次数较多，请一分钟后再试。'}, status_code=429)
            attempts.setdefault(client, []).append(stamp)
        try:
            body = await request.json()
            code = str(body.get('code', '')).strip().upper()
        except Exception:
            raise ControlError('访问码格式不正确。', 400)
        candidate = hashlib.pbkdf2_hmac('sha256', code.encode(), bytes.fromhex(config['salt']), 260000).hex()
        if not hmac.compare_digest(candidate, config['hash']):
            return JSONResponse({'message': '访问码不正确，请重新输入。'}, status_code=401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with controller.db() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest, csrf, time.time() + 30 * 86400))
        with auth_lock:
            attempts.pop(client, None)
        response = JSONResponse({'authenticated': True, 'csrf': csrf})
        response.set_cookie(COOKIE, token, httponly=True, secure=request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver'),
                            samesite='strict', max_age=30 * 86400, path='/')
        return response

    @app.post('/api/logout')
    def logout(request: Request):
        _, digest = session(request, True)
        with controller.db() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest,))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.get('/api/state')
    def state(request: Request):
        session(request)
        return controller.state()

    @app.post('/api/command')
    async def command(request: Request):
        session(request, True)
        try:
            body = await request.json()
        except Exception:
            raise ControlError('请求格式不正确。', 400)
        if not isinstance(body, dict):
            raise ControlError('请求格式不正确。', 400)
        import asyncio
        return await asyncio.to_thread(controller.execute, request.headers.get('x-request-id', ''), body)

    app.mount('/static', StaticFiles(directory=ROOT / 'controller/static'), name='static')
    return app


app = create_app()
