"""MASTERWORLD canlı veri kaynak kaydı (docs/masterworld.md §2–§3): sözlükler, yerleşik katalog (KNOWN), doğrulama ve Excel içe aktarma.

- xlsx okuyucu yalnız stdlib (zipfile + ElementTree; openpyxl YOK): ilk sayfa, paylaşılan dizgiler, satır içi dizgiler, hücre dolgu rengi
  (styles.xml cellXfs → fills) ve koşullu biçimlendirme (SEARCH("…") / containsText kuralları, dxf dolgusu). Lisans hücresi turuncu ise
  (doğrudan dolgu ya da koşullu biçim) kaynak `noncommercial=1` sayılır — metin kuralına ek olarak.
- İçe aktarma idempotent (§3.1): var olan slug'da yalnız Excel bilgi sütunları + bayraklar güncellenir; enabled, api_key, sort, default_on,
  params, kind, dolu adapter ve dolu attribution KORUNUR. Excel'de olmayan kayıt silinmez. Yerleşik ekler (origin='builtin') yoksa eklenir.
- CLI: `python -m sshm.mw_catalog <dosya.xlsx>` — önce data/sshm-pre-mw-<ts>.db yedeği (sqlite backup API), sonra içe aktarma; sonuç JSON."""
import colorsys
import io
import json
import re
import sqlite3
import sys
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

from . import db, settings

# ---------------- sözlükler (§2) ----------------
CATEGORIES = {
    'air': ('aircraft',),
    'sea': ('vessel', 'warning'),
    'space': ('satellite', 'iss', 'aurora'),
    'natural': ('quake', 'fire', 'disaster', 'event', 'volcano', 'lightning'),
    'weather': ('metar', 'buoy', 'sonde', 'radar', 'forecast', 'alert'),
    'environment': ('airquality', 'radiation', 'imagery'),
    'camera': ('camera',),
    'radio': ('radio',),
    'ground': ('transit', 'bike'),
    'basemap': ('basemap',),
    'ham': ('aprs', 'spot'),
    'infra': ('cable', 'plant', 'cell', 'internet'),
    'news': ('news',),
}
# Türkçe kategori etiketleri (Merkez › MASTERWORLD; radio Excel'de yok, yerleşik eklerle gelir)
CATEGORY_LABELS = {'air': 'Hava trafiği', 'sea': 'Deniz trafiği', 'space': 'Uzay', 'natural': 'Doğal olaylar', 'weather': 'Meteoroloji',
                   'environment': 'Çevre', 'camera': 'Kamera', 'radio': 'Radyo', 'ground': 'Kara ulaşımı', 'basemap': 'Altlık', 'ham': 'Telsiz',
                   'infra': 'Altyapı', 'news': 'Olay / Haber'}
KINDS = tuple(dict.fromkeys(k for ks in CATEGORIES.values() for k in ks))
EXCEL_CATEGORIES = {'hava trafiği': 'air', 'deniz trafiği': 'sea', 'uzay': 'space', 'doğal olaylar': 'natural', 'meteoroloji': 'weather',
                    'çevre': 'environment', 'kamera': 'camera', 'radyo': 'radio', 'kara ulaşımı': 'ground', 'altlık': 'basemap',
                    'telsiz': 'ham', 'altyapı': 'infra', 'olay / haber': 'news', 'olay/haber': 'news'}
# masterworld sunucusundaki adaptör anahtarları (app/sources/<ad>.py); 'points' = Merkez'den elle eklenen noktalar (mw_points)
ADAPTERS = ('adsb_lol', 'adsb_fi', 'airplanes_live', 'opensky', 'celestrak', 'wheretheiss', 'usgs', 'emsc', 'afad', 'gdacs', 'eonet', 'firms',
            'open_meteo', 'metar', 'ndbc', 'rainviewer', 'sondehub', 'safecast', 'sensor_community', 'windy_webcams', 'caltrans_cctv',
            'radio_browser', 'digitraffic_cam', 'submarine_cables', 'swpc_aurora', 'aisstream', 'points')
MEDIA_TYPES = ('image', 'mjpeg', 'audio', 'link')
# Excel başlıkları → sütun (§3.1); karşılaştırma büyük/küçük harf ve boşluk duyarsız
COLUMNS = {'kategori': 'category_tr', 'kaynak': 'name', 'veri': 'data_desc', 'erişim/endpoint': 'endpoint', 'protokol': 'protocol',
           'kimlik doğrulama': 'auth', 'push/pull': 'push_pull', 'ölçek/güncelleme': 'scale', 'lisans/ticari kullanım': 'license', 'not': 'note'}
