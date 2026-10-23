#!/usr/bin/env python3
"""Bayram temaları verisini DERLER (çalışma zamanında bağımlılık yok) — docs/bayram-temalari.md.

Çıktılar (depoya girer):
  static/data/holidays/<yıl>.json      ülke → bayram listesi (tema kodu, İngilizce ad, 7 dil + ülkenin kendi dilinde ad, yarım gün / tahmini / ertelenmiş bayrakları)
  static/data/holidays/borders.json    konum → ülke için Natural Earth 1:50m ülke sınırları (kamu malı), 0,05° nicemlenmiş (yalnız sunucu okur)
  static/js/modules/holiday_tz.js      saat dilimi → ülke tablosu (IANA zone.tab + tzdata.zi bağları; istemci ülke tespiti)

Bağımlılıklar YALNIZ bu betik için, AYRI venv'de (HEPGO/SIMUMAV requirements'a girmez):
    python3 -m venv /tmp/bayram/venv && /tmp/bayram/venv/bin/pip install holidays
    /tmp/bayram/venv/bin/python -I tools/holiday_themes_build.py --root . --borders <ne_50m_admin_0_countries.geojson> [--years 2026-2030]
--borders verilmezse borders.json DOKUNULMAZ (sınırlar yıllık yenilemede değişmez). Tema eşlemesi app/holiday_themes.py (tek kaynak).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

UI_LANGS = ('tr', 'en', 'de', 'fr', 'es', 'ru', 'ar')
DISLA_KATEGORI = {'workday'}        # Çin/Vietnam vb. telafi iş günleri bayram değildir


def tema_modulu(root: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('holiday_themes', root / 'app' / 'holiday_themes.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def dil_esle(desteklenen, ui):
    """UI dili ('en') → ülkenin desteklediği yerel ayar ('en_US' / 'en_GB' / 'en')."""
    for s in desteklenen:
        if s == ui:
            return s
    for s in desteklenen:
        if s.split('_')[0] == ui:
            return s
    return None


def ulke_yili(holidays, kod: str, yil: int, HT) -> tuple[list[dict], str]:
    cls = holidays.country_holidays(kod)
    diller = tuple(getattr(cls, 'supported_languages', ()) or ())
    kats = [c for c in (getattr(cls, 'supported_categories', None) or ('public',)) if c not in DISLA_KATEGORI]
    en = dil_esle(diller, 'en')

    def ad_tablosu(dil):
        """{(tarih, sıra) → ad} — kategori kategori; ';' ile birleşik adlar ayrılır."""
        out = {}
        for c in kats:
            try:
                kw = {'years': yil, 'categories': (c,)}
                if dil:
                    kw['language'] = dil
                h = holidays.country_holidays(kod, **kw)
            except Exception:   # noqa: BLE001 — desteklenmeyen kategori/dil
                continue
            for d, n in h.items():
                for i, parca in enumerate(x.strip() for x in str(n).split(';')):
                    if parca:
                        out.setdefault((d, c, i), parca)
        return out

    taban = ad_tablosu(en)                  # İngilizce (tema eşlemesi buna göre)
    varsayilan = getattr(cls, 'default_language', None)
    yerel = {'_': ad_tablosu(varsayilan) if (varsayilan and varsayilan != en) else {}}   # dil açıkça verilir (yoksa kütüphane sistem LANG'ını kullanır)
    for ui in UI_LANGS:
        s = dil_esle(diller, ui)
        if s and s != en:
            yerel[ui] = ad_tablosu(s)
    satirlar, gor = [], set()
    for (d, c, i), ad in sorted(taban.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        temiz, bay = HT.clean_name(ad)
        anahtar = (d, temiz.lower())
        if anahtar in gor:                 # aynı gün aynı bayram iki kategoride (public + optional …) → tek kayıt
            continue
        gor.add(anahtar)
        r = {'d': d.isoformat(), 't': HT.theme_for(temiz), 'n': temiz, 'c': c, **bay}
        l = {}
        for dil, tablo in yerel.items():
            a = tablo.get((d, c, i))
            if a:
                a2 = HT.clean_name(a)[0]
                if a2 and a2 != temiz:
                    l[dil] = a2
        yer_dil = (varsayilan or '').split('_')[0]
        if '_' in l and l.get(yer_dil) == l['_']:
            l.pop(yer_dil)                 # UI dili = ülkenin dili → '_' yeter (holiday_themes._name local_lang ile çözer)
        if l:
            r['l'] = l
        satirlar.append(r)
    return satirlar, (varsayilan or '').split('_')[0]


def yil_uret(holidays, kodlar, yil, HT):
    ulkeler, yerel_dil = {}, {}
    for kod in kodlar:
        try:
            rs, dil = ulke_yili(holidays, kod, yil, HT)
        except Exception as e:   # noqa: BLE001
            print(f'  ! {kod} {yil}: {e}', file=sys.stderr)
            continue
        if rs:
            ulkeler[kod] = rs
            if dil:
                yerel_dil[kod] = dil
    return {'v': 1, 'year': yil, 'source': f'python-holidays {holidays.__version__}', 'generated': dt.date.today().isoformat(),
            'note': 'Hicri / ay takvimi tarihleri tahminidir (e:1); ülkeye göre ±1 gün kayabilir.', 'local_lang': yerel_dil, 'countries': ulkeler}


def rdp(pts: list, eps: float) -> list:
    """Ramer–Douglas–Peucker (yinelemeli; kapalı halka uçları korunur)."""
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    yigin = [(0, len(pts) - 1)]
    while yigin:
        a, b = yigin.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = (dx * dx + dy * dy) ** .5
        en, ei = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / n if n else ((x0 - x1) ** 2 + (y0 - y1) ** 2) ** .5
            if d > en:
                en, ei = d, i
        if en > eps:
            keep[ei] = True
            yigin += [(a, ei), (ei, b)]
    return [p for p, k in zip(pts, keep) if k]


def sinirlar(geojson: Path, q: float = 0.05) -> dict:
    """Natural Earth admin-0 → {kod: [[halka(düz int listesi)…]…]}; ISO_A2 -99 ise ISO_A2_EH; ikisi de yoksa atlanır."""
    d = json.loads(geojson.read_text(encoding='utf-8'))
    out = {}
    for f in d['features']:
        p = f['properties']
        kod = p.get('ISO_A2') if p.get('ISO_A2') not in (None, '-99') else p.get('ISO_A2_EH')
        if not kod or kod == '-99':
            continue
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in polys:
            halkalar = []
            for ring in poly:
                pts = []
                for x, y in ring:
                    t = (round(x / q), round(y / q))
                    if not pts or pts[-1] != t:
                        pts.append(t)
                ham = [(round(x / q), round(y / q)) for x, y in ring]
                xs, ys = [p[0] for p in ham], [p[1] for p in ham]
                if max(xs) - min(xs) + max(ys) - min(ys) > 30:   # küçük halkalar (≤ ~1,5°) sadeleştirilmez: ada ülkeler kaybolmasın
                    pts = rdp(pts, 1.0)
                if len(pts) < 4 and not halkalar:        # küçük ada ülke (Singapur, Malta …): dış halka sınır kutusu (+1 birim) olarak kalır
                    xs, ys = [p[0] for p in ham], [p[1] for p in ham]
                    pts = [(min(xs) - 1, min(ys) - 1), (max(xs) + 1, min(ys) - 1), (max(xs) + 1, max(ys) + 1), (min(xs) - 1, max(ys) + 1), (min(xs) - 1, min(ys) - 1)]
                if len(pts) >= 4:
                    halkalar.append([v for pt in pts for v in pt])
            if halkalar:
                out.setdefault(kod, []).append(halkalar)
    return {'v': 1, 'q': q, 'source': 'Natural Earth 1:50m Admin 0 – Countries (public domain)', 'countries': out}


def tz_tablosu(zdir: Path = Path('/usr/share/zoneinfo')) -> dict:
    tz = {}
    for line in (zdir / 'zone.tab').read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            p = line.split('\t')
            tz[p[2]] = p[0]
    zi = zdir / 'tzdata.zi'
    if zi.is_file():
        for line in zi.read_text(encoding='utf-8').splitlines():
            if line.startswith('L '):
                _, hedef, takma = line.split()[:3]
                if hedef in tz and takma not in tz:
                    tz[takma] = tz[hedef]
    return dict(sorted(tz.items()))


def tz_js(tz: dict) -> str:
    govde = ',\n'.join(f'  {json.dumps(k)}: {json.dumps(v)}' for k, v in tz.items())
    return ('// ÜRETİLDİ — tools/holiday_themes_build.py (IANA zone.tab + tzdata.zi bağları). Elle düzenlemeyin.\n'
            '// Saat dilimi → ISO 3166-1 alfa-2 ülke kodu: tarayıcının Intl saat diliminden ülke tahmini (IP sorgusu YOK).\n'
            f'export const TZ_COUNTRY = {{\n{govde},\n}};\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default='.', help='HEPGO depo kökü')
    ap.add_argument('--years', default='2026-2030')
    ap.add_argument('--borders', help='ne_50m_admin_0_countries.geojson (verilmezse borders.json değişmez)')
    ap.add_argument('--countries', help='virgüllü ülke listesi (deneme)')
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    HT = tema_modulu(root)
    import holidays
    out = root / 'static' / 'data' / 'holidays'
    out.mkdir(parents=True, exist_ok=True)
    y0, _, y1 = a.years.partition('-')
    yillar = range(int(y0), int(y1 or y0) + 1)
    kodlar = a.countries.split(',') if a.countries else sorted(k for k in holidays.list_supported_countries() if len(k) == 2 and k.isalpha() and k.isupper())
    for yil in yillar:
        d = yil_uret(holidays, kodlar, yil, HT)
        p = out / f'{yil}.json'
        p.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print(f'{p.relative_to(root)}: {len(d["countries"])} ülke, {sum(len(v) for v in d["countries"].values())} kayıt, {p.stat().st_size // 1024} KB')
    if a.borders:
        b = sinirlar(Path(a.borders))
        p = out / 'borders.json'
        p.write_text(json.dumps(b, separators=(',', ':')), encoding='utf-8')
        print(f'{p.relative_to(root)}: {len(b["countries"])} ülke, {p.stat().st_size // 1024} KB')
    tz = tz_tablosu()
    p = root / 'static' / 'js' / 'modules' / 'holiday_tz.js'
    p.write_text(tz_js(tz), encoding='utf-8')
    print(f'{p.relative_to(root)}: {len(tz)} saat dilimi, {p.stat().st_size // 1024} KB')


if __name__ == '__main__':
    main()
