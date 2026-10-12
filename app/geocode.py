"""Firma konumlarını internetten bulma (Firma Yönetimi › Konumları bul; Canlı Konum haritasında firma logoları).

Sıra: (1) firmanın kayıtlı adresi varsa Google Geocoding, (2) firma adıyla Google Places 'Find Place' (Türkiye odaklı),
(3) Google anahtarı yoksa / sonuç yoksa OpenStreetMap Nominatim (ad + Türkiye; kullanım kuralı: en çok 1 istek/sn, UA zorunlu).
Toplu tarama arka planda tek iş parçacığında çalışır; ilerleme STATE'te okunur. Sonuç companies.lat/lng (+ geo_source/geo_label/geo_at)."""
import json
import threading
import time
import urllib.parse
import urllib.request

from . import config, db

UA = 'HEPGO-ERP/1.0 (firma konum; +https://hepgo.com)'
STATE = {'running': False, 'total': 0, 'done': 0, 'found': 0, 'failed': 0, 'current': '', 'started_at': None, 'finished_at': None, 'error': None}
_lock = threading.Lock()
_last_nominatim = [0.0]


def _get_json(url, timeout=12):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', errors='replace'))


def _google_key():
    """Sunucu anahtarı (IP kısıtlı olabilir) öncelikli; yoksa tarayıcı anahtarı."""
    return (getattr(config, 'GOOGLE_MAPS_SERVER_KEY', '') or '').strip() or (getattr(config, 'GOOGLE_MAPS_API_KEY', '') or '').strip()


def google_geocode(address, key):
    q = urllib.parse.urlencode({'address': address, 'region': 'tr', 'language': 'tr', 'key': key})
    d = _get_json(f'https://maps.googleapis.com/maps/api/geocode/json?{q}')
    if d.get('status') != 'OK' or not d.get('results'):
        return None
    r = d['results'][0]
    loc = r['geometry']['location']
    return {'lat': loc['lat'], 'lng': loc['lng'], 'label': r.get('formatted_address'), 'source': 'google-geocode'}


def google_place(name, key):
    q = urllib.parse.urlencode({'input': f'{name}, Türkiye', 'inputtype': 'textquery', 'fields': 'geometry,name,formatted_address',
                                'language': 'tr', 'locationbias': 'rectangle:35.8,25.6|42.2,44.9', 'key': key})
    d = _get_json(f'https://maps.googleapis.com/maps/api/place/findplacefromtext/json?{q}')
    if d.get('status') != 'OK' or not d.get('candidates'):
        return None
    c = d['candidates'][0]
    loc = c['geometry']['location']
    return {'lat': loc['lat'], 'lng': loc['lng'], 'label': f"{c.get('name', '')} · {c.get('formatted_address', '')}".strip(' ·'), 'source': 'google-places'}


def google_place_new(query, key):
    """Places API (New) Text Search — Google Cloud'da 'Places API (New)' etkinse (eski Places API kapalıyken de çalışır)."""
    body = json.dumps({'textQuery': query, 'regionCode': 'TR', 'languageCode': 'tr', 'maxResultCount': 1}).encode()
    req = urllib.request.Request('https://places.googleapis.com/v1/places:searchText', data=body, method='POST', headers={
        'User-Agent': UA, 'Content-Type': 'application/json', 'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location'})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.loads(r.read().decode('utf-8', errors='replace'))
    pl = (d.get('places') or [None])[0]
    if not pl or not pl.get('location'):
        return None
    return {'lat': pl['location']['latitude'], 'lng': pl['location']['longitude'],
            'label': f"{(pl.get('displayName') or {}).get('text', '')} · {pl.get('formattedAddress', '')}".strip(' ·'), 'source': 'google-places'}


def nominatim(query):
    wait = 1.1 - (time.monotonic() - _last_nominatim[0])
    if wait > 0:
        time.sleep(wait)
    _last_nominatim[0] = time.monotonic()
    q = urllib.parse.urlencode({'q': query, 'format': 'json', 'limit': 1, 'countrycodes': 'tr', 'accept-language': 'tr'})
    d = _get_json(f'https://nominatim.openstreetmap.org/search?{q}')
    if not d:
        return None
    r = d[0]
    return {'lat': float(r['lat']), 'lng': float(r['lon']), 'label': r.get('display_name'), 'source': 'nominatim'}


def _clean_name(name):
    """Arama için şirket adından tür eklerini sadeleştir (A.Ş., LTD. ŞTİ., SAN. VE TİC. …)."""
    import re
    s = re.sub(r'\b(anonim şirketi|a\.?ş\.?|limited şirketi|ltd\.?\s*şti\.?|san\.?|tic\.?|ve|sanayi|ticaret|ltd|şti|inc|gmbh)\b', ' ', name, flags=re.I)
    return re.sub(r'\s+', ' ', s).strip(' .,-') or name


def _simplify_address(address):
    """Nominatim için adres sadeleştirme: 'No: 2-B', posta kodu, 'Mahallesi' ekleri atılır; mahalle + cadde + ilçe/il kalır."""
    import re
    s = re.sub(r'\b(no|numara)\s*[:.]?\s*[\w/-]+', ' ', address, flags=re.I)
    s = re.sub(r'\b\d{5}\b', ' ', s)
    s = re.sub(r'\b(mah\.?|mahallesi|cad\.?|caddesi|sok\.?|sokak|bulv\.?|bulvarı|türkiye|turkey)\b', ' ', s, flags=re.I)
    return re.sub(r'[\s,/.-]+', ' ', s).strip()


