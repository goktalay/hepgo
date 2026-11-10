"""Veri tabloları katmanı (static/js/datatable.js): sütun başlığından sıralama + filtre — gerçek tarayıcıda.
- tip algılama: TR sayı / para / birim, tarih, süre, metin (Türkçe harf sırası); boşlar her yönde sonda
- başlık tıklaması: artan → azalan → özgün sıra
- filtre: arama (Türkçe / aksan duyarsız), değer listesi, sayı aralığı, tarih aralığı; "n / N kayıt" şeridi; Excel'e yalnız görünenler
- ayrıntı satırı üst satırıyla taşınır / gizlenir; grup başlıklı tabloda sıralama grup içinde, boş grup başlığı gizlenir
- tablo yeniden çizilince (modülün yenilemesi) sıralama + filtre yeniden uygulanır
- kapsam dışı: satırında giriş kutusu olan, birleşik başlıklı, kendi sıralaması (th.sortable) olan, data-dt="off" tablolar
Çalıştırma: .venv/bin/python -m tests.test_datatable
"""
import functools
import http.server
import os
import threading
from pathlib import Path

os.environ.setdefault('LD_LIBRARY_PATH', '/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu')
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXE = os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')

PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><link rel="stylesheet" href="/static/css/app.css"></head><body>
<main id="view">
<div class="table-wrap"><table id="t1"><thead><tr><th>Ad</th><th class="num">Tutar</th><th>Tarih</th><th>Süre</th><th>Durum</th><th></th></tr></thead><tbody>
<tr><td>Çınar</td><td class="num">1.250,50 ₺</td><td>05.03.2026</td><td>1 sa 5 dk</td><td>Açık</td><td><button>Sil</button></td></tr>
<tr><td>ahmet</td><td class="num">99,90 ₺</td><td>17.11.2025 14:30</td><td>45 dk 00 sn</td><td>Kapalı</td><td><button>Sil</button></td></tr>
<tr><td>Zeynep</td><td class="num">—</td><td>—</td><td>—</td><td>Açık</td><td><button>Sil</button></td></tr>
<tr><td>İbrahim</td><td class="num">12.000 ₺</td><td>01.01.2026</td><td>2 g 0 sa 3 dk</td><td>Açık</td><td><button>Sil</button></td></tr>
<tr><td>Ömer</td><td class="num">7 ₺</td><td>28.02.2026 09:05</td><td>00 dk 30 sn</td><td>Beklemede</td><td><button>Sil</button></td></tr>
</tbody><tfoot><tr><td>Toplam</td><td class="num">13.357,40 ₺</td><td></td><td></td><td></td><td></td></tr></tfoot></table></div>

<table id="t2"><thead><tr><th>Kod</th><th>Kişi</th></tr></thead><tbody>
<tr><td>Z-2</td><td>3</td></tr><tr class="det"><td colspan="2">Z-2 ayrıntısı</td></tr>
<tr><td>A-10</td><td>1</td></tr><tr class="det"><td colspan="2">A-10 ayrıntısı</td></tr>
<tr><td>A-9</td><td>12</td></tr>
</tbody></table>

<table id="t3"><thead><tr><th>Ürün</th><th>Adet</th></tr></thead><tbody>
<tr class="grp"><td colspan="2">Grup B</td></tr><tr><td>vida</td><td>30</td></tr><tr><td>cıvata</td><td>4</td></tr>
<tr class="grp"><td colspan="2">Grup A</td></tr><tr><td>somun</td><td>100</td></tr><tr><td>pul</td><td>9</td></tr>
</tbody></table>