INFO_FIELDS = ('name', 'data_desc', 'endpoint', 'protocol', 'auth', 'push_pull', 'scale', 'license', 'note')
TEXT_FIELDS = ('data_desc', 'protocol', 'auth', 'push_pull', 'scale', 'license', 'note', 'attribution')
SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,39}$')
ADAPTER_RE = re.compile(r'^[a-z0-9_]{2,40}$')
URL_RE = re.compile(r'^https?://[^\s<>"\']+$', re.I)
PARAMS_MAX, PROPS_MAX, TEXT_MAX, KEY_MAX = 4096, 2048, 500, 2000
XLSX_MAX = 5 * 1024 * 1024
UNZIP_MAX = 60 * 1024 * 1024          # sıkıştırılmış bomba: açılmış toplam boyut sınırı

# ---------------- yerleşik katalog (slug → öneriler) ----------------
# kind, adapter, params, attribution, attribution_url, default_on (oran / TTL: masterworld adaptörünün META varsayılanı; yönetici ezebilir). Excel'de bulunan ama burada olmayan satır: kind =
# kategorinin ilk türü, adapter NULL (yalnız katalog). Atıf metinleri kaynağın lisans / kullanım koşullarına göre yazılmıştır.
KNOWN = {
    # hava trafiği
    'adsb-lol': {'kind': 'aircraft', 'adapter': 'adsb_lol', 'attribution': '© adsb.lol contributors (ODbL)', 'attribution_url': 'https://adsb.lol/',
                 'default_on': 1},
    'adsb-fi': {'kind': 'aircraft', 'adapter': 'adsb_fi', 'attribution': 'Veri: adsb.fi (kişisel / ticari olmayan kullanım)',
                'attribution_url': 'https://adsb.fi/'},
    'airplanes-live': {'kind': 'aircraft', 'adapter': 'airplanes_live', 'attribution': 'Veri: airplanes.live (ticari olmayan kullanım)',
                       'attribution_url': 'https://airplanes.live/', 'enabled': 0},   # veri merkezi IP'lerine 403; erişim onayı gelene dek kapalı
    'opensky-network': {'kind': 'aircraft', 'adapter': 'opensky', 'attribution': 'The OpenSky Network (araştırma / ticari olmayan)',
                        'attribution_url': 'https://opensky-network.org/'},
    'gcmb-io': {'kind': 'aircraft'}, 'freeflight-api': {'kind': 'aircraft'},
    # deniz
    'aisstream-io': {'kind': 'vessel', 'adapter': 'aisstream', 'attribution': 'AIS: aisstream.io', 'attribution_url': 'https://aisstream.io/'},
    'kystverket': {'kind': 'vessel'}, 'danimarka-dma-ais': {'kind': 'vessel'}, 'noaa-marinecadastre': {'kind': 'vessel'},
    'nga-navigational-warnings': {'kind': 'warning'},
    # uzay
    'celestrak': {'kind': 'satellite', 'adapter': 'celestrak', 'params': {'groups': ['stations', 'visual', 'gps-ops']},
                  'attribution': 'Yörünge verisi: CelesTrak (T.S. Kelso)', 'attribution_url': 'https://celestrak.org/'},
    'space-track-org': {'kind': 'satellite'}, 'n2yo': {'kind': 'satellite'}, 'satnogs-db': {'kind': 'satellite'},
    'open-notify': {'kind': 'iss', 'adapter': 'wheretheiss', 'attribution': 'ISS konumu: wheretheiss.at', 'attribution_url': 'https://wheretheiss.at/',
                    'default_on': 1},
    'noaa-swpc': {'kind': 'aurora', 'adapter': 'swpc_aurora', 'attribution': 'NOAA Space Weather Prediction Center',
                  'attribution_url': 'https://www.swpc.noaa.gov/'},
    # doğal olaylar
    'usgs-earthquake': {'kind': 'quake', 'adapter': 'usgs', 'params': {'feed': 'all_day'}, 'attribution': 'USGS Earthquake Hazards Program',
                        'attribution_url': 'https://earthquake.usgs.gov/', 'default_on': 1},
    'emsc-seismicportal': {'kind': 'quake', 'adapter': 'emsc', 'attribution': 'EMSC – Euro-Mediterranean Seismological Centre (CC BY 4.0)',
                           'attribution_url': 'https://www.seismicportal.eu/'},
    'afad-deprem': {'kind': 'quake', 'adapter': 'afad', 'attribution': 'T.C. İçişleri Bakanlığı AFAD Deprem Dairesi',
                    'attribution_url': 'https://deprem.afad.gov.tr/'},
    'nasa-firms': {'kind': 'fire', 'adapter': 'firms', 'attribution': 'NASA FIRMS (LANCE / EOSDIS)', 'attribution_url': 'https://firms.modaps.eosdis.nasa.gov/'},
    'gdacs': {'kind': 'disaster', 'adapter': 'gdacs', 'attribution': 'GDACS – Global Disaster Alert and Coordination System (AB JRC / BM OCHA)',
              'attribution_url': 'https://www.gdacs.org/'},
    'nasa-eonet': {'kind': 'event', 'adapter': 'eonet', 'attribution': 'NASA EONET', 'attribution_url': 'https://eonet.gsfc.nasa.gov/'},
    'smithsonian-gvp': {'kind': 'volcano'}, 'blitzortung': {'kind': 'lightning'},
    # meteoroloji
    'open-meteo': {'kind': 'forecast', 'adapter': 'open_meteo', 'params': {'mode': 'point'}, 'attribution': 'Weather data by Open-Meteo.com (CC BY 4.0)',
                   'attribution_url': 'https://open-meteo.com/'},
    'noaa-nws-api': {'kind': 'alert'},
    'noaa-ndbc': {'kind': 'buoy', 'adapter': 'ndbc', 'attribution': 'NOAA National Data Buoy Center', 'attribution_url': 'https://www.ndbc.noaa.gov/'},
    'aviationweather-gov': {'kind': 'metar', 'adapter': 'metar', 'attribution': 'NOAA Aviation Weather Center (aviationweather.gov)',
                            'attribution_url': 'https://aviationweather.gov/'},
    'rainviewer': {'kind': 'radar', 'adapter': 'rainviewer', 'attribution': 'Radar: RainViewer', 'attribution_url': 'https://www.rainviewer.com/'},
    'sondehub': {'kind': 'sonde', 'adapter': 'sondehub', 'attribution': 'Radyosonde: SondeHub', 'attribution_url': 'https://sondehub.org/'},
    # çevre
    'openaq': {'kind': 'airquality'},
    'sensor-community': {'kind': 'airquality', 'adapter': 'sensor_community', 'attribution': '© Sensor.Community contributors (ODbL)',
                         'attribution_url': 'https://sensor.community/'},
    'safecast': {'kind': 'radiation', 'adapter': 'safecast', 'attribution': 'Safecast (CC0)', 'attribution_url': 'https://safecast.org/'},
    'copernicus': {'kind': 'imagery'},
    # kamera
    'windy-webcams-api-v3': {'kind': 'camera', 'adapter': 'windy_webcams', 'attribution': 'Webcams provided by windy.com',
                             'attribution_url': 'https://www.windy.com/webcams'},
    'abd-eyalet-511': {'kind': 'camera'},
    # kara ulaşımı
    'mobility-database': {'kind': 'transit'}, 'gbfs': {'kind': 'bike'}, 'transitland': {'kind': 'transit'},
    # altlık
    'openstreetmap': {'kind': 'basemap', 'attribution': '© OpenStreetMap contributors (ODbL)', 'attribution_url': 'https://www.openstreetmap.org/copyright'},
    'cesium-osm-buildings': {'kind': 'basemap'},
    # telsiz
    'aprs-is': {'kind': 'aprs'}, 'wsprnet': {'kind': 'spot'},
    # altyapı
    'cloudflare-radar': {'kind': 'internet'},
    'telegeography-submarine-cable-map': {'kind': 'cable', 'adapter': 'submarine_cables', 'attribution': '© TeleGeography – Submarine Cable Map (CC BY-NC-SA 3.0)',
                                          'attribution_url': 'https://www.submarinecablemap.com/'},
    'global-power-plant-database': {'kind': 'plant'}, 'opencellid': {'kind': 'cell'},
    # haber
    'gdelt-2-0': {'kind': 'news'}, 'acled': {'kind': 'news'}, 'reliefweb-api': {'kind': 'news'},
}
# Excel'de olmayan, her içe aktarmada yoksa eklenen kaynaklar (§2)
BUILTIN = [
    {'slug': 'caltrans-cctv', 'category': 'camera', 'kind': 'camera', 'name': 'Caltrans CCTV', 'adapter': 'caltrans_cctv',
     'data_desc': 'Kaliforniya DOT trafik kameraları (anlık görüntü)', 'endpoint': 'https://cwwp2.dot.ca.gov/data/', 'protocol': 'JSON',
     'auth': 'Yok', 'push_pull': 'Pull', 'scale': '~3.000 kamera; 1–5 dk', 'license': 'Kamu malı (ABD eyalet kurumu)',
     'note': '"ABD eyalet 511 / DOT" satırının somut örneği', 'attribution': 'Kamera görüntüleri: Caltrans (California DOT)',
     'attribution_url': 'https://cwwp2.dot.ca.gov/', 'default_on': 1, 'rate_per_min': 6, 'ttl_s': 300, 'sort': 375},
    {'slug': 'digitraffic-cam', 'category': 'camera', 'kind': 'camera', 'name': 'Digitraffic Weathercams (Finlandiya)', 'adapter': 'digitraffic_cam',
     'data_desc': 'Finlandiya karayolu hava kameraları (anlık görüntü)', 'endpoint': 'https://tie.digitraffic.fi/api/weathercam/v1/stations',
     'protocol': 'REST / GeoJSON', 'auth': 'Yok', 'push_pull': 'Pull', 'scale': '~800 istasyon; 10 dk', 'license': 'CC BY 4.0',
     'note': 'Fintraffic açık veri', 'attribution': 'Fintraffic / digitraffic.fi (CC BY 4.0)', 'attribution_url': 'https://www.digitraffic.fi',
     'default_on': 1, 'rate_per_min': 6, 'ttl_s': 600, 'sort': 376},
    {'slug': 'radio-browser', 'category': 'radio', 'kind': 'radio', 'name': 'Radio Browser', 'adapter': 'radio_browser',
     'data_desc': 'Dünya radyo istasyonları (konumlu, canlı yayın akışı)', 'endpoint': 'https://api.radio-browser.info/', 'protocol': 'REST',
     'auth': 'Yok', 'push_pull': 'Pull', 'scale': '~50.000 istasyon; günlük', 'license': 'Açık veri (kamu malı)',
     'note': 'Ses akışı tarayıcıda doğrudan çalınır (yayıncının sunucusundan)', 'attribution': 'İstasyon kataloğu: Radio Browser (radio-browser.info)',
     'attribution_url': 'https://www.radio-browser.info/', 'default_on': 1, 'rate_per_min': 6, 'ttl_s': 21600, 'sort': 900},
]


