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
