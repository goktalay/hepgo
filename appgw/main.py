"""HEPGO Uygulama Geçidi (app.hepgo.com) — tek köken ters-vekil + HEPGO logolu merkezî giriş.

Mobil (Capacitor) uygulama TEK kökende (app.hepgo.com) kalır → native köprü korunur.
Giriş: HEPGO logolu ekran. Firma CİHAZDA hatırlanır (hg_tenant çerezi); ilk sefer firma adresi + kullanıcı + şifre,
sonrasında yalnız kullanıcı + şifre (firma adı görünür). Kimlik doğrulama firmanın mevcut backend'ine iletilir;
oturum çerezi (caymaz_session) Domain'i kaldırılarak app.hepgo.com'a yazılır. Logout sonrası firma hatırlandığından
aynı firmanın giriş ekranı açılır. Firmalar hâlâ ayrı işlem/DB'de (izolasyon korunur).

Çalıştırma: uvicorn appgw.main:app --uds /run/hepgo/appgw.sock
"""
import asyncio
import re

import httpx
import websockets
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

# slug → { ad, soket, alias listesi }. Firma backend'i İŞLEM (soket) ile belirlenir, Host ile değil.
TENANTS = {
    'gokkubbe': {'name': 'GÖKKUBBE Teknoloji', 'sock': '/run/hepgo/caymaz.sock',
                 'alias': ['gokkubbe', 'gökkubbe', 'caymaz', 'gokkubbe.hepgo.com', 'caymaz.app']},
    'turkbey': {'name': 'Türkbey Teknoloji A.Ş.', 'sock': '/run/hepgo/turkbey.sock',
                'alias': ['turkbey', 'türkbey', 'turkbey.app', 'turkbey.hepgo.com']},
    'merkez': {'name': 'HEPGO Merkez', 'sock': '/run/hepgo/merkez.sock',
               'alias': ['merkez', 'merkez.veilox.app', 'merkez.hepgo.com']},
}
COOKIE = 'hg_tenant'
GW_HOST = 'app.hepgo.com'
DEFAULT_SOCK = '/run/hepgo/caymaz.sock'   # firma seçilmeden önce app-düzeyi statik dosyalar (tüm firmalarda aynı)
NOSTORE = {'cache-control': 'no-store', 'pragma': 'no-cache'}
TENANT_HOSTS = re.compile(r'https?://(?:www\.)?(?:caymaz\.app|turkbey\.app|veilox\.app|merkez\.veilox\.app|[a-z0-9-]+\.hepgo\.com|hepgo\.com)', re.I)
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'}

_ALIAS = {a: slug for slug, t in TENANTS.items() for a in t['alias']}
_clients: dict[str, httpx.AsyncClient] = {}


def client_for(sock: str) -> httpx.AsyncClient:
    c = _clients.get(sock)
    if c is None:
        c = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=sock), timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False)
        _clients[sock] = c
    return c


def resolve_firm(raw: str):
    """Kullanıcının yazdığı firma adresi/kodu → slug. 'https://gokkubbe.hepgo.com/' → 'gokkubbe'."""
    s = (raw or '').strip().lower()
    s = re.sub(r'^https?://', '', s).split('/')[0]
    s = re.sub(r'^www\.', '', s)
    if s in _ALIAS:
        return _ALIAS[s]
    s2 = re.sub(r'\.(hepgo\.com|veilox\.app|app)$', '', s)   # son eki at
    return _ALIAS.get(s2) or _ALIAS.get(s)


def login_page(firm_name: str | None) -> HTMLResponse:
    firm_field = '' if firm_name else (
        '<label>Firma adresi<input id="firma" autocomplete="organization" autocapitalize="none" '
        'placeholder="ör. firmaniz" required></label>')
    firm_hdr = (f'<div class="firm">Firma: <b>{firm_name}</b> · '
                '<a href="/_firma">değiştir</a></div>') if firm_name else ''
    html = f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>HEPGO — Giriş</title>