# ---------------- metin yardımcıları ----------------
_TR = str.maketrans('çğıöşüÇĞİÖŞÜâîûÂÎÛ', 'cgiosuCGIOSUaiuAIU')


def tr_lower(s):
    return (s or '').replace('I', 'ı').replace('İ', 'i').lower()


def slugify(name):
    """Kaynak adından slug: ilk '/' ya da '(' öncesi, Türkçe harfler sadeleşir, [a-z0-9-], ≤ 40."""
    base = re.split(r'[/(]', name or '', maxsplit=1)[0].translate(_TR)
    base = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', base).strip('-')[:40].strip('-')


def _norm_head(s):
    return re.sub(r'\s*/\s*', '/', re.sub(r'\s+', ' ', tr_lower(s).strip()))


def flags_from_text(auth, license_):
    """§3.1 bayrakları: key_required (Kimlik Doğrulama 'Yok' ile başlamıyorsa), noncommercial, attribution_required."""
    a, lic = tr_lower(auth).strip(), tr_lower(license_)
    key = 1 if a and not a.startswith('yok') else 0
    nc = 1 if (any(w in lic for w in ('ticari olmayan', 'ticari için', 'non-commercial', 'noncommercial', 'kişisel'))
               or re.search(r'(?<![A-Za-z])NC(?![A-Za-z])', license_ or '')) else 0
    att = 1 if any(w in lic for w in ('atıf', 'cc by', 'odbl')) else 0
    return key, nc, att


