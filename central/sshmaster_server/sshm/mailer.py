"""Mastertool e-postaları (SSH Master / FTP Masters / Mastertool markalı).

Gönderen yapılandırılabilir:
- MT_SMTP_HOST / MT_SMTP_PORT / MT_SMTP_USER / MT_SMTP_PASS (+ MT_MAIL_FROM, vars. MT_SMTP_USER) tanımlıysa onunla gider
  (hedef: register@mastertool.download).
- Tanımlı değilse geçiş dönemi için mevcut gönderen kullanılır: VEILOX_SMTP_* (register@hepgo.com; SSHM_MAIL_FROM ile değişir).
Gönderen ADI, konu ve logo markadır (sm = SSH Master, fm = FTP Masters, mt = Mastertool). SMTP yoksa enabled() False döner (kayıt 503).
SSHM_MAIL_TEST=1 iken iletiler gönderilmez, OUTBOX'ta birikir (testler)."""
import html as _h
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import settings

BRANDS = {'sm': ('SSH Master', 'sshmasters.com'), 'fm': ('FTP Masters', 'ftpmasters.com'), 'sq': ('SQL Master', 'sqlmaster.app'),
          'np': ('Notepad Master', 'notepadmaster.com'), 'cv': ('Convert Master', 'convertmaster.app'),
          'mt': ('Mastertool', 'mastertool.download')}

if os.environ.get('MT_SMTP_USER', '').strip() and os.environ.get('MT_SMTP_PASS', ''):
    HOST = os.environ.get('MT_SMTP_HOST', 'smtp.zoho.com').strip() or 'smtp.zoho.com'
    PORT = int(os.environ.get('MT_SMTP_PORT', '465') or 465)
    USER = os.environ['MT_SMTP_USER'].strip()
    PASS = os.environ['MT_SMTP_PASS']
    FROM = os.environ.get('MT_MAIL_FROM', '').strip() or USER
else:
    HOST = os.environ.get('VEILOX_SMTP_HOST', 'smtp.zoho.com').strip() or 'smtp.zoho.com'
    PORT = int(os.environ.get('VEILOX_SMTP_PORT', '465') or 465)
    USER = os.environ.get('VEILOX_SMTP_USER', '').strip()
    PASS = os.environ.get('VEILOX_SMTP_PASS', '')
    FROM = os.environ.get('SSHM_MAIL_FROM', '').strip() or os.environ.get('VEILOX_MAIL_FROM', '').strip() or USER or 'register@hepgo.com'
OUTBOX = []


def enabled():
    return os.environ.get('SSHM_MAIL_TEST') == '1' or bool(USER and PASS)


def _brand(b):
    return b if b in BRANDS else 'mt'


def send(to, subject, text, html=None, brand='mt'):
    if os.environ.get('SSHM_MAIL_TEST') == '1':
        OUTBOX.append({'to': to, 'subject': subject, 'text': text, 'html': html, 'brand': brand, 'from_name': BRANDS[_brand(brand)][0]})
        return
    if not (USER and PASS):
        raise RuntimeError('mail-disabled')
    msg = EmailMessage()
    msg['From'] = formataddr((BRANDS[_brand(brand)][0], FROM))
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


def _layout(brand, title, body_html, button_text=None, button_url=None, foot=None):
    """Markalı HTML gövde: üstte marka logosu (PNG; e-posta istemcileri SVG göstermez), başlık, metin, düğme."""
    name, domain = BRANDS[brand]
    logo = f'{settings.ACCOUNT_URL}/brand/{brand}.png'
    btn = (f'<p style="margin:26px 0"><a href="{_h.escape(button_url)}" style="background:#22d3ee;color:#06101c;text-decoration:none;'
           f'font-weight:700;padding:12px 22px;border-radius:10px;display:inline-block">{_h.escape(button_text)}</a></p>'
           f'<p style="color:#8b98b0;font-size:12px;word-break:break-all">Düğme çalışmazsa bu adresi tarayıcınıza yapıştırın:<br>'
           f'{_h.escape(button_url)}</p>') if button_url else ''
    acct = '' if brand == 'mt' else ' · Mastertool hesabı'
    return f"""<div style="background:#0b0f17;padding:28px 12px;font-family:Segoe UI,Arial,sans-serif">
  <div style="max-width:520px;margin:auto;background:#131b2b;border:1px solid #1f2a40;border-radius:14px;padding:28px;color:#d6deeb">
    <table role="presentation" style="border-collapse:collapse"><tr>
      <td style="vertical-align:middle"><img src="{logo}" width="40" height="40" alt="{name}" style="display:block;border:0"></td>
      <td style="vertical-align:middle;padding-left:10px;font-size:20px;font-weight:800;color:#ffffff">{name}</td></tr></table>
    <h2 style="color:#ffffff;margin:22px 0 10px;font-size:20px">{_h.escape(title)}</h2>
    <div style="font-size:15px;line-height:1.6;color:#c4cede">{body_html}</div>
    {btn}
    <p style="color:#5b6b85;font-size:12px;margin-top:24px">{_h.escape(foot or 'Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.')}<br>— {name}{acct} · {domain}</p>
  </div></div>"""


