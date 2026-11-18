"""Uçuş Simülatörü — KARIŞTIRMA (docs/ucus-simulatoru.md §48; yalnız HEPGO oturum ekranı).

Kullanıcı isteği: "Hepgo içinde simülasyon ekranında karıştırma diye bir bölüm olmalı, istersek spoofing ve gps jamming etkisini simüle etmemiz
gerekiyor."

Yalnız simülasyon: ArduPilot SITL'in kendi GPS benzetimi parametreleri (SIM_GPS1_*) oturum içinde sürülür; otopilot (EKF3, failsafe'ler) buna
gerçek donanımdaki gibi tepki verir. Etki alanı o oturumun SITL sürecidir.

- `cmd jam {gps?, spoof?, dur_s?}` ya da `{off: true}`; dönüş `{ok, jam: durum}`; WS `{t:'jam', …durum, reason}`.
  * `gps` — GPS karıştırma seviyesi: 'off' | 'light' (hafif: az uydu + kötü doğruluk + birkaç metrelik gezinen konum hatası; uçuş sürer, konum
    tutma gevşer) | 'heavy' (ağır: SIM_GPS1_JAM — kilit aralıklı düşer, konum yüzlerce metre savrulur → "GPS Glitch", EKF failsafe) |
    'full' (tam: SIM_GPS1_ENABLE 0 — alıcı susar; EKF konumsuz kalır → EKF failsafe / kipe göre LAND).
  * `spoof` — GPS aldatma `{on, dir 0…360°, speed 0…50 m/s, max_m 1…5000 m}`: alıcının bildirdiği konum gerçek konumdan `dir` yönünde
    `speed` hızıyla uzaklaşır, `max_m`'de durur (speed 0 → anında sıçrama). Ofset SIM_GPS1_GLTCH_X/Y (derece), sürükleme hızı SIM_GPS1_VERR_X/Y
    (NED m/s) ile birlikte yazılır: konum ve hız birbirini tutar. Hız IVME ile rampalanır — SITL ölçümü: havada 3 m/s'lik ANİ hız basamağını EKF
    ~10 sn reddedip sonra sıçrayarak kabul etti; yumuşak başlangıçta EKF sürüklenmeyi izler ve otopilot "yerinde kalmak" için aracı TERS yöne
    götürür (gerçek "yumuşak ele geçirme" davranışı).
  * `dur_s` — 0 = elle kapatılana dek; > 0 = bu kadar SİMÜLASYON saniyesi sonra kendiliğinden kapanır (SIM_SPEEDUP ile uyumlu).
- Adım simülasyon zamanıyladır (tele.tbm; ADIM_MS). Parametre yalnız değiştiğinde yazılır.
- GERÇEK KONUM KİPİ: karıştırma etkinken (ve kapandıktan sonra EKF gerçek konuma dönene dek) `tele.lat/lon` SITL fiziğinin GERÇEK konumudur
  (SIMSTATE, 50 Hz istenir); otopilotun sandığı konum `tele.nav_lat/nav_lon`, aradaki fark `tele.nav_err` (m). 3B sahne, çarpışma, hedefler ve
  görev izleme aracın gerçekte olduğu yeri kullanır; Mission Planner ve harekât paneli MAVLink'i ham aldığından otopilotun aldatılmış konumunu
  görür (sahadaki yer istasyonu gibi). İrtifa ve hız alanları EKF'ten kalır.
- Sahte kinematik (SITL'siz) kipte fiziksel etki yoktur: yalnız göstergeler (gps_fix / sats, nav_* ve sapma) taklit edilir; `durum().sim = 'fake'`.
- PX4 ve SIMUMAV oturumlarında kapalıdır (`desteksiz(not)` → `supported: False`; komut gerekçeyle reddedilir).
"""
import math
import random
import time

