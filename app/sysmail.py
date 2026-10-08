"""Sistem (transactional) e-posta gönderimi — "şifremi unuttum" sıfırlama kodu vb.

Kullanıcıların kendi posta kutuları (app/mail.py, IMAP/SMTP) ile KARIŞTIRMAYIN; bu, sistemin kendi
gönderici hesabıdır (ör. Zoho register@hepgo.com).

.env ayarları (yapılandırılmazsa enabled()=False → e-posta ile sıfırlama kapalı):
  SYSMAIL_HOST   (vars. smtp.zoho.com)
  SYSMAIL_PORT   (vars. 465 = SSL; 587 = STARTTLS)
  SYSMAIL_USER   (ör. register@hepgo.com)
  SYSMAIL_PASS   (Zoho uygulama parolası)
  SYSMAIL_FROM   (vars. SYSMAIL_USER)
  SYSMAIL_FROM_NAME (vars. HEPGO)
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

HOST = os.environ.get('SYSMAIL_HOST', 'smtp.zoho.com').strip() or 'smtp.zoho.com'
PORT = int(os.environ.get('SYSMAIL_PORT', '465') or 465)
USER = os.environ.get('SYSMAIL_USER', '').strip()
PASS = os.environ.get('SYSMAIL_PASS', '')
FROM = os.environ.get('SYSMAIL_FROM', '').strip() or USER
FROM_NAME = os.environ.get('SYSMAIL_FROM_NAME', 'HEPGO').strip() or 'HEPGO'


def enabled():
    """SMTP yapılandırıldı mı? (kullanıcı adı + parola)."""
    return bool(USER and PASS)


def send(to, subject, text, html=None):
    if not enabled():
        raise RuntimeError('mail-disabled')
    msg = EmailMessage()
    msg['From'] = formataddr((FROM_NAME, FROM))
    msg['To'] = to
    msg['Subject'] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype='html')
    ctx = ssl.create_default_context()
    if PORT == 465:
        with smtplib.SMTP_SSL(HOST, PORT, context=ctx, timeout=25) as s:
            s.login(USER, PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(HOST, PORT, timeout=25) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(USER, PASS)
            s.send_message(msg)


def send_reset_code(to, code, username=''):
    """Şifre sıfırlama kodunu gönderir."""
    subject = f'HEPGO şifre sıfırlama kodunuz: {code}'
    who = f' ({username})' if username else ''
    text = (f'HEPGO hesabınız{who} için şifre sıfırlama kodunuz: {code}\n\n'
            f'Bu kodu şifre sıfırlama ekranına girip yeni şifrenizi belirleyin. Kod 15 dakika geçerlidir.\n'
            f'Bu isteği siz yapmadıysanız bu e-postayı yok sayın; şifreniz değişmez.\n\n— HEPGO')
    html = f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:auto;color:#0f1d3d">
      <h2 style="margin:0 0 8px">HEPGO şifre sıfırlama</h2>
      <p style="color:#555">Hesabınız{html_escape(who)} için şifre sıfırlama kodu:</p>
      <div style="font-size:32px;font-weight:700;letter-spacing:8px;background:#f1f5fb;border-radius:12px;
                  padding:18px;text-align:center;margin:16px 0">{code}</div>
      <p style="color:#888;font-size:13px">Kodu sıfırlama ekranına girip yeni şifrenizi belirleyin. Kod 15 dakika geçerlidir.
      Bu isteği siz yapmadıysanız yok sayın; şifreniz değişmez.</p>
      <p style="color:#aaa;font-size:12px">— HEPGO</p>
    </div>"""
    send(to, subject, text, html)


def html_escape(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