def find(name, address=None, city=None):
    """Bir firma için konum: {'lat','lng','label','source'} ya da None.
    Sıra: adres (Google → Nominatim → sadeleştirilmiş), ad (+il) (Google Places → Nominatim)."""
    key = _google_key()
    cname = _clean_name(name)
    tries = []
    if address:
        if key:
            tries.append(lambda: google_geocode(address, key))
        tries.append(lambda: nominatim(address))
        simp = _simplify_address(address)
        if simp and simp != address:
            tries.append(lambda: nominatim(simp))
    if key:
        q1 = f'{name}{", " + city if city else ""}'
        tries.append(lambda: google_place_new(q1, key))        # Places API (New)
        tries.append(lambda: google_place(q1, key))            # eski Places API (hâlâ açıksa)
        if cname != name:
            q2 = f'{cname}{", " + city if city else ""}'
            tries.append(lambda: google_place_new(q2, key))
            tries.append(lambda: google_place(q2, key))
    if city:
        tries.append(lambda: nominatim(f'{cname}, {city}'))
    tries.append(lambda: nominatim(name))
    if cname != name:
        tries.append(lambda: nominatim(cname))
    # son çare: adresten cadde/sokak + ilçe + il (sokak düzeyi), o da yoksa ilçe/il merkezi (yaklaşık; kaynak 'approx')
    if address:
        import re
        street = re.search(r'([A-Za-zÇĞİÖŞÜçğıöşü0-9. ]{3,}?)\s*(Caddesi|Cad\.?|Sokak|Sok\.?|Bulvarı|Bulv\.?)', address, flags=re.I)
        district = re.search(r'([A-Za-zÇĞİÖŞÜçğıöşü]{3,})\s*[/-]\s*([A-Za-zÇĞİÖŞÜçğıöşü]{3,})\s*(?:,|$)', address.replace('TÜRKİYE', '').replace('Türkiye', '').strip())
        dist = district.group(1) if district else None
        cty = city or (district.group(2) if district else None)
        if street and cty:
            q = f"{street.group(1).strip()} {street.group(2)}, {dist + ', ' if dist else ''}{cty}"
            tries.append(lambda q=q: nominatim(q))
        if dist and cty:
            def _approx(q=f'{dist}, {cty}'):
                r = nominatim(q)
                if r:
                    r['source'] = 'approx'; r['label'] = f"Yaklaşık (ilçe merkezi): {r.get('label') or q}"
                return r
            tries.append(_approx)
    for fn in tries:
        try:
            r = fn()
            if r and r.get('lat') is not None:
                return r
        except Exception:   # noqa: BLE001 — bir kaynak düşerse sıradakine geç
            continue
    return None


def _company_address(conn, cid):
    """(adres, il) — ilk kayıtlı adres; il yoksa adresin son parçasından kestirilir."""
    r = conn.execute('SELECT address, city FROM company_addresses WHERE company_id = ? ORDER BY id LIMIT 1', (cid,)).fetchone()
    if not r:
        return None, None
    addr, city = r[0], r[1]
    if not city and addr:
        import re
        m = re.search(r'([A-Za-zÇĞİÖŞÜçğıöşü]{3,})\s*/?\s*(?:TÜRKİYE|Türkiye)?\s*$', addr.replace('/TÜRKİYE', '').strip())
        city = m.group(1) if m else None
    return (', '.join(x for x in (addr, city) if x) or None), city


def run(conn_factory, only_missing=True, ids=None, redo_osm=False):
    """Toplu tarama (arka plan). conn_factory: yeni bağlantı üreten fonksiyon (iş parçacığı kendi bağlantısını açar)."""
    with _lock:
        if STATE['running']:
            return False
        STATE.update(running=True, total=0, done=0, found=0, failed=0, current='', started_at=db.now(), finished_at=None, error=None)

    def work():
        conn = conn_factory()
        try:
            where = 'active = 1'
            args = []
            if redo_osm:   # OSM/yaklaşık bulunanlar Google ile yeniden aranır (Google sonucu olanlara dokunulmaz)
                where += " AND (lat IS NULL OR lng IS NULL OR geo_source IN ('nominatim', 'approx'))"
            elif only_missing:
                where += ' AND (lat IS NULL OR lng IS NULL)'
            if ids:
                where += f" AND id IN ({','.join('?' * len(ids))})"
                args += list(ids)
            rows = conn.execute(f'SELECT id, name FROM companies WHERE {where} ORDER BY name', args).fetchall()
            STATE['total'] = len(rows)
            for cid, name in rows:
                STATE['current'] = name
                try:
                    addr, city = _company_address(conn, cid)
                    r = find(name, addr, city)
                except Exception:   # noqa: BLE001
                    r = None
                if r:
                    conn.execute('UPDATE companies SET lat = ?, lng = ?, geo_source = ?, geo_label = ?, geo_at = ? WHERE id = ?',
                                 (round(r['lat'], 6), round(r['lng'], 6), r['source'], (r.get('label') or '')[:300], db.now(), cid))
                    conn.commit()
                    STATE['found'] += 1
                else:
                    STATE['failed'] += 1
                STATE['done'] += 1
        except Exception as e:   # noqa: BLE001
            STATE['error'] = str(e)
        finally:
            STATE.update(running=False, current='', finished_at=db.now())
            try:
                conn.close()
            except Exception:   # noqa: BLE001
                pass

    threading.Thread(target=work, daemon=True, name='geocode').start()
    return True
