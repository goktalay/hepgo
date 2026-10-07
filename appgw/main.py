"""HEPGO Uygulama Geçidi (app.hepgo.com) — tek köken ters-vekil.

Amaç: Mobil (Capacitor) uygulama TEK kökende (app.hepgo.com) kalsın ki native köprü korunsun.
Giriş sırasında firma SEÇİLİR (çerez hg_tenant), sonrası tüm istekler o firmanın mevcut backend soketine
şeffafça yönlendirilir. Firmalar hâlâ ayrı işlem/DB'de (izolasyon bozulmaz); SPA olduğu gibi çalışır (yol 1:1).

Çalıştırma: uvicorn appgw.main:app --uds /run/hepgo/appgw.sock
"""
import re

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

# slug → { ad, soket }. Firmalar buradan seçilir; backend tenant'ı İŞLEM (soket) belirler, Host değil.
TENANTS = {
    'gokkubbe': {'name': 'GÖKKUBBE Teknoloji', 'sock': '/run/hepgo/caymaz.sock'},
    'turkbey': {'name': 'Türkbey Teknoloji A.Ş.', 'sock': '/run/hepgo/turkbey.sock'},
    'merkez': {'name': 'HEPGO Merkez', 'sock': '/run/hepgo/merkez.sock'},
}
COOKIE = 'hg_tenant'
GW_HOST = 'app.hepgo.com'
# Üst akış mutlak yönlendirmelerinde bu hostlar app.hepgo.com'a çevrilir (tek kökende kal)
TENANT_HOSTS = re.compile(r'https?://(?:www\.)?(?:caymaz\.app|turkbey\.app|veilox\.app|merkez\.veilox\.app|[a-z0-9-]+\.hepgo\.com|hepgo\.com)', re.I)
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade'}

_clients: dict[str, httpx.AsyncClient] = {}


def client_for(sock: str) -> httpx.AsyncClient:
    c = _clients.get(sock)
    if c is None:
        c = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=sock), timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False)
        _clients[sock] = c
    return c


def selection_page() -> HTMLResponse:
    rows = ''.join(
        f'<a class="firm" href="/_sel?t={slug}"><span class="nm">{t["name"]}</span><span class="go">Giriş →</span></a>'
        for slug, t in TENANTS.items())
    html = f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>HEPGO — Firma seçin</title>
<style>:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;min-height:100dvh;display:flex;
flex-direction:column;align-items:center;justify-content:center;gap:10px;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
color:#e8eefc;padding:max(28px,env(safe-area-inset-top)) 24px max(28px,env(safe-area-inset-bottom));
background:radial-gradient(130% 150% at 0% 0%,#1e3a8a 0%,#0f1d3d 55%,#070d1c 100%)}}
h1{{font-size:22px;margin:0 0 4px}}p{{color:#aebbdc;margin:0 0 18px;font-size:14px}}
.firm{{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;max-width:380px;text-decoration:none;
color:#fff;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:16px 18px;transition:background .15s}}
.firm:active{{background:rgba(255,255,255,.14)}}.nm{{font-weight:600;font-size:16px}}.go{{color:#9ab7ff;font-size:13px}}
.logo{{width:72px;height:72px;border-radius:20px;background:rgba(255,255,255,.06);display:grid;place-items:center;margin-bottom:12px}}
.logo img{{width:48px;height:48px;border-radius:12px}}</style></head>
<body><div class="logo"><img src="/static/img/logo-mark.png" alt="" onerror="this.style.display='none'"></div>
<h1>HEPGO</h1><p>Lütfen firmanızı seçin</p>{rows}</body></html>"""
    return HTMLResponse(html)


async def gateway(request: Request) -> Response:
    path = request.url.path

    # Firma seçimi
    if path == '/_sel':
        t = request.query_params.get('t')
        if t in TENANTS:
            r = RedirectResponse('/app', status_code=302)
            r.set_cookie(COOKIE, t, max_age=31536000, secure=True, httponly=True, samesite='lax', path='/')
            return r
        return RedirectResponse('/', status_code=302)
    if path == '/_firma':   # firma değiştir
        r = RedirectResponse('/', status_code=302)
        r.delete_cookie(COOKIE, path='/')
        return r

    tenant = request.cookies.get(COOKIE)
    if tenant not in TENANTS:
        if request.method in ('GET', 'HEAD'):
            return selection_page()   # çerez yoksa her sayfa isteğinde firma seçimi
        return Response('Firma seçilmedi', status_code=409)

    sock = TENANTS[tenant]['sock']
    client = client_for(sock)
    # Üst akışa ilet: Host=app.hepgo.com (mutlak linkler/çerezler tek köken olsun), hop-by-hop çıkar
    up_headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP and k.lower() != 'host']
    up_headers.append(('host', GW_HOST))
    body = await request.body()
    url = httpx.URL(scheme='http', host='x', path=path, query=request.url.query.encode('utf-8'))
    req = client.build_request(request.method, url, headers=up_headers, content=body)
    try:
        up = await client.send(req, stream=True)
    except Exception:   # noqa: BLE001
        return Response('Firma sunucusuna ulaşılamadı', status_code=502)

    # Yanıt başlıkları: hop-by-hop çıkar, Set-Cookie Domain'ini kaldır (app.hepgo.com'a düşsün),
    # mutlak Location'ı tek kökene çevir.
    resp = StreamingResponse(up.aiter_raw(), status_code=up.status_code, background=BackgroundTask(up.aclose))
    resp.raw_headers.clear()
    for k, v in up.headers.multi_items():
        kl = k.lower()
        if kl in HOP or kl == 'set-cookie':
            continue
        if kl == 'location':
            v = TENANT_HOSTS.sub('https://' + GW_HOST, v)
        resp.raw_headers.append((k.encode('latin-1'), v.encode('latin-1')))
    for sc in up.headers.get_list('set-cookie'):
        sc = re.sub(r';\s*[Dd]omain=[^;]+', '', sc)   # Domain kaldır → çerez app.hepgo.com'a yazılır
        resp.raw_headers.append((b'set-cookie', sc.encode('latin-1')))
    return resp


app = Starlette(routes=[Route('/{path:path}', gateway, methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])])
