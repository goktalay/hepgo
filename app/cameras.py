"""ONVIF kameralar: ağda bulma (WS-Discovery), cihaz bilgisi ve akış adresi (GetStreamUri), şifre saklama.

- Bulma: 239.255.255.250:3702'ye Probe; her fiziksel ağ arayüzünden gönderilir. Yanıttaki XAddrs cihaz servisidir.
- Bilgi / akış: SOAP + WS-Security UsernameToken (PasswordDigest). Akış adresine kullanıcı adı ve şifre eklenir.
- Şifre: veri klasöründeki camera.key ile SHA-256 sayaç kipinde (akış şifresi) ve HMAC ile saklanır; API'den dönmez.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from . import config

TIMEOUT = 4

# ---------- Şifre saklama

def _key():
    path = config.DATA_DIR / 'camera.key'
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        os.chmod(path, 0o600)
    return path.read_bytes()


def _stream(key, nonce, n):
    out = b''
    i = 0
    while len(out) < n:
        out += hashlib.sha256(key + nonce + i.to_bytes(4, 'big')).digest()
        i += 1
    return out[:n]


def encrypt(text):
    if not text:
        return None
    key, nonce, data = _key(), secrets.token_bytes(16), text.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))
    tag = hmac.new(key, nonce + ct, 'sha256').digest()[:16]
    return base64.b64encode(nonce + tag + ct).decode()


def decrypt(blob):
    if not blob:
        return ''
    raw = base64.b64decode(blob)
    nonce, tag, ct = raw[:16], raw[16:32], raw[32:]
    key = _key()
    if not hmac.compare_digest(tag, hmac.new(key, nonce + ct, 'sha256').digest()[:16]):
        return ''
    return bytes(a ^ b for a, b in zip(ct, _stream(key, nonce, len(ct)))).decode()


def with_credentials(url, username, password):
    """rtsp://host/yol → rtsp://kullanıcı:şifre@host/yol (adreste zaten varsa dokunulmaz)."""
    if not url or not username:
        return url
    p = urlsplit(url)
    if '@' in p.netloc:
        return url
    return urlunsplit((p.scheme, f'{quote(username, safe="")}:{quote(password or "", safe="")}@{p.netloc}', p.path, p.query, p.fragment))


def mask(url):
    """Adresteki şifreyi gizler (arayüzde gösterim)."""
    return re.sub(r'//([^:/@]+):[^@]*@', r'//\1:***@', url or '')


# ---------- WS-Discovery

PROBE = '''<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header><w:MessageID>uuid:{id}</w:MessageID><w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>'''


def _interface_ips():
    ips = []
    try:
        out = subprocess.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            parts = line.split()
            iface, cidr = parts[1], parts[3]
            if iface == 'lo' or iface.startswith(('docker', 'br-', 'veth', 'virbr', 'tailscale', 'zt')):
                continue
            ips.append(cidr.split('/')[0])
    except Exception:
        pass
    return ips or ['0.0.0.0']


def _scope(scopes, key):
    for s in scopes:
        if f'/{key}/' in s:
            from urllib.parse import unquote
            return unquote(s.rsplit('/', 1)[-1]).replace('_', ' ')
    return None


def discover(seconds=4):
    """Ağdaki ONVIF cihazları: [{'ip', 'xaddr', 'name', 'hardware'}]."""
    found = {}
    socks = []
    for ip in _interface_ips():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if ip != '0.0.0.0':
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                s.bind((ip, 0))
            s.setblocking(False)
            for _ in range(2):
                s.sendto(PROBE.format(id=uuid.uuid4()).encode(), ('239.255.255.250', 3702))
            socks.append(s)
        except OSError:
            continue
    end = time.time() + seconds
    while time.time() < end and socks:
        for s in socks:
            try:
                data, addr = s.recvfrom(65535)
            except (BlockingIOError, OSError):
                continue
            text = data.decode(errors='ignore')
            xaddrs = (re.findall(r'XAddrs>([^<]+)<', text) or [''])[0].split()
            scopes = (re.findall(r'Scopes>([^<]+)<', text) or [''])[0].split()
            xaddr = next((x for x in xaddrs if addr[0] in x), xaddrs[0] if xaddrs else None)
            if xaddr:
                found[addr[0]] = {'ip': addr[0], 'xaddr': xaddr, 'name': _scope(scopes, 'name'), 'hardware': _scope(scopes, 'hardware')}
        time.sleep(0.05)
    for s in socks:
        s.close()
    return sorted(found.values(), key=lambda d: socket.inet_aton(d['ip']))


# ---------- SOAP (WS-Security UsernameToken)

def _security(username, password):
    if not username:
        return ''
    nonce = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + (password or '').encode()).digest()).decode()
    return f'''<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<UsernameToken><Username>{_esc(username)}</Username>
<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</Password>
<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>
<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>
</UsernameToken></Security></s:Header>'''


def _esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _soap(url, body, username, password):
    env = (f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
           f'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
           f'xmlns:tt="http://www.onvif.org/ver10/schema">{_security(username, password)}<s:Body>{body}</s:Body></s:Envelope>')
    r = httpx.post(url, content=env.encode(), headers={'Content-Type': 'application/soap+xml; charset=utf-8'}, timeout=TIMEOUT)
    text = r.text
    if r.status_code >= 400 or 'Fault' in text[:2000] and 'Body' in text:
        if 'NotAuthorized' in text or r.status_code in (401, 403) or 'Sender' in text and 'uthoriz' in text:
            raise PermissionError('Kamera kullanıcı adı / şifre kabul etmedi')
        if r.status_code >= 400 or re.search(r'<[^>]*Fault[ >]', text):
            raise RuntimeError(f'Kamera ONVIF hatası ({r.status_code})')
    return text


def _tag(text, name):
    m = re.search(rf'<(?:\w+:)?{name}[^>]*>([^<]*)<', text)
    return m.group(1).strip() if m else None


def probe_camera(xaddr, username, password):
    """ONVIF cihazından bilgi ve akış adresi: {'manufacturer', 'model', 'stream_url'} (akış adresinde şifre yok)."""
    info = _soap(xaddr, '<tds:GetDeviceInformation/>', username, password)
    caps = _soap(xaddr, '<tds:GetCapabilities><tds:Category>Media</tds:Category></tds:GetCapabilities>', username, password)
    m = re.search(r'<(?:\w+:)?Media>\s*<(?:\w+:)?XAddr>([^<]+)<', caps)
    media = m.group(1).strip() if m else xaddr
    profiles = _soap(media, '<trt:GetProfiles/>', username, password)
    tokens = re.findall(r'<(?:\w+:)?Profiles[^>]*token="([^"]+)"', profiles)
    if not tokens:
        raise RuntimeError('Kamerada görüntü profili bulunamadı')
    uri = _soap(media, f'<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol>'
                       f'</tt:Transport></trt:StreamSetup><trt:ProfileToken>{_esc(tokens[0])}</trt:ProfileToken></trt:GetStreamUri>',
                username, password)
    stream = _tag(uri, 'Uri')
    if not stream:
        raise RuntimeError('Kamera akış adresi vermedi')
    return {'manufacturer': _tag(info, 'Manufacturer'), 'model': _tag(info, 'Model'), 'stream_url': stream.replace('&amp;', '&')}
