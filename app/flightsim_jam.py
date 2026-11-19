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

BAĞLANTI KARIŞTIRMA + KARIŞTIRICI BÖLGESİ (§49). Kullanıcı isteği: "Kumanda / telemetri bağlantısının karıştırılması … Haritada konumu ve yarıçapı
olan bir karıştırıcı bölgesi: araç içine girince etkilenir … otomatik land yapmasın, gerçek bir sistemde ne oluyorsa o olsun, amacımız zaten
gerçek sistemi taklit etmek."

- `rc: true` — KUMANDA bağlantısı kesik: tarayıcının RC override'ları (sanal kumanda / oyun kolu) araca iletilmez, SIM_RC_FAIL 1 (alıcıda darbe
  yok) yazılır; bekleyen override BIRAKILMAZ (bırakma çerçevesi araca SITL'in iç kumandasını okutur: kip anahtarı sıçrar) ve aracın RC arıza koruması gerçek araçtaki gibi çalışır: FS_THR_ENABLE / THR_FAILSAFE = oturumda yazılan → dron kaydındaki →
  ArduPilot fabrika değeri 1 (kopter: RTL; konum yoksa otopilot kendi kararıyla iner). Simülatör kip ZORLAMAZ. Bitince SIM_RC_FAIL 0 ve
  arıza koruması oturum değerine (kumandasız oturum: 0) döner; kip otopilotun bıraktığı yerde kalır.
- `tlm: true` — TELEMETRİ (yer istasyonu) bağlantısı kesik: Mission Planner ↔ SITL UDP köprüsü iki yönde susar, sunucunun yer istasyonu kalp
  atışı durur, harekât paneli (hub) beslenmez, tarayıcıdan / panelden araca giden komutlar "araca ulaşmadı" diye reddedilir. Araç uçmayı
  sürdürür; tepkisi kendi FS_GCS_ENABLE değeridir (fabrika 0: yok sayar). SITL ölçümü: sayaç yalnız HEARTBEAT ile sıfırlanır (sunucunun
  PARAM_SET akışı sıfırlamaz). 3B sahne gerçek hareketi göstermeyi sürdürür (simülatör günlüğü); ön yüz gösterge kutusunu dondurur.
- `zone: {on, lat, lon, r_m}` — KARIŞTIRICI BÖLGESİ: kurulu etkiler yalnız aracın GERÇEK konumu dairenin içindeyken uygulanır (giriş d ≤ r,
  çıkış d > r·BOLGE_CIKIS). `on` = kurulu, `active` = şu an uygulanıyor; giriş / çıkışta parametreler yazılır / geri alınır.
- `fs: 'althold' | 'land' | 'none'` — yalnız kopter: GPS kaybında otopilot tepkisi (FS_EKF_ACTION 2 / 1 / 0). ArduPilot fabrika değeri 1'dir
  (LAND); kullanıcı isteğiyle varsayılan 'althold' (dron kaydında FS_EKF_ACTION varsa o). Karıştırma kurulunca yazılır, toparlanınca eski
  değer geri yazılır. SITL ölçümleri (kopter, 25 m askı): 2 → "EKF Failsafe: changed to Altitude Hold Mode", irtifa korunur, araç rüzgârla
  sürüklenir, kip kendiliğinden geri dönmez · 1 → LAND · 0 → kipte kalır, konum kestirimi bozuldukça araç yüzlerce metre kaçar.
- GAZ ORTADA: ALT_HOLD'da irtifayı gaz çubuğu belirler; kumanda bağlı değilken SITL'in iç RC'si gazı en altta (1000) tutar ve araç alçalıp
  yere iner (ölçüldü). Kopterde GPS karıştırması kurulduktan sonra araç ALT_HOLD'dayken ve gaz girdisi yokken sunucu gaz kanalını 1500'de
  tutar — "çubuklar bırakılmış kumanda". Kumanda bağlı değilse kendi RC override çerçevesini gönderir (diğer kanallar serbest); sanal kumanda
  açık ama gaz çubuğuna hiç dokunulmamışsa (gaz kanalı 0 = dokunma) tarayıcı çerçevesindeki boş gaz kanalını doldurur (rc_gaz). Pilot gaz
  çubuğunu oynatınca devralır. Kip değişince / disarm'da bırakılır.
- SINIR: ArduPilot, yer istasyonu sysid'inden gelen RC override'ı kalp atışı sayar; telemetri kesikken sanal kumanda ya da "gaz ortada"
  etkinse FS_GCS_ENABLE tetiklenmez (kumanda MAVLink üzerinden taşındığı için). Mission Planner oyun kolu telemetri bağlantısından gider:
  kumanda karıştırması onu etkilemez, telemetri karıştırması keser.
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
# §49 bağlantı karıştırma + bölge
FS_SECENEKLERI = ('althold', 'land', 'none')
FS_DEGER = {'none': 0.0, 'land': 1.0, 'althold': 2.0}   # FS_EKF_ACTION
FS_ADI = {'althold': 'irtifa tut (ALT_HOLD)', 'land': 'iniş (LAND)', 'none': 'yalnız bildir'}
FS_VARSAYILAN = 'althold'
FS_EKF_FABRIKA = 1.0                 # ArduCopter FS_EKF_ACTION fabrika değeri (LAND)
RC_FS_FABRIKA = 1.0                  # FS_THR_ENABLE / THR_FAILSAFE fabrika değeri (etkin)
BOLGE_R_MIN, BOLGE_R_MAX, BOLGE_R_VARSAYILAN = 10.0, 20000.0, 300.0   # m
BOLGE_CIKIS = 1.05                   # çıkış eşiği = r · bu (sınırda titreme olmasın)
GAZ_ORTA_PWM = 1500
RC_FS_ADLARI = ('FS_THR_ENABLE', 'THR_FAILSAFE')   # aracın RC arıza koruması (kopter / uçak)
RC_GECIS_S = 0.4                     # kumanda geri verilirken: çerçeveler yeniden aktıktan bu kadar sonra SIM_RC_FAIL 0 (gerçek zaman, sn)
RC_YOK_S = 1.0                       # tarayıcıdan bu kadar süredir RC gelmediyse "kumanda bağlı değil"
ALT_HOLD = 'ALT_HOLD'
IZLEYICIDEN_GIZLI = ('FS_EKF_ACTION',)   # kalıcı parametre izleyicisine "bizim yazımımız" diye bildirilen adlar
TLM_RET = 'Telemetri bağlantısı karıştırılıyor — komut araca ulaşmadı'


class KaristirmaHata(ValueError):
    pass


def _sayi(v, ad, alt, ust):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not alt <= v <= ust:
        raise KaristirmaHata(f'{ad} {alt:g}…{ust:g} aralığında sayı olmalı')
    return float(v)


def dogrula(p, onceki=None):
    """`jam` gövdesi → tam ayar sözlüğü `{gps, spoof: {on, dir, speed, max_m}, dur_s, rc, tlm, zone: {on, lat, lon, r_m}, fs}`. Verilmeyen alan
    önceki ayardan gelir. Hatalı alan → KaristirmaHata (oturum komutu 'invalid' döner)."""
    if not isinstance(p, dict):
        raise KaristirmaHata('jam gövdesi sözlük olmalı')
    onceki = onceki or {}
    eski_spoof = {**SPOOF_VARSAYILAN, 'on': False, **(onceki.get('spoof') or {})}
    eski_bolge = {'on': False, 'lat': None, 'lon': None, 'r_m': BOLGE_R_VARSAYILAN, **(onceki.get('zone') or {})}
    eski_fs = onceki.get('fs') if onceki.get('fs') in FS_SECENEKLERI else FS_VARSAYILAN
    if 'off' in p:
        if p['off'] is not True:
            raise KaristirmaHata('jam.off yalnız true olabilir')
        return {'gps': 'off', 'spoof': {**eski_spoof, 'on': False}, 'dur_s': 0, 'rc': False, 'tlm': False, 'zone': {**eski_bolge, 'on': False}, 'fs': eski_fs}
    if not any(k in p for k in ('gps', 'spoof', 'dur_s', 'rc', 'tlm', 'zone', 'fs')):
        raise KaristirmaHata('jam: gps, spoof, rc, tlm, zone, fs, dur_s ya da off alanlarından biri gerekir')
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
    bag = {}
    for k, ad in (('rc', 'kumanda'), ('tlm', 'telemetri')):
        v = p.get(k, bool(onceki.get(k)))
        if not isinstance(v, bool):
            raise KaristirmaHata(f'jam.{k} ({ad} bağlantısı) doğru/yanlış (true/false) olmalı')
        bag[k] = v
    bolge = eski_bolge
    if 'zone' in p:
        z = p['zone']
        if not isinstance(z, dict) or not isinstance(z.get('on'), bool):
            raise KaristirmaHata('jam.zone.on doğru/yanlış (true/false) olmalı')
        lat, lon = z.get('lat', eski_bolge['lat']), z.get('lon', eski_bolge['lon'])
        if z['on'] or lat is not None or lon is not None:
            if lat is None or lon is None:
                raise KaristirmaHata('jam.zone: bölge merkezi (lat, lon) gerekir')
            lat, lon = round(_sayi(lat, 'jam.zone.lat (°)', -90, 90), 7), round(_sayi(lon, 'jam.zone.lon (°)', -180, 180), 7)
        bolge = {'on': z['on'], 'lat': lat, 'lon': lon,
                 'r_m': round(_sayi(z.get('r_m', eski_bolge['r_m']), 'jam.zone.r_m (m)', BOLGE_R_MIN, BOLGE_R_MAX), 1)}
    fs = p.get('fs', eski_fs)
    if fs not in FS_SECENEKLERI:
        raise KaristirmaHata(f"jam.fs {' | '.join(FS_SECENEKLERI)} olmalı")
    return {'gps': gps, 'spoof': spoof, 'dur_s': dur, **bag, 'zone': bolge, 'fs': fs}


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
    if cfg.get('rc'):
        p.append('kumanda bağlantısı kesik')
    if cfg.get('tlm'):
        p.append('telemetri bağlantısı kesik')
    if p and (cfg.get('zone') or {}).get('on'):
        p.append(f"bölge {cfg['zone']['r_m']:g} m yarıçap")
    if p and cfg['dur_s']:
        p.append(f"{cfg['dur_s']} sn")
    return ' · '.join(p) or 'kapalı'


class Karistirma:
    """Oturum başına karıştırma durumu (SimSession.jam)."""

    def __init__(self, s, kopter=False):
        self.s = s
        self.kopter = bool(kopter)            # FS_EKF_ACTION + "gaz ortada" yalnız kopter ailesinde (ArduCopter)
        self.destek, self.destek_notu = True, None
        self.cfg = dogrula({'off': True}, {'fs': self._fs_varsayilan()})
        self.g_lat = self.g_lon = None        # SITL fiziğinin gerçek konumu (SIMSTATE)
        self.e_lat = self.e_lon = None        # otopilotun (EKF) konumu — gerçek konum kipinde
        self._gercek = False                  # gerçek konum kipi isteği (SIMSTATE gelince etkin)
        self._rng = random.Random()
        self.ist = {'count': 0, 'gps_s': {'light': 0.0, 'heavy': 0.0, 'full': 0.0}, 'spoof_s': 0.0, 'max_off_m': 0.0, 'max_nav_err': 0.0,
                    'rc_s': 0.0, 'tlm_s': 0.0, 'zone_in': 0, 'zone': None}
        self._son = {}                        # son yazılan SIM_GPS1_* değerleri (değişmeyen yeniden yazılmaz)
        self._fs_eski = None                  # FS_EKF_ACTION'ın bizim yazmamızdan önceki değeri (toparlanınca / yeni SITL'de geri yazılır)
        self._fs_secildi = False              # kullanıcı tepkiyi panelden seçti (seçmediyse varsayılan dron kaydından gelir)
        self._rc_kesildi = False              # SIM_RC_FAIL 1 + RC arıza koruması yazıldı
        self._rc_gecis = None                 # kumanda geri verilirken SIM_RC_FAIL 0'ın yazılacağı an (gerçek zaman)
        self._temizle()

    def _temizle(self):
        self.ok = self.od = 0.0               # aldatma ofseti (kuzey, doğu m)
        self.v = 0.0                          # sürükleme sürati (m/s)
        self.gk = self.gd = 0.0               # hafif karıştırma gezinmesi (m)
        self._son_tbm = self._bas_tbm = None
        self._kalan = None
        self._kapali_s = self._yakin_s = 0.0
        self._icerde, self._mesafe = False, None   # karıştırıcı bölgesi: araç içinde mi, merkeze mesafe (m)
        self._gaz_orta = False                # kopter + GPS karıştırması kuruldu: ALT_HOLD'da kumandasız gaz ortada tutulur
        self._gaz_etkin = False               # şu an gaz ortada tutuluyor
        self._rc_gaz_t = 0.0                  # tarayıcı kumandasında gaz kanalının en son sürüldüğü an

    # ---------------- durum ----------------
    @property
    def gps_kurulu(self):
        return self.cfg['gps'] != 'off' or self.cfg['spoof']['on']

    @property
    def on(self):
        """Karıştırma KURULU (bölge varsa araç dışarıdayken de)."""
        return self.gps_kurulu or self.cfg['rc'] or self.cfg['tlm']

    @property
    def aktif(self):
        """Etkiler şu an UYGULANIYOR: kurulu ve (bölge yok ya da araç bölgenin içinde)."""
        return self.on and (not self.cfg['zone']['on'] or self._icerde)

    @property
    def gps_etkin(self):
        return self.cfg['gps'] if self.aktif else 'off'

    @property
    def spoof_etkin(self):
        return self.cfg['spoof']['on'] and self.aktif

    @property
    def rc_kesik(self):
        """Kumanda bağlantısı şu an kesik: SimSession tarayıcı RC override'larını iletmez."""
        return self.cfg['rc'] and self.aktif

    @property
    def tlm_kesik(self):
        """Telemetri bağlantısı şu an kesik: SimSession GCS köprüsünü, kalp atışını, hub beslemesini ve araç komutlarını keser."""
        return self.cfg['tlm'] and self.aktif

    @property
    def gercek_kip(self):
        """tele.lat/lon şu an SIMSTATE'ten mi (gerçek SITL + en az bir SIMSTATE alındı)."""
        return self._gercek and self.g_lat is not None

    def desteksiz(self, not_):
        """Bu oturumda karıştırma yok (PX4 / SIMUMAV): düğme gösterilmez, komut gerekçeyle reddedilir."""
        self.destek, self.destek_notu = False, str(not_)

    def _kayit_degeri(self, ad):
        """Dron kaydındaki (kalıcı) parametre değeri; yoksa None."""
        for r in getattr(self.s, 'kayitli_params', None) or ():
            if r.get('name') == ad:
                try:
                    return float(r['value'])
                except (KeyError, TypeError, ValueError):
                    return None
        return None

    def _oturum_degeri(self, ad):
        """Kullanıcının bu oturumda (Mission Planner / panel) yazdığı değer; yoksa None."""
        v = (getattr(self.s, 'oturum_paramlari', None) or {}).get(ad)
        try:
            return float(v[0]) if v is not None else None
        except (TypeError, ValueError, IndexError):
            return None

    def _fs_varsayilan(self):
        """GPS kaybı tepkisinin oturum varsayılanı: dron kaydında FS_EKF_ACTION varsa o (0 bildir · 1 / 3 iniş · 2 irtifa tut), yoksa irtifa tut."""
        v = self._kayit_degeri('FS_EKF_ACTION')
        if v is None:
            return FS_VARSAYILAN
        return {0: 'none', 2: 'althold'}.get(int(round(v)), 'land')

    def _bolge_durum(self):
        z = self.cfg['zone']
        return {**z, 'inside': self._icerde if z['on'] else None, 'dist_m': round(self._mesafe, 1) if z['on'] and self._mesafe is not None else None}

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
        return {'supported': True, 'on': self.on, 'active': self.aktif, 'gps': self.cfg['gps'], 'spoof': dict(self.cfg['spoof']),
                'dur_s': self.cfg['dur_s'], 'rc': self.cfg['rc'], 'tlm': self.cfg['tlm'], 'zone': self._bolge_durum(),
                'fs': self.cfg['fs'] if self.kopter else None, 'thr_mid': self._gaz_etkin,
                'left_s': self._kalan, 'off_m': round(math.hypot(self.ok, self.od), 1), 'nav_err': round(e, 1) if e is not None else None,
                'real': self._gercek, 'sim': 'fake' if self.s.sahte is not None else 'sitl',
                'limits': {'speed': HIZ_MAX, 'max_m': [SAPMA_MIN, SAPMA_MAX], 'dur_s': SURE_MAX, 'r_m': [BOLGE_R_MIN, BOLGE_R_MAX]}}

    def _yay(self, reason):
        self.s._yay({'t': 'jam', 'ts': round(time.time(), 3), 'reason': reason, **self.durum()})

    def ozet(self):
        """Özet raporu `jam` bölümü; oturumda hiç karıştırma açılmadıysa None."""
        if not self.ist['count']:
            return None
        i = self.ist
        o = {'count': i['count'], 'gps_s': {k: round(v, 1) for k, v in i['gps_s'].items() if v > 0}, 'spoof_s': round(i['spoof_s'], 1),
             'max_off_m': round(i['max_off_m'], 1), 'max_nav_err': round(i['max_nav_err'], 1), 'sim': 'fake' if self.s.sahte is not None else 'sitl'}
        if i['rc_s'] > 0:
            o['rc_s'] = round(i['rc_s'], 1)
        if i['tlm_s'] > 0:
            o['tlm_s'] = round(i['tlm_s'], 1)
        if i['zone'] is not None:   # son kurulan bölge + giriş sayısı (rapor haritası)
            o['zone'] = {**i['zone'], 'entries': i['zone_in']}
        return o

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
            iz = getattr(s, 'param_izleyici', None)
            if iz is not None:   # dron kaydına sızmasın: bizim yazdığımızın yankısı "SITL'de değişti" diye kalıcı kaydedilmez (SIM_* / FS_THR_* zaten hariç)
                iz.yukleme_isaretle([ad for ad, _ in degisen if ad in IZLEYICIDEN_GIZLI])
            s._param_set(degisen)
        return degisen

    def _ofset_yaz(self, vk=0.0, vd=0.0):
        lat = self.g_lat if self.g_lat is not None else self.s.tele.get('lat')
        x, y = ofset_derece(self.ok + self.gk, self.od + self.gd, lat)
        self._yaz((('SIM_GPS1_GLTCH_X', x), ('SIM_GPS1_GLTCH_Y', y), ('SIM_GPS1_VERR_X', vk), ('SIM_GPS1_VERR_Y', vd)))

    def kalp_atisi(self):
        """İlk araç kalp atışı (oturum açılışı / Sıfırla sonrası yeni SITL): eeprom'da kalmış olabilecek karıştırma parametreleri kapatılır."""
        self._son = {}
        self._rc_kesildi = False   # SIM_RC_FAIL / FS_THR_ENABLE'ı oturum varsayılanları (RC_PARAMLAR) az önce yeniden yazdı
        self._rc_gecis = None
        if self.destek:
            self._yaz(KAPALI_PARAMLARI, zorla=True)
            self._fs_geri()        # "Sıfırla": eeprom'da kalan FS_EKF_ACTION yazımımız eski değerine döner
            if not self._fs_secildi and self.cfg['fs'] != self._fs_varsayilan():   # dron kaydı SITL açılışında yüklendi
                self.cfg['fs'] = self._fs_varsayilan()
                self._yay('init')

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
        g = self.gps_etkin
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
        if isinstance(p, dict) and 'fs' in p:
            self._fs_secildi = True
        s = self.s
        once, onceki = self.on, self.cfg
        self.cfg = yeni
        s.oturum_param_unut('SIM_GPS1_', 'SIM_RC_FAIL')   # §35: Mission Planner'ın eski SIM_GPS1_* değeri "Sıfırla"da geri yazılmasın
        self._bas_tbm, self._kalan = None, (float(yeni['dur_s']) if self.on and yeni['dur_s'] else None)
        if yeni['zone'] != onceki['zone']:
            self._icerde, self._mesafe = False, None
        if self.on and yeni['zone']['on']:
            self.ist['zone'] = {k: yeni['zone'][k] for k in ('lat', 'lon', 'r_m')}
        girdi = self._bolge_olc() and self._icerde
        if not (once or self._gercek):
            self._son_tbm = None   # yeni dönem: adım tabanı ilk telemetriyle kurulur (eski damgadan sıçrama olmasın)
        if self.on:
            if not once:
                self.ist['count'] += 1
            self._kapali_s = self._yakin_s = 0.0
            if s.sahte is None and not self._gercek:
                self._gercek = True
                self.akis()
        if self.gps_kurulu:
            self._fs_yaz()
            self._gaz_orta = self.kopter and s.sahte is None
        self._uygula(zorla_gps=yeni['gps'] != onceki['gps'])
        if self.on:
            s._olay('Karıştırma: ' + ayar_metni(yeni) + (' — sahte kinematik: yalnız göstergeler etkilenir' if s.sahte is not None else ''), 4)
            if yeni['zone']['on']:
                if girdi:
                    self.ist['zone_in'] += 1
                s._olay('Karıştırıcı bölgesi: araç ' + ('içeride — etkiler uygulanıyor' if self._icerde else 'dışarıda — bölgeye girince etkilenir'), 6)
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
        self._icerde, self._mesafe = False, None
        self._yaz(KAPALI_PARAMLARI)
        self._rc_uygula()
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
        self._rc_kesildi = False   # yeni SITL: oturum varsayılanları ilk kalp atışında yeniden yazılır
        self._tele()
        if acikti:
            self._yay('reset')

    # ---------------- §49 bağlantı / bölge / arıza koruması ----------------
    def _uygula(self, zorla_gps=False):
        """Şu anki etkinliğe (kurulu ayar × bölge) göre SITL'e yazar: GPS seviyesi, aldatma ofseti, kumanda bağlantısı."""
        cfg = self.cfg
        if self.gps_etkin != 'light':
            self.gk = self.gd = 0.0
        if not self.spoof_etkin:
            self.ok = self.od = self.v = 0.0   # aldatıcı sustu / araç bölgeden çıktı: alıcı gerçek konuma döner (EKF birkaç saniye sonra izler)
        elif cfg['spoof']['speed'] <= 0:
            self.ok, self.od, self.v, _, _ = surukle(self.ok, self.od, 0.0, cfg['spoof'], 0.0)   # anında sıçrama
        self._yaz(SEVIYE_PARAMLARI[self.gps_etkin], zorla=zorla_gps)
        self._ofset_yaz()
        self._rc_uygula()

    def _rc_serbest(self):
        """RC override'ı bırak (8×0): araç alıcı girişine döner."""
        s = self.s
        if s.sahte is not None:
            s.sahte.komut('rc', {'ch': [0] * 8})
        elif s._heartbeat_alindi and s.sysid is not None:
            s._gonder(s.mav.rc_channels_override_encode(s.sysid, s.comp, 0, 0, 0, 0, 0, 0, 0, 0))

    def _rc_uygula(self):
        """Kumanda bağlantısı: kesilince SIM_RC_FAIL 1 + aracın RC arıza koruması etkinleşir; dönünce geri alınır.

        Araç hiçbir an SITL'in iç kumandasını (kip anahtarı başka konumda, gaz en altta) görmemeli: görürse kip anahtarı "çevrilmiş" sayılır
        (STABILIZE) ve gaz sıfırken motorlar durur — gerçek bir bağlantı kaybında olmayan yapay bir etki. Bu yüzden:
        - kesilirken override BIRAKILMAZ (8×0 gönderilmez): bırakma çerçevesi ArduPilot'a kanalları alıcıdan yeniden okutur ve SIM_RC_FAIL
          yalnız yeni darbeyi keser, son değerleri değil. Çerçeveler durunca araç gerçek alıcı kaybındaki gibi son girdilerde donar ve kendi
          zaman aşımıyla (RC_FS_TIMEOUT ≈ 1 sn) Radio Failsafe'e girer.
        - dönerken önce tarayıcı çerçeveleri yeniden akar, "darbe yok" RC_GECIS_S sonra kaldırılır (`_rc_gecis_adim`).
        Sahte kinematikte alıcı benzetimi yoktur: override hemen bırakılır."""
        kes = self.rc_kesik
        if kes == self._rc_kesildi:
            return
        self._rc_kesildi = kes
        self._rc_gecis = None
        if kes:
            self._gaz_etkin = False
            fs = [(ad, next((v for v in (self._oturum_degeri(ad), self._kayit_degeri(ad)) if v is not None), RC_FS_FABRIKA)) for ad in RC_FS_ADLARI]
            self._yaz((*fs, ('SIM_RC_FAIL', 1.0)), zorla=True)
            if self.s.sahte is not None:
                self._rc_serbest()
        elif self.s.sahte is None:
            self._rc_gecis = time.time() + RC_GECIS_S

    def _rc_gecis_adim(self):
        """Kumanda geri verilirken sıranın ikinci yarısı (her telemetri adımında; gerçek zaman): "darbe yok" kalkar, arıza koruması oturum değerine."""
        if self._rc_gecis is None or time.time() < self._rc_gecis:
            return
        self._rc_gecis = None
        if not self._rc_kesildi:
            self._yaz((('SIM_RC_FAIL', 0.0), *((ad, self._oturum_degeri(ad) or 0.0) for ad in RC_FS_ADLARI)), zorla=True)

    def _fs_yaz(self):
        """Kopter: GPS kaybında otopilot tepkisi (FS_EKF_ACTION) seçilen değere; önceki değer toparlanınca geri yazılmak üzere saklanır."""
        s = self.s
        if not self.kopter or s.sahte is not None:
            return
        if self._fs_eski is None:
            v = self._oturum_degeri('FS_EKF_ACTION')
            if v is None:
                v = (getattr(s, 'param_son', None) or {}).get('FS_EKF_ACTION')
            if v is None:
                v = self._kayit_degeri('FS_EKF_ACTION')
            self._fs_eski = float(v) if v is not None else FS_EKF_FABRIKA
        self._yaz((('FS_EKF_ACTION', FS_DEGER[self.cfg['fs']]),))

    def _fs_geri(self):
        if self._fs_eski is not None:
            v = self._oturum_degeri('FS_EKF_ACTION')   # karıştırma sürerken Mission Planner'dan yazıldıysa o değer
            self._yaz((('FS_EKF_ACTION', self._fs_eski if v is None else v),), zorla=True)
            self._fs_eski = None
            self._son.pop('FS_EKF_ACTION', None)

    def _bolge_olc(self):
        """Aracın GERÇEK konumunun bölge merkezine mesafesi + içeride mi (histerezisli). Dönüş: içeride durumu değişti mi."""
        z = self.cfg['zone']
        once = self._icerde
        if not (self.on and z['on']):
            self._icerde, self._mesafe = False, None
            return once
        te = self.s.tele
        lat, lon = (self.g_lat, self.g_lon) if self.g_lat is not None else (te.get('lat'), te.get('lon'))
        if lat is None or lon is None:
            return False
        self._mesafe = fark_m(z['lat'], z['lon'], lat, lon)
        self._icerde = self._mesafe <= z['r_m'] * (BOLGE_CIKIS if once else 1.0)
        return once != self._icerde

    def _bolge_degisti(self):
        if self._icerde:
            self.ist['zone_in'] += 1
        self._uygula(zorla_gps=True)
        self.s._olay('Karıştırıcı bölgesine girildi — ' + ayar_metni({**self.cfg, 'zone': None, 'dur_s': 0}) if self._icerde
                     else 'Karıştırıcı bölgesinden çıkıldı — bağlantılar ve GPS geri geliyor', 4 if self._icerde else 6)
        self._tele()
        self._yay('zone')

    def rc_gaz(self, ch):
        """Tarayıcı kumanda çerçevesi araca gitmeden önce: "gaz ortada" kuralı geçerliyken gaz kanalı boşsa (0 = kanala dokunma: sanal kumanda
        açık ama gaz çubuğu hiç oynatılmamış) 1500 ile doldurulur. Ayrı bir override çerçevesi gönderilmez: RC_CHANNELS_OVERRIDE'da 0 "kanalı
        bırak" demektir, iki kaynak birbirinin kanallarını bırakırdı. Gaz kanalı doluysa pilot gazı devralmıştır."""
        if ch[2]:
            self._rc_gaz_t = time.time()
            return ch
        te = self.s.tele
        if not self._gaz_orta or not any(ch) or not (te.get('armed') and te.get('mode') == ALT_HOLD):
            return ch
        ch = list(ch)
        ch[2] = GAZ_ORTA_PWM
        return ch

    def _gaz_adim(self):
        """ "Gaz ortada": kopter ALT_HOLD'dayken ve gaz girdisi yokken (kumanda bağlı değil ya da sanal kumandada gaz çubuğuna hiç dokunulmamış)
        gaz kanalı 1500'de tutulur (aksi hâlde SITL'in iç RC'si gazı en altta tutar, araç alçalır). Pilot gaz çubuğunu oynatınca devralır; kip
        değişince / disarm'da override bırakılır."""
        if not self._gaz_orta:
            return
        s = self.s
        te = s.tele
        asili = bool(te.get('armed')) and te.get('mode') == ALT_HOLD
        simdi = time.time()
        akis = simdi - getattr(s, '_rc_son', 0.0) <= RC_YOK_S   # tarayıcıdan kumanda çerçevesi akıyor (gaz kanalı rc_gaz() içinde doldurulur)
        pilot = simdi - self._rc_gaz_t <= RC_YOK_S              # pilot gaz çubuğunu sürüyor
        if asili and not self.rc_kesik and not pilot and s._heartbeat_alindi and s.sysid is not None:
            if not akis:
                s._gonder(s.mav.rc_channels_override_encode(s.sysid, s.comp, 0, 0, GAZ_ORTA_PWM, 0, 0, 0, 0, 0))
            if not self._gaz_etkin:
                self._gaz_etkin = True
                s._olay('Gaz girdisi yok: gaz çubuğu ortada kabul ediliyor (irtifa korunur; araç rüzgârla sürüklenir)', 4)
                self._yay('thr')
            return
        if self._gaz_etkin:
            self._gaz_etkin = False
            if not akis and not self.rc_kesik:
                self._rc_serbest()
            self._yay('thr')
        if not asili and not self.on and not self._gercek:
            self._gaz_orta = False   # karıştırma bitti, EKF toparlandı ve araç ALT_HOLD'da değil: kural biter

    # ---------------- adım ----------------
    def _tele(self):
        te = self.s.tele
        if self.on:
            te['jam'] = {'gps': self.cfg['gps'], 'spoof': self.cfg['spoof']['on'], 'off_m': round(math.hypot(self.ok, self.od), 1), 'left_s': self._kalan,
                         'rc': self.cfg['rc'], 'tlm': self.cfg['tlm'], 'active': self.aktif}
            if self.cfg['zone']['on']:
                te['jam']['inside'], te['jam']['dist_m'] = self._icerde, (round(self._mesafe, 1) if self._mesafe is not None else None)
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
        self._rc_gecis_adim()
        if not (self.on or self._gercek or self._gaz_orta):
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
        elif self._gercek:
            self._adim_toparlanma(dt)
        self._gaz_adim()
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
        if self._bolge_olc():
            self._bolge_degisti()
        vk = vd = 0.0
        g = self.gps_etkin
        if self.spoof_etkin:
            self.ok, self.od, self.v, vk, vd = surukle(self.ok, self.od, self.v, cfg['spoof'], dt)
            self.ist['spoof_s'] += dt
            self.ist['max_off_m'] = max(self.ist['max_off_m'], math.hypot(self.ok, self.od))
        if g == 'light':
            f = math.exp(-dt / HAFIF_TAU_S)
            q = HAFIF_SIGMA_M * math.sqrt(1.0 - f * f)
            self.gk, self.gd = self.gk * f + self._rng.gauss(0.0, q), self.gd * f + self._rng.gauss(0.0, q)
        if g != 'off':
            self.ist['gps_s'][g] += dt
        if self.rc_kesik:
            self.ist['rc_s'] += dt
        if self.tlm_kesik:
            self.ist['tlm_s'] += dt
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
            self._fs_geri()   # GPS kaybı tepkisi eski değerine (kip otopilotun bıraktığı yerde kalır)
            self._tele()
            self._yay('settled')
