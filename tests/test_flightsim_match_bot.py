"""Uçuş Simülatörü §44 — KARŞILAŞMADA YAPAY ZEKÂ PİLOT: saf çekirdek testleri (DB/ağ yok).

Kapsam: seviye tablosu (tek tablo, alanlar, Kolay < Normal < Zor tekdüzeliği), bot adları/renkleri, halka hedef seçimi (yaklaşma noktası →
düz geçiş, arkadan gelince yandan dolaşma, ıskalama sonrası yeni deneme), kovala/kaç kararları (öngörü karışımı, tepki gecikmesi, uzaklaşma
yönü, alan sınırı, güvenli irtifa), Karsilasma'da bot oyuncular (ekle/çıkar, it dalaşında tek rakip, yalnız botlar kalınca bitiş) ve SAHTE
KİNEMATİKLE (flightsim.SahteKinematik — oturumların kullandığı aynı model) uçtan uca: bot halka yarışını bitirir, ortalama süre Zor < Normal <
Kolay (kopter + sabit kanat); kovalayan bot yavaş hedefi angaje eder; kaçan bot yere çarpmaz, alanı terk etmez.

Çalıştırma: .venv/bin/python -m tests.test_flightsim_match_bot
"""
import math
import os
import tempfile

os.environ.setdefault('CAYMAZ_DATA_DIR', tempfile.mkdtemp())
os.environ.setdefault('HEPGO_SITL', '0')

from app import flightsim  # noqa: E402
from app import flightsim_match_bot as mbot  # noqa: E402
from app import flightsim_match_core as core  # noqa: E402

M = {'lat': 39.9, 'lon': 32.8, 'alt': 900.0}


def seviye_testleri():
    S = core.BOT_SEVIYE
    assert core.BOT_SEVIYELER == ('easy', 'normal', 'hard') and set(S) == set(core.BOT_SEVIYELER)
    alanlar = set(S['easy'])
    assert all(set(v) == alanlar for v in S.values()), 'her seviyede aynı alanlar'
    assert (S['easy']['hiz'], S['normal']['hiz'], S['hard']['hiz']) == (0.55, 0.75, 0.95)
    assert S['easy']['gecikme_s'] == 1.5 and S['easy']['gecikme_s'] > S['normal']['gecikme_s'] > S['hard']['gecikme_s']
    assert S['easy']['donus_dps'] < S['normal']['donus_dps'] < S['hard']['donus_dps']
    assert S['easy']['sapma'] > S['normal']['sapma'] > S['hard']['sapma'] and S['hard']['iska'] == 0 < S['normal']['iska'] < S['easy']['iska']
    assert S['hard']['on_donus'] and not S['normal']['on_donus'] and not S['easy']['on_donus']
    assert S['easy']['tahmin_hata_m'] > S['normal']['tahmin_hata_m'] > S['hard']['tahmin_hata_m']
    assert S['easy']['rastgele'] == 0 < S['normal']['rastgele'] < S['hard']['rastgele']
    try:
        core.bot_seviye('uzman')
        raise AssertionError('geçersiz seviye kabul edildi')
    except core.MacHata as e:
        assert e.kod == 'invalid'
    assert core.bot_adi('hard', 0) == 'AI-Şahin (Zor)' and core.bot_adi('easy', 1, etiket=False) == 'AI-Kartal'
    p = mbot.BotPilot('easy', 'ucak')
    assert p.vmax == core.BOT_UCAK_VMIN + 1.5 and mbot.BotPilot('hard', 'dikey').vmax == 16.0 * 0.95   # uçakta alt sınır
    print('  seviye tablosu geçti')


def _halka(x, y, nx, ny, agl=20.0, r=6.0):
    return {'i': 1, 'x': x, 'y': y, 'nx': nx, 'ny': ny, 'agl_m': agl, 'alt_msl': 900 + agl, 'radius_m': r}


