"""Yerel yapılandırma arayüzü — yalnız stdlib (http.server), 127.0.0.1:8765'e bağlanır.

HEPGO_INTEG'e göre parametrelenir: SADECE o entegrasyonun alanlarını (Domain + API Anahtarı + cihaz
alanları) gösterir. Türkçe arayüz.

Uçlar:
  GET  /        → yapılandırma sayfası
  POST /test    → JSON {values} alır; wss://<domain>/ws/agent'e auth dener (integ ile), ok bekler;
                  mikro için ayrıca Mikro host:port'a TCP bağlantı dener.
  POST /save    → agent-config.env yazar (chmod 600) ve servisi yeniden başlatmak için süreçten çıkar.

Yalnız 127.0.0.1'e bağlanır (dışarıdan erişilemez).
"""
import asyncio
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import envcfg, profiles

HOST = '127.0.0.1'
PORT = int(os.environ.get('HEPGO_LOCALCONFIG_PORT', '8765'))

# Kaydetme sonrası serve_until_saved()'in dönmesi için.
_saved_event = threading.Event()


def _integ():
    return envcfg.integ_name()


def _profile():
    integ = _integ()
    return profiles.get(integ) if integ in profiles.names() else None


def _esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _page():
    integ = _integ()
    prof = _profile()
    title = prof['name'] if prof else 'HEPGO Ajanı'
    existing = envcfg.read_file()
    # Domain alanı için mevcut değeri CAYMAZ_AGENT_CENTRAL_URL'den de türet.
    if not existing.get('CAYMAZ_AGENT_CENTRAL_URL_DOMAIN') and existing.get('CAYMAZ_AGENT_CENTRAL_URL'):
        existing['CAYMAZ_AGENT_CENTRAL_URL_DOMAIN'] = envcfg.url_to_domain(
            existing['CAYMAZ_AGENT_CENTRAL_URL'])

    fields = profiles.all_fields(integ) if prof else []
    rows = []
    for f in fields:
        env = f['env']
        label = _esc(f['label'])
        ftype = f.get('type', 'text')
        help_txt = _esc(f.get('help', ''))
        if ftype == 'note':
            rows.append(
                f'<div class="note">{help_txt or label}</div>')
            continue
        val = _esc(existing.get(env, f.get('default', '')))
        ph = _esc(f.get('placeholder', ''))
        html_type = 'password' if ftype == 'password' else ('number' if ftype == 'number' else 'text')
        rows.append(
            f'<div class="fld"><label for="{env}">{label}</label>'
            f'<input id="{env}" name="{env}" type="{html_type}" value="{val}" placeholder="{ph}">'
            + (f'<small>{help_txt}</small>' if help_txt else '')
            + '</div>')

    hw = _esc(prof['hw_note']) if prof and prof.get('hw_note') else ''
    hw_html = f'<div class="hw">⚠️ {hw}</div>' if hw else ''
    integ_badge = (f'<span class="badge">Entegrasyon: {_esc(title)}</span>'
                   if prof else '<span class="badge warn">HEPGO_INTEG ayarlı değil</span>')
    fields_json = json.dumps([f['env'] for f in fields if f.get('type') != 'note'])
    is_mikro = 'true' if integ == 'mikro' else 'false'

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — HEPGO Ajan Ayarları</title>
<style>
 body{{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
 .card{{max-width:620px;margin:0 auto;background:#1e293b;border-radius:14px;padding:28px;box-shadow:0 10px 30px rgba(0,0,0,.4)}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#94a3b8;font-size:13px;margin-bottom:16px}}
 .badge{{display:inline-block;background:#2563eb;color:#fff;border-radius:999px;padding:4px 12px;font-size:12px;font-weight:600}}
 .badge.warn{{background:#b91c1c}}
 .hw{{background:#78350f;color:#fde68a;border-radius:10px;padding:12px 14px;margin:14px 0;font-size:13px;line-height:1.5}}
 .note{{background:#0b2a4a;color:#bae6fd;border-radius:10px;padding:12px 14px;margin:10px 0;font-size:13px;line-height:1.5}}
 .fld{{margin:12px 0;display:flex;flex-direction:column}}
 label{{font-size:13px;color:#cbd5e1;margin-bottom:5px}}
 input{{background:#0f172a;border:1px solid #334155;color:#e2e8f0;border-radius:8px;padding:10px 12px;font-size:14px}}
 input:focus{{outline:none;border-color:#2563eb}}
 small{{color:#64748b;font-size:11px;margin-top:4px}}
 .btns{{display:flex;gap:10px;margin-top:20px}}
 button{{flex:1;border:0;border-radius:9px;padding:12px;font-size:14px;font-weight:600;cursor:pointer}}
 #test{{background:#334155;color:#e2e8f0}} #save{{background:#16a34a;color:#fff}}
 button:disabled{{opacity:.6;cursor:default}}
 #msg{{margin-top:14px;font-size:13px;border-radius:8px;padding:10px 12px;display:none}}
 #msg.ok{{display:block;background:#064e3b;color:#a7f3d0}} #msg.err{{display:block;background:#7f1d1d;color:#fecaca}}
 #msg.info{{display:block;background:#1e3a5f;color:#bfdbfe}}
</style></head><body>
<div class="card">
 {integ_badge}
 <h1 style="margin-top:10px">{_esc(title)} — Ajan Ayarları</h1>
 <div class="sub">Bu sayfa yalnız bu bilgisayarda (127.0.0.1) görünür. Bilgileri girip önce bağlantıyı test edin.</div>
 {hw_html}
 <form id="f" onsubmit="return false">{''.join(rows)}</form>
 <div class="btns">
   <button id="test" onclick="run('test')">Bağlantıyı Test Et</button>
   <button id="save" onclick="run('save')">Kaydet ve Bağlan</button>
 </div>
 <div id="msg"></div>
</div>
<script>
 var FIELDS={fields_json}, IS_MIKRO={is_mikro};
 function vals(){{var o={{}};FIELDS.forEach(function(k){{var el=document.getElementById(k);if(el)o[k]=el.value;}});return o;}}
 function msg(cls,t){{var m=document.getElementById('msg');m.className=cls;m.textContent=t;}}
 function run(action){{
   var t=document.getElementById('test'),s=document.getElementById('save');
   t.disabled=s.disabled=true; msg('info', action==='save'?'Kaydediliyor…':'Test ediliyor…');
   fetch('/'+action,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(vals())}})
   .then(function(r){{return r.json();}})
   .then(function(d){{
      if(d.ok){{ msg('ok', d.detail||'Başarılı.');
        if(action==='save'){{ msg('ok',(d.detail||'Kaydedildi.')+' Servis yeniden başlatılıyor…'); }} }}
      else {{ msg('err', d.detail||'Başarısız.'); }}
   }})
   .catch(function(e){{ msg('err','İstek hatası: '+e); }})
   .finally(function(){{ t.disabled=s.disabled=false; }});
 }}
</script></body></html>"""


async def _ws_auth_test(url, key, integ, timeout=10):
    import websockets
    auth = {'t': 'auth', 'key': key, 'host': socket.gethostname()}
    if integ:
        auth['integ'] = integ
    async with websockets.connect(url, open_timeout=timeout, close_timeout=5, ping_interval=None,
                                  max_size=None) as ws:
        await ws.send(json.dumps(auth))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        return bool(ack.get('ok'))


def _do_test(values):
    integ = _integ()
    domain = (values.get('CAYMAZ_AGENT_CENTRAL_URL_DOMAIN') or '').strip()
    key = (values.get('CAYMAZ_AGENT_KEY') or '').strip()
    if not domain or not key:
        return False, 'Merkez alan adı (domain) ve API anahtarı gereklidir.'
    url = envcfg.domain_to_url(domain)

    # Mikro için önce yerel Mikro sunucusuna TCP bağlantısı dene.
    if integ == 'mikro':
        host = (values.get('CAYMAZ_MIKRO_HOST') or '').strip()
        port = (values.get('CAYMAZ_MIKRO_PORT') or '1433').strip()
        if host:
            try:
                s = socket.create_connection((host, int(port)), timeout=5)
                s.close()
            except Exception as e:   # noqa: BLE001
                return False, f'Mikro sunucusuna ({host}:{port}) ulaşılamadı: {e}'

    try:
        ok = asyncio.run(_ws_auth_test(url, key, integ))
    except Exception as e:   # noqa: BLE001
        return False, f'Merkeze ({url}) bağlanılamadı: {e}'
    if not ok:
        return False, 'Merkez kimliği reddetti (API anahtarı yanlış olabilir).'
    extra = ' Mikro sunucusuna TCP bağlantısı da başarılı.' if integ == 'mikro' else ''
    return True, f'Bağlantı başarılı — merkez kimliği onayladı.{extra}'


def _do_save(values):
    integ = _integ()
    domain = (values.get('CAYMAZ_AGENT_CENTRAL_URL_DOMAIN') or '').strip()
    key = (values.get('CAYMAZ_AGENT_KEY') or '').strip()
    if not domain or not key:
        return False, 'Merkez alan adı (domain) ve API anahtarı gereklidir.'
    out = {}
    out['CAYMAZ_AGENT_CENTRAL_URL_DOMAIN'] = domain
    out['CAYMAZ_AGENT_CENTRAL_URL'] = envcfg.domain_to_url(domain)
    if integ:
        out['HEPGO_INTEG'] = integ
    for k, v in values.items():
        if k.startswith('_') or k == 'CAYMAZ_AGENT_CENTRAL_URL_DOMAIN':
            continue
        if v is not None and str(v).strip() != '':
            out[k] = str(v).strip()
    path = envcfg.write_file(out)
    return True, f'Yapılandırma kaydedildi ({path}).'


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):   # sessiz
        pass

    def _send(self, code, body, ctype='text/html; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split('?', 1)[0] in ('/', '/index.html'):
            self._send(200, _page())
        else:
            self._send(404, 'Bulunamadı')

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        length = int(self.headers.get('Content-Length', '0') or '0')
        raw = self.rfile.read(length) if length else b''
        try:
            values = json.loads(raw.decode('utf-8')) if raw else {}
        except ValueError:
            self._send(400, json.dumps({'ok': False, 'detail': 'Geçersiz istek.'}),
                       'application/json; charset=utf-8')
            return
        if path == '/test':
            ok, detail = _do_test(values)
            self._send(200, json.dumps({'ok': ok, 'detail': detail}), 'application/json; charset=utf-8')
        elif path == '/save':
            ok, detail = _do_save(values)
            self._send(200, json.dumps({'ok': ok, 'detail': detail}), 'application/json; charset=utf-8')
            if ok:
                # Yanıt gönderildikten sonra süreçten çık → systemd yeniden başlatır ve ajan çalışır.
                threading.Timer(1.0, _saved_event.set).start()
        else:
            self._send(404, json.dumps({'ok': False, 'detail': 'Bulunamadı'}),
                       'application/json; charset=utf-8')


def _make_server():
    return ThreadingHTTPServer((HOST, PORT), _Handler)


def serve_until_saved():
    """Yapılandırma kaydedilene kadar arayüzü sun; kaydedilince döner (süreç çıkmalı)."""
    srv = _make_server()
    url = f'http://{HOST}:{PORT}/'
    print('=' * 60)
    print(f'  HEPGO ajan yapılandırması: {url}')
    print('  Tarayıcıda açıp bilgileri girin, ardından "Kaydet ve Bağlan".')
    print('=' * 60)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        _saved_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()


def main():
    serve_until_saved()


if __name__ == '__main__':
    main()
