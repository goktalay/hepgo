"""Kişisel rehber ve kişisel takvim öğeleri — yalnız sahibi görür (yönetici dahil kimse başkasınınkini göremez).

- Kişiler (personal_contacts): yazışılan adresler otomatik (source=mail), Google Kişiler / Outlook kişileri (OAuth hesaplarında),
  elle eklenenler. Rehber › Kişilerim'de ve mail yazarken otomatik tamamlamada kullanılır.
- Takvim (personal_events): mail davetleri (ICS), Google Takvim ve Outlook takvimi. Kişisel Takvim'de görünür.
"""
from datetime import datetime, timedelta

import httpx

from . import db, mail
from .cameras import decrypt


def collect(conn, user_id, addrs, own=()):
    """Yazışılan adresleri kişisel rehbere ekler / sayacını artırır (kendi adresleri hariç)."""
    own = {a.lower() for a in own}
    now = db.now()
    for name, email in addrs:
        e = (email or '').strip().lower()
        if not e or '@' not in e or e in own or e.startswith(('no-reply', 'noreply', 'mailer-daemon', 'postmaster')):
            continue
        nm = (name or '').strip().strip('"') or None
        conn.execute('''INSERT INTO personal_contacts (user_id, source, ext_id, name, email, hits, created_at, updated_at) VALUES (?, 'mail', ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(user_id, source, ext_id) DO UPDATE SET hits = hits + 1, updated_at = excluded.updated_at,
                        name = COALESCE(personal_contacts.name, excluded.name)''', (user_id, e, nm, e, now, now))


def upsert_event(conn, user_id, box_id, source, ev):
    conn.execute('''INSERT INTO personal_events (user_id, box_id, source, ext_id, title, starts_at, ends_at, all_day, location, description, organizer, status, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(user_id, source, ext_id) DO UPDATE SET title = excluded.title, starts_at = excluded.starts_at, ends_at = excluded.ends_at,
                    all_day = excluded.all_day, location = excluded.location, description = excluded.description, organizer = excluded.organizer,
                    status = excluded.status, updated_at = excluded.updated_at''',
                 (user_id, box_id, source, ev['uid'][:300], (ev.get('title') or '')[:300], ev['starts_at'], ev.get('ends_at'), int(bool(ev.get('all_day'))),
                  (ev.get('location') or '')[:300] or None, (ev.get('description') or '')[:2000] or None, ev.get('organizer'), ev.get('status') or 'confirmed', db.now()))


def calendar_items(conn, user_id, start, end):
    """Kişisel Takvim'e eklenecek mail / Google / Outlook takvim öğeleri (iptal edilenler hariç)."""
    rows = db.rows(conn.execute('''SELECT * FROM personal_events WHERE user_id = ? AND starts_at >= ? AND starts_at < ? AND COALESCE(status, '') != 'cancelled'
                                   ORDER BY starts_at''', (user_id, start, end)))
    src = {'ics': 'Mail daveti', 'google': 'Google Takvim', 'microsoft': 'Outlook Takvimi'}
    return [{'id': f'p{r["id"]}', 'kind': 'KISISEL', 'title': r['title'] + (' (yanıt bekliyor)' if r['status'] == 'tentative' else ''),
             'starts_at': r['starts_at'], 'ends_at': r['ends_at'], 'location': r['location'], 'users': [], 'readonly': True,
             'all_day': bool(r['all_day']), 'source': src.get(r['source'], r['source']), 'note': r['description']} for r in rows]


# ---------------- Google / Microsoft eşitleme (OAuth hesapları) ----------------
def _window():
    now = datetime.now()
    return (now - timedelta(days=30)).replace(microsecond=0), (now + timedelta(days=180)).replace(microsecond=0)


def _gtime(t):
    if not t:
        return None, False
    if 'date' in t and 'dateTime' not in t:
        return f"{t['date']}T00:00:00", True
    try:
        dt = datetime.fromisoformat(t['dateTime'].replace('Z', '+00:00')).astimezone()
        return dt.replace(tzinfo=None).isoformat(timespec='seconds'), False
    except ValueError:
        return None, False