def halka_hedef_testleri():
    p = mbot.BotPilot('hard', 'dikey', tohum=3)
    H = [_halka(0, 100, 0, 1), _halka(60, 160, 1, 0)]
    # önde, eksen üstünde → düz geçiş (hedef halkanın ardında)
    h, mod = p.halka_hedefi({'x': 0, 'y': 40, 'z': 20}, H, 0)
    assert mod == 'gec' and h[1] > 100 and abs(h[0]) < 3, (h, mod)
    # önde ama çok yandan → önce yaklaşma noktası (halkanın önünde)
    h, mod = p.halka_hedefi({'x': 90, 'y': 95, 'z': 20}, H, 0)
    assert mod == 'yaklas' and h[1] < 100 - 15, (h, mod)
    # halkanın arkasında → yandan dolaşarak yaklaşma noktasına (içinden ters geçmez)
    h, mod = p.halka_hedefi({'x': 1, 'y': 130, 'z': 20}, H, 0)
    assert mod == 'yaklas' and abs(h[0]) > 6 * 2.5, (h, mod)
    # Zor: halkaya çok yakınken bir sonrakinin yaklaşma noktasına önceden döner
    h, mod = p.halka_hedefi({'x': 0, 'y': 97, 'z': 20}, H, 0, v=15)
    assert mod == 'gec' and h[0] < 60 and abs(h[1] - 160) < 1, h
    n = mbot.BotPilot('normal', 'dikey', tohum=3)
    h, mod = n.halka_hedefi({'x': 0, 'y': 97, 'z': 20}, H, 0, v=15)
    assert mod == 'gec' and h[1] > 100, h   # Normal önceden dönmez
    # kaçıklık: Kolay > Zor (ortalama), ıskalama yalnız ilk denemede
    def ort(sev):
        q = mbot.BotPilot(sev, 'dikey', tohum=11)
        return sum(math.hypot(*q._halka_kacik(i, 6.0)) for i in range(200)) / 200
    assert ort('easy') > ort('normal') > ort('hard'), (ort('easy'), ort('normal'), ort('hard'))
    e = mbot.BotPilot('easy', 'dikey', tohum=11)
    iska = [i for i in range(300) if math.hypot(*e._halka_kacik(i, 6.0)) > 6.0]
    assert 15 < len(iska) < 80, len(iska)
    for i in iska[:5]:
        e.deneme[i] = 1
        assert math.hypot(*e._halka_kacik(i, 6.0)) < 6.0   # ikinci denemede ıskalama yok
    # tepki gecikmesi: sıra değişince eski komut gecikme süresince sürer
    k = mbot.BotPilot('easy', 'dikey', tohum=1)
    c1 = k.halka_adim(0.0, {'x': 0, 'y': 40, 'z': 20, 'heading': 0}, H, 0)
    c2 = k.halka_adim(0.2, {'x': 0, 'y': 105, 'z': 20, 'heading': 0}, H, 1)
    assert c2 is c1 or c2 == c1
    c3 = k.halka_adim(1.8, {'x': 0, 'y': 110, 'z': 20, 'heading': 0}, H, 1)
    assert c3['hedef'] != c1['hedef']
    print('  halka hedef seçimi geçti')


