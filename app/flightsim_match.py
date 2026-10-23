"""Uçuş Simülatörü — ÇOK OYUNCULU KARŞILAŞMA, HEPGO çalışma zamanı (docs/ucus-simulatoru.md §33).

Saf mantık `flightsim_match_core` (durum makinesi, halka üretimi, geçiş tespiti, sıralama — SIMUMAV aşama 2 de onu kullanır). Burada HEPGO'ya
özgü kısımlar: oyuncu SITL oturumları (`flightsim.MANAGER.ac(start=…, match_id=…)`; ayrı tavan MATCH_MAX_SESSIONS), telemetri kancasıyla
sunucuda halka doğrulama, komut kapısı (yarış başlamadan ARM/kalkış yok), karşılaşma WS yayını (`/ws/drone/match/{id}`: anlık görüntü +
10 Hz konum çerçeveleri + halka/bitiş olayları + sohbet), `drone_sim_matches` satırı, davet bildirimi (zil 'sim-match-invite' + anlık push).

Akış: kurucu sihirbazdan oluşturur (LOBI; kurucu "geldi") → davetliler bildirimden salona gelir (`join`) → hepsi gelince HAZIRLIK: her oyuncuya
kendi başlangıç noktasında SITL açılır; istemci oturum ekranına geçer, 3B dünya kurulunca WS `ready` → herkes hazır → GERI_SAYIM (sunucu saatiyle
`start_at`) → YARIS (ARM/kalkış serbest) → ilk bitiren / süre sınırı → BITTI (sonuç herkese) → oturumlar KAPANIS_GECIKME_S sonra kapanır.
§41 İT DALAŞI (`kind: 'dogfight'`, tam 2 oyuncu): roller HAZIRLIK'ta atanır, başlangıç noktaları `core.it_baslangiclari` (rol başına), angajman
sunucuda (`core.ItDalasi`; her iki oyuncunun telemetrisi tele kancasından), çarpışma (`gorev.crashes` artışı) → `k.carpti`, `pos` çerçevesinde
`df` (mesafe, koni açısı, tutma süresi, koruma) — HUD. Yarışta Sıfırla yok (kaçış ışınlanması olmasın).
§44 YAPAY ZEKÂ PİLOT: kurucu oluştururken (`bots`) ya da salonda (`POST /{id}/bot`) bot ekler; bot "geldi" sayılır, HAZIRLIK'ta KENDİ SITL oturumu
açılır (karşılaşma tavanına sayılır; sahibi bot kimliği → insan komut veremez; uçuş kaydı yok), oturum HAZIR olunca hazırdır; YARIS'ta
`flightsim_match_bot.BotSurucu` ARM + kalkış + 5 Hz GUIDED komutlarıyla uçurur. Bot kazanırsa `winner_id` NULL (kullanıcı değil; sonuç JSON'unda).
§47 FPV PARKUR YARIŞI (`kind: 'fpv'`): hazır parkurun kontrol noktaları (`flightsim_fpv.kontrol_noktalari`) halka yerine; başlangıç pedi ızgarası
(`parkur_baslangiclari`); çarpma kuralı `reset` olayında oyuncu aracına Sıfırla; bitişte insan oyuncuların süreleri + hayalet kaydı
`drone_fpv_records`'a yazılır, sonuç satırlarına kişisel rekor (önceki en iyi, yeni rekor mu) eklenir. Tek kişilik karşılaşma (davetli/bot yok)
= zaman denemesi (halka yarışı ve FPV parkuru).
"""
import asyncio
import json
import random
import time

from . import db, flightsim
from . import flightsim_fpv as fpv
from . import flightsim_match_bot as mbot
from . import flightsim_match_core as core

POS_HZ = 10                      # konum çerçevesi yayını (diğer oyuncular 3B'de)
KAPANIS_GECIKME_S = 8.0          # BITTI/IPTAL → oyuncu oturumları kapanır (sonuç ekranı SITL'e ihtiyaç duymaz)
BELLEK_TUT_S = 15 * 60.0         # biten karşılaşma bellekte (WS/GET canlı); sonra yalnız DB
VIEWER_QUEUE = 128
SOHBET_MAX = 300


