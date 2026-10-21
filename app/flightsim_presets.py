"""Uçuş Simülatörü KAYITLI SİMÜLASYONLAR — tablo `drone_sim_presets` (docs/ucus-simulatoru.md §27).

Kullanıcı isteği (özet): "Simülasyonlarda başlatmak zorunlu olmasın; tasarlayan yönetici pilot atayabilsin (pilot yetkisi olanlardan). Sihirbazın
son adımında 'Uç' yanıp sönsün, yanında 'Kaydet'. Kaydet ayarları adla saklar; Uçuş Simülatörü altında 'Kayıtlı Simülasyonlar': atanan pilot bunu
defalarca, farklı zamanlarda, yeniden ayar yapmadan çalıştırır. Kartta Başlat / Düzenle / Sil; Başlat sihirbazı atlar (onay/özet + geri sayım)."
Yetki (kullanıcı kararı): BAŞLAT = atanan pilot ya da tasarlayan (MASTER her şeye erişir); diğerleri yalnız görür. DÜZENLE/SİL = tasarlayan ya da
yönetici (ADMIN rolü / MASTER). Atanan pilota bildirim ("Size bir simülasyon atandı": anlık push + zil — `notifications.sim_assigned`).

`settings` = oturum başlatma gövdesinin AYNISI (POST /api/drone/sim/sessions, mode sitl). Kaydederken de başlatmadaki doğrulayıcılardan geçer
(`ayar_dogrula`: tip, merkez, model, dron kaydı, güç, kontrol düzeni, kamera, hedefler, saha/görev, dünya + kalkış) — ama saklanan gövde normalize
EDİLMEZ (başlatırken yeniden doğrulanır; sonradan değişen varsayılanlar uygulanır). Silme yumuşak (`deleted_at`): uçuş kayıtlarının `preset_id` bağı kalır.
"""
import json
import re
import unicodedata

from . import auth, db

AD_MAX = 80
ACIKLAMA_MAX = 500
# Oturum gövdesinin kayda giren alanları (routers/flightsim.SessionIn ile aynı; mode/log_id/airframe hariç — kayıtlı simülasyon yalnız canlı SITL)
ALANLAR = ('type', 'center_id', 'world', 'model', 'drone_id', 'rec', 'power', 'camera', 'layout', 'targets', 'site', 'defend', 'drive')


class PresetHata(ValueError):
    def __init__(self, kod, mesaj):
        super().__init__(mesaj)
        self.kod = kod   # invalid (400) · conflict (409) · forbidden (403) · notfound (404)


# ---------------- ad ----------------
def ad_anahtari(ad):
    """Benzersizlik anahtarı: baş/son boşluk, ardışık boşluk, büyük/küçük harf (Türkçe İ/I dahil) ve birleşik işaretler duyarsız."""
    s = unicodedata.normalize('NFC', str(ad or '')).strip()
    s = re.sub(r'\s+', ' ', s)
    return s.replace('I', 'ı').replace('İ', 'i').lower()


def ad_dogrula(ad):
    s = re.sub(r'\s+', ' ', unicodedata.normalize('NFC', str(ad or '')).strip())
    if not s:
        raise PresetHata('invalid', 'Kayıt adı gerekir')
    if len(s) > AD_MAX:
        raise PresetHata('invalid', f'Kayıt adı en çok {AD_MAX} karakter olmalı')
    return s


def ad_cakisan(conn, ad, haric_id=None):
    """Aynı anahtarlı (silinmemiş) kayıt varsa {id, name}; yoksa None."""
    k = ad_anahtari(ad)
    for r in conn.execute('SELECT id, name FROM drone_sim_presets WHERE deleted_at IS NULL'):
        if r[0] != haric_id and ad_anahtari(r[1]) == k:
            return {'id': r[0], 'name': r[1]}
    return None