_ONE = ('Tek Mastertool hesabıyla tüm Mastertool uygulamalarına (SSH Master, FTP Masters, SQL Master, Notepad Master, Convert Master) giriş yapabilir, indirmelerinizi ve şifreli eşitlemenizi '
        'tek yerden yönetebilirsiniz.')


def send_verify(to, name, url, brand='mt'):
    brand = _brand(brand)
    bn = BRANDS[brand][0]
    subject = f'{bn}: e-posta adresinizi doğrulayın'
    text = (f'Merhaba {name},\n\n{bn} hesabınızı etkinleştirmek için bu bağlantıyı açın (24 saat geçerli):\n{url}\n\n{_ONE}\n\n'
            f'Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.\n\n— {bn}')
    send(to, subject, text, _layout(brand, 'Hesabınızı etkinleştirin',
                                    f'Merhaba {_h.escape(name)},<br>{bn} hesabınızı etkinleştirmek için aşağıdaki düğmeye tıklayın. '
                                    f'Bağlantı 24 saat geçerlidir.<br><br><span style="color:#8b98b0">{_h.escape(_ONE)}</span>',
                                    'E-postamı doğrula', url), brand)


def send_reset(to, name, url, brand='mt'):
    brand = _brand(brand)
    bn = BRANDS[brand][0]
    subject = f'{bn}: şifre sıfırlama'
    text = (f'Merhaba {name},\n\nMastertool hesabınızın (tüm Mastertool uygulamaları) şifresini sıfırlamak için bu bağlantıyı açın '
            f'(1 saat geçerli):\n{url}\n\nNot: şifre sıfırlanınca web\'de saklanan şifreli kütüphaneleriniz silinir; uygulamalarda yeni '
            f'şifrenizle giriş yaptığınızda bilgisayarınızdaki kayıtlar yeniden yüklenir.\n\n— {bn}')
    send(to, subject, text, _layout(brand, 'Şifrenizi sıfırlayın',
                                    f'Merhaba {_h.escape(name)},<br>Yeni şifre belirlemek için aşağıdaki düğmeye tıklayın. Bağlantı 1 saat geçerlidir. '
                                    'Yeni şifre tüm Mastertool uygulamaları için birlikte geçerli olur.'
                                    '<br><br><span style="color:#8b98b0">Şifre sıfırlanınca web\'de saklanan şifreli kütüphaneleriniz silinir; '
                                    'uygulamalarda yeni şifrenizle giriş yaptığınızda bilgisayarınızdaki kayıtlar yeniden yüklenir.</span>',
                                    'Yeni şifre belirle', url), brand)


def send_exists(to, name, login_url, reset_url, brand='mt'):
    brand = _brand(brand)
    bn = BRANDS[brand][0]
    subject = f'{bn}: bu e-postayla zaten bir hesabınız var'
    text = (f'Merhaba {name},\n\nBu e-posta adresiyle yeni bir kayıt denendi; ancak zaten bir Mastertool hesabınız var '
            f'(tüm Mastertool uygulamaları için aynı hesap).\nGiriş: {login_url}\nŞifrenizi hatırlamıyorsanız: {reset_url}\n\n— {bn}')
    send(to, subject, text, _layout(brand, 'Zaten bir hesabınız var',
                                    f'Merhaba {_h.escape(name)},<br>Bu e-posta adresiyle yeni bir kayıt denendi; ancak zaten bir Mastertool hesabınız var '
                                    '(tüm Mastertool uygulamaları için aynı hesap). Şifrenizi hatırlamıyorsanız '
                                    f'<a style="color:#22d3ee" href="{_h.escape(reset_url)}">şifre sıfırlama</a> sayfasını kullanın.',
                                    'Giriş yap', login_url), brand)


def send_ticket_reply(to, name, code, subject_line, url, brand='mt'):
    brand = _brand(brand)
    bn = BRANDS[brand][0]
    subject = f'{bn}: destek talebinize yanıt ({code})'
    text = (f'Merhaba {name},\n\n"{subject_line}" konulu {code} numaralı destek talebinize yanıt verildi. Yanıtı okumak için:\n{url}\n\n— {bn} Destek')
    send(to, subject, text, _layout(brand, 'Destek talebinize yanıt verildi',
                                    f'Merhaba {_h.escape(name)},<br><b>{_h.escape(code)}</b> numaralı, “{_h.escape(subject_line)}” konulu '
                                    'destek talebinize yanıt verildi.', 'Yanıtı oku', url,
                                    'Bu e-postayı destek talebiniz güncellendiği için aldınız.'), brand)