class MatchRuntime:
    def __init__(self, yonetici, k, center, settings):
        self.yonetici = yonetici
        self.k = k                      # core.Karsilasma
        self.center = dict(center)
        self.settings = dict(settings)
        self.viewers = {}               # ws → asyncio.Queue
        self.sessions = {}              # uid → SimSession
        self.ready = set()              # istemcisi `ready` gönderen oyuncular
        self.task = None
        self.loop = None
        self.sohbet = []                # son mesajlar (yeni bağlanana hello'da)
        self._son_kayit = None
        self._kapanis = None
        self.bitti_t = None
        self.bot_gorevleri = {}         # §44 uid → asyncio.Task (BotSurucu)

    # ---------------------------------------------------------------- yayın
    def _yay(self, obj):
        txt = json.dumps(obj, ensure_ascii=False, default=str)
        for q in list(self.viewers.values()):
            flightsim._kuyruga(q, txt, obj.get('t') != 'pos')

    def anlik(self):
        d = self.k.dict(time.time())
        d['center'] = {k: self.center.get(k) for k in ('id', 'name', 'lat', 'lon', 'alt')}
        d['viewers'] = sorted({getattr(w, '_uid', None) for w in self.viewers} - {None})
        return d

    def izleyici_ekle(self, ws, uid):
        q = asyncio.Queue(maxsize=VIEWER_QUEUE)
        ws._uid = uid
        self.viewers[ws] = q
        return q

    def izleyici_sil(self, ws):
        self.viewers.pop(ws, None)

    # ---------------------------------------------------------------- olaylar
    def isle(self, olaylar):
        """Çekirdek olayları: yayın + yan etkiler (durum değişimi → oturum aç/kapat, kayıt). Senkron (olay döngüsünde)."""
        if not olaylar:
            return
        durum_degisti = False
        for e in olaylar:
            if e['t'] == 'result' and self.k.tur == core.TUR_FPV:
                try:
                    fpv_kayit_yaz(self.k, e['result'])   # §47 süreler + hayalet; satırlara kişisel rekor bilgisi
                except Exception:   # noqa: BLE001
                    pass
            elif e['t'] == 'reset':   # §47 çarpma kuralı "sıfırla": aracı başlangıca döndür
                s = self.sessions.get(e['id'])
                if s is not None:
                    asyncio.get_running_loop().create_task(_sifirla(s))
            self._yay(e)
            if e['t'] == 'state':
                durum_degisti = True
                self._durum_yan_etkisi(e['state'])
        self._yay({'t': 'match', 'match': self.anlik()})
        if durum_degisti or any(e['t'] in ('player', 'finish') for e in olaylar):
            self.kaydet()

    def _durum_yan_etkisi(self, st):
        if st == core.HAZIRLIK:
            for o in self.k.aktifler():
                asyncio.get_running_loop().create_task(self._oturum_ac(o))
        elif st in core.SON_DURUMLAR:
            self.bitti_t = time.time()
            if self._kapanis is None:
                self._kapanis = asyncio.get_running_loop().create_task(self._oturumlari_kapat())

    async def _oturum_ac(self, o):
        """Oyuncunun SITL oturumu: ortak ayarlar + kendi başlangıç noktası. Hata → oyuncu düşer."""
        from .routers.flightsim import SessionIn, oturum_ac
        from fastapi import HTTPException
        k = self.k
        n = len(k.aktifler())
        pist = (self.settings.get('world') or {}).get('runway_heading') or 0
        if k.tur == core.TUR_IT:   # §41: rol başına (kaçan önde)
            x, y, yaw = core.it_baslangiclari(k.halka_ayar, self.settings['type'], pist)[o.rol or core.KOVALAYAN]
        elif k.tur == core.TUR_FPV:   # §47: başlangıç pedi ızgarası
            x, y, yaw = fpv.parkur_baslangiclari(fpv.parkur(k.halka_ayar['course_id']), n)[(o.sira_no or 0) % n]
        else:
            noktalar = core.baslangic_noktalari(n, self.settings['type'], pist, hedef=(k.halkalar[0]['x'], k.halkalar[0]['y']) if k.halkalar else None)
            x, y, yaw = noktalar[o.sira_no % len(noktalar)]
        lat, lon = core.latlon(self.center['lat'], self.center['lon'], x, y)
        o.baslangic = {'x': x, 'y': y, 'lat': round(lat, 7), 'lon': round(lon, 7), 'yaw_deg': yaw}
        body = SessionIn(**{**self.settings, 'mode': 'sitl', 'rec': {'bin': False}})
        # §44 bot: sahibi bot kimliği (insanın REST/WS komutu mac_yazabilir'de reddedilir), kullanıcı/denetim kaydı kurucu adına
        owner = {'id': o.uid, 'name': o.ad, 'bot': True} if o.bot else {'id': o.uid, 'name': o.ad}
        audit_uid = k.kurucu_id if o.bot else o.uid
        try:
            s = await oturum_ac(body, owner, {'id': audit_uid, 'modules': []}, audit_uid,
                                start={'lat': lat, 'lon': lon, 'yaw_deg': None if self.settings['type'] in core.UCAK_TIPLER else yaw}, match_id=k.id)
        except HTTPException as e:
            self.isle(k.dusur(o.uid, time.time(), f'Simülatör açılamadı: {e.detail}'))
            return
        except Exception as e:   # noqa: BLE001
            self.isle(k.dusur(o.uid, time.time(), f'Simülatör açılamadı: {e}'))
            return
        if k.durum in core.SON_DURUMLAR or o.durum in core.KATILMAYAN:
            await flightsim.MANAGER.kapat(s.id, 'karsilasma_bitti')
            return
        self.sessions[o.uid] = s
        k.oturum_bagla(o.uid, s.id)
        s.tele_kanca = lambda tele, uid=o.uid, ss=s: self._tele(uid, ss, tele)
        s.komut_kapisi = self._kapi
        if o.bot:   # §44: istemcisi yok → oturum HAZIR olunca hazır; sürücü yarışta uçurur
            s.bot = {'uid': o.uid, 'level': o.bot}
            self.ready.add(o.uid)
            self.bot_gorevleri[o.uid] = asyncio.get_running_loop().create_task(mbot.BotSurucu(k, o.uid, s, self.settings['type']).calis())
        self.isle([{'t': 'player', 'id': o.uid, 'status': o.durum, 'session_id': s.id}])

    def _kapi(self, ad):
        if ad == 'reset':   # §41: Sıfırla başlangıca ışınlar → it dalaşında (geri sayım + yarış) yok; halka yarışında serbest
            return 'İt dalaşında Sıfırla yok' if self.k.tur == core.TUR_IT and self.k.durum in (core.GERI_SAYIM, core.YARIS) else None
        if self.k.durum == core.YARIS:
            return None
        if self.k.durum in core.SON_DURUMLAR:
            return 'Karşılaşma bitti'
        if ad == 'rc':
            return 'Yarış başlamadı'
        return 'Yarış henüz başlamadı: geri sayımı bekleyin'

    def _tele(self, uid, s, tele):
        o = self.k.oyuncu(uid)
        if o is None:
            return
        o.poz = {'lat': tele.get('lat'), 'lon': tele.get('lon'), 'alt_msl': tele.get('alt_msl'), 'alt_rel': tele.get('alt_rel'), 'yaw': tele.get('yaw'),
                 'roll': tele.get('roll'), 'pitch': tele.get('pitch'), 'gs': tele.get('groundspeed'), 'armed': bool(tele.get('armed'))}
        try:
            n = len(getattr(s.gorev, 'crashes', []) or [])
            if n > o.carpisma and self.k.tur == core.TUR_IT:   # §41: kesin çarpışma kaydı → çarpan kaybeder
                o.carpisma = n
                self.isle(self.k.carpti(uid, time.time()))
            o.carpisma = n
        except Exception:   # noqa: BLE001
            pass
        if self.k.durum == core.YARIS and tele.get('lat') is not None:
            self.isle(self.k.konum(uid, tele['lat'], tele['lon'], float(tele.get('alt_msl') or 0), time.time(), tele.get('groundspeed'),
                                   heading=tele.get('heading'), pitch=tele.get('pitch'), roll=tele.get('roll'), yaw=tele.get('yaw')))

    def pos_cercevesi(self, now):
        p = []
        for o in self.k.oyuncular.values():
            if o.poz is None or o.durum in core.KATILMAYAN:
                continue
            iz = o.iz
            p.append({'id': o.uid, **{k: (round(v, 7) if k in ('lat', 'lon') else round(v, 3)) if isinstance(v, float) else v for k, v in o.poz.items()},
                      'rings': (iz.sira if hasattr(iz, 'ozet') else len(iz.gecisler)) if iz else 0, 'next': (iz.sira + 1) if iz and not iz.bitti else None,
                      'dist': round(iz.mesafe, 1) if iz and iz.mesafe is not None else None,
                      **({'lap': iz.tur, 'pen': round(iz.ceza, 2)} if iz is not None and hasattr(iz, 'ozet') else {})})
        out = {'t': 'pos', 'ts': round(now, 3), 'p': p}
        if self.k.tur == core.TUR_IT:   # §41 HUD: mesafe, koni açısı, tutma süresi, koruma, roller
            out['df'] = self.k.it_durum()
        return out

    # ---------------------------------------------------------------- döngü
    async def run(self):
        self.loop = asyncio.get_running_loop()
        aralik = 1.0 / POS_HZ
        try:
            while True:
                await asyncio.sleep(aralik)
                now = time.time()
                k = self.k
                self.isle(k.tik(now))
                if k.durum == core.HAZIRLIK:
                    for o in list(k.aktifler()):
                        s = self.sessions.get(o.uid)
                        if s is None:
                            continue
                        if s.state == 'HATA' or s.state == 'KAPANDI':
                            self.isle(k.dusur(o.uid, now, (s.sitl or {}).get('error') or 'Simülatör kapandı'))
                        elif s.state == 'HAZIR' and o.uid in self.ready and o.durum == core.HAZIRLANIYOR:
                            self.isle(k.hazir(o.uid, now))
                elif k.durum in (core.GERI_SAYIM, core.YARIS):
                    for o in list(k.aktifler()):
                        s = self.sessions.get(o.uid)
                        if s is not None and s.state == 'KAPANDI':
                            self.isle(k.ayril(o.uid, now) if k.durum == core.YARIS else k.dusur(o.uid, now, 'Simülatör kapandı'))
                    self._yay(self.pos_cercevesi(now))
                if k.durum in core.SON_DURUMLAR and now - (self.bitti_t or now) > BELLEK_TUT_S:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if self.k.durum not in core.SON_DURUMLAR:
                self.isle(self.k.iptal(time.time(), 'sunucu_kapaniyor'))
            await self._oturumlari_kapat(0)
            self.yonetici.matches.pop(self.k.id, None)

    async def _oturumlari_kapat(self, gecikme=KAPANIS_GECIKME_S):
        for t in list(self.bot_gorevleri.values()):   # §44 bot sürücüleri hemen durur (araç komutu kesilir)
            t.cancel()
        if gecikme:
            await asyncio.sleep(gecikme)
        for uid, s in list(self.sessions.items()):
            s.tele_kanca = None
            try:
                await flightsim.MANAGER.kapat(s.id, 'karsilasma_bitti')
            except Exception:   # noqa: BLE001
                pass

    # ---------------------------------------------------------------- kayıt
    def kaydet(self):
        k = self.k
        d = {'state': k.durum, 'reason': k.neden, 'rings': json.dumps(k.halkalar or [], ensure_ascii=False),
             'players': json.dumps([o.dict(len(k.halkalar or [])) for o in k.oyuncular.values()], ensure_ascii=False),
             'result': json.dumps(k.sonuc(), ensure_ascii=False) if k.durum == core.BITTI else None,
             'winner_id': k.kazanan if k.kazanan is not None and k.kazanan > 0 else None,   # §44 bot kazanırsa NULL (users FK); sonuç JSON'unda
             'bots': len(k.botlar()),
             'started_at': _iso(k.baslangic_t) if k.durum in (core.YARIS, core.BITTI) else None, 'ended_at': _iso(k.bitis_t) if k.bitis_t else None}
        mid = k.id

        def yaz():
            with db.connect() as conn:
                conn.execute('UPDATE drone_sim_matches SET state = ?, reason = ?, rings = ?, players = ?, result = ?, winner_id = ?, started_at = COALESCE(?, started_at), ended_at = ?, bots = ? WHERE id = ?',
                             (d['state'], d['reason'], d['rings'], d['players'], d['result'], d['winner_id'], d['started_at'], d['ended_at'], d['bots'], mid))
                conn.commit()
        try:
            asyncio.get_running_loop().run_in_executor(None, yaz)
        except RuntimeError:
            yaz()


