"""Araçlar › Ağ Tarayıcı: sunucunun yerel ağındaki bilgisayarlar (yalnızca Sistem Yöneticisi)."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db, netscan

router = APIRouter(prefix='/api/tools/network')
admin_only = auth.require_module('admin')


class LabelIn(BaseModel):
    label: Optional[str] = None
    note: Optional[str] = None


@router.get('')
def devices(user=Depends(admin_only), conn=db.DB):
    rows = db.rows(conn.execute('SELECT * FROM network_devices ORDER BY online DESC, ip'))
    for r in rows:
        r['ports'] = [{'port': p, 'name': netscan.PORTS.get(p, str(p))} for p in json.loads(r['ports'] or '[]')]
    last = conn.execute("SELECT v FROM app_kv WHERE k = 'netscan.last'").fetchone()
    return {'devices': rows, 'last': json.loads(last[0]) if last else None, 'state': netscan.state(), 'networks': netscan.networks()}


@router.post('/scan')
def scan(user=Depends(admin_only), conn=db.DB):
    if not netscan.start():
        raise HTTPException(409, 'Tarama zaten sürüyor')
    db.audit(conn, user['id'], 'Ağ taraması başlattı', 'network', None, ', '.join(n['cidr'] for n in netscan.networks()))
    return netscan.state()


@router.get('/state')
def scan_state(user=Depends(admin_only)):
    return netscan.state()


@router.put('/{did}')
def set_label(did: int, body: LabelIn, user=Depends(admin_only), conn=db.DB):
    if not conn.execute('UPDATE network_devices SET label = ?, note = ? WHERE id = ?',
                        ((body.label or '').strip()[:80] or None, (body.note or '').strip()[:300] or None, did)).rowcount:
        raise HTTPException(404, 'Cihaz bulunamadı')
    return {'ok': True}


@router.delete('/{did}')
def forget(did: int, user=Depends(admin_only), conn=db.DB):
    """Artık ağda olmayan cihaz kaydını siler."""
    if not conn.execute('DELETE FROM network_devices WHERE id = ? AND online = 0', (did,)).rowcount:
        raise HTTPException(400, 'Yalnızca şu an çevrimdışı cihazın kaydı silinir')
    return {'ok': True}