def _gerr(r, what):
    """Google API hatası → anlaşılır Türkçe neden."""
    try:
        e = r.json().get('error') or {}
    except ValueError:
        e = {}
    msg = (e.get('message') or '').strip()
    reasons = ' '.join(str(d.get('reason', '')) for d in e.get('details', []) if isinstance(d, dict)) + ' ' + str(e.get('status', ''))
    if r.status_code == 403 and ('SERVICE_DISABLED' in reasons or 'has not been used' in msg or 'is disabled' in msg):
        api = 'People API' if 'people' in str(r.url) else 'Google Calendar API'
        return f'{what}: Google Cloud Console’da {api} kapalı — API’ler ve Hizmetler › Kütüphane’den etkinleştirin'
    if r.status_code == 403 and ('SCOPE' in reasons or 'insufficient' in msg.lower()):
        return f'{what}: bu izin verilmemiş — hesabı “Google ile yeniden bağlan” ile tekrar bağlayın'
    return f'{what}: Google hatası {r.status_code}{(" — " + msg[:160]) if msg else ""}'


def _google_pages(url, params, hdr, key):
    """Sayfalı Google listesi (nextPageToken) → (öğeler, hata yanıtı ya da None)."""
    items, token = [], None
    for _ in range(50):   # en çok 50 sayfa (50 000 kişi)
        r = httpx.get(url, params={**params, **({'pageToken': token} if token else {})}, headers=hdr, timeout=30)
        if r.status_code != 200:
            return items, r
        d = r.json()
        items += d.get(key, [])
        token = d.get('nextPageToken')
        if not token:
            break
    return items, None


def _google_contact(conn, user_id, p, source='google'):
    """Bir Google kişisi → rehber: kişinin HER e-posta adresi ayrı satır (kaynak kimliği adresle birlikte)."""
    name = ((p.get('names') or [{}])[0]).get('displayName')
    phone = ((p.get('phoneNumbers') or [{}])[0]).get('value')
    org = (p.get('organizations') or [{}])[0]
    rid = p.get('resourceName') or name or ''
    emails = [e.get('value') for e in (p.get('emailAddresses') or []) if e.get('value')]
    for i, email in enumerate(emails or [None]):
        _upsert_contact(conn, user_id, source, rid if i == 0 else f'{rid}#{email.lower()}', name, email, phone, org.get('name'), org.get('title'))
    return 1


def sync_google(conn, box):
    """Google Takvim (birincil) + Google Kişiler (Kişilerim + Gmail'in otomatik kaydettiği "Diğer kişiler") → takvim / rehber.
    Hatalar sessizce yutulmaz: (takvim, kişi, [hatalar]) döner; hesapta gösterilir."""
    tok = mail.access_token(decrypt(box['secret']), 'google')
    hdr = {'Authorization': f'Bearer {tok}'}
    a, b = _window()
    n_ev = n_ct = 0
    errors = []
    if box['sync_calendar']:
        url = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
        params = {'timeMin': a.isoformat() + 'Z', 'timeMax': b.isoformat() + 'Z', 'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': 2500}
        r = httpx.get(url, params=params, headers=hdr, timeout=30)
        if r.status_code == 200:
            for it in r.json().get('items', []):
                st, all_day = _gtime(it.get('start'))
                en, _ = _gtime(it.get('end'))
                if not st:
                    continue
                upsert_event(conn, box['user_id'], box['id'], 'google', {'uid': it['id'], 'title': it.get('summary') or '(başlıksız)', 'starts_at': st, 'ends_at': en,
                                                                        'all_day': all_day, 'location': it.get('location'), 'description': it.get('description'),
                                                                        'organizer': (it.get('organizer') or {}).get('email'), 'status': it.get('status')})
                n_ev += 1
        else:
            errors.append(_gerr(r, 'Takvim'))
    if box['sync_contacts']:
        people, bad = _google_pages('https://people.googleapis.com/v1/people/me/connections',
                                    {'personFields': 'names,emailAddresses,phoneNumbers,organizations', 'pageSize': 1000}, hdr, 'connections')
        if bad is not None:
            errors.append(_gerr(bad, 'Kişiler'))
        for p in people:
            n_ct += _google_contact(conn, box['user_id'], p)
        others, bad = _google_pages('https://people.googleapis.com/v1/otherContacts',
                                    {'readMask': 'names,emailAddresses,phoneNumbers', 'pageSize': 1000}, hdr, 'otherContacts')
        if bad is not None:
            errors.append(_gerr(bad, 'Diğer kişiler'))
        for p in others:
            n_ct += _google_contact(conn, box['user_id'], p, 'google-other')
    return n_ev, n_ct, errors