GPS_SEVIYELERI = ('off', 'light', 'heavy', 'full')
SEVIYE_ADI = {'off': 'kapalı', 'light': 'hafif', 'heavy': 'ağır', 'full': 'tam'}
HIZ_MAX = 50.0                       # m/s sürükleme hızı üst sınırı
SAPMA_MIN, SAPMA_MAX = 1.0, 5000.0   # m azami sapma
SURE_MAX = 3600                      # sn
SPOOF_VARSAYILAN = {'dir': 90.0, 'speed': 2.0, 'max_m': 200.0}
ADIM_MS = 200                        # simülasyon zamanı adımı (SITL GPS'i 5 Hz)
IVME = 0.5                           # m/s²: sürükleme hızının rampası (ve hedefe yaklaşırken yavaşlama)
HAFIF_SIGMA_M, HAFIF_TAU_S = 2.5, 4.0   # hafif karıştırma: Gauss–Markov konum gezinmesi (eksen başına σ, korelasyon süresi)
HAFIF_UYDU, HAFIF_DOGRULUK = 6.0, 5.0   # hafif karıştırma: SIM_GPS1_NUMSATS, SIM_GPS1_ACC (m)
YAKIN_M, YAKIN_S = 3.0, 2.0          # kapanış sonrası EKF–gerçek farkı bu kadar süre bu eşiğin altındaysa gerçek konum kipi biter
GERCEK_AZAMI_S = 90.0                # … ya da en geç bu kadar simülasyon saniyesi sonra
M_ENLEM = 110574.0                   # m / derece enlem
M_BOYLAM = 111320.0                  # m / derece boylam (ekvatorda; cos(enlem) ile çarpılır)
SIMSTATE_ID, SIMSTATE_HIZLI_US, SIMSTATE_NORMAL_US = 164, 20000, 100000
# Karıştırma kapalıyken SITL GPS'i (ilk kalp atışında ve her kapanışta yazılır; eeprom "Sıfırla"da korunduğundan JAM / ENABLE açıkça geri alınır)
KAPALI_PARAMLARI = (('SIM_GPS1_JAM', 0.0), ('SIM_GPS1_ENABLE', 1.0), ('SIM_GPS1_NUMSATS', 18.0), ('SIM_GPS1_ACC', 0.02),
                    ('SIM_GPS1_GLTCH_X', 0.0), ('SIM_GPS1_GLTCH_Y', 0.0), ('SIM_GPS1_VERR_X', 0.0), ('SIM_GPS1_VERR_Y', 0.0))
SEVIYE_PARAMLARI = {
    'off': (('SIM_GPS1_JAM', 0.0), ('SIM_GPS1_ENABLE', 1.0), ('SIM_GPS1_NUMSATS', 18.0), ('SIM_GPS1_ACC', 0.02)),
    'light': (('SIM_GPS1_JAM', 0.0), ('SIM_GPS1_ENABLE', 1.0), ('SIM_GPS1_NUMSATS', HAFIF_UYDU), ('SIM_GPS1_ACC', HAFIF_DOGRULUK)),
    'heavy': (('SIM_GPS1_JAM', 1.0), ('SIM_GPS1_ENABLE', 1.0), ('SIM_GPS1_NUMSATS', 18.0), ('SIM_GPS1_ACC', 0.02)),
    'full': (('SIM_GPS1_JAM', 0.0), ('SIM_GPS1_ENABLE', 0.0), ('SIM_GPS1_NUMSATS', 18.0), ('SIM_GPS1_ACC', 0.02)),
}
# Sahte kinematik kipte gösterge taklidi: seviye → (gps_fix, sats); ağır seviyede kilit SAHTE_AGIR_MS çevrimiyle gidip gelir
SAHTE_GPS = {'light': (3, 6), 'full': (1, 0)}
SAHTE_AGIR_MS = 3000


class KaristirmaHata(ValueError):
    pass


def _sayi(v, ad, alt, ust):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not alt <= v <= ust:
        raise KaristirmaHata(f'{ad} {alt:g}…{ust:g} aralığında sayı olmalı')
    return float(v)