<table id="edit"><thead><tr><th>Kalem</th><th>Adet</th></tr></thead><tbody><tr><td>x</td><td><input type="number" value="1"></td></tr><tr><td>y</td><td><input type="number" value="2"></td></tr></tbody></table>
<table id="span"><thead><tr><th colspan="2">Birleşik</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>
<table id="own"><thead><tr><th class="sortable">Kendi</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>
<table id="off" data-dt="off"><thead><tr><th>Kapalı</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>
</main>
<script type="module">
import { enableDataTables, parse } from '/static/js/datatable.js';
window.__parse = parse;
enableDataTables();
window.__ready = true;
</script></body></html>"""

COL = "(id, c) => [...document.querySelectorAll(`#${id} > tbody > tr:not(.dt-hide)`)].filter(tr => tr.cells.length > 1).map(tr => tr.cells[c].textContent.trim())"
ROWS = "id => [...document.querySelectorAll(`#${id} > tbody > tr:not(.dt-hide)`)].map(tr => tr.cells[0].textContent.trim())"


def serve():
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Q, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    srv = serve()
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE, args=['--no-sandbox'])
        pg = b.new_page(viewport={'width': 1200, 'height': 800})
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.route('**/__dt.html', lambda r: r.fulfill(status=200, content_type='text/html; charset=utf-8', body=PAGE))
        pg.goto(f'{base}/__dt.html#/test')
        pg.wait_for_function('window.__ready')
        pg.wait_for_selector('#t1.dt-on')
        col = lambda i, c: pg.evaluate(f'({COL})("{i}", {c})')   # noqa: E731
        rows = lambda i: pg.evaluate(f'({ROWS})("{i}")')          # noqa: E731
        settle = lambda: pg.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')   # noqa: E731

        # --- ayrıştırıcı ---
        P = lambda s: pg.evaluate('s => window.__parse(s)', s)   # noqa: E731
        assert P('1.250,50 ₺') == ['num', 1250.5] and P('12.000') == ['num', 12000] and P('%45') == ['num', 45] and P('12,5 MB') == ['num', 12.5e6]
        assert P('-3,2') == ['num', -3.2] and P('12.5') == ['num', 12.5] and P('1.1.8') is None and P('A-10') is None and P('0532 111 22 33') is None
        assert P('1 sa 5 dk') == ['dur', 3900] and P('2 g 0 sa 3 dk') == ['dur', 172980] and P('14:30') == ['dur', 52200]
        assert P('05.03.2026')[0] == 'date' and P('2026-03-05T10:00:00')[0] == 'date' and P('5 Kasım 2026')[0] == 'date'
        assert P('17.11.2025 14:30')[1] < P('01.01.2026')[1]

        # --- kapsam ---
        on = pg.evaluate("[...document.querySelectorAll('table')].filter(t => t.classList.contains('dt-on')).map(t => t.id)")
        assert on == ['t1', 't2', 't3'], on
        assert pg.evaluate("document.querySelectorAll('#t1 th.dt-th').length") == 5      # başlıksız (eylem) sütununda yok
        assert pg.evaluate("[...document.querySelectorAll('#t1 th')].map(th => th.textContent.trim()).join('|')") == 'Ad|Tutar|Tarih|Süre|Durum|'   # Excel başlıkları bozulmaz

        # --- sıralama: metin (Türkçe), artan → azalan → özgün ---
        orig = col('t1', 0)
        pg.click('#t1 th:nth-child(1)')
        assert col('t1', 0) == ['ahmet', 'Çınar', 'İbrahim', 'Ömer', 'Zeynep'], col('t1', 0)
        assert pg.get_attribute('#t1 th:nth-child(1)', 'aria-sort') == 'ascending'
        pg.click('#t1 th:nth-child(1)')
        assert col('t1', 0) == ['Zeynep', 'Ömer', 'İbrahim', 'Çınar', 'ahmet']
        pg.click('#t1 th:nth-child(1)')
        assert col('t1', 0) == orig and pg.get_attribute('#t1 th:nth-child(1)', 'aria-sort') is None
        # sayı: boş (—) her iki yönde sonda
        pg.click('#t1 th:nth-child(2)')
        assert col('t1', 0) == ['Ömer', 'ahmet', 'Çınar', 'İbrahim', 'Zeynep'], col('t1', 0)
        pg.click('#t1 th:nth-child(2)')
        assert col('t1', 0) == ['İbrahim', 'Çınar', 'ahmet', 'Ömer', 'Zeynep'], col('t1', 0)
        # tarih ve süre
        pg.click('#t1 th:nth-child(3)')
        assert col('t1', 0) == ['ahmet', 'İbrahim', 'Ömer', 'Çınar', 'Zeynep'], col('t1', 0)
        pg.click('#t1 th:nth-child(4)')
        assert col('t1', 0) == ['Ömer', 'ahmet', 'Çınar', 'İbrahim', 'Zeynep'], col('t1', 0)
        assert pg.evaluate("document.querySelectorAll('#t1 th[aria-sort]').length") == 1
        pg.click('#t1 th:nth-child(4)')
        pg.click('#t1 th:nth-child(4)')
        assert col('t1', 0) == orig

        # --- filtre: değer listesi ---
        pg.hover('#t1 th:nth-child(5)')
        pg.click('#t1 th:nth-child(5) .dt-f')
        pg.wait_for_selector('.dt-pop')
        items = pg.evaluate("[...document.querySelectorAll('.dt-pop-list .dt-pop-i')].map(l => l.textContent)")
        assert items == ['Açık3', 'Beklemede1', 'Kapalı1'], items
        pg.click(".dt-pop-list .dt-pop-i:has-text('Açık') input")
        assert col('t1', 0) == ['ahmet', 'Ömer'], col('t1', 0)
        assert 'gösteriliyor' in pg.inner_text('#t1 caption.dt-cap') and '2 / 5' in pg.inner_text('#t1 caption.dt-cap')
        assert pg.evaluate("document.querySelector('#t1 tfoot').classList.contains('dt-stale')")
        assert pg.evaluate("document.querySelector('#t1 th:nth-child(5) .dt-f').classList.contains('on')")
        assert col('t1', 0) == ['ahmet', 'Ömer'] and orig == pg.evaluate("[...document.querySelectorAll('#t1 > tbody > tr')].map(tr => tr.cells[0].textContent)")   # sıra bozulmadı
        pg.keyboard.press('Escape')
        assert pg.query_selector('.dt-pop') is None
        # ikinci sütunda arama (Türkçe duyarsız): "OMER" → Ömer; diğer filtreyle birlikte (VE)
        pg.click('#t1 th:nth-child(1) .dt-f')
        assert pg.evaluate("[...document.querySelectorAll('.dt-pop-list .dt-pop-v')].map(l => l.textContent)") == ['ahmet', 'Ömer']   # diğer filtreden geçenler
        pg.fill('.dt-pop-q', 'OMER')
        assert col('t1', 0) == ['Ömer']
        pg.click('.dt-pop-clr')
        assert col('t1', 0) == ['ahmet', 'Ömer']
        pg.click('.dt-pop-ok')
        # şeritten tümünü temizle
        pg.click('#t1 caption.dt-cap button')
        assert col('t1', 0) == orig and pg.query_selector('#t1 caption.dt-cap') is None
        assert not pg.evaluate("document.querySelector('#t1 tfoot').classList.contains('dt-stale')")
        # sayı aralığı (TR biçimli giriş) ve tarih aralığı
        pg.click('#t1 th:nth-child(2) .dt-f')
        pg.fill('.dt-pop-range label:nth-child(1) input', '50')
        pg.fill('.dt-pop-range label:nth-child(2) input', '1.500,00')
        assert col('t1', 0) == ['Çınar', 'ahmet'], col('t1', 0)
        pg.click('.dt-pop-clr')
        pg.click('.dt-pop-ok')
        pg.click('#t1 th:nth-child(3) .dt-f')
        pg.fill('.dt-pop-range label:nth-child(1) input', '2026-01-01')
        pg.fill('.dt-pop-range label:nth-child(2) input', '2026-02-28')
        assert col('t1', 0) == ['İbrahim', 'Ömer'], col('t1', 0)
        # "Tümünü seç" kapat → hiçbiri; tek değer işaretle
        pg.click('.dt-pop-clr')
        pg.click('.dt-pop-all input')
        assert col('t1', 0) == []
        pg.click(".dt-pop-list .dt-pop-i:has-text('01.01.2026') input")
        assert col('t1', 0) == ['İbrahim']

        # --- yeniden çizim: modül tabloyu baştan kurar → sıralama + filtre korunur ---
        pg.click('.dt-pop-sort button:nth-child(2)')   # Tarih azalan (pencereden)
        pg.click('.dt-pop-clr')
        pg.click('.dt-pop-ok')
        assert col('t1', 0) == ['Çınar', 'Ömer', 'İbrahim', 'ahmet', 'Zeynep'], col('t1', 0)
        pg.click('#t1 th:nth-child(5) .dt-f')
        pg.click(".dt-pop-list .dt-pop-i:has-text('Kapalı') input")
        pg.click('.dt-pop-ok')
        assert col('t1', 0) == ['Çınar', 'Ömer', 'İbrahim', 'Zeynep']
        pg.evaluate("""() => { const w = document.querySelector('#t1').parentNode, html = w.innerHTML.replace(/ class="dt-[^"]*"/g, ''); w.innerHTML = '';
            const d = document.createElement('div'); d.innerHTML = html; const t = d.querySelector('table');
            t.className = ''; t.querySelectorAll('.dt-s, .dt-f, caption').forEach(x => x.remove()); t.querySelectorAll('[aria-sort]').forEach(x => x.removeAttribute('aria-sort'));
            const tb = t.tBodies[0]; [...tb.rows].sort((a, b) => a.cells[0].textContent.localeCompare(b.cells[0].textContent, 'tr')).forEach(r => { r.className = ''; tb.append(r); });
            const n = tb.rows[0].cloneNode(true); n.cells[0].textContent = 'Yeni'; n.cells[2].textContent = '09.09.2026'; n.cells[4].textContent = 'Açık'; tb.append(n);
            w.append(t); }""")
        settle()
        assert col('t1', 0) == ['Yeni', 'Çınar', 'Ömer', 'İbrahim', 'Zeynep'], col('t1', 0)
        assert '5 / 6' in pg.inner_text('#t1 caption.dt-cap')
        # canlı güncelleme: hücre değişince sıra yeniden kurulur
        pg.evaluate("[...document.querySelectorAll('#t1 > tbody > tr')].find(tr => tr.cells[0].textContent === 'Zeynep').cells[2].textContent = '31.12.2026'")
        settle()
        assert col('t1', 0)[0] == 'Zeynep', col('t1', 0)

        # --- ayrıntı satırı üst satırıyla birlikte ---
        pg.click('#t2 th:nth-child(1)')   # doğal sıra: A-9 < A-10 < Z-2
        assert rows('t2') == ['A-9', 'A-10', 'A-10 ayrıntısı', 'Z-2', 'Z-2 ayrıntısı'], rows('t2')
        pg.click('#t2 th:nth-child(2) .dt-f')
        pg.fill('.dt-pop-range label:nth-child(1) input', '2')
        assert rows('t2') == ['A-9', 'Z-2', 'Z-2 ayrıntısı'], rows('t2')
        pg.click('.dt-pop-clr')
        pg.keyboard.press('Escape')

        # --- grup başlıklı tablo: sıralama grup içinde; satırı kalmayan grup başlığı gizlenir ---
        pg.click('#t3 th:nth-child(2)')
        assert rows('t3') == ['Grup B', 'cıvata', 'vida', 'Grup A', 'pul', 'somun'], rows('t3')
        pg.click('#t3 th:nth-child(1) .dt-f')
        pg.fill('.dt-pop-q', 'civ')
        assert rows('t3') == ['Grup B', 'cıvata'], rows('t3')
        pg.keyboard.press('Escape')

        # --- modül değişince filtreler bırakılır, sıralama tercihi kalır ---
        pg.evaluate("location.hash = '#/baska'")
        settle()
        pg.evaluate("location.hash = '#/test'")
        settle()
        assert rows('t3') == ['Grup B', 'cıvata', 'vida', 'Grup A', 'pul', 'somun'], rows('t3')
        assert errors == [], errors
        b.close()
    srv.shutdown()
    print('Veri tablosu (sıralama + filtre) testleri geçti.')


if __name__ == '__main__':
    main()