def sync_microsoft(conn, box):
    """Outlook takvimi + kişileri (Microsoft Graph) → kişisel takvim / rehber."""
    tok = mail.access_token(decrypt(box['secret']), 'microsoft', mail.MS_GRAPH_SCOPE)
    hdr = {'Authorization': f'Bearer {tok}', 'Prefer': 'outlook.timezone="Turkey Standard Time"'}
    a, b = _window()
    n_ev = n_ct = 0
    errors = []
    if box['sync_calendar']:
        r = httpx.get('https://graph.microsoft.com/v1.0/me/calendarView', params={'startDateTime': a.isoformat(), 'endDateTime': b.isoformat(), '$top': 500},
                      headers=hdr, timeout=30)
        if r.status_code == 200:
            for it in r.json().get('value', []):
                st = (it.get('start') or {}).get('dateTime', '')[:19]
                en = (it.get('end') or {}).get('dateTime', '')[:19]
                if not st:
                    continue
                upsert_event(conn, box['user_id'], box['id'], 'microsoft', {
                    'uid': it['id'], 'title': it.get('subject') or '(başlıksız)', 'starts_at': st, 'ends_at': en or None, 'all_day': it.get('isAllDay'),
                    'location': (it.get('location') or {}).get('displayName'), 'description': it.get('bodyPreview'),
                    'organizer': ((it.get('organizer') or {}).get('emailAddress') or {}).get('address'),
                    'status': 'cancelled' if it.get('isCancelled') else 'confirmed'})
                n_ev += 1
        else:
            errors.append(_merr(r, 'Takvim'))
    if box['sync_contacts']:
        url, params = 'https://graph.microsoft.com/v1.0/me/contacts', {'$top': 1000}
        for _ in range(50):   # sayfalı (@odata.nextLink)
            r = httpx.get(url, params=params, headers=hdr, timeout=30)
            if r.status_code != 200:
                errors.append(_merr(r, 'Kişiler'))
                break
            d = r.json()
            for p in d.get('value', []):
                phone = (p.get('mobilePhone') or (p.get('businessPhones') or [None])[0])
                emails = [e.get('address') for e in (p.get('emailAddresses') or []) if e.get('address')]
                for i, email in enumerate(emails or [None]):   # kişinin her adresi
                    _upsert_contact(conn, box['user_id'], 'microsoft', p['id'] if i == 0 else f"{p['id']}#{email.lower()}",
                                    p.get('displayName'), email, phone, p.get('companyName'), p.get('jobTitle'))
                n_ct += 1
            url, params = d.get('@odata.nextLink'), None
            if not url:
                break
    return n_ev, n_ct, errors


def _merr(r, what):
    try:
        msg = ((r.json().get('error') or {}).get('message') or '').strip()
    except ValueError:
        msg = ''
    if r.status_code in (401, 403):
        return f'{what}: izin yok ({r.status_code}) — hesabı “Microsoft ile yeniden bağlan” ile tekrar bağlayın'
    return f'{what}: Microsoft hatası {r.status_code}{(" — " + msg[:160]) if msg else ""}'


def _upsert_contact(conn, user_id, source, ext_id, name, email, phone, company, title):
    now = db.now()
    conn.execute('''INSERT INTO personal_contacts (user_id, source, ext_id, name, email, phone, company, title, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(user_id, source, ext_id) DO UPDATE SET name = excluded.name, email = excluded.email, phone = excluded.phone,
                    company = excluded.company, title = excluded.title, updated_at = excluded.updated_at''',
                 (user_id, source, str(ext_id)[:300], (name or '')[:200] or None, (email or '').lower()[:200] or None, (phone or '')[:60] or None,
                  (company or '')[:200] or None, (title or '')[:200] or None, now, now))


def sync_box(conn, box):
    """Hesabın takvim / kişi eşitlemesi (yalnız Google / Microsoft OAuth hesaplarında)."""
    if box['auth_type'] == 'google':
        r = sync_google(conn, box)
    elif box['auth_type'] == 'microsoft':
        r = sync_microsoft(conn, box)
    else:
        return None
    errors = r[2]
    conn.execute('UPDATE mail_boxes SET last_sync = ?, sync_error = ? WHERE id = ?', (db.now(), '; '.join(errors)[:500] or None, box['id']))
    conn.commit()
    return {'events': r[0], 'contacts': r[1], 'errors': errors}