def _iso(ts):
    if ts is None:
        return None
    from datetime import datetime
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds')


class MatchManager:
    def __init__(self):
        self.matches = {}
        self._kurtarildi = False

    def kurtar(self):
        """Sunucu açılışında bitmemiş karşılaşma satırları IPTAL (bellek kayboldu). İlk erişimde bir kez."""
        if self._kurtarildi:
            return
        self._kurtarildi = True
        try:
            with db.connect() as conn:
                ids = [r[0] for r in conn.execute("SELECT id FROM drone_sim_matches WHERE state NOT IN ('BITTI', 'IPTAL')")]
                ids = [i for i in ids if i not in self.matches]
                if ids:
                    conn.execute(f"UPDATE drone_sim_matches SET state = 'IPTAL', reason = 'sunucu_yeniden_basladi', ended_at = ? WHERE id IN ({','.join('?' * len(ids))})",
                                 [db.now(), *ids])
                    conn.commit()
        except Exception:   # noqa: BLE001
            pass

    def get(self, mid):
        try:
            return self.matches.get(int(mid))
        except (TypeError, ValueError):
            return None

    def ayrilmis_slot(self):
        """Bitmemiş karşılaşmaların katılabilecek oyuncu sayısı (eşzamanlı SITL tavanı MATCH_MAX_SESSIONS ile karşılaştırılır)."""
        return sum(len(r.k.aktifler()) for r in self.matches.values() if r.k.durum not in core.SON_DURUMLAR)

    def davetler(self, uid):
        """Zil: kullanıcının bekleyen davetleri (LOBI, durum davetli) → [{id, host_name, created_at}]."""
        out = []
        for r in self.matches.values():
            o = r.k.oyuncu(uid)
            if r.k.durum == core.LOBI and o is not None and o.durum == core.DAVETLI:
                h = r.k.oyuncu(r.k.kurucu_id)
                out.append({'id': r.k.id, 'host_name': h.ad if h else '', 'created_at': r.k.olusturma_t})
        return sorted(out, key=lambda x: -x['created_at'])

    async def olustur(self, host, settings, center, rings_cfg, davetliler, tur=core.TUR_HALKA, botlar=()):
        """host {id, name}; settings: doğrulanmış oturum gövdesi; center: merkez satırı; rings_cfg: core.halka_ayar_dogrula çıktısı (§41 it dalaşında
        core.it_ayar_dogrula çıktısı); davetliler [(uid, ad)] (doğrulanmış); §44 botlar [seviye] (yapay zekâ pilotlar). Dönüş MatchRuntime."""
        self.kurtar()
        botlar = list(botlar or ())
        for sev in botlar:
            core.bot_seviye(sev)
        n = 1 + len(davetliler) + len(botlar)
        if self.ayrilmis_slot() + n > flightsim.MATCH_MAX_SESSIONS:
            bot_not = f' — her yapay zekâ pilot da kendi simülatörünü kullanır ({len(botlar)} bot)' if botlar else ''
            raise core.MacHata('limit', f'Şu an yeterli simülatör kapasitesi yok (eşzamanlı en çok {flightsim.MATCH_MAX_SESSIONS} karşılaşma oyuncusu, '
                               f'{max(0, flightsim.MATCH_MAX_SESSIONS - self.ayrilmis_slot())} boş; bu karşılaşma {n} ister){bot_not}; bir karşılaşmanın bitmesini bekleyin')
        bot_kayit = [(-(i + 1), core.bot_adi(sev, i), sev, core.BOT_RENKLERI[i % len(core.BOT_RENKLERI)]) for i, sev in enumerate(botlar)]
        cfg = dict(rings_cfg)
        if not cfg.get('seed'):
            cfg['seed'] = random.randint(1, 2 ** 31 - 2)
        merkez = {'lat': float(center['lat']), 'lon': float(center['lon']), 'alt': float(center['alt']) if center.get('alt') is not None else 0.0}
        it = tur == core.TUR_IT
        oyun_cfg = tur in (core.TUR_IT, core.TUR_FPV)   # ayar game_cfg sütununda (rings_cfg '{}')
        halkalar = [] if it else fpv.kontrol_noktalari(cfg, merkez) if tur == core.TUR_FPV else core.halkalar_uret(cfg, merkez)
        now = time.time()
        # çekirdek doğrulaması (davetli sayısı, tavan; it dalaşında tam 2 oyuncu) DB satırından önce
        core.Karsilasma(0, (host['id'], host['name']), davetliler, settings, cfg, merkez, now, halkalar, tur=tur, botlar=bot_kayit)
        loop = asyncio.get_running_loop()

        def ekle():
            with db.connect() as conn:
                cur = conn.execute('INSERT INTO drone_sim_matches (host_id, state, settings, rings_cfg, rings, players, created_at, kind, game_cfg) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                   (host['id'], core.LOBI, json.dumps(settings, ensure_ascii=False), '{}' if oyun_cfg else json.dumps(cfg), json.dumps(halkalar), '[]', db.now(),
                                    tur, json.dumps(cfg) if oyun_cfg else None))
                mid = cur.lastrowid
                db.audit(conn, host['id'], 'Çok oyunculu karşılaşma oluşturdu', 'drone_sim_match', mid,
                         f"{settings.get('type')} · {center.get('name')} · " + ('it dalaşı' if it else f"FPV parkuru {cfg['course_id']} × {cfg['laps']} tur" if tur == core.TUR_FPV else f"{cfg['count']} halka") + f" · davetli: {', '.join(a for _, a in davetliler) or '-'}"
                         + (f" · yapay zekâ: {', '.join(b[1] for b in bot_kayit)}" if bot_kayit else ''))
                conn.commit()
                return mid
        mid = await loop.run_in_executor(None, ekle)
        k = core.Karsilasma(mid, (host['id'], host['name']), davetliler, settings, cfg, merkez, now, halkalar, tur=tur, botlar=bot_kayit)
        r = MatchRuntime(self, k, center, settings)
        self.matches[mid] = r
        r.kaydet()
        r.task = loop.create_task(r.run())
        if davetliler:
            _davet_bildir([u for u, _ in davetliler], host, mid, settings, center, tur)
        else:   # §44 yalnız yapay zekâ rakip(ler) / §47 tek kişilik: beklenecek davetli yok → HAZIRLIK
            r.isle(k.lobi_denetle(time.time()))
        return r

    async def kapat_hepsi(self):
        for r in list(self.matches.values()):
            if r.task is not None and not r.task.done():
                r.task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(r.task), 30)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):   # noqa: BLE001
                    pass
        self.matches.clear()