# ---------------- ayarlar ----------------
def ayar_dogrula(conn, settings):
    """Kayıtlı simülasyon ayarları → saklanacak gövde (yalnız ALANLAR; mode 'sitl'). Başlatmadaki doğrulayıcılar (flightsim.MANAGER.ac + router
    yükleme adımı) SIRAYLA çalışır; ilk hata PresetHata('invalid'). Oturum AÇILMAZ (limit/SITL/port denetimi yok — o başlatırken)."""
    from . import drone_params, flightsim, flightsim_gcs, flightsim_models, flightsim_power, flightsim_targets
    if not isinstance(settings, dict):
        raise PresetHata('invalid', 'settings nesne olmalı')
    if settings.get('mode') not in (None, 'sitl'):
        raise PresetHata('invalid', 'Kayıtlı simülasyon yalnız canlı SITL (mode sitl) olabilir')
    s = {k: settings[k] for k in ALANLAR if settings.get(k) is not None}
    tip = s.get('type')
    if not tip or s.get('center_id') is None:
        raise PresetHata('invalid', 'type ve center_id gerekir')
    if tip not in flightsim.TIP_ADLARI:
        raise PresetHata('invalid', 'Geçersiz dron tipi')
    try:
        cid = int(s['center_id'])
    except (TypeError, ValueError):
        raise PresetHata('invalid', 'center_id sayı olmalı')
    s['center_id'] = cid
    if not db.row(conn.execute('SELECT id FROM drone_route_centers WHERE id = ? AND active = 1', (cid,))):
        raise PresetHata('invalid', 'Merkez bulunamadı (Dron Yönetimi › Rotalar › Merkezler)')
    drone = None
    if s.get('drone_id') is not None:
        try:
            s['drone_id'] = int(s['drone_id'])
        except (TypeError, ValueError):
            raise PresetHata('invalid', 'drone_id sayı olmalı')
        drone = db.row(conn.execute('SELECT id FROM drone_drones WHERE id = ? AND active = 1', (s['drone_id'],)))
        if not drone:
            raise PresetHata('invalid', 'Dron kaydı bulunamadı (Dron Yönetimi › Dron Envanteri)')
    if s.get('rec') is not None and not isinstance(s['rec'], dict):
        raise PresetHata('invalid', 'rec nesne olmalı')
    try:
        mdl = flightsim_models.coz(conn, tip, s.get('model'))
        flightsim.kamera_dogrula(s.get('camera'))
        try:
            oneri = drone_params.guc_onerisi(drone['id']) if drone else None
        except Exception:   # noqa: BLE001 — öneri okunamazsa varsayılanlar (başlatmadaki gibi)
            oneri = None
        try:
            flightsim_power.dogrula(s.get('power'), tip, oneri)
        except ValueError as e:
            raise PresetHata('invalid', str(e))
        flightsim.layout_dogrula(tip, s.get('layout'), mdl)
        flightsim.drive_dogrula(tip, s.get('drive'), mdl)   # §31 kara aracı sürüş biçimi
        try:
            flightsim_targets.dogrula(s.get('targets'))
        except flightsim_targets.HedefHata as e:
            raise PresetHata('invalid', str(e))
        try:
            flightsim_gcs.gcs_dogrula(s.get('site'))
            flightsim_gcs.savunma_dogrula(s.get('defend'), tip)
        except flightsim_gcs.GcsHata as e:
            raise PresetHata('invalid', str(e))
        flightsim.world_dogrula(s.get('world'))
    except flightsim.SimHata as e:
        raise PresetHata('invalid', str(e))
    return s


# ---------------- pilotlar ----------------
def pilotlar(conn):
    """Pilot atanabilecek kullanıcılar: etkin, Uçuş Simülatörü'nde YAZMA izni olan (oturum açıp uçurabilen; Rol Yönetimi — 'drone' modülünden
    miras) ya da MASTER. Dönüş [{id, full_name, username, pilot (PILOT rolü), roles}] — PILOT rolündekiler önce, sonra ada göre."""
    from . import rbac
    out = []
    for u in db.rows(conn.execute('SELECT id, username, full_name FROM users WHERE active = 1')):
        roller = auth.user_roles(conn, u['id'])
        master = auth.is_master(u['username'])
        if not master and 'drone.sim' not in rbac.writable(roller):
            continue
        out.append({'id': u['id'], 'full_name': u['full_name'] or u['username'], 'username': u['username'], 'pilot': auth.PILOT in rbac.expand(roller),
                    'master': master})
    out.sort(key=lambda r: (not r['pilot'], ad_anahtari(r['full_name'])))
    return out


def pilot_mu(conn, uid):
    return any(p['id'] == int(uid) for p in pilotlar(conn))


# ---------------- yetki ----------------
def yonetici_mi(user):
    return bool(user.get('master')) or auth.ADMIN in (user.get('roles') or [])


def baslatabilir(p, user):
    """Başlat: atanan pilot ya da tasarlayan (MASTER her zaman)."""
    return bool(user.get('master')) or user['id'] in (p.get('pilot_id'), p.get('created_by'))


def duzenleyebilir(p, user):
    """Düzenle / Sil: tasarlayan ya da yönetici (ADMIN / MASTER)."""
    return yonetici_mi(user) or user['id'] == p.get('created_by')


# ---------------- okuma ----------------
_SELECT = '''SELECT p.*, cu.full_name AS created_by_name, pu.full_name AS pilot_name, c.name AS center_name,
                    (SELECT COUNT(*) FROM drone_sim_runs r WHERE r.preset_id = p.id) AS run_count,
                    (SELECT MAX(r.started_at) FROM drone_sim_runs r WHERE r.preset_id = p.id) AS last_run_at
             FROM drone_sim_presets p LEFT JOIN users cu ON cu.id = p.created_by LEFT JOIN users pu ON pu.id = p.pilot_id
             LEFT JOIN drone_route_centers c ON c.id = p.center_id'''


def _satir(r, user):
    from . import flightsim_power
    r = dict(r)
    try:
        r['settings'] = json.loads(r['settings']) if r.get('settings') else {}
    except ValueError:
        r['settings'] = {}
    r['can_start'] = baslatabilir(r, user)
    r['can_edit'] = duzenleyebilir(r, user)
    r['mine'] = user['id'] in (r.get('pilot_id'), r.get('created_by'))
    r['budget'] = flightsim_power.menzil_sure(r['settings'].get('power'), r.get('type'))   # §27 azami süre / menzil (kartta)
    return r


