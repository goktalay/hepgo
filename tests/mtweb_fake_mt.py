"""Sahte hesap servisi (mastertool.download) — mtweb testleri için: `GET /api/mt/me` yalnız `Cookie: sm_session=<tok>` ile.
Belirteçler TOKENS sözlüğünde (tok → kullanıcı); bilinmeyen → 401. `POST /api/mt/auth/logout` (x-sshm: 1) belirteci siler.
`GET /__fake/calls` → alınan /me çağrı sayısı. Thread içinde `serve(port)` ya da alt süreç: `python -m tests.mtweb_fake_mt --port N`."""
import argparse
import json
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKENS = {
    'tok-ali-0123456789abcdef': {'id': 501, 'email': 'ali@test.com', 'name': 'Ali Yılmaz', 'verified': True},
    'tok-ayse-0123456789abcdef': {'id': 502, 'email': 'ayse@test.com', 'name': 'Ayşe Kaya', 'verified': True},
    'tok-dogrulanmamis-0123456': {'id': 503, 'email': 'yeni@test.com', 'name': 'Yeni', 'verified': False},
}
STATE = {'me_calls': 0, 'headers': []}
_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _tok(self):
        c = SimpleCookie(self.headers.get('Cookie') or '')
        return c['sm_session'].value if 'sm_session' in c else None

    def do_GET(self):
        if self.path == '/__fake/calls':
            return self._send(200, {'me_calls': STATE['me_calls'], 'headers': STATE['headers'][-5:]})
        if self.path == '/api/mt/me':
            with _LOCK:
                STATE['me_calls'] += 1
                STATE['headers'].append({k: v for k, v in self.headers.items() if k.lower() in ('cookie', 'authorization')})
                u = TOKENS.get(self._tok() or '')
            if not u:
                return self._send(401, {'code': 'unauthorized', 'message': 'Oturum yok'})
            return self._send(200, {'user': u})
        self._send(404, {'code': 'not_found'})

    def do_POST(self):
        if self.path == '/api/mt/auth/logout':
            if self.headers.get('x-sshm') != '1':
                return self._send(403, {'code': 'csrf'})
            with _LOCK:
                TOKENS.pop(self._tok() or '', None)
            return self._send(200, {'ok': True})
        self._send(404, {'code': 'not_found'})


def serve(port=0):
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8796)
    a = ap.parse_args()
    ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()