# ---------------- xlsx okuyucu (stdlib) ----------------
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
NS_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
NS_A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
NS_PR = '{http://schemas.openxmlformats.org/package/2006/relationships}'


class XlsxError(ValueError):
    pass


def _col_index(ref):
    m = re.match(r'^([A-Z]{1,3})(\d+)$', ref or '')
    if not m:
        return None, None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1, int(m.group(2))


def _is_orange(rgb):
    """Turuncu tonu (Excel 'Turuncu, Vurgu 2' ve açık tonları dahil): ton 12°–50°, doygunluk ≥ 0.12, parlaklık ≥ 0.45."""
    if not rgb or not re.fullmatch(r'[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8}', rgb):
        return False
    r, g, b = (int(rgb[-6:][i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ss, vv = colorsys.rgb_to_hsv(r, g, b)
    return 12 <= hh * 360 <= 50 and ss >= 0.12 and vv >= 0.45


def _theme_colors(z):
    """theme1.xml renk şeması; Excel tema dizini sırası lt1, dk1, lt2, dk2, accent1..6, hlink, folHlink."""
    try:
        root = ET.fromstring(z.read('xl/theme/theme1.xml'))
    except (KeyError, ET.ParseError):
        return []
    cs = root.find(f'.//{NS_A}clrScheme')
    if cs is None:
        return []
    vals = {}
    for el in cs:
        tag = el.tag.replace(NS_A, '')
        c = el[0] if len(el) else None
        vals[tag] = (c.get('lastClr') or c.get('val')) if c is not None else None
    return [vals.get(k) for k in ('lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink')]


def _fill_orange(fill, theme):
    pf = fill.find(f'{NS}patternFill') if fill is not None else None
    if pf is None:
        return False
    for tag in ('fgColor', 'bgColor'):
        c = pf.find(f'{NS}{tag}')
        if c is None:
            continue
        rgb = c.get('rgb')
        if not rgb and c.get('theme') is not None:
            try:
                rgb = theme[int(c.get('theme'))]
            except (ValueError, IndexError):
                rgb = None
        if _is_orange(rgb):
            return True
    return False


def _sqref_cells(sqref):
    out = []
    for part in (sqref or '').split():
        a, _, b = part.partition(':')
        c1, r1 = _col_index(a.replace('$', ''))
        c2, r2 = _col_index((b or a).replace('$', ''))
        if c1 is not None and c2 is not None:
            out.append((c1, r1, c2, r2))
    return out


def read_xlsx(data):
    """İlk sayfa → [(satır_no, [(değer, turuncu_mu), …]), …]. Hatalı / büyük dosyada XlsxError."""
    if len(data) > XLSX_MAX:
        raise XlsxError('Dosya 5 MB sınırını aşıyor')
    if data[:2] != b'PK':
        raise XlsxError('Dosya .xlsx (zip) değil')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist()) > UNZIP_MAX:
            raise XlsxError('Dosya içeriği çok büyük')
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        sheet = wb.find(f'{NS}sheets/{NS}sheet')
        if sheet is None:
            raise XlsxError('Çalışma kitabında sayfa yok')
        rid = sheet.get(f'{NS_R}id')
        target = 'worksheets/sheet1.xml'
        try:
            for rel in ET.fromstring(z.read('xl/_rels/workbook.xml.rels')).iter(f'{NS_PR}Relationship'):
                if rel.get('Id') == rid:
                    target = rel.get('Target')
        except KeyError:
            pass
        path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).iter(f'{NS}si'):
                shared.append(''.join(t.text or '' for t in si.iter(f'{NS}t')))
        theme = _theme_colors(z)
        xf_orange, dxf_orange = [], []
        if 'xl/styles.xml' in z.namelist():
            st = ET.fromstring(z.read('xl/styles.xml'))
            fills = list(st.find(f'{NS}fills') if st.find(f'{NS}fills') is not None else [])
            fill_o = [_fill_orange(f, theme) for f in fills]
            xfs = st.find(f'{NS}cellXfs')
            for xf in (xfs if xfs is not None else []):
                try:
                    xf_orange.append(fill_o[int(xf.get('fillId') or 0)])
                except (ValueError, IndexError):
                    xf_orange.append(False)
            dx = st.find(f'{NS}dxfs')
            dxf_orange = [_fill_orange(d.find(f'{NS}fill'), theme) for d in (dx if dx is not None else [])]
        ws = ET.fromstring(z.read(path))
    except XlsxError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
        raise XlsxError(f'xlsx okunamadı: {str(e)[:120]}')
    # koşullu biçim: turuncu dxf'li kurallar → (aralıklar, aranan metinler) — SEARCH("x", hücre) büyük/küçük harf duyarsız
    cf_rules = []
    for cf in ws.iter(f'{NS}conditionalFormatting'):
        cells = _sqref_cells(cf.get('sqref'))
        for rule in cf.iter(f'{NS}cfRule'):
            try:
                orange = dxf_orange[int(rule.get('dxfId'))]
            except (TypeError, ValueError, IndexError):
                orange = False
            if not orange:
                continue
            needles = []
            if rule.get('type') == 'containsText' and rule.get('text'):
                needles.append(rule.get('text'))
            for f in rule.iter(f'{NS}formula'):
                needles += re.findall(r'SEARCH\(\s*"([^"]+)"', f.text or '', re.I)
            if needles:
                cf_rules.append((cells, [tr_lower(n) for n in needles]))
    rows = []
    for row in ws.iter(f'{NS}row'):
        vals = {}
        for c in row.findall(f'{NS}c'):
            ci, ri = _col_index(c.get('r'))
            if ci is None or ci > 60:
                continue
            t = c.get('t')
            v = c.find(f'{NS}v')
            if t == 's':
                try:
                    val = shared[int(v.text)] if v is not None else ''
                except (ValueError, IndexError):
                    val = ''
            elif t == 'inlineStr':
                val = ''.join(x.text or '' for x in c.iter(f'{NS}t'))
            else:
                val = v.text if v is not None and v.text is not None else ''
            val = str(val).strip()
            try:
                orange = xf_orange[int(c.get('s') or 0)]
            except (ValueError, IndexError):
                orange = False
            if not orange and val:
                low = tr_lower(val)
                orange = any(any(c1 <= ci <= c2 and r1 <= ri <= r2 for c1, r1, c2, r2 in cells) and any(n in low for n in nd)
                             for cells, nd in cf_rules)
            vals[ci] = (val, orange)
        rn = int(row.get('r') or len(rows) + 1)
        if vals:
            rows.append((rn, [vals.get(i, ('', False)) for i in range(max(vals) + 1)]))
    return rows


def parse_sources(data):
    """xlsx → (kaynak satırları, atlananlar). Başlık satırı ilk dolu satırdır; sütunlar ada göre eşlenir."""
    rows = read_xlsx(data)
    if not rows:
        raise XlsxError('Sayfa boş')
    head_rn, head = rows[0]
    cols = {}
    for i, (v, _) in enumerate(head):
        key = COLUMNS.get(_norm_head(v))
        if key and key not in cols:
            cols[key] = i
    if 'name' not in cols or 'category_tr' not in cols:
        raise XlsxError('Başlıkta "Kategori" ve "Kaynak" sütunları bulunamadı')
    out, skipped = [], []
    for rn, cells in rows[1:]:
        get = lambda k: cells[cols[k]][0] if k in cols and cols[k] < len(cells) else ''   # noqa: E731
        if not any(v for v, _ in cells):
            continue
        name = get('name')
        if not name:
            skipped.append({'row': rn, 'reason': 'Kaynak adı boş'})
            continue
        cat = EXCEL_CATEGORIES.get(_norm_head(get('category_tr')).replace(' / ', '/')) or EXCEL_CATEGORIES.get(tr_lower(get('category_tr')).strip())
        if not cat:
            skipped.append({'row': rn, 'reason': f'Bilinmeyen kategori: {get("category_tr")[:60]}'})
            continue
        slug = slugify(name)
        if not SLUG_RE.match(slug):
            skipped.append({'row': rn, 'reason': f'Addan geçerli slug türetilemedi: {name[:60]}'})
            continue
        rec = {k: (get(k)[:TEXT_MAX] or None) for k in INFO_FIELDS}
        rec['name'] = name[:TEXT_MAX]
        key, nc, att = flags_from_text(rec['auth'], rec['license'])
        lic_col = cols.get('license')
        if lic_col is not None and lic_col < len(cells) and cells[lic_col][1]:
            nc = 1   # Excel'de Lisans hücresi turuncu: ticari kullanım kısıtlı
        rec |= {'slug': slug, 'category': cat, 'key_required': key, 'noncommercial': nc, 'attribution_required': att, 'row': rn}
        out.append(rec)
    return out, skipped


# ---------------- içe aktarma (§3.1) ----------------
SRC_COLS = ('slug', 'category', 'kind', 'name', 'data_desc', 'endpoint', 'protocol', 'auth', 'push_pull', 'scale', 'license', 'note', 'adapter', 'params',
            'api_key', 'key_required', 'noncommercial', 'attribution_required', 'attribution', 'attribution_url', 'rate_per_min', 'ttl_s', 'enabled',
            'default_on', 'sort', 'origin', 'created_at', 'updated_at')


def _insert(conn, rec):
    now = db.now()
    row = {k: rec.get(k) for k in SRC_COLS} | {'created_at': now, 'updated_at': now}
    row['params'] = json.dumps(rec.get('params') or {}, ensure_ascii=False, separators=(',', ':'))
    for k in ('key_required', 'noncommercial', 'attribution_required', 'enabled', 'default_on'):
        row[k] = int(bool(row.get(k)))
    row['sort'] = int(row.get('sort') or 100)
    row['origin'] = row.get('origin') or 'manual'
    cur = conn.execute(f"INSERT INTO mw_sources ({', '.join(SRC_COLS)}) VALUES ({', '.join('?' * len(SRC_COLS))})", [row[k] for k in SRC_COLS])
    return cur.lastrowid


def _new_from_excel(rec):
    k = KNOWN.get(rec['slug'], {})
    adapter = k.get('adapter')
    return rec | {'kind': k.get('kind') or CATEGORIES[rec['category']][0], 'adapter': adapter, 'params': k.get('params') or {},
                  'attribution': k.get('attribution'), 'attribution_url': k.get('attribution_url'), 'default_on': k.get('default_on', 0),
                  'rate_per_min': k.get('rate_per_min'), 'ttl_s': k.get('ttl_s'), 'sort': k.get('sort') or rec['row'] * 10,
                  'enabled': k.get('enabled', 1 if adapter and not rec['key_required'] else 0), 'origin': 'excel'}


def ensure_builtins(conn):
    added = 0
    for b in BUILTIN:
        if conn.execute('SELECT 1 FROM mw_sources WHERE slug = ?', (b['slug'],)).fetchone():
            continue
        key, nc, att = flags_from_text(b['auth'], b['license'])
        _insert(conn, b | {'key_required': key, 'noncommercial': nc, 'attribution_required': att or 1, 'enabled': 1 if not key else 0, 'origin': 'builtin'})
        added += 1
    return added


def import_records(conn, recs, skipped=None):
    """Ayrıştırılmış Excel satırlarını kayda işler; dönüş {added, updated, unchanged, skipped:[{row, reason}]}."""
    res = {'added': 0, 'updated': 0, 'unchanged': 0, 'skipped': list(skipped or [])}
    seen = set()
    for rec in recs:
        if rec['slug'] in seen:
            res['skipped'].append({'row': rec['row'], 'reason': f'Aynı slug ikinci kez: {rec["slug"]}'})
            continue
        seen.add(rec['slug'])
        cur = conn.execute('SELECT * FROM mw_sources WHERE slug = ?', (rec['slug'],)).fetchone()
        if not cur:
            _insert(conn, _new_from_excel(rec))
            res['added'] += 1
            continue
        k = KNOWN.get(rec['slug'], {})
        upd = {f: rec[f] for f in INFO_FIELDS + ('category', 'key_required', 'noncommercial', 'attribution_required')}
        # boş alanlar yerleşik katalogdan doldurulur; dolu adapter / attribution (elle değişmiş olabilir) korunur
        for f in ('adapter', 'attribution', 'attribution_url', 'rate_per_min', 'ttl_s'):
            if (cur[f] is None or cur[f] == '') and k.get(f) is not None:
                upd[f] = k[f]
        changed = {f: v for f, v in upd.items() if cur[f] != v}
        if not changed:
            res['unchanged'] += 1
            continue
        changed['updated_at'] = db.now()
        conn.execute(f"UPDATE mw_sources SET {', '.join(f'{f} = ?' for f in changed)} WHERE id = ?", [*changed.values(), cur['id']])
        res['updated'] += 1
    res['added'] += ensure_builtins(conn)
    return res


def import_xlsx(conn, data):
    recs, skipped = parse_sources(data)
    res = import_records(conn, recs, skipped)
    conn.commit()
    return res


# ---------------- doğrulama (§3.2; yönetici uçları) ----------------
class Invalid(ValueError):
    pass


def _text(v, name, required=False, mx=TEXT_MAX):
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise Invalid(f'{name} gerekli')
        return None
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise Invalid(f'{name} metin olmalı')
    v = str(v).strip()
    if len(v) > mx:
        raise Invalid(f'{name} en fazla {mx} karakter')
    return v


def _url(v, name, https_only=False):
    v = _text(v, name)
    if v is None:
        return None
    if not (v.lower().startswith('https://') if https_only else URL_RE.match(v)) or not URL_RE.match(v):
        raise Invalid(f'{name} {"https://" if https_only else "http(s)://"} ile başlayan bir adres olmalı')
    return v


def _endpoint(v):
    """Bilgi alanı: Excel'de 'gcmb.io', 'wss://…', 'Eyalet bazlı 511 portalları' gibi değerler var. Şema içeriyorsa yalnız http/https/ws/wss."""
    v = _text(v, 'endpoint')
    if v and '://' in v and not re.match(r'^(https?|wss?)://[^\s<>"\']+$', v, re.I):
        raise Invalid('endpoint http(s):// ya da ws(s):// ile başlamalı')
    return v


def _json_obj(v, name, mx):
    if v is None or v == '':
        return '{}'
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise Invalid(f'{name} geçerli JSON değil')
    if not isinstance(v, dict):
        raise Invalid(f'{name} bir JSON nesnesi olmalı')
    s = json.dumps(v, ensure_ascii=False, separators=(',', ':'))
    if len(s.encode()) > mx:
        raise Invalid(f'{name} {mx // 1024} KB sınırını aşıyor')
    return s


def _flag(v, name):
    if isinstance(v, bool) or v in (0, 1):
        return int(v)
    raise Invalid(f'{name} true/false olmalı')


def _num(v, name, lo, hi, cast=float):
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        raise Invalid(f'{name} sayı olmalı')
    try:
        x = cast(v) if cast is float else int(float(v))
    except (TypeError, ValueError):
        raise Invalid(f'{name} sayı olmalı')
    if cast is int and float(v) != x:
        raise Invalid(f'{name} tam sayı olmalı')
    if not lo <= x <= hi:
        raise Invalid(f'{name} {lo}–{hi} aralığında olmalı')
    return x


def clean_source(b, partial):
    """Gövde → sütun sözlüğü. partial=False (oluşturma): slug, category, kind, name zorunlu. api_key: yok/None = dokunma, '' = sil."""
    if not isinstance(b, dict):
        raise Invalid('Gövde bir JSON nesnesi olmalı')
    out = {}
    if 'slug' in b or not partial:
        s = b.get('slug')
        if not isinstance(s, str) or not SLUG_RE.match(s):
            raise Invalid('slug [a-z0-9-] 2–40 karakter olmalı')
        out['slug'] = s
    if 'category' in b or not partial:
        if b.get('category') not in CATEGORIES:
            raise Invalid('category geçersiz')
        out['category'] = b['category']
    if 'kind' in b or not partial:
        if b.get('kind') not in KINDS:
            raise Invalid('kind geçersiz')
        out['kind'] = b['kind']
    if 'name' in b or not partial:
        out['name'] = _text(b.get('name'), 'name', required=True)
    for f in TEXT_FIELDS:
        if f in b:
            out[f] = _text(b[f], f)
    if 'endpoint' in b:
        out['endpoint'] = _endpoint(b['endpoint'])
    if 'attribution_url' in b:
        out['attribution_url'] = _url(b['attribution_url'], 'attribution_url')
    if 'adapter' in b:
        a = b['adapter']
        if a in (None, ''):
            out['adapter'] = None
        elif isinstance(a, str) and ADAPTER_RE.match(a):
            out['adapter'] = a
        else:
            raise Invalid('adapter [a-z0-9_] 2–40 karakter olmalı')
    if 'params' in b:
        out['params'] = _json_obj(b['params'], 'params', PARAMS_MAX)
    if b.get('api_key') is not None:
        k = b['api_key']
        if not isinstance(k, str) or len(k) > KEY_MAX or any(ord(c) < 32 for c in k):
            raise Invalid('api_key geçersiz')
        out['api_key'] = k.strip() or None
    for f in ('key_required', 'noncommercial', 'attribution_required', 'enabled', 'default_on'):
        if f in b:
            out[f] = _flag(b[f], f)
    if 'rate_per_min' in b:
        out['rate_per_min'] = _num(b['rate_per_min'], 'rate_per_min', 0.1, 600)
    if 'ttl_s' in b:
        out['ttl_s'] = _num(b['ttl_s'], 'ttl_s', 5, 86400, int)
    if 'sort' in b:
        out['sort'] = _num(b['sort'], 'sort', -100000, 100000, int)
        if out['sort'] is None:
            out['sort'] = 100
    return out


def clean_point(b, partial):
    if not isinstance(b, dict):
        raise Invalid('Gövde bir JSON nesnesi olmalı')
    out = {}
    if 'name' in b or not partial:
        out['name'] = _text(b.get('name'), 'name', required=True)
    for f, lo, hi in (('lat', -90, 90), ('lon', -180, 180)):
        if f in b or not partial:
            v = _num(b.get(f), f, lo, hi)
            if v is None:
                raise Invalid(f'{f} gerekli')
            out[f] = v
    if 'media_type' in b:
        mt = b['media_type'] or None
        if mt is not None and mt not in MEDIA_TYPES:
            raise Invalid('media_type image | mjpeg | audio | link olmalı')
        out['media_type'] = mt
    if 'media_url' in b:
        out['media_url'] = _url(b['media_url'], 'media_url', https_only=True)
    if 'props' in b:
        out['props'] = _json_obj(b['props'], 'props', PROPS_MAX)
    if 'enabled' in b:
        out['enabled'] = _flag(b['enabled'], 'enabled')
    return out


def is_live(r, has_key):
    """Haritada çizilir mi (§3): enabled VE adapter dolu VE (anahtar gerekmez YA DA anahtar var)."""
    return bool(r['enabled'] and r['adapter'] and (not r['key_required'] or has_key))


# ---------------- CLI ----------------
def backup(conn):
    """data/sshm-pre-mw-<ts>.db (sqlite çevrimiçi yedek; WAL dahil tutarlı kopya)."""
    dst = settings.DATA_DIR / f"sshm-pre-mw-{time.strftime('%Y%m%d-%H%M%S')}.db"
    with sqlite3.connect(dst) as out:
        conn.backup(out)
    try:
        dst.chmod(0o600)
    except OSError:
        pass
    return dst


def main(argv):
    if len(argv) != 1:
        print('Kullanım: python -m sshm.mw_catalog <dosya.xlsx>', file=sys.stderr)
        return 2
    with open(argv[0], 'rb') as f:
        data = f.read()
    db.init()
    with db.connect() as conn:
        dst = backup(conn)
        print(f'Yedek: {dst}', file=sys.stderr)
        try:
            res = import_xlsx(conn, data)
        except XlsxError as e:
            print(f'Hata: {e}', file=sys.stderr)
            return 1
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
