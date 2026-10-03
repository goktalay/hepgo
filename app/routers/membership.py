"""Firma paneli — Üyeliğim & Destek: merkezle (Veilox) ilişki. Paket/modüller, aylık ücret ve ödeme geçmişi,
destek talepleri (aç, yanıtla, takip et). Veriler merkezde; burası federasyon üzerinden okur/yazar (central_client)."""
from fastapi import APIRouter, Depends, HTTPException, Request
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


# ---- Sözleşmeler: Merkez'in yayınladığı üyelik sözleşmeleri; yetkili kişi okuyup elektronik olarak onaylar
@router.get('/contracts')
def contracts(user=Depends(member_user)):
    return central_client.call('GET', '/contracts')


@router.get('/contracts/{did}')
def contract(did: int, user=Depends(member_user)):
    return central_client.call('GET', f'/contracts/{did}')


class AcceptIn(BaseModel):
    hash: str
    signer_name: str
    signer_title: str = ''
    agree: bool = False


@router.post('/contracts/{did}/accept')
def contract_accept(did: int, body: AcceptIn, request: Request, user=Depends(member_user), conn=db.DB):
    if not body.agree:
        raise HTTPException(400, 'Onay için “Okudum, kabul ediyorum” kutusunu işaretleyin')
    ip = (request.headers.get('cf-connecting-ip') or (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
          or (request.client.host if request.client else ''))
    r = central_client.call('POST', f'/contracts/{did}/accept', json={
        'hash': body.hash, 'signer_name': body.signer_name, 'signer_title': body.signer_title,
        'signer_email': user['username'] if '@' in (user.get('username') or '') else '',
        'ip': ip, 'user_agent': request.headers.get('user-agent', '')})
    central_client.forget_contracts()
    db.audit(conn, user['id'], 'Üyelik sözleşmesini onayladı', 'contract', did, f"{body.signer_name} · {r.get('hash', '')[:12]}")
    return r