def dogrula(p, onceki=None):
    """`jam` gövdesi → tam ayar sözlüğü `{gps, spoof: {on, dir, speed, max_m}, dur_s}`. Verilmeyen alan önceki ayardan gelir.
    Hatalı alan → KaristirmaHata (oturum komutu 'invalid' döner)."""
    if not isinstance(p, dict):
        raise KaristirmaHata('jam gövdesi sözlük olmalı')
    onceki = onceki or {}
    eski_spoof = {**SPOOF_VARSAYILAN, 'on': False, **(onceki.get('spoof') or {})}
    if 'off' in p:
        if p['off'] is not True:
            raise KaristirmaHata('jam.off yalnız true olabilir')
        return {'gps': 'off', 'spoof': {**eski_spoof, 'on': False}, 'dur_s': 0}
    if not any(k in p for k in ('gps', 'spoof', 'dur_s')):
        raise KaristirmaHata('jam: gps, spoof, dur_s ya da off alanlarından biri gerekir')
    gps = p.get('gps', onceki.get('gps', 'off'))
    if gps not in GPS_SEVIYELERI:
        raise KaristirmaHata(f"jam.gps {' | '.join(GPS_SEVIYELERI)} olmalı")
    spoof = eski_spoof
    if 'spoof' in p:
        sp = p['spoof']
        if not isinstance(sp, dict) or not isinstance(sp.get('on'), bool):
            raise KaristirmaHata('jam.spoof.on doğru/yanlış (true/false) olmalı')
        spoof = {'on': sp['on'],
                 'dir': round(_sayi(sp.get('dir', eski_spoof['dir']), 'jam.spoof.dir (°)', 0, 360) % 360.0, 2),
                 'speed': round(_sayi(sp.get('speed', eski_spoof['speed']), 'jam.spoof.speed (m/s)', 0, HIZ_MAX), 2),
                 'max_m': round(_sayi(sp.get('max_m', eski_spoof['max_m']), 'jam.spoof.max_m (m)', SAPMA_MIN, SAPMA_MAX), 1)}
    dur = int(round(_sayi(p['dur_s'], 'jam.dur_s (sn)', 0, SURE_MAX))) if 'dur_s' in p else int(onceki.get('dur_s') or 0)
    return {'gps': gps, 'spoof': spoof, 'dur_s': dur}


def ofset_derece(kuzey_m, dogu_m, lat):
    """Metre ofset → (SIM_GPS1_GLTCH_X, SIM_GPS1_GLTCH_Y) derece. SITL'de ölçüldü: GPS = gerçek + ofset."""
    c = max(0.01, math.cos(math.radians(lat or 0.0)))
    return kuzey_m / M_ENLEM, dogu_m / (M_BOYLAM * c)


def fark_m(lat1, lon1, lat2, lon2):
    """İki yakın nokta arası yatay mesafe (m; düz dünya yaklaşımı — karıştırma ölçeğinde yeterli)."""
    c = math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.hypot((lat2 - lat1) * M_ENLEM, (lon2 - lon1) * M_BOYLAM * c)


def surukle(ok, od, v, cfg, dt):
    """Aldatma ofsetini (kuzey, doğu m) hedefe (max_m, dir) doğru bir adım ilerletir. Dönüş (ok, od, v, vk, vd): yeni ofset, sürat ve hız
    bileşenleri (NED m/s). Sürat IVME ile artar, hedefe yaklaşırken √(2·IVME·kalan) ile sınırlanır; speed 0 → anında hedef."""
    a = math.radians(cfg['dir'])
    hk, hd = cfg['max_m'] * math.cos(a), cfg['max_m'] * math.sin(a)
    dk, dd = hk - ok, hd - od
    kalan = math.hypot(dk, dd)
    if cfg['speed'] <= 0 or kalan < 0.05:
        return hk, hd, 0.0, 0.0, 0.0
    v = min(v + IVME * dt, cfg['speed'], math.sqrt(2.0 * IVME * kalan))
    adim = min(kalan, v * dt)
    bk, bd = dk / kalan, dd / kalan
    return ok + bk * adim, od + bd * adim, v, bk * v, bd * v


def ayar_metni(cfg):
    """Olay şeridi / özet için kısa Türkçe metin."""
    p = []
    if cfg['gps'] != 'off':
        p.append(f"GPS karıştırma {SEVIYE_ADI[cfg['gps']]}")
    sp = cfg['spoof']
    if sp['on']:
        p.append(f"GPS aldatma {sp['dir']:.0f}° yönünde " + (f"{sp['speed']:g} m/s ile " if sp['speed'] else 'anında ') + f"{sp['max_m']:g} m")
    if p and cfg['dur_s']:
        p.append(f"{cfg['dur_s']} sn")
    return ' · '.join(p) or 'kapalı'


