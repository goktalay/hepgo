"""Firma paneli — Üyeliğim & Destek: merkezle (Veilox) ilişki. Paket/modüller, aylık ücret ve ödeme geçmişi,
destek talepleri (aç, yanıtla, takip et). Veriler merkezde; burası federasyon üzerinden okur/yazar (central_client)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import auth, central_client, config, db

router = APIRouter(prefix='/api/membership')
member_user = auth.require_module('uyelik')


@router.get('')
def overview(user=Depends(member_user)):
    return central_client.call('GET', '/membership')


@router.get('/tickets')
def tickets(user=Depends(member_user)):
    return central_client.call('GET', '/tickets')


class TicketIn(BaseModel):
    subject: str
    body: str
    category: str = 'teknik'
    priority: str = 'normal'


@router.post('/tickets')
def ticket_create(body: TicketIn, user=Depends(member_user), conn=db.DB):
    r = central_client.call('POST', '/tickets', json={**body.model_dump(), 'name': user['full_name'], 'email': user['username'],
                                                      'company_name': config.COMPANY_NAME})
    db.audit(conn, user['id'], 'Merkeze destek talebi açtı', 'ticket', r.get('code'), body.subject[:80])
    return r


@router.get('/tickets/{tid}')
def ticket_detail(tid: int, user=Depends(member_user)):
    return central_client.call('GET', f'/tickets/{tid}')


class MsgIn(BaseModel):
    body: str


@router.post('/tickets/{tid}/messages')
def ticket_reply(tid: int, body: MsgIn, user=Depends(member_user)):
    return central_client.call('POST', f'/tickets/{tid}/messages', json={'body': body.body, 'name': user['full_name']})
