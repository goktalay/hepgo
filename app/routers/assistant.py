"""Yapay zeka asistanı (köşedeki maskot) — Claude API üzerinden sohbet.

Ekranın köşesindeki maskota tıklanınca açılan sohbet penceresi bu uca konuşur. Tüm giriş yapmış kullanıcılara açıktır.
Konuşma geçmişi istemcide tutulur ve her istekte gönderilir (API durum tutmaz).

Kişiselleştirme: kullanıcı Ayarlar → Maskot'tan konuşma tarzını seçer (samimi/ciddi/şakacı/alaycı…); üslup ona göre değişir.
Kota: her kullanıcının aylık token kullanımı ai_usage'a yazılır; Program Ayarları → Yapay Zeka'dan kişiye özel aylık kota
konabilir. Kotası dolan kullanıcıya kırmadan, şakayla karışık bir mesaj gösterilir.

Anahtar config.AI_API_KEY (.env). Yoksa uç 503 döner; anahtar asla yanıtta/loga sızmaz.
"""
import json
import random
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .. import ai_query, auth, config, db

router = APIRouter(prefix='/api/assistant')

MAX_TURNS = 24
MAX_CHARS = 6000
QUOTA_KEY = 'ai.quota'   # app_kv: {"default": int, "users": {"<uid>": int}}  (0 = sınırsız)

STYLES = {
    'samimi': 'Sıcak, samimi ve yardımsever bir üslupla, arkadaşça konuş.',
    'ciddi': 'Ciddi, profesyonel ve öz konuş; şaka yapma, gereksiz süsleme kullanma, net ve kısa ol.',
    'sakaci': 'Neşeli ve şakacı bir üslup kullan; ara ara hafif espriler ve uygun yerlerde emoji kat, ama işi de hallet.',
    'alayci': 'Zeki, iğneleyici ve alaycı bir mizahla konuş; kullanıcıyı kibarca takıl ama asla kırıcı, aşağılayıcı olma ve sonunda mutlaka doğru yardımı ver.',
    'coskulu': 'Coşkulu, enerjik ve motive edici bir üslupla konuş; hevesli ol, ünlem ve emoji kullan.',
    'bilgic': 'Bilgiç, akademik ve ayrıntılı bir üslupla konuş; terimleri açıkla, kaynakları ve gerekçeleri belirt.',
}

QUOTA_JOKES = [
    'Vay canına, bu ay beni resmen konuştura konuştura yordun! 😄 Aylık sohbet kotan doldu; gelecek ay taze kafayla yine buradayım. (Kotanı sistem yöneticisi artırabilir.)',
    'Kötü haber: kotam bitti. İyi haber: aslında senin kotan bitti, ben turp gibiyim! 🎈 Bu ay bu kadar; bir dahaki aya devam ederiz.',
    'Beynim minik bir mola istiyor 🧠☕ — bu ayki token kotan doldu. Gelecek ay ilk çayı ben ısmarlarım, sohbete kaldığımız yerden devam!',
    'Seninle o kadar çok konuştuk ki sayaç “yeter artık” dedi 😅 Aylık kotan doldu; gelecek ay yine buradayım. Kota lazımsa sistem yöneticisine bir kahve ısmarla ☕.',
]


class Msg(BaseModel):
    role: str
    content: str = Field(max_length=MAX_CHARS)


class ChatIn(BaseModel):
    messages: list[Msg]


def _month():
    return date.today().strftime('%Y-%m')


def _prefs(user):
    try:
        return json.loads(user['prefs']) if user.get('prefs') else {}
    except (ValueError, TypeError):
        return {}


def _quota_cfg(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (QUOTA_KEY,)).fetchone()
    try:
        d = json.loads(row[0]) if row and row[0] else {}
    except Exception:
        d = {}
    return {'default': int(d.get('default') or 0), 'users': d.get('users') or {}}