def it_karar_testleri():
    a = core.it_ayar_dogrula({'distance_m': 400, 'alt_m': 40, 'area_radius_m': 800, 'range_m': 120}, 'multirotor')
    ben = {'x': 0, 'y': 0, 'z': 40, 'heading': 0, 'gs': 10}
    rakip = {'x': 0, 'y': 200, 'z': 40, 'vx': 10, 'vy': 0}
    hz, _ = mbot.BotPilot('hard', 'dikey').kovala_hedefi(ben, rakip, a, 15)
    he, _ = mbot.BotPilot('easy', 'dikey').kovala_hedefi(ben, rakip, a, 15)
    assert hz[0] > he[0] > 0 and hz[1] == 200, (hz, he)   # Zor rakibin ilerisine daha çok öngörür
    # kovalayan komut yönü rakibe doğru (gecikme + hata içinde)
    p = mbot.BotPilot('hard', 'dikey', tohum=2)
    for t in range(10):
        c = p.it_adim(t * 0.2, ben, {'x': 300, 'y': 0, 'z': 40, 'vx': 0, 'vy': 0}, core.KOVALAYAN, a)
    assert c['vx'] > 10 and abs(c['vy']) < 4, c
    # tepki gecikmesi: rakip ani yer değiştirince Kolay eski konumu daha uzun görür
    for sev, beklenen in (('easy', 'eski'), ('hard', 'yeni')):
        q = mbot.BotPilot(sev, 'dikey', tohum=2)
        for t in range(10):
            q.it_adim(t * 0.2, ben, {'x': 300, 'y': 0, 'z': 40}, core.KOVALAYAN, a)
        q._rakip_gor(2.0, {'x': -300, 'y': 0, 'z': 40})   # rakip 2,0 sn'de ışınlandı; 2,4 sn'de Zor yeni, Kolay eski konumu görür
        g = q._rakip_gor(2.4, {'x': -300, 'y': 0, 'z': 40})
        assert (g['x'] > 0) == (beklenen == 'eski'), (sev, g)
    # kaçan rakipten uzaklaşır (yakında Zor neredeyse dümdüz)
    k = mbot.BotPilot('hard', 'dikey', tohum=4)
    yon, _ = k.kacis_yonu(0.0, {'x': 0, 'y': 0, 'z': 40}, {'x': 0, 'y': -80, 'z': 40}, a)
    assert math.cos(yon) > 0.8, math.degrees(yon)
    # Kolay öngörülebilir: manevra yönü sırayla değişir
    e = mbot.BotPilot('easy', 'dikey', tohum=4)
    isaretler = []
    for i in range(4):
        e.kacis_yonu(i * 7.01, {'x': 0, 'y': 0, 'z': 40}, {'x': 0, 'y': -600, 'z': 40}, a)
        isaretler.append(e.manevra['isaret'])
    assert isaretler == [1.0, -1.0, 1.0, -1.0], isaretler
    # alan sınırı + güvenli irtifa
    g = k._guvenli({'x': 790, 'y': 0, 'z': 40}, (1200, 0, 2), a)
    assert math.hypot(g[0], g[1]) <= 0.72 * 800 + 1 and g[2] >= mbot.ZEMIN_MIN['dikey'], g
    print('  kovala / kaç kararları geçti')


def karsilasma_bot_testleri():
    t0 = 1000.0
    k = core.Karsilasma(1, (10, 'Kurucu'), [], {}, core.halka_ayar_dogrula({'count': 3, 'seed': 2}, 'multirotor'), M, t0,
                        halkalar=[], botlar=[(-1, 'AI-Şahin (Zor)', 'hard', '#ef4444')])
    b = k.oyuncu(-1)
    assert b.durum == core.GELDI and b.dict()['is_bot'] and b.dict()['level'] == 'hard' and b.dict()['color'] == '#ef4444'
    assert not k.oyuncu(10).dict()['is_bot']
    ev = k.lobi_denetle(t0)
    assert k.durum == core.HAZIRLIK and any(e['t'] == 'state' for e in ev)
    k.hazir(10, t0 + 1)
    k.hazir(-1, t0 + 1)
    assert k.durum == core.GERI_SAYIM
    k.tik(k.baslangic_t + 0.1)
    assert k.durum == core.YARIS
    ev = k.ayril(10, k.baslangic_t + 5)   # insan ayrıldı → yalnız bot kaldı → biter
    assert k.durum == core.BITTI and k.neden == 'oyuncu_kalmadi', (k.durum, k.neden)
    # LOBI: bot ekle/çıkar, sınırlar
    k2 = core.Karsilasma(2, (10, 'Kurucu'), [(11, 'Ayşe')], {}, core.halka_ayar_dogrula({}, 'multirotor'), M, t0)
    for kod, fn in (('forbidden', lambda: k2.bot_ekle(11, 'easy', t0)), ('invalid', lambda: k2.bot_ekle(10, 'x', t0))):
        try:
            fn()
            raise AssertionError(kod)
        except core.MacHata as e:
            assert e.kod == kod
    ev, uid = k2.bot_ekle(10, 'normal', t0)
    assert uid == -1 and k2.oyuncu(uid).ad == 'AI-Şahin (Normal)' and k2.durum == core.LOBI
    _, uid2 = k2.bot_ekle(10, 'easy', t0)
    assert uid2 == -2 and k2.oyuncu(uid2).ad == 'AI-Kartal (Kolay)'
    k2.cikar(10, uid, t0)
    assert k2.oyuncu(uid) is None and len(k2.oyuncular) == 3
    k2.katil(11, t0 + 2)
    assert k2.durum == core.HAZIRLIK and {o.uid for o in k2.aktifler()} == {10, 11, -2}
    # it dalaşı: tek rakip
    a = core.it_ayar_dogrula({'seed': 3, 'roles': 'host_evader'}, 'multirotor')
    k3 = core.Karsilasma(3, (10, 'Kurucu'), [], {}, a, M, t0, botlar=[(-1, 'AI-Doğan (Zor)', 'hard')], tur=core.TUR_IT)
    try:
        k3.bot_ekle(10, 'easy', t0)
        raise AssertionError('ikinci rakip')
    except core.MacHata as e:
        assert e.kod == 'conflict'
    k3.lobi_denetle(t0)
    assert k3.oyuncu(-1).rol == core.KOVALAYAN and k3.oyuncu(10).rol == core.KACAN
    k3.hazir(10, t0)
    k3.hazir(-1, t0)
    k3.tik(k3.baslangic_t + 0.1)
    k3.ayril(10, k3.baslangic_t + 3)   # insan kaçtı → bot kazanır (rakip ayrıldı)
    assert k3.durum == core.BITTI and k3.kazanan == -1 and k3.neden == 'rakip_ayrildi'
    try:
        core.Karsilasma(4, (10, 'K'), [], {}, a, M, t0, botlar=[(5, 'x', 'easy')])
        raise AssertionError('pozitif bot kimliği')
    except core.MacHata:
        pass
    print('  karşılaşmada bot oyuncu geçti')


