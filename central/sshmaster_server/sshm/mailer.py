"""SSH Master e-postaları: register@hepgo.com (Zoho SMTP; Veilox'un VEILOX_SMTP_* ayarları) üzerinden, gönderen adı / konu / logo
SSH Master. SSHM_MAIL_FROM_NAME ile ad değiştirilebilir. SMTP tanımlı değilse enabled() False döner (kayıt 503 verir)."""
import html as _h
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import settings

HOST = os.environ.get('VEILOX_SMTP_HOST', 'smtp.zoho.com').strip() or 'smtp.zoho.com'
PORT = int(os.environ.get('VEILOX_SMTP_PORT', '465') or 465)
USER = os.environ.get('VEILOX_SMTP_USER', '').strip()
PASS = os.environ.get('VEILOX_SMTP_PASS', '')
FROM = os.environ.get('SSHM_MAIL_FROM', '').strip() or os.environ.get('VEILOX_MAIL_FROM', '').strip() or USER or 'register@hepgo.com'
FROM_NAME = os.environ.get('SSHM_MAIL_FROM_NAME', 'SSH Master').strip() or 'SSH Master'
OUTBOX = []   # testler için (SSHM_MAIL_TEST=1): gönderilmeyen iletiler burada birikir


def enabled():
    return os.environ.get('SSHM_MAIL_TEST') == '1' or bool(USER and PASS)


def send(to, subject, text, html=None):
    if os.environ.get('SSHM_MAIL_TEST') == '1':
        OUTBOX.append({'to': to, 'subject': subject, 'text': text, 'html': html})
        return
    if not (USER and PASS):
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


def _layout(title, body_html, button_text=None, button_url=None, foot=None):
    """Markalı HTML gövde: üstte SSH Master logosu (PNG; e-posta istemcileri SVG göstermez), başlık, metin, düğme."""
    logo = f'{settings.PUBLIC_URL}/logo.png'
    btn = (f'<p style="margin:26px 0"><a href="{_h.escape(button_url)}" style="background:#22d3ee;color:#06101c;text-decoration:none;'
           f'font-weight:700;padding:12px 22px;border-radius:10px;display:inline-block">{_h.escape(button_text)}</a></p>'
           f'<p style="color:#8b98b0;font-size:12px;word-break:break-all">Düğme çalışmazsa bu adresi tarayıcınıza yapıştırın:<br>'
           f'{_h.escape(button_url)}</p>') if button_url else ''
    return f"""<div style="background:#0b0f17;padding:28px 12px;font-family:Segoe UI,Arial,sans-serif">
  <div style="max-width:520px;margin:auto;background:#131b2b;border:1px solid #1f2a40;border-radius:14px;padding:28px;color:#d6deeb">
    <table role="presentation" style="border-collapse:collapse"><tr>
      <td style="vertical-align:middle"><img src="{logo}" width="40" height="40" alt="SSH Master" style="display:block;border:0"></td>
      <td style="vertical-align:middle;padding-left:10px;font-size:20px;font-weight:800;color:#ffffff">SSH Master</td></tr></table>
    <h2 style="color:#ffffff;margin:22px 0 10px;font-size:20px">{_h.escape(title)}</h2>
    <div style="font-size:15px;line-height:1.6;color:#c4cede">{body_html}</div>
    {btn}
    <p style="color:#5b6b85;font-size:12px;margin-top:24px">{_h.escape(foot or 'Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.')}<br>— SSH Master · sshmasters.com</p>
  </div></div>"""


def send_verify(to, name, url):
    subject = 'SSH Master: e-posta adresinizi doğrulayın'
    text = (f'Merhaba {name},\n\nSSH Master hesabınızı etkinleştirmek için bu bağlantıyı açın (24 saat geçerli):\n{url}\n\n'
            f'Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.\n\n— SSH Master')
    send(to, subject, text, _layout('Hesabınızı etkinleştirin',
                                    f'Merhaba {_h.escape(name)},<br>SSH Master hesabınızı etkinleştirmek için aşağıdaki düğmeye tıklayın. '
                                    'Bağlantı 24 saat geçerlidir.', 'E-postamı doğrula', url))


def send_reset(to, name, url):
    subject = 'SSH Master: şifre sıfırlama'
    text = (f'Merhaba {name},\n\nSSH Master şifrenizi sıfırlamak için bu bağlantıyı açın (1 saat geçerli):\n{url}\n\n'
            f'Not: şifre sıfırlanınca web\'de saklanan şifreli bağlantı kütüphaneniz silinir; uygulamada yeni şifrenizle '
            f'giriş yaptığınızda bilgisayarınızdaki kütüphane yeniden yüklenir.\n\n— SSH Master')
    send(to, subject, text, _layout('Şifrenizi sıfırlayın',
                                    f'Merhaba {_h.escape(name)},<br>Yeni şifre belirlemek için aşağıdaki düğmeye tıklayın. Bağlantı 1 saat geçerlidir.'
                                    '<br><br><span style="color:#8b98b0">Şifre sıfırlanınca web\'de saklanan şifreli bağlantı kütüphaneniz silinir; '
                                    'uygulamada yeni şifrenizle giriş yaptığınızda bilgisayarınızdaki kütüphane yeniden yüklenir.</span>',
                                    'Yeni şifre belirle', url))


def send_exists(to, name, login_url, reset_url):
    subject = 'SSH Master: bu e-postayla zaten bir hesabınız var'
    text = (f'Merhaba {name},\n\nBu e-posta adresiyle yeni bir kayıt denendi; ancak zaten bir SSH Master hesabınız var.\n'
            f'Giriş: {login_url}\nŞifrenizi hatırlamıyorsanız: {reset_url}\n\n— SSH Master')
    send(to, subject, text, _layout('Zaten bir hesabınız var',
                                    f'Merhaba {_h.escape(name)},<br>Bu e-posta adresiyle yeni bir kayıt denendi; ancak zaten bir SSH Master hesabınız var. '
                                    f'Şifrenizi hatırlamıyorsanız <a style="color:#22d3ee" href="{_h.escape(reset_url)}">şifre sıfırlama</a> sayfasını kullanın.',
                                    'Giriş yap', login_url))