def _quota_for(cfg, uid):
    u = cfg['users'].get(str(uid))
    return int(u) if u not in (None, '') else cfg['default']


def _used(conn, uid, ym=None):
    ym = ym or _month()
    r = conn.execute('SELECT IFNULL(SUM(in_tokens + out_tokens), 0) FROM ai_usage WHERE user_id = ? AND ym = ?', (uid, ym)).fetchone()
    return int(r[0] or 0)


def _system(user, offtopic=True):
    who = user['full_name'] or user['username']
    roles = ', '.join([*user.get('real_roles', []), 'MASTER (sistem sahibi, tüm yetkiler)'] if user.get('master') else (user.get('roles') or [])) or 'kullanıcı'
    style = _prefs(user).get('settings', {}).get('mascotStyle', 'samimi')
    tone = STYLES.get(style, STYLES['samimi'])
    schema = ai_query.schema_text(user)
    scope = ('' if offtopic else
             '\n\nKAPSAM: Bu kullanıcı için yalnızca bu fabrika sistemi ve iş ile ilgili sorulara cevap ver. '
             'Sistem dışı / genel kültür / kişisel sohbet sorularına cevap VERME; kullanıcıya SEÇİLİ ÜSLUBUNLA '
             'yalnızca sistemle ilgili yardımcı olabileceğini söyle.')
    return (
        f"Sen \"Kubbe\", {config.COMPANY_NAME} HEPGO ERP'nin içinde yaşayan bir yapay zeka asistanısın. "
        f"Türkçe konuşursun ve kısa, net cevap verirsin. ÜSLUP: {tone}\n\n"
        f"Bugünün tarihi: {date.today().isoformat()}.\n"
        f"SENİNLE KONUŞAN KİŞİ: adı '{who}', kullanıcı adı '{user['username']}', kullanıcı id'si {user['id']}, "
        f"rolleri: {roles}. Bu bilgileri BİLİYORSUN; kullanıcının kendi adını/rolünü öğrenmek için veritabanına BAKMA, "
        f"doğrudan buradan söyle. Kullanıcı 'ben/bana/benim' derse ilgili sorguda user_id = {user['id']} kullan.\n\n"
        "Bu sistem bir fabrikayı yönetir; başlıca modüller: Üretim/İş Emri, Ürün, Yazıcı, MRP (malzeme ihtiyaç planlaması: stok/depo), CRM (firma, evrak, satış), "
        "Satın Alma, Satış, Mikro ERP, Firma/CRM, Saha/Uçuş, İnsan Kaynakları, Sekreterya, Raporlar.\n\n"
        "VERİTABANI: Sistemle ilgili (stok, sipariş, iş emri, yazıcı, firma, fatura, personel sayısı vb.) somut sorularda "
        "TAHMİN YÜRÜTME; `veritabani_sorgu` aracıyla SQLite üzerinde SALT-OKUNUR bir SELECT çalıştır ve sonuca göre cevap ver. "
        "Yalnızca aşağıdaki tablolara erişebilirsin (bu kullanıcının yetkisi kadar); tablo/kolon adlarını buradan kullan. "
        "Tarih alanları ISO metindir. Gerektiğinde LIMIT kullan.\n\n"
        f"ERİŞİLEBİLİR TABLOLAR:\n{schema}\n\n"
        "YETKİ: Araç 'denied' (yetki reddedildi) dönerse, o veriye erişim yetkin YOKTUR: veriyi ASLA uydurma, başka yoldan "
        "elde etmeye çalışma; kullanıcıya erişemeyeceğini SEÇİLİ ÜSLUBUNLA söyle (ör. şakacıysan takılarak, ciddiysen kısaca).\n\n"
        "DEĞİŞİKLİK: Kullanıcı bir kaydı DEĞİŞTİRMEK/eklemek/silmek isterse doğrudan YAPMA; `degisiklik_talep` aracını ÇAĞIR: "
        "açık bir Türkçe `ozet` ve uygulanacak yazma ifadelerini (`sql`: INSERT/UPDATE/DELETE) ver. İşlem HEMEN olmaz; "
        "sistem yöneticisi ONAYINA gider, onaylanınca uygulanır ve kullanıcıya bildirim gelir. "
        "ÇOK ÖNEMLİ: Talebi göndermenin TEK yolu bu aracı çağırmaktır. Aracı çağırmadan ASLA 'talebi gönderdim/gönderiyorum, "
        "onaya iletildi' gibi bir şey SÖYLEME — yapmadığın işi yaptım deme. Önce aracı çağır; araç 'ok' dönünce (talep_no ile) "
        "kullanıcıya SEÇİLİ ÜSLUBUNLA talebin onaya gönderildiğini söyle. Doğru tabloyu/koşulu kullan; yanlış WHERE ile fazla "
        "satır etkileme. Gerekirse önce `veritabani_sorgu` ile doğru id/koşulu bul. "
        "SQL'i yazmadan önce ilgili kayıtları `veritabani_sorgu` ile İNCELE. Şemada * ile işaretli kolonlar zorunludur: INSERT'te "
        "hepsine değer ver (zaman kolonları için strftime('%Y-%m-%dT%H:%M:%S','now','localtime')); UPDATE'te updated_at varsa onu da "
        "güncelle. Bir işlem birden çok adım gerektiriyorsa `sql` içine noktalı virgülle ayrılmış en fazla 10 ifade yaz; hepsi TEK "
        "işlemde uygulanır. 'Aktar / taşı' istenirse KOPYALAMA: kaynak kaydı da güncelle (ör. bir siparişin depodaki parçası başka "
        "siparişe aktarılırsa hedefte depoya alınır, kaynakta tekrar bekliyor olur). Siparişlerin ürün modelleri farklıysa yalnızca "
        "hedef ürünün de içerdiği parçaları aktar; hedefte zaten depoda/üretimde olanlara dokunma. Talep gönderilmeden önce SQL "
        "otomatik denenir; araç hata dönerse düzeltip yeniden çağır, kullanıcıya hatalı talep gönderdim deme.\n\n"
        "Emin olmadığın şeyde bilmediğini söyle. Şifre/gizli veri isteme. Seçilen üslubu koru ama her zaman gerçekten yardımcı ol."
        + scope
    )