def _yaris(sev, tip, seed, n=5):
    vc = core.sinif(tip)
    cfg = core.halka_ayar_dogrula({'count': n, 'seed': seed}, tip)
    H = core.halkalar_uret(cfg, M)
    k = flightsim.SahteKinematik(tip, M['lat'], M['lon'], M['alt'], 0, heading=0)
    iz = core.HalkaIzleyici(H)
    p = mbot.BotPilot(sev, vc, tohum=seed)
    alt = max(10.0, H[0]['agl_m']) if vc == 'dikey' else 40.0
    k.komut('takeoff', {'alt': alt})
    t, dt, ucus = 0.0, 0.02, False
    while t < 900:
        k.adim(dt)
        t += dt
        x, y = core.enu(M['lat'], M['lon'], k.lat, k.lon)
        iz.konum(x, y, M['alt'] + k.alt_rel, t)
        if iz.bitti:
            return t
        if not ucus and (k.alt_rel >= alt * 0.7 if vc == 'dikey' else (k.kalkis is None and k.alt_rel > 25)):
            ucus = True
        if ucus and round(t / dt) % 10 == 0:
            te = k.tele()
            c = p.halka_adim(t, {'x': x, 'y': y, 'z': k.alt_rel, 'heading': te['heading'], 'gs': te['groundspeed']}, H, iz.sira)
            if k.mode != 'GUIDED':
                k.komut('mode', {'mode': 'GUIDED'})
            k.bot_hiz(c['vx'], c['vy'], c['vz'])
    return None


def sahte_yaris_testleri():
    for tip, tohumlar in (('multirotor', (11, 5, 77)), ('sabit_kanat', (11, 5, 3))):
        ort = {}
        for sev in core.BOT_SEVIYELER:
            sureler = [_yaris(sev, tip, s) for s in tohumlar]
            assert all(x is not None for x in sureler), (tip, sev, sureler)
            ort[sev] = sum(sureler) / len(sureler)
        assert ort['hard'] < ort['normal'] < ort['easy'], (tip, ort)
        print(f'  sahte kinematik yarış {tip}: ' + ' · '.join(f'{core.BOT_SEVIYE_AD[k]} {v:.0f} sn' for k, v in ort.items()))


