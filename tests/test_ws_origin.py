"""WebSocket Origin koruması: başka siteden (ör. başka firmanın alt alanı) açılan WebSocket el sıkışmada reddedilir;
aynı adres, tanımlı genel adres ve Origin'siz (tarayıcı dışı, ajan) istemciler geçer.
Çalıştırma: .venv/bin/python -m tests.test_ws_origin
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_PUBLIC_URL='https://firma.veilox.app')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.main import app  # noqa: E402


def opened(client, origin):
    headers = {'origin': origin} if origin is not None else {}
    try:
        with client.websocket_connect('/ws/console', headers=headers) as ws:
            ws.receive_text()   # konsol kapalı/yetkisiz mesajı: bağlantı kabul edildi demektir
            return True
    except WebSocketDisconnect as e:
        assert e.code == 4403, e.code
        return False


def main():
    with TestClient(app) as c:   # TestClient Host: testserver
        assert opened(c, None)                                    # Origin yok (ajan / tarayıcı dışı)
        assert opened(c, 'http://testserver')                     # aynı adres
        assert opened(c, 'https://firma.veilox.app')              # CAYMAZ_PUBLIC_URL
        assert not opened(c, 'https://baska-firma.veilox.app')    # başka firmanın alt alanı
        assert not opened(c, 'https://saldirgan.example')
        assert not opened(c, 'null')                              # sandbox iframe / file://
        assert not opened(c, 'http://testserver.saldirgan.example')
    print('WebSocket Origin testleri geçti.')


if __name__ == '__main__':
    main()
