"""Google / Microsoft rehber + takvim eşitlemesi: sayfalı liste, kişinin TÜM adresleri, Gmail'in "Diğer kişiler"i; hata yutulmaz —
anlaşılır neden hesapta (sync_error) ve yanıtta görünür (ör. People/Calendar API kapalı, izin verilmemiş). API'ler taklit edilir.
Çalıştırma: .venv/bin/python -m tests.test_contacts_sync
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from app import db, mail, personal  # noqa: E402
from app.cameras import encrypt  # noqa: E402


class R:
    def __init__(self, code, data, url=''):
        self.status_code, self._d, self.url = code, data, url

    def json(self):
        return self._d


scenario = {}


def fake_get(url, params=None, headers=None, timeout=None):
    return scenario[url](params or {}) if url in scenario else R(404, {})


def denied(status, reason, msg, url):
    return lambda p: R(403, {'error': {'code': 403, 'status': status, 'message': msg, 'details': [{'reason': reason}]}}, url)


def main():
    db.init()
    personal.httpx.get = fake_get
    mail.access_token = lambda *a, **k: 'jeton'
    with db.connect() as conn:
        uid = conn.execute("INSERT INTO users (username, full_name, password_hash, created_at) VALUES ('rehber@test', 'Rehber', 'x', ?)",
                           (db.now(),)).lastrowid
        gid = conn.execute("INSERT INTO mail_boxes (user_id, email, provider, auth_type, secret, created_at) VALUES (?,?,?,?,?,?)",
                           (uid, 'ali@gmail.com', 'gmail', 'google', encrypt('yenileme'), db.now())).lastrowid
        mid = conn.execute("INSERT INTO mail_boxes (user_id, email, provider, auth_type, secret, created_at) VALUES (?,?,?,?,?,?)",
                           (uid, 'ali@outlook.com', 'outlook', 'microsoft', encrypt('yenileme'), db.now())).lastrowid
        conn.commit()
        box = lambda i: db.row(conn.execute('SELECT * FROM mail_boxes WHERE id = ?', (i,)))  # noqa: E731

        # Google: kişiler iki sayfa (biri iki adresli); diğer kişiler izinsiz; takvim API'si kapalı
        cal = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'
        scenario.update({
            'https://people.googleapis.com/v1/people/me/connections': lambda p: R(200, {
                'connections': [{'resourceName': 'people/1', 'names': [{'displayName': 'Ayşe Kaya'}],
                                 'emailAddresses': [{'value': 'Ayse@Acme.com'}, {'value': 'ayse.k@gmail.com'}]}],
                'nextPageToken': 's2'} if not p.get('pageToken') else {
                'connections': [{'resourceName': 'people/2', 'names': [{'displayName': 'Cem'}], 'emailAddresses': [{'value': 'cem@beta.com'}]}]}),
            'https://people.googleapis.com/v1/otherContacts': denied('PERMISSION_DENIED', 'ACCESS_TOKEN_SCOPE_INSUFFICIENT',
                                                                     'Request had insufficient authentication scopes.', 'https://people.googleapis.com/v1/otherContacts'),
            cal: denied('PERMISSION_DENIED', 'SERVICE_DISABLED', 'Google Calendar API has not been used in project 1 before or it is disabled.', cal),
        })
        r = personal.sync_box(conn, box(gid))
        assert r['contacts'] == 2 and r['events'] == 0, r
        assert any('Calendar API kapalı' in e for e in r['errors']) and any('Diğer kişiler' in e and 'yeniden bağlan' in e for e in r['errors']), r['errors']
        rows = {e: n for e, n in conn.execute("SELECT email, name FROM personal_contacts WHERE user_id = ? AND source LIKE 'google%'", (uid,))}
        assert rows == {'ayse@acme.com': 'Ayşe Kaya', 'ayse.k@gmail.com': 'Ayşe Kaya', 'cem@beta.com': 'Cem'}, rows
        assert 'Calendar API kapalı' in box(gid)['sync_error']

        # Diğer kişiler izni verilince gelir; hata temizlenir
        scenario['https://people.googleapis.com/v1/otherContacts'] = lambda p: R(200, {'otherContacts': [
            {'resourceName': 'otherContacts/9', 'names': [{'displayName': 'Tedarikçi Satış'}], 'emailAddresses': [{'value': 'satis@tedarik.com'}]}]})
        scenario[cal] = lambda p: R(200, {'items': []})
        r = personal.sync_box(conn, box(gid))
        assert r['errors'] == [] and r['contacts'] == 3 and box(gid)['sync_error'] is None, r
        assert conn.execute("SELECT name FROM personal_contacts WHERE email = 'satis@tedarik.com'").fetchone()[0] == 'Tedarikçi Satış'
        r = personal.sync_box(conn, box(gid))   # tekrar eşitleme kopya oluşturmaz
        assert conn.execute("SELECT COUNT(*) FROM personal_contacts WHERE user_id = ? AND source LIKE 'google%'", (uid,)).fetchone()[0] == 4

        # Microsoft: sayfalı kişiler, çok adres; takvim izinsiz
        nxt = 'https://graph.microsoft.com/v1.0/me/contacts?$skip=1'
        scenario.update({
            'https://graph.microsoft.com/v1.0/me/contacts': lambda p: R(200, {'value': [
                {'id': 'm1', 'displayName': 'Deniz', 'emailAddresses': [{'address': 'deniz@x.com'}, {'address': 'deniz@y.com'}]}], '@odata.nextLink': nxt}),
            nxt: lambda p: R(200, {'value': [{'id': 'm2', 'displayName': 'Ege', 'emailAddresses': [{'address': 'ege@z.com'}]}]}),
            'https://graph.microsoft.com/v1.0/me/calendarView': lambda p: R(401, {'error': {'message': 'InvalidAuthenticationToken'}}),
        })
        r = personal.sync_box(conn, box(mid))
        assert r['contacts'] == 2 and any('Microsoft ile yeniden bağlan' in e for e in r['errors']), r
        got = {e for (e,) in conn.execute("SELECT email FROM personal_contacts WHERE source = 'microsoft'")}
        assert got == {'deniz@x.com', 'deniz@y.com', 'ege@z.com'}, got
    print('Rehber / takvim eşitleme testleri geçti.')


if __name__ == '__main__':
    main()