def _dalas(sev, botrol, hiz):
    tip = 'multirotor'
    a = core.it_ayar_dogrula({'seed': 3, 'alt_m': 40}, tip)
    B = core.it_baslangiclari(a, tip)
    ks = {}
    for rol in (core.KOVALAYAN, core.KACAN):
        lat, lon = core.latlon(M['lat'], M['lon'], B[rol][0], B[rol][1])
        ks[rol] = flightsim.SahteKinematik(tip, lat, lon, M['alt'], 0)
        ks[rol].komut('takeoff', {'alt': a['alt_m']})
    it = core.ItDalasi(a, 0.0)
    p = mbot.BotPilot(sev, 'dikey', tohum=3)
    insan = core.KACAN if botrol == core.KOVALAYAN else core.KOVALAYAN
    t, dt, minz, maxr = 0.0, 0.02, 1e9, 0.0

    def poz(rol):
        k = ks[rol]
        x, y = core.enu(M['lat'], M['lon'], k.lat, k.lon)
        return x, y, k.alt_rel
    while t < 150:
        for k in ks.values():
            k.adim(dt)
        t += dt
        if round(t / dt) % 10:
            continue
        for rol in ks:
            x, y, z = poz(rol)
            for e in it.konum(rol, x, y, z, math.degrees(ks[rol].yaw) % 360, ks[rol].pitch, t):
                if e['kind'] in ('engage', 'area'):
                    return t, e['kind'], minz, maxr
        bx, by, bz = poz(botrol)
        rx, ry, rz = poz(insan)
        kb, ki = ks[botrol], ks[insan]
        if kb.alt_rel > a['alt_m'] * 0.7:
            minz, maxr = min(minz, bz), max(maxr, math.hypot(bx, by))
            c = p.it_adim(t, {'x': bx, 'y': by, 'z': bz, 'heading': math.degrees(kb.yaw) % 360, 'gs': math.hypot(kb.vn, kb.ve)},
                          {'x': rx, 'y': ry, 'z': rz, 'vx': ki.ve, 'vy': ki.vn}, botrol, a)
            kb.komut('mode', {'mode': 'GUIDED'})
            kb.bot_hiz(c['vx'], c['vy'], c['vz'])
        if ki.alt_rel > a['alt_m'] * 0.7:   # "insan": kaçan geniş daire / kovalayan doğrudan takip
            if insan == core.KACAN:
                vx, vy = hiz * math.cos(0.08 * t), hiz * math.sin(0.08 * t)
            else:
                L = math.hypot(bx - rx, by - ry) or 1.0
                vx, vy = (bx - rx) / L * hiz, (by - ry) / L * hiz
            ki.komut('mode', {'mode': 'GUIDED'})
            ki.bot_hiz(vx, vy, (a['alt_m'] - ki.alt_rel) * 0.5)
    return None, None, minz, maxr


def sahte_dalas_testleri():
    t_z, k_z, _, _ = _dalas('hard', core.KOVALAYAN, 8.0)
    t_n, k_n, _, _ = _dalas('normal', core.KOVALAYAN, 8.0)
    assert k_z == 'engage' and k_n == 'engage' and t_z < t_n, (t_z, k_z, t_n, k_n)
    for sev in core.BOT_SEVIYELER:
        t, kind, minz, maxr = _dalas(sev, core.KACAN, 11.0)
        assert kind != 'area' and minz >= mbot.ZEMIN_MIN['dikey'] * core.BOT_SEVIYE[sev]['zemin_pay'] - 1 and maxr < 800, (sev, t, kind, minz, maxr)
    print(f'  sahte kinematik it dalaşı: kovalayan Zor {t_z:.0f} sn < Normal {t_n:.0f} sn; kaçan alanda ve yerden yüksekte')


def main():
    seviye_testleri()
    halka_hedef_testleri()
    it_karar_testleri()
    karsilasma_bot_testleri()
    sahte_yaris_testleri()
    sahte_dalas_testleri()
    print('test_flightsim_match_bot: TAMAM')


if __name__ == '__main__':
    main()