<style>:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;min-height:100dvh;display:flex;
align-items:center;justify-content:center;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#e8eefc;
padding:max(28px,env(safe-area-inset-top)) 22px max(28px,env(safe-area-inset-bottom));
background:radial-gradient(130% 150% at 0% 0%,#1e3a8a 0%,#0f1d3d 55%,#070d1c 100%)}}
.card{{width:100%;max-width:380px;display:flex;flex-direction:column;align-items:center;gap:6px}}
.logo{{width:96px;height:96px;display:grid;place-items:center;margin-bottom:10px}}
.logo img{{width:96px;height:96px;border-radius:22px;box-shadow:0 14px 36px rgba(7,13,28,.55)}}
.brand{{font-size:26px;font-weight:800;letter-spacing:.5px;margin:0}}.sub{{color:#aebbdc;font-size:13.5px;margin:0 0 16px}}
.firm{{font-size:13px;color:#aebbdc;margin:0 0 10px}}.firm a{{color:#9ab7ff}}
form{{width:100%;display:flex;flex-direction:column;gap:12px}}
label{{display:flex;flex-direction:column;gap:6px;font-size:13px;color:#cdd9f5}}
input{{height:46px;border-radius:12px;border:1px solid rgba(255,255,255,.22);background:rgba(0,0,0,.25);color:#fff;
padding:0 14px;font-size:16px;outline:none}}input:focus{{border-color:rgba(147,183,255,.8)}}
button{{height:48px;border:0;border-radius:12px;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;font:inherit;
font-weight:700;font-size:16px;cursor:pointer;margin-top:4px;box-shadow:0 10px 26px rgba(37,99,235,.35)}}
button:disabled{{opacity:.6}}.err{{min-height:18px;color:#ffb4b4;font-size:13px;text-align:center}}</style></head>
<body><div class="card">
<div class="logo"><img src="/_logo?v=2" alt="" onerror="this.parentElement.textContent='🛰️'"></div>
<h1 class="brand">HEPGO</h1><p class="sub">Fabrika Yönetim Sistemi</p>
{firm_hdr}
<form id="f" autocomplete="on">{firm_field}
<label>Kullanıcı adı<input id="u" autocapitalize="none" autocomplete="username" required></label>
<label>Şifre<input id="p" type="password" autocomplete="current-password" required></label>
<div class="err" id="e"></div>
<button type="submit" id="b">Giriş yap</button></form></div>
<script>
var hasFirm={str(bool(firm_name)).lower()};
var f=document.getElementById('f'),e=document.getElementById('e'),b=document.getElementById('b');
f.addEventListener('submit',async function(ev){{ev.preventDefault();e.textContent='';b.disabled=true;b.textContent='…';
 try{{
  if(!hasFirm){{
   var fv=document.getElementById('firma').value.trim();
   var rs=await fetch('/_sel',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{firma:fv}})}});
   if(!rs.ok){{e.textContent='Firma bulunamadı. Adresi kontrol edin.';b.disabled=false;b.textContent='Giriş yap';return;}}
  }}
  var r=await fetch('/api/auth/login',{{method:'POST',credentials:'include',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{username:document.getElementById('u').value,password:document.getElementById('p').value}})}});
  if(r.ok){{location.replace('/app');return;}}
  var d={{}};try{{d=await r.json();}}catch(_e){{}}
  e.textContent=(d&&d.detail)||'Kullanıcı adı ya da şifre hatalı';
 }}catch(_e){{e.textContent='Bağlantı hatası';}}
 b.disabled=false;b.textContent='Giriş yap';}});
</script></body></html>"""
    return HTMLResponse(html, headers=dict(NOSTORE))


async def is_authed(sock: str, cookie: str) -> bool:
    try:
        c = client_for(sock)
        r = await c.get(httpx.URL(scheme='http', host='x', path='/api/auth/me'),
                        headers=[('cookie', cookie), ('host', GW_HOST)])
        return r.status_code == 200
    except Exception:   # noqa: BLE001
        return False


async def proxy_to(sock: str, request: Request, path: str) -> Response:
    client = client_for(sock)
    up_headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP and k.lower() != 'host']
    up_headers.append(('host', GW_HOST))
    body = await request.body()
    url = httpx.URL(scheme='http', host='x', path=path, query=request.url.query.encode('utf-8'))
    req = client.build_request(request.method, url, headers=up_headers, content=body)
    try:
        up = await client.send(req, stream=True)
    except Exception:   # noqa: BLE001
        return Response('Firma sunucusuna ulaşılamadı', status_code=502)
    # Kod dosyaları (JS/CSS): no-store → Cloudflare önbelleğe almaz, tarayıcı hep tazesini çeker
    # (Cloudflare Browser Cache TTL 4sa dayatması bu dosyalara uygulanmaz → güncellemeler ANINDA yayılır).
    code = path.startswith(('/static/js', '/static/css')) or path.endswith(('.js', '.mjs', '.css'))
    resp = StreamingResponse(up.aiter_raw(), status_code=up.status_code, background=BackgroundTask(up.aclose))
    resp.raw_headers.clear()
    for k, v in up.headers.multi_items():
        kl = k.lower()
        if kl in HOP or kl == 'set-cookie':
            continue
        if code and kl in ('cache-control', 'expires', 'etag', 'last-modified', 'age', 'pragma'):
            continue   # kod dosyalarında önbellek başlıklarını at → kendi no-store'umuzu koyacağız
        if kl == 'location':
            v = TENANT_HOSTS.sub('https://' + GW_HOST, v)
        resp.raw_headers.append((k.encode('latin-1'), v.encode('latin-1')))
    if code:
        resp.raw_headers.append((b'cache-control', b'no-store, must-revalidate'))
    for sc in up.headers.get_list('set-cookie'):
        sc = re.sub(r';\s*[Dd]omain=[^;]+', '', sc)
        resp.raw_headers.append((b'set-cookie', sc.encode('latin-1')))
    return resp


async def gateway(request: Request) -> Response:
    path = request.url.path
    tenant = request.cookies.get(COOKIE)
    tvalid = tenant in TENANTS

    # Firma değiştir
    if path == '/_firma':
        r = RedirectResponse('/', status_code=302)
        r.delete_cookie(COOKIE, path='/')
        return r
    # HEPGO logosu (app-düzeyi statik; firma seçilmese de varsayılan firmadan sun) — HEPGO amblemi (koyu zemine uygun)
    if path == '/_logo':
        return await proxy_to(TENANTS[tenant]['sock'] if tvalid else DEFAULT_SOCK, request, '/static/img/hepgo-mark.png')
    # Firma seçimi (login formundan)
    if path == '/_sel':
        raw = ''
        if request.method == 'POST':
            try:
                raw = (await request.json()).get('firma', '')
            except Exception:   # noqa: BLE001
                raw = (await request.form()).get('firma', '')
        else:
            raw = request.query_params.get('t', '')
        slug = resolve_firm(raw)
        if not slug:
            return JSONResponse({'detail': 'Firma bulunamadı'}, status_code=404)
        r = JSONResponse({'ok': True, 'name': TENANTS[slug]['name']}) if request.method == 'POST' else RedirectResponse('/app', status_code=302)
        r.set_cookie(COOKIE, slug, max_age=31536000, secure=True, httponly=True, samesite='lax', path='/')
        r.headers['cache-control'] = 'no-store'
        return r

    # Sayfa girişi: kimlik yoksa HEPGO logolu giriş ekranı (firma hatırlanıyorsa yalnız kullanıcı+şifre)
    if request.method == 'GET' and path in ('/', '/app', '/index.html'):
        if not tvalid:
            return login_page(None)
        if not await is_authed(TENANTS[tenant]['sock'], request.headers.get('cookie', '')):
            return login_page(TENANTS[tenant]['name'])
        # kimlik var → firma ERP'sine ilet
        return await proxy_to(TENANTS[tenant]['sock'], request, path)

    # Diğer tüm yollar: şeffaf vekil
    if not tvalid:
        # app-düzeyi statik dosyalar (tüm firmalarda aynı) firma seçilmeden de sunulur → asla HTML dönmesin
        if path.startswith('/static/') or path in ('/favicon.ico', '/manifest.json', '/sw.js'):
            return await proxy_to(DEFAULT_SOCK, request, path)
        return Response('Firma seçilmedi', status_code=409, headers=dict(NOSTORE))
    return await proxy_to(TENANTS[tenant]['sock'], request, path)


async def ws_proxy(ws: WebSocket):
    """WebSocket (arama/telsiz/toplantı/canlı…) şeffaf vekil: firmanın backend soketine aktarır, çerezi iletir."""
    tenant = ws.cookies.get(COOKIE)
    if tenant not in TENANTS:
        await ws.close(code=1008)
        return
    sock = TENANTS[tenant]['sock']
    qs = ws.scope.get('query_string', b'').decode('latin-1')
    uri = 'ws://x' + ws.scope['path'] + (('?' + qs) if qs else '')
    subprotos = ws.scope.get('subprotocols') or []
    try:
        backend = await websockets.unix_connect(
            sock, uri,
            additional_headers={'Cookie': ws.headers.get('cookie', ''), 'Host': GW_HOST},
            subprotocols=subprotos or None, max_size=None, open_timeout=15)
    except Exception:   # noqa: BLE001
        try: await ws.close(code=1011)
        except Exception: pass   # noqa: BLE001
        return
    await ws.accept(subprotocol=getattr(backend, 'subprotocol', None))

    async def c2s():
        try:
            while True:
                m = await ws.receive()
                if m.get('type') == 'websocket.disconnect':
                    break
                if m.get('text') is not None:
                    await backend.send(m['text'])
                elif m.get('bytes') is not None:
                    await backend.send(m['bytes'])
        except Exception:   # noqa: BLE001
            pass
        finally:
            try: await backend.close()
            except Exception: pass   # noqa: BLE001

    async def s2c():
        try:
            async for msg in backend:
                if isinstance(msg, (bytes, bytearray)):
                    await ws.send_bytes(bytes(msg))
                else:
                    await ws.send_text(msg)
        except Exception:   # noqa: BLE001
            pass
        finally:
            try: await ws.close()
            except Exception: pass   # noqa: BLE001

    await asyncio.gather(c2s(), s2c())


app = Starlette(routes=[
    WebSocketRoute('/{path:path}', ws_proxy),
    Route('/{path:path}', gateway, methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']),
])
