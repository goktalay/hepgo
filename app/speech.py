"""Konuşma tanımanın modül bazında açılıp kapanması (Program Ayarları › Modül Ayarları).

Bir özellik ancak ikisi birden açıkken çalışır: Konuşma Tanıma entegrasyonu (document_media.whisper_available:
Entegrasyonlar › Konuşma Tanıma açık ve Whisper kurulu) VE o modüldeki anahtar (app_kv['speech.features']).
Entegrasyon çalışmıyorsa anahtar açılamaz. Kapalıyken sesler yalnız kaydedilir; metin / konuşmacı çıkarılmaz.
"""
import json

from . import db, document_media

KV_KEY = 'speech.features'
# anahtar → (sekme başlığı, ne yapar)
FEATURES = {
    'meetings': ('Toplantılar', 'Toplantı odasında alınan ses kaydı toplantı bitince metne çevrilir, konuşanlar ayrılır ve ses '
                                'profilleriyle tanınır.'),
    'meet': ('Online Toplantı', 'Online toplantı kayıtları metne çevrilir; her katılımcının sesi konuşmacı olarak etiketlenir ve '
                                'ses kimliği öğrenilir.'),
    'calls': ('Sesli Görüşmeler', 'Uygulama içi sesli görüşme kayıtları metne çevrilir ve konuşmacılara ayrılır.'),
    'documents': ('Evrak Yönetimi', 'Evrak olarak yüklenen ses ve videoların konuşması metne çevrilir; evrak aramasında bulunur.'),
    'dictation': ('Sesle Yazdırma', 'Çok satırlı metin kutularında mikrofon düğmesi: konuşulan metin kutuya yazılır (ses saklanmaz).'),
}


def _flags(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    try:
        data = json.loads(row[0]) if row else {}
    except ValueError:
        data = {}
    return {k: data.get(k, True) is not False for k in FEATURES}   # varsayılan: entegrasyon açılınca hepsi çalışır


def integration_ok():
    return document_media.whisper_available()


def enabled(feature, conn=None):
    """Bu modülde konuşma tanıma şu an çalışır mı (entegrasyon + modül anahtarı)?"""
    if not integration_ok():
        return False
    if conn is not None:
        return _flags(conn)[feature]
    with db.connect() as c:
        return _flags(c)[feature]


def view(conn):
    ok, flags = integration_ok(), _flags(conn)
    return {'integration': ok, 'features': [{'key': k, 'title': t, 'desc': d, 'on': flags[k], 'active': ok and flags[k]}
                                            for k, (t, d) in FEATURES.items()]}


def set_flag(conn, feature, on):
    if feature not in FEATURES:
        raise KeyError(feature)
    if on and not integration_ok():
        raise ValueError('Konuşma Tanıma entegrasyonu çalışmıyor; önce Program Ayarları › Entegrasyonlar › Konuşma Tanıma açılmalı')
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    data = json.loads(row[0]) if row else {}
    data[feature] = bool(on)
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV_KEY, json.dumps(data)))
    conn.commit()