def _davet_bildir(uids, host, mid, settings, center, tur=core.TUR_HALKA):
    """Davetlilere anlık bildirim (Web Push + mobil); zil ayrıca 'sim-match-invite' taramasıyla (push=False — çift olmasın)."""
    try:
        from . import push
        push.send(list(uids), {'type': 'notif', 'title': 'Karşılaşma daveti', 'tag': f'notif-sim-match-{int(mid)}',
                               'body': f"{host.get('name') or ''} sizi {'it dalaşına' if tur == core.TUR_IT else 'FPV parkur yarışına' if tur == core.TUR_FPV else 'halka yarışına'} davet etti · {center.get('name') or ''}".strip(' ·'),
                               'url': f'/app#/drone/sim/match/{int(mid)}'})
    except Exception:   # noqa: BLE001
        pass


async def _sifirla(s):
    try:
        await s.komut('reset', {})
    except Exception:   # noqa: BLE001
        pass


def fpv_kayit_yaz(k, sonuc, conn=None):
    """§47 bitişte insan oyuncuların FPV parkur kaydı (`drone_fpv_records`): süre (ceza dahil), en iyi tur, tur/sektör süreleri, ara süreler,
    kaçırma/çarpma, hayalet (sıkıştırılmış). Sonuç satırlarına `pb_prev` (önceki kişisel en iyi) ve `new_pb` eklenir (yerinde)."""
    cid = k.halka_ayar.get('course_id')
    laps = int(k.halka_ayar.get('laps') or 0)
    satirlar = {p['id']: p for p in sonuc.get('standings') or []}
    kendi = conn is None
    conn = conn or db.connect()
    try:
        for o in k.oyuncular.values():
            p = satirlar.get(o.uid)
            if o.bot or o.uid <= 0 or p is None or o.iz is None or not hasattr(o.iz, 'ozet'):
                continue
            ozet = o.iz.ozet()
            onceki = conn.execute('SELECT MIN(time_s) FROM drone_fpv_records WHERE course_id = ? AND user_id = ? AND laps = ?', (cid, o.uid, laps)).fetchone()[0]
            p['pb_prev'] = onceki
            if ozet['total_s'] is None:
                p['new_pb'] = False
                continue
            p['new_pb'] = onceki is None or ozet['total_s'] < float(onceki)
            conn.execute('INSERT INTO drone_fpv_records (course_id, user_id, match_id, type, laps, time_s, best_lap_s, lap_times, sectors, splits, misses, hits, '
                         'penalty_s, crash_rule, ghost, solo, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (cid, o.uid, k.id, (k.ayar or {}).get('type'), laps, ozet['total_s'], ozet['best_lap_s'], json.dumps(ozet['lap_times']),
                          json.dumps(ozet['sectors']), json.dumps(ozet['splits']), ozet['misses'], ozet['hits'], ozet['pen_s'], k.halka_ayar.get('crash_rule'),
                          fpv.hayalet_kodla(o.iz.ornekler), 1 if sonuc.get('solo') else 0, db.now()))
        conn.commit()
    finally:
        if kendi:
            conn.close()


def satir_dict(r):
    """DB satırı → GET biçimi (bellekte olmayan, bitmiş karşılaşma)."""
    j = lambda v, d=None: json.loads(v) if v else d   # noqa: E731
    kind = r.get('kind') or core.TUR_HALKA
    return {'id': r['id'], 'state': r['state'], 'reason': r['reason'], 'host_id': r['host_id'], 'settings': j(r['settings'], {}),
            'rings_cfg': j(r['game_cfg'], {}) if kind in (core.TUR_IT, core.TUR_FPV) else j(r['rings_cfg'], {}), 'rings': j(r['rings'], []), 'players': j(r['players'], []), 'result': j(r['result']),
            'winner': (j(r['result']) or {}).get('winner', r['winner_id']) if r['result'] else r['winner_id'], 'created_at': r['created_at'], 'started_at': r['started_at'], 'ended_at': r['ended_at'], 'live': False, 'kind': kind}


MANAGER = MatchManager()