def listele(conn, user):
    return [_satir(r, user) for r in db.rows(conn.execute(_SELECT + ' WHERE p.deleted_at IS NULL ORDER BY p.updated_at DESC, p.id DESC'))]


def getir(conn, pid, user, silinmis=False):
    r = db.row(conn.execute(_SELECT + ' WHERE p.id = ?' + ('' if silinmis else ' AND p.deleted_at IS NULL'), (int(pid),)))
    return _satir(r, user) if r else None


# ---------------- yazma ----------------
def _girdi(conn, body, haric_id=None):
    ad = ad_dogrula(body.get('name'))
    c = ad_cakisan(conn, ad, haric_id)
    if c:
        raise PresetHata('conflict', f'"{c["name"]}" adlı kayıtlı simülasyon zaten var; başka bir ad seçin')
    aciklama = re.sub(r'[ \t]+', ' ', str(body.get('description') or '')).strip() or None
    if aciklama and len(aciklama) > ACIKLAMA_MAX:
        raise PresetHata('invalid', f'Açıklama en çok {ACIKLAMA_MAX} karakter olmalı')
    pilot = body.get('pilot_id')
    if pilot not in (None, ''):
        try:
            pilot = int(pilot)
        except (TypeError, ValueError):
            raise PresetHata('invalid', 'pilot_id sayı olmalı')
        if not pilot_mu(conn, pilot):
            raise PresetHata('invalid', 'Seçilen kullanıcının pilot yetkisi yok (Uçuş Simülatörü yazma izni gerekir)')
    else:
        pilot = None
    s = ayar_dogrula(conn, body.get('settings'))
    return ad, aciklama, pilot, s


def olustur(conn, body, user):
    ad, aciklama, pilot, s = _girdi(conn, body)
    now = db.now()
    cur = conn.execute('''INSERT INTO drone_sim_presets (name, description, settings, type, center_id, created_by, pilot_id, created_at, updated_at)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (ad, aciklama, json.dumps(s, ensure_ascii=False), s['type'], s['center_id'], user['id'], pilot, now, now))
    return cur.lastrowid, pilot


def guncelle(conn, pid, body, user):
    """Dönüş: (eski pilot_id, yeni pilot_id)."""
    p = getir(conn, pid, user)
    if not p:
        raise PresetHata('notfound', 'Kayıtlı simülasyon bulunamadı')
    if not duzenleyebilir(p, user):
        raise PresetHata('forbidden', 'Yalnız tasarlayan ya da yönetici düzenleyebilir')
    ad, aciklama, pilot, s = _girdi(conn, body, haric_id=p['id'])
    conn.execute('''UPDATE drone_sim_presets SET name = ?, description = ?, settings = ?, type = ?, center_id = ?, pilot_id = ?, updated_at = ?
                    WHERE id = ?''', (ad, aciklama, json.dumps(s, ensure_ascii=False), s['type'], s['center_id'], pilot, db.now(), p['id']))
    return p.get('pilot_id'), pilot


def sil(conn, pid, user):
    p = getir(conn, pid, user)
    if not p:
        raise PresetHata('notfound', 'Kayıtlı simülasyon bulunamadı')
    if not duzenleyebilir(p, user):
        raise PresetHata('forbidden', 'Yalnız tasarlayan ya da yönetici silebilir')
    conn.execute('UPDATE drone_sim_presets SET deleted_at = ? WHERE id = ?', (db.now(), p['id']))
    return p


# ---------------- bildirim ----------------
def atanan_bekleyenler(conn, uid):
    """Zil (notifications 'sim-assigned'): bana atanan, başkasının tasarladığı, silinmemiş ve henüz benim uçmadığım kayıtlı simülasyonlar."""
    return db.rows(conn.execute('''SELECT p.id, p.name, cu.full_name AS created_by_name FROM drone_sim_presets p LEFT JOIN users cu ON cu.id = p.created_by
                                   WHERE p.pilot_id = ? AND p.deleted_at IS NULL AND COALESCE(p.created_by, 0) != ?
                                     AND NOT EXISTS (SELECT 1 FROM drone_sim_runs r WHERE r.preset_id = p.id AND r.owner_id = ?)
                                   ORDER BY p.updated_at DESC''', (uid, uid, uid)))


def pilota_bildir(pilot_id, actor, ad, pid):
    """Atanan pilota anlık bildirim (Web Push + mobil). Kendine atamada gönderilmez; hata atamayı bozmaz."""
    if not pilot_id or pilot_id == actor['id']:
        return
    try:
        from . import push
        push.send([pilot_id], {'type': 'notif', 'title': 'Size bir simülasyon atandı', 'tag': f'notif-sim-assigned-{pid}',
                               'body': f'{ad} · {actor.get("full_name") or ""}'.strip(' ·'), 'url': f'/app#/drone/sim?tab=saved&preset={int(pid)}'})
    except Exception:   # noqa: BLE001
        pass
