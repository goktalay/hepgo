# SSH Master hesap ve senkronizasyon servisi (sshmasters.com)

Sözleşme: `docs/sshmaster-api.md` (v2). Tanıtım sitesi + hesap sayfaları (`static/`), hesap/oturum/kütüphane/indirme/sürüm uçları (`sshm/main.py`).
Düz şifre sunucuya hiç gelmez (istemci PBKDF2 → auth_hash); bağlantı kütüphanesi uçtan uca şifrelidir.

Canlı: `/opt/hepgo/sshmaster` (hepgo kullanıcısı), systemd `hepgo-sshmasters` (`deploy/hepgo-sshmasters.service`, 127.0.0.1:8095),
Cloudflare tüneli `sshmasters.com` + `www` → `http://127.0.0.1:8095`. Veri `data/sshm.db` + `data/releases/<sürüm>/`.
`.env` (sunucuda üretilir, repoda yok): `SSHM_SALT_KEY`, `SSHM_RELEASE_KEY`, `SSHM_DATA_DIR`. SMTP (register@hepgo.com) ve Merkez iç
anahtarı `/opt/hepgo/veilox/.env`'den okunur. Yönetim: HEPGO Merkez › SSH Master (`app/routers/sshmaster_admin.py`).

Dağıtım: `rsync -rlc --delete --exclude=__pycache__ central/sshmaster_server/{sshm,static} hepgo-new:/opt/hepgo/sshmaster/` →
`chown -R hepgo:hepgo /opt/hepgo/sshmaster` → `systemctl restart hepgo-sshmasters`.
Testler: `cd central/sshmaster_server && ../../.venv/bin/python -m tests.test_sshm`; Merkez vekilleri: `.venv/bin/python -m tests.test_sshmaster_admin`.

## Mastertool (v2: SSH Master + FTP Masters tek hesap)
- Uygulamalar: `sm` (SSH Master, `/api/sm` — v2 sözleşmesi aynen), `fm` (FTP Masters, `/api/fm` — docs/ftpmasters-api.md),
  portal web hesabı `/api/mt`. Siteler Host'a göre: `mastertool.download` (portal), `sshmasters.com`, `ftpmasters.com` (static/<site>/).
- Veritabanı aynı (`data/sshm.db`); v1 şeması ilk açılışta yerinde taşınır (kütüphane / sürüm / indirme / oturum → `sm`, `user_apps`).
- Ortam: `FTPM_RELEASE_KEY` (FTP Masters CI), `MT_PORTAL_LIVE=1` (DNS + tünel hazır olunca: ürün sitelerinin hesap sayfaları ve
  e-posta bağlantıları portala), `MT_PUBLIC_URL`, `FTPM_PUBLIC_URL`, `MT_SMTP_HOST/PORT/USER/PASS` + `MT_MAIL_FROM`
  (yoksa VEILOX_SMTP_* ile register@hepgo.com), `MT_MERKEZ_UDS` (vars. /run/hepgo/merkez.sock — destek talepleri Merkez'e).
- Testler: `../../.venv/bin/python -m tests.test_sshm` (v1 uyumu) ve `-m tests.test_mastertool`.