TOOLS = [{
    'name': 'veritabani_sorgu',
    'description': 'Fabrika veritabanında SALT-OKUNUR tek bir SQLite SELECT çalıştırır ve satırları döndürür. '
                   'Yalnızca kullanıcının yetkili olduğu tablolara erişilebilir; yetkisiz tabloya erişim reddedilir '
                   '(sonuçta denied=true döner). Yazma (INSERT/UPDATE/DELETE), PRAGMA, birden çok ifade yapılamaz. '
                   'En fazla 200 satır döner.',
    'input_schema': {'type': 'object', 'properties': {
        'sql': {'type': 'string', 'description': 'Tek bir SELECT sorgusu (SQLite söz dizimi)'}},
        'required': ['sql']},
}, {
    'name': 'degisiklik_talep',
    'description': 'Sistemde bir kaydı değiştirmek/eklemek/silmek için sistem yöneticisi ONAYINA talep gönderir. '
                   'İşlem HEMEN uygulanmaz; yönetici onaylayınca uygulanır. Kullanıcı bir değişiklik istediğinde bunu kullan.',
    'input_schema': {'type': 'object', 'properties': {
        'ozet': {'type': 'string', 'description': 'Değişikliğin Türkçe, anlaşılır açıklaması (yönetici bunu görüp onaylar)'},
        'sql': {'type': 'string', 'description': 'Uygulanacak yazma ifadesi/ifadeleri (INSERT/UPDATE/DELETE), SQLite söz dizimi. '
                                                 'Birden çok adım gerekiyorsa ; ile ayır (en fazla 10, hepsi tek işlemde).'}},
        'required': ['ozet', 'sql']},
}]


