"""Bayram temaları (docs/bayram-temalari.md) — HEPGO uç noktaları. Veri ve kurallar app/holiday_themes.py (SIMUMAV ile ortak, saf modül).

GET /api/holiday-theme?country=TR&date=YYYY-MM-DD&lang=tr   oturumsuz; o gün etkin temalar + sıradaki bayram (önbellekli; yanıt 1 sa paylaşılabilir)
GET /api/holiday-theme/me                                    oturumlu; kullanıcının ayarı (prefs.settings.holiday) + KULLANICININ GİRDİĞİ konumdan ülke
                                                             (kendi çalışan adresi → firmadaki adreslerin çoğunluğu). IP'den konum sorgusu YOK.
"""
import datetime as dt
import json
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from .. import auth, db, holiday_themes

router = APIRouter(prefix='/api/holiday-theme', tags=['holiday'])
_FIRMA = {'t': 0.0, 'v': None}   # firma çoğunluk ülkesi önbelleği (10 dk)


def _gun(date: str | None) -> dt.date:
    if not date:
        return dt.date.today()
    try:
        d = dt.date.fromisoformat(date[:10])
    except ValueError:
        raise HTTPException(422, 'date YYYY-MM-DD olmalı')
    if abs((d - dt.date.today()).days) > 3700:
        raise HTTPException(422, 'Tarih aralık dışında')
    return d


@router.get('')
def holiday_theme(country: str = Query(..., max_length=2), date: str | None = Query(None, max_length=10), lang: str | None = Query(None, max_length=5)):
    c = holiday_themes.norm_country(country)
    if not c:
        raise HTTPException(422, 'country ISO 3166-1 alfa-2 olmalı (ör. TR)')
    return JSONResponse(holiday_themes.day_info(c, _gun(date), lang), headers={'Cache-Control': 'public, max-age=3600'})


def konumdan_ulke(conn, user_id: int):
    """(ülke, kaynak) — kullanıcının kendi çalışan adresi (girilmiş koordinat) → firmadaki adreslerin çoğunluk ülkesi. Yoksa (None, None)."""
    try:
        r = conn.execute('''SELECT a.lat, a.lng FROM employee_addresses a JOIN employees e ON e.id = a.employee_id
                            WHERE e.user_id = ? AND a.lat IS NOT NULL AND a.lng IS NOT NULL ORDER BY a.is_primary DESC, a.id LIMIT 1''', (user_id,)).fetchone()
    except Exception:   # noqa: BLE001 — eski şema (lat/lng sütunu yok)
        r = None
    if r:
        c = holiday_themes.country_at(r[0], r[1])
        if c:
            return c, 'address'
    import time
    if time.time() - _FIRMA['t'] > 600:
        sayac = Counter()
        try:
            for la, lo in conn.execute('SELECT lat, lng FROM employee_addresses WHERE lat IS NOT NULL AND lng IS NOT NULL ORDER BY id DESC LIMIT 300'):
                c = holiday_themes.country_at(la, lo)
                if c:
                    sayac[c] += 1
        except Exception:   # noqa: BLE001
            pass
        _FIRMA.update(t=time.time(), v=sayac.most_common(1)[0][0] if sayac else None)
    return (_FIRMA['v'], 'company') if _FIRMA['v'] else (None, None)


@router.get('/me')
def holiday_me(user=Depends(auth.current_user), conn=db.DB):
    try:
        prefs = json.loads(user['prefs']) if user.get('prefs') else {}
    except (TypeError, ValueError):
        prefs = {}
    h = (prefs.get('settings') or {}).get('holiday') or {}
    located, kaynak = konumdan_ulke(conn, user['id'])
    return {'enabled': h.get('on', True) is not False, 'country': holiday_themes.norm_country(h.get('country')), 'located': located, 'located_source': kaynak,
            'countries': holiday_themes.countries(), 'themes': [{'code': k, 'name': v} for k, v in holiday_themes.THEME_TR.items()]}