class Karistirma:
    """Oturum başına karıştırma durumu (SimSession.jam)."""

    def __init__(self, s):
        self.s = s
        self.destek, self.destek_notu = True, None
        self.cfg = dogrula({'off': True})
        self.g_lat = self.g_lon = None        # SITL fiziğinin gerçek konumu (SIMSTATE)
        self.e_lat = self.e_lon = None        # otopilotun (EKF) konumu — gerçek konum kipinde
        self._gercek = False                  # gerçek konum kipi isteği (SIMSTATE gelince etkin)
        self._rng = random.Random()
        self.ist = {'count': 0, 'gps_s': {'light': 0.0, 'heavy': 0.0, 'full': 0.0}, 'spoof_s': 0.0, 'max_off_m': 0.0, 'max_nav_err': 0.0}
        self._son = {}                        # son yazılan SIM_GPS1_* değerleri (değişmeyen yeniden yazılmaz)
        self._temizle()

    def _temizle(self):
        self.ok = self.od = 0.0               # aldatma ofseti (kuzey, doğu m)
        self.v = 0.0                          # sürükleme sürati (m/s)
        self.gk = self.gd = 0.0               # hafif karıştırma gezinmesi (m)
        self._son_tbm = self._bas_tbm = None
        self._kalan = None
        self._kapali_s = self._yakin_s = 0.0

    # ---------------- durum ----------------
    @property
    def on(self):
        return self.cfg['gps'] != 'off' or self.cfg['spoof']['on']

    @property
    def gercek_kip(self):
        """tele.lat/lon şu an SIMSTATE'ten mi (gerçek SITL + en az bir SIMSTATE alındı)."""
        return self._gercek and self.g_lat is not None

    def desteksiz(self, not_):
        """Bu oturumda karıştırma yok (PX4 / SIMUMAV): düğme gösterilmez, komut gerekçeyle reddedilir."""
        self.destek, self.destek_notu = False, str(not_)

    def nav_err(self):
        if self.s.sahte is not None:
            return math.hypot(self.ok + self.gk, self.od + self.gd) if self.on else None
        if None in (self.g_lat, self.e_lat):
            return None
        return fark_m(self.g_lat, self.g_lon, self.e_lat, self.e_lon)

    def durum(self):
        if not self.destek:
            return {'supported': False, 'reason': self.destek_notu}
        e = self.nav_err()
        return {'supported': True, 'on': self.on, 'gps': self.cfg['gps'], 'spoof': dict(self.cfg['spoof']), 'dur_s': self.cfg['dur_s'],
                'left_s': self._kalan, 'off_m': round(math.hypot(self.ok, self.od), 1), 'nav_err': round(e, 1) if e is not None else None,
                'real': self._gercek, 'sim': 'fake' if self.s.sahte is not None else 'sitl',
                'limits': {'speed': HIZ_MAX, 'max_m': [SAPMA_MIN, SAPMA_MAX], 'dur_s': SURE_MAX}}

    def _yay(self, reason):
        self.s._yay({'t': 'jam', 'ts': round(time.time(), 3), 'reason': reason, **self.durum()})

    def ozet(self):
        """Özet raporu `jam` bölümü; oturumda hiç karıştırma açılmadıysa None."""
        if not self.ist['count']:
            return None
        i = self.ist
        return {'count': i['count'], 'gps_s': {k: round(v, 1) for k, v in i['gps_s'].items() if v > 0}, 'spoof_s': round(i['spoof_s'], 1),
                'max_off_m': round(i['max_off_m'], 1), 'max_nav_err': round(i['max_nav_err'], 1), 'sim': 'fake' if self.s.sahte is not None else 'sitl'}

    # ---------------- SITL'e yazma ----------------
    def _yaz(self, ciftler, zorla=False):
        degisen = []
        for ad, v in ciftler:
            eski = self._son.get(ad)
            if zorla or eski is None or abs(eski - v) > (1e-9 if 'GLTCH' in ad else 1e-3):
                self._son[ad] = v
                degisen.append((ad, v))
        s = self.s
        if degisen and s.sahte is None and s._heartbeat_alindi and s.sysid is not None:
            s._param_set(degisen)
        return degisen

    def _ofset_yaz(self, vk=0.0, vd=0.0):
        lat = self.g_lat if self.g_lat is not None else self.s.tele.get('lat')
        x, y = ofset_derece(self.ok + self.gk, self.od + self.gd, lat)
        self._yaz((('SIM_GPS1_GLTCH_X', x), ('SIM_GPS1_GLTCH_Y', y), ('SIM_GPS1_VERR_X', vk), ('SIM_GPS1_VERR_Y', vd)))

    def kalp_atisi(self):
        """İlk araç kalp atışı (oturum açılışı / Sıfırla sonrası yeni SITL): eeprom'da kalmış olabilecek karıştırma parametreleri kapatılır."""
        self._son = {}
        if self.destek:
            self._yaz(KAPALI_PARAMLARI, zorla=True)

    def akis(self):
        """SIMSTATE akış hızı: gerçek konum kipinde 50 Hz (SET_MESSAGE_INTERVAL reddedildiyse akış bazlı istek zaten EXTRA1 hızındadır)."""
        s = self.s
        if not self._gercek or s.sahte is not None or s._smi_red or s.sysid is None:
            return
        s._gonder(s.mav.command_long_encode(s.sysid, s.comp, 511, 0, SIMSTATE_ID, SIMSTATE_HIZLI_US, 0, 0, 0, 0, 0))

    # ---------------- telemetri kancaları (SimSession._isle) ----------------
    def simstate(self, m):
        """SIMSTATE: gerçek fizik konumu. Gerçek konum kipinde tele.lat/lon buradan yazılır (konum damgası son tele.tbm)."""
        if not (m.lat or m.lng):
            return
        self.g_lat, self.g_lon = m.lat / 1e7, m.lng / 1e7
        if self._gercek:
            te = self.s.tele
            te['lat'], te['lon'] = self.g_lat, self.g_lon
            if te.get('tbm') is not None:
                te['tbm_pos'] = te['tbm']

    def ekf_konum(self, lat, lon):
        """GLOBAL_POSITION_INT (gerçek konum kipinde): otopilotun sandığı konum → tele.nav_lat / nav_lon / nav_err."""
        self.e_lat, self.e_lon = lat, lon
        te = self.s.tele
        te['nav_lat'], te['nav_lon'] = lat, lon
        e = self.nav_err()
        if e is not None:
            te['nav_err'] = round(e, 1)
            self.ist['max_nav_err'] = max(self.ist['max_nav_err'], e)

    def sahte_tele(self):
        """Sahte kinematik: `tele.update(sahte.tele())` sonrası gösterge taklidi (fiziksel etki yok)."""
        if not self.on:
            return
        te = self.s.tele
        g = self.cfg['gps']
        if g == 'heavy':
            te['gps_fix'], te['sats'] = (1, 3) if int(te.get('tbm') or 0) % SAHTE_AGIR_MS < SAHTE_AGIR_MS * 0.6 else (3, 7)
        elif g in SAHTE_GPS:
            te['gps_fix'], te['sats'] = SAHTE_GPS[g]
        if te.get('lat') is not None:
            x, y = ofset_derece(self.ok + self.gk, self.od + self.gd, te['lat'])
            te['nav_lat'], te['nav_lon'] = round(te['lat'] + x, 7), round(te['lon'] + y, 7)
            te['nav_err'] = round(math.hypot(self.ok + self.gk, self.od + self.gd), 1)

    # ---------------- komut ----------------
    async def komut(self, p):
        if not self.destek:
            raise KaristirmaHata(self.destek_notu or 'Bu oturumda karıştırma yok')
        yeni = dogrula(p, self.cfg)
        s = self.s
        once, onceki = self.on, self.cfg
        self.cfg = yeni
        s.oturum_param_unut('SIM_GPS1_')   # §35: Mission Planner'ın eski SIM_GPS1_* değeri "Sıfırla"da geri yazılmasın
        self._bas_tbm, self._kalan = None, (float(yeni['dur_s']) if self.on and yeni['dur_s'] else None)
        if not (once or self._gercek):
            self._son_tbm = None   # yeni dönem: adım tabanı ilk telemetriyle kurulur (eski damgadan sıçrama olmasın)
        if self.on:
            if not once:
                self.ist['count'] += 1
            self._kapali_s = self._yakin_s = 0.0
            if s.sahte is None and not self._gercek:
                self._gercek = True
                self.akis()
        if yeni['gps'] != 'light':
            self.gk = self.gd = 0.0
        if not yeni['spoof']['on']:
            self.ok = self.od = self.v = 0.0   # aldatıcı sustu: alıcı gerçek konuma döner (EKF birkaç saniye sonra izler)
        elif yeni['spoof']['speed'] <= 0:
            self.ok, self.od, self.v, _, _ = surukle(self.ok, self.od, 0.0, yeni['spoof'], 0.0)   # anında sıçrama
        self._yaz(SEVIYE_PARAMLARI[yeni['gps']], zorla=yeni['gps'] != onceki['gps'])
        self._ofset_yaz()
        if self.on:
            s._olay('Karıştırma: ' + ayar_metni(yeni) + (' — sahte kinematik: yalnız göstergeler etkilenir' if s.sahte is not None else ''), 4)
        elif once:
            s._olay('Karıştırma kapatıldı', 6)
        self._tele()
        self._yay('cmd')
        return {'ok': True, 'jam': self.durum()}

    def _kapat(self, reason, metin):
        """Kendiliğinden kapanış (süre doldu). Gerçek konum kipi EKF toparlanana dek sürer."""
        self.cfg = dogrula({'off': True}, self.cfg)
        self.ok = self.od = self.v = self.gk = self.gd = 0.0
        self._bas_tbm = self._kalan = None
        self._kapali_s = self._yakin_s = 0.0
        self._yaz(KAPALI_PARAMLARI)
        self.s._olay(metin, 6)
        self._tele()
        self._yay(reason)

    def sifirla(self):
        """"Sıfırla": yeni SITL / sıfır kinematik → karıştırma kapanır (parametreler ilk kalp atışında geri alınır)."""
        acikti = self.on or self._gercek
        self.cfg = dogrula({'off': True}, self.cfg)
        self._temizle()
        self._gercek = False
        self.g_lat = self.g_lon = self.e_lat = self.e_lon = None
        self._son = {}
        self._tele()
        if acikti:
            self._yay('reset')

    # ---------------- adım ----------------
    def _tele(self):
        te = self.s.tele
        if self.on:
            te['jam'] = {'gps': self.cfg['gps'], 'spoof': self.cfg['spoof']['on'], 'off_m': round(math.hypot(self.ok, self.od), 1), 'left_s': self._kalan}
        else:
            te.pop('jam', None)
            if self.s.sahte is not None:   # sahte kinematik: gösterge taklidi aynı çerçevede geri alınır
                k = self.s.sahte.tele()
                te['gps_fix'], te['sats'] = k['gps_fix'], k['sats']
        if not self.on and not self._gercek:
            for k in ('nav_lat', 'nav_lon', 'nav_err'):
                te.pop(k, None)

    def adim(self, tbm=None):
        """Her telemetri adımı (SimSession._tele_yay; izleyici olmasa da): ADIM_MS simülasyon zamanında bir ofset / gürültü / süre ilerler."""
        if not (self.on or self._gercek):
            return
        t = tbm if tbm is not None else self.s.tele.get('tbm')
        if t is None:
            return
        t = int(t)
        if self._son_tbm is None or t < self._son_tbm:   # ilk adım / SITL saati geri gitti
            self._son_tbm = t
            return
        if t - self._son_tbm < ADIM_MS:
            return
        dt = min((t - self._son_tbm) / 1000.0, 1.0)
        self._son_tbm = t
        if self.on:
            self._adim_acik(t, dt)
        else:
            self._adim_toparlanma(dt)
        self._tele()

    def _adim_acik(self, t, dt):
        cfg = self.cfg
        if cfg['dur_s']:
            if self._bas_tbm is None:
                self._bas_tbm = t
            self._kalan = round(max(0.0, cfg['dur_s'] - (t - self._bas_tbm) / 1000.0), 1)
            if self._kalan <= 0:
                self._kapat('timeout', 'Karıştırma süresi doldu — kapatıldı')
                return
        vk = vd = 0.0
        if cfg['spoof']['on']:
            self.ok, self.od, self.v, vk, vd = surukle(self.ok, self.od, self.v, cfg['spoof'], dt)
            self.ist['spoof_s'] += dt
            self.ist['max_off_m'] = max(self.ist['max_off_m'], math.hypot(self.ok, self.od))
        if cfg['gps'] == 'light':
            f = math.exp(-dt / HAFIF_TAU_S)
            q = HAFIF_SIGMA_M * math.sqrt(1.0 - f * f)
            self.gk, self.gd = self.gk * f + self._rng.gauss(0.0, q), self.gd * f + self._rng.gauss(0.0, q)
        if cfg['gps'] != 'off':
            self.ist['gps_s'][cfg['gps']] += dt
        self._ofset_yaz(vk, vd)
        if self.s.sahte is not None:
            self.ist['max_nav_err'] = max(self.ist['max_nav_err'], math.hypot(self.ok + self.gk, self.od + self.gd))

    def _adim_toparlanma(self, dt):
        """Karıştırma kapandı: EKF gerçek konuma dönene (ya da GERCEK_AZAMI_S dolana) dek gerçek konum kipi sürer."""
        self._kapali_s += dt
        e = self.nav_err()
        self._yakin_s = self._yakin_s + dt if e is not None and e < YAKIN_M else 0.0
        if self._yakin_s >= YAKIN_S or self._kapali_s >= GERCEK_AZAMI_S:
            self._gercek = False
            s = self.s
            if s.sahte is None and not s._smi_red and s.sysid is not None:
                s._gonder(s.mav.command_long_encode(s.sysid, s.comp, 511, 0, SIMSTATE_ID, SIMSTATE_NORMAL_US, 0, 0, 0, 0, 0))
            self._tele()
            self._yay('settled')
