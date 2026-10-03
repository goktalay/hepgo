# Veilox kurulum servisi (veilox.app)

Sunucuda `/opt/hepgo/veilox` altında `uvicorn veilox.main:app --uds /run/hepgo/veilox.sock` olarak çalışır
(systemd: `hepgo-veilox`). Tanıtım sayfası (veilox.app / hepgo.com), self-servis kayıt, firma kurulumu
(provisioning: systemd + Cloudflare), offline paket ve kurulum linkleri buradadır.

**Yönetim arayüzü artık HEPGO Merkez'dedir** (`merkez.veilox.app`, HEPGO uygulaması merkez modunda —
`CAYMAZ_FEDERATION_CENTRAL=1`). Merkez bu servisi yerel soketten `X-Central-Secret` iç anahtarıyla çağırır
(`VEILOX_CENTRAL_API_SECRET` = Merkez'deki `CAYMAZ_CENTRAL_API_SECRET`; firmalarda bulunmaz).

Dağıtım: `rsync -a central/veilox_server/{veilox,static} root@sunucu:/opt/hepgo/veilox/` → `systemctl restart hepgo-veilox`.
Gizli bilgiler (`.env`, `data/central.db`) repoda yoktur.