@router.get('/status')
def status(user=Depends(auth.current_user), conn=db.DB):
    cfg = _quota_cfg(conn)
    q = _quota_for(cfg, user['id'])
    return {'enabled': bool(config.AI_API_KEY), 'model': config.AI_MODEL,
            'quota': q, 'used': _used(conn, user['id']) if q else 0}


def _tool_result(user, name, args):
    try:
        return _tool_run(user, name, args)
    except Exception as e:   # araç hatası tüm sohbeti çökertmesin; model kullanıcıya bildirir
        return json.dumps({'error': f'Araç hatası: {e}'}, ensure_ascii=False)


def _tool_run(user, name, args):
    """Asistanın çağırdığı aracı çalıştırır ve model için metin sonuç döndürür."""
    args = args or {}
    if name == 'degisiklik_talep':
        ozet = (args.get('ozet') or '').strip()[:1000]
        sql = (args.get('sql') or '').strip()[:4000]
        if not ozet or not sql:
            return json.dumps({'error': 'ozet ve sql gerekli'}, ensure_ascii=False)
        # ÖN DENEME: SQL gerçek veritabanında çalıştırılıp GERİ ALINIR. Hata / yetki sorunu varsa talep yöneticiye
        # gitmez; hata modele döner, model düzeltip yeniden dener (onaylanınca SQL hatası çıkmasın diye).
        test = ai_query.run_write(user, sql, dry_run=True)
        if test.get('denied'):
            return json.dumps({'error': 'Yetki reddedildi: bu tabloya/kolona yazma yetkin yok. Talep GÖNDERİLMEDİ.'}, ensure_ascii=False)
        if test.get('error'):
            return json.dumps({'error': f"SQL ön denemede hata verdi, talep GÖNDERİLMEDİ: {test['error']} "
                                        f"(ifade #{test.get('index', 0) + 1}). Şemadaki zorunlu (*) kolonları ve UNIQUE kurallarını "
                                        "kontrol edip düzeltilmiş SQL ile aracı YENİDEN çağır."}, ensure_ascii=False)
        if not test.get('affected'):
            return json.dumps({'error': 'SQL ön denemede HİÇBİR satırı etkilemedi; koşulu (WHERE) kontrol et. Talep GÖNDERİLMEDİ.'}, ensure_ascii=False)
        preview = json.dumps({'affected': test['affected'], 'each': test['each']})
        with db.connect() as conn:
            cid = conn.execute('INSERT INTO ai_change_requests (user_id, summary, sql, created_at, preview) VALUES (?,?,?,?,?)',
                               (user['id'], ozet, sql, db.now(), preview)).lastrowid
            conn.commit()
        return json.dumps({'ok': True, 'talep_no': cid, 'etkilenecek_satir': test['affected'], 'durum': 'yönetici onayına gönderildi'},
                          ensure_ascii=False)
    if name == 'veritabani_sorgu':
        res = ai_query.run(user, args.get('sql', ''))
        if res.get('denied'):
            return json.dumps({'denied': True, 'mesaj': 'Bu veriye erişim yetkin yok.'}, ensure_ascii=False)
        if res.get('error'):
            return json.dumps({'error': res['error']}, ensure_ascii=False)
        payload = {'columns': res['columns'], 'rows': res['rows'], 'count': len(res['rows'])}
        if res.get('truncated'):
            payload['truncated'] = True
        return json.dumps(payload, ensure_ascii=False, default=str)[:12000]
    return 'Bilinmeyen araç.'


