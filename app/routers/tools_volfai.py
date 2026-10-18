"""Araçlar › VOLFAI (web) — oyun profili HEPGO kullanıcısında saklanır.

Oyun static/mt/volfai/ altında birebir (goktalay/Volfia v0.5.0); Master Tool hesap servisi (/api/vf/auth/*, /api/vf/profile)
yerine HEPGO oturumu + bu uçlar (yetki: Araçlar modülü):
  GET  /api/tools/volfai/profile      → {user:{id,name,photo}, profile: JSON|None, updated_at}   (vf/profile ile aynı şema)
  PUT  /api/tools/volfai/profile      {profile:{...}} → {ok:True}   (nesne zorunlu, ≤ 64 KB; sunucu olduğu gibi saklar)
  GET  /api/tools/volfai/leaderboard  → şirket içi skor tablosu [{user_id,name,photo,hi_score,coins,honor,parkurs,updated_at}]
Tablo: tools_mt_store(user_id, app, key, json, updated_at) — Master Tool web araçlarının ortak kullanıcı-başına JSON deposu
(diğer araçlar da aynı tabloyu CREATE TABLE IF NOT EXISTS ile kurar; ad/sütunlar aynı).
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db
from .tools_common import tools_user

router = APIRouter(prefix='/api/tools/volfai')
APP = 'volfai'
KEY = 'profile'
MAX_LEN = 64 * 1024   # vf/profile sınırı ile aynı
LEADERBOARD_LIMIT = 50

STORE_SQL = """CREATE TABLE IF NOT EXISTS tools_mt_store (
    user_id INTEGER NOT NULL,
    app TEXT NOT NULL,
    key TEXT NOT NULL,
    json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, app, key))"""


def _ensure(conn):
    conn.execute(STORE_SQL)


def _name(row):
    return row['full_name'] or row['username']


@router.get('/profile')
def get_profile(user=Depends(tools_user), conn=db.DB):
    _ensure(conn)
    row = conn.execute('SELECT json, updated_at FROM tools_mt_store WHERE user_id = ? AND app = ? AND key = ?',
                       (user['id'], APP, KEY)).fetchone()
    profile = None
    if row:
        try:
            profile = json.loads(row['json'])
        except ValueError:
            profile = None
    return {'user': {'id': user['id'], 'name': _name(user), 'photo': user['photo']},
            'profile': profile, 'updated_at': row['updated_at'] if row else None}


@router.put('/profile')
def put_profile(body=Body(...), user=Depends(tools_user), conn=db.DB):
    if not isinstance(body, dict) or not isinstance(body.get('profile'), dict):
        raise HTTPException(400, 'profile nesnesi gerekli')
    raw = json.dumps(body['profile'], ensure_ascii=False, separators=(',', ':'))
    if len(raw.encode('utf-8')) > MAX_LEN:
        raise HTTPException(413, 'Profil 64 KB sınırını aşıyor')
    _ensure(conn)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    conn.execute('INSERT INTO tools_mt_store (user_id, app, key, json, updated_at) VALUES (?, ?, ?, ?, ?) '
                 'ON CONFLICT(user_id, app, key) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at',
                 (user['id'], APP, KEY, raw, now))
    return {'ok': True}


def _honor(profile):
    """Profildeki tüm parkurların onur toplamı (profile.js levelHonor/totalHonor ile aynı)."""
    s = 0
    for lv in (profile.get('levels') or {}).values():
        for r in ((lv or {}).get('parkurs') or {}).values():
            try:
                s += int((r or {}).get('honor') or 0)
            except (TypeError, ValueError):
                pass
    return s


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


@router.get('/leaderboard')
def leaderboard(user=Depends(tools_user), conn=db.DB):
    """Şirket içi skor tablosu: en yüksek skora göre (eşitlikte onur). En çok 50 kayıt."""
    _ensure(conn)
    rows = conn.execute('SELECT s.user_id, s.json, s.updated_at, u.full_name, u.username, u.photo FROM tools_mt_store s '
                        'JOIN users u ON u.id = s.user_id WHERE s.app = ? AND s.key = ?', (APP, KEY)).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r['json'])
        except ValueError:
            continue
        if not isinstance(p, dict):
            continue
        stats = p.get('stats') or {}
        out.append({'user_id': r['user_id'], 'name': _name(r), 'photo': r['photo'],
                    'hi_score': _int(p.get('hiScore')), 'coins': _int(p.get('coins')), 'honor': _honor(p),
                    'parkurs': _int(stats.get('parkursCleared')), 'updated_at': r['updated_at']})
    out.sort(key=lambda x: (-x['hi_score'], -x['honor'], x['name']))
    return out[:LEADERBOARD_LIMIT]