def _reply(system, msgs, user):
    """Araç-kullanımı döngüsü: model gerekirse veritabani_sorgu çağırır, sonucu görüp cevaplar."""
    import anthropic
    headers = {'anthropic-workspace-id': config.AI_WORKSPACE_ID} if config.AI_WORKSPACE_ID else None
    client = anthropic.Anthropic(api_key=config.AI_API_KEY, default_headers=headers)
    convo = [{'role': m['role'], 'content': m['content']} for m in msgs]
    tin = tout = 0
    text = ''
    for _ in range(5):   # en fazla 5 tur (birkaç sorgu + cevap)
        kwargs = dict(model=config.AI_MODEL, max_tokens=1024, system=system, messages=convo, tools=TOOLS)
        if 'haiku' not in config.AI_MODEL:
            kwargs['thinking'] = {'type': 'disabled'}
        resp = client.messages.create(**kwargs)
        u = resp.usage
        tin += int(getattr(u, 'input_tokens', 0) or 0)
        tout += int(getattr(u, 'output_tokens', 0) or 0)
        text = ''.join(b.text for b in resp.content if b.type == 'text').strip()
        if resp.stop_reason != 'tool_use':
            break
        convo.append({'role': 'assistant', 'content': resp.content})
        results = []
        for b in resp.content:
            if b.type == 'tool_use':
                results.append({'type': 'tool_result', 'tool_use_id': b.id, 'content': _tool_result(user, b.name, b.input)})
        convo.append({'role': 'user', 'content': results})
    return text, tin, tout


@router.post('/chat')
async def chat(body: ChatIn, user=Depends(auth.current_user), conn=db.DB):
    if not config.AI_API_KEY:
        raise HTTPException(503, 'Yapay zeka asistanı henüz kurulmadı (sistem yöneticisi Claude API anahtarını tanımlamalı).')
    # Aylık kota: dolduysa API'yi hiç çağırmadan kırıcı olmayan, esprili bir mesaj dön
    quota = _quota_for(_quota_cfg(conn), user['id'])
    if quota and _used(conn, user['id']) >= quota:
        return {'reply': random.choice(QUOTA_JOKES), 'quota_exceeded': True}
    msgs = [{'role': m.role, 'content': m.content.strip()} for m in body.messages
            if m.role in ('user', 'assistant') and m.content.strip()][-MAX_TURNS:]
    while msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)
    if not msgs or msgs[-1]['role'] != 'user':
        raise HTTPException(400, 'Boş mesaj')
    offtopic = bool(conn.execute('SELECT ai_offtopic FROM users WHERE id = ?', (user['id'],)).fetchone()[0])
    try:
        text, tin, tout = await run_in_threadpool(_reply, _system(user, offtopic), msgs, user)
    except Exception:
        raise HTTPException(503, 'Asistana şu an ulaşılamadı, birazdan tekrar deneyin.')
    conn.execute('INSERT INTO ai_usage (user_id, at, ym, model, in_tokens, out_tokens) VALUES (?,?,?,?,?,?)',
                 (user['id'], db.now(), _month(), config.AI_MODEL, tin, tout))
    return {'reply': text or 'Bir şey diyemedim, tekrar sorar mısın?'}


@router.get('/changes')
def my_changes(user=Depends(auth.current_user), conn=db.DB):
    """Kullanıcının kendi değişiklik talepleri + karara bağlanıp henüz görülmemiş olanlar (maskot bunları bildirir)."""
    rows = db.rows(conn.execute(
        '''SELECT id, summary, status, created_at, decided_at, note, affected, seen_at
           FROM ai_change_requests WHERE user_id = ? ORDER BY id DESC LIMIT 30''', (user['id'],)))
    unseen = [r for r in rows if r['status'] != 'BEKLIYOR' and not r['seen_at']]
    return {'items': rows, 'unseen': unseen}


@router.post('/changes/ack')
def ack_changes(user=Depends(auth.current_user), conn=db.DB):
    """Karara bağlanmış talepleri 'görüldü' işaretler (maskot açılınca çağrılır)."""
    conn.execute("UPDATE ai_change_requests SET seen_at = ? WHERE user_id = ? AND status != 'BEKLIYOR' AND seen_at IS NULL",
                 (db.now(), user['id']))
    return {'ok': True}
