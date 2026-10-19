# SIMUMAV — kurulum (PROD; docs/simumav.md §6)

Sözleşme ve güvenlik kuralları: `docs/simumav.md` (§7 bağlayıcı). Kod `app/simumav/`, ayrı ASGI uygulaması; HEPGO ERP ile veri paylaşmaz.

## 1. Veri dizini ve .env

```
sudo mkdir -p /opt/hepgo/simumav-data && sudo chown hepgo:hepgo /opt/hepgo/simumav-data && sudo chmod 750 /opt/hepgo/simumav-data
```

`/opt/hepgo/caymazbuild/.env` dosyasına (gerçek değerleri buraya YAZMAYIN; yalnız anahtar adları):

| Anahtar | Açıklama |
| --- | --- |
| `SIMUMAV_SECRET` | 32+ bayt rastgele (dev imzaları vb.) |
| `SIMUMAV_MT_URL` | `https://mastertool.download` (tarayıcının giriş yaptığı hesap servisi) |
| `SIMUMAV_MT_INTERNAL` | `http://127.0.0.1:8095` (sunucu-sunucu belirteç doğrulaması) |
| `SIMUMAV_MT_APP` | `sv` (hesap servisindeki oyun kodu) |
| `SIMUMAV_MT_SHARED_SECRET` | hesap servisi `.env`'deki `SIMUMAV_MT_SHARED_SECRET` ile AYNI (sv_profiles yazımı, `X-Simumav-Secret`) |
| `SIMUMAV_PUBLIC_HOST` | MP bağlantı satırında gösterilen sunucu adı/IP (ör. sunucunun genel IP'si) |
| `SIMUMAV_MAX_FLIGHTS` | eşzamanlı uçuş (varsayılan 6) |
| `SIMUMAV_MP_PORT_BASE` / `SIMUMAV_MP_PORT_COUNT` | MP TCP aralığı (varsayılan 15600 / 400 → 15600–15999) |
| `GOOGLE_MAPS_API_KEY` | ortak anahtar (zaten var; referrer listesine `simumav.com` eklenir) |
| `HEPGO_SITL_DIR` | `/opt/hepgo/sitl/bin` (servis dosyasında da var) |

İsteğe bağlı: `SIMUMAV_UDP_BASE` (iç SITL↔MP UDP aralığı, varsayılan 14550; dışa KAPALI), `SIMUMAV_ALLOWED_ORIGINS` (ek CSRF kökenleri).
`SIMUMAV_DEV_LOGIN` PROD'da ASLA 1 yapılmaz.

## 2. Servis

```
sudo cp deploy/simumav/hepgo-simumav.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now hepgo-simumav
sudo systemctl status hepgo-simumav --no-pager; curl --unix-socket /run/hepgo/simumav.sock http://x/api/meta
```

## 3. cloudflared

`deploy/simumav/cloudflared-ingress.yml` parçasını `/etc/cloudflared/config.yml` ingress'ine ekle → `sudo systemctl restart cloudflared`.
Cloudflare DNS: CNAME `simumav.com`, `www` → tünel (proxied) — kullanıcı panelden.

## 4. Güvenlik duvarı

Mission Planner TCP aralığı yalnız aralık olarak açık: `sudo ufw allow 15600:15999/tcp comment 'SIMUMAV MP'`. UDP 14550–14649 (iç köprü) DIŞA KAPALI kalır.

## 5. Hesap servisi (mastertool.download)

`central/sshmaster_server` güncel sürümü dağıt (`GAMES['sv']`, `sv_profiles`, CORS `https://simumav.com`, `/api/sv/web-releases`), `.env`'e
`SIMUMAV_MT_SHARED_SECRET` ve `SIMUMAV_RELEASE_KEY` ekle → `sudo systemctl restart hepgo-sshmasters`.
İkon dosyaları: `static/mt/img/simumav.svg|png|-512.png` (depoda).

## 6. Doğrulama (dışarıdan)

- `https://simumav.com/` 200 (tanıtım), `https://simumav.com/app/` (oturumsuz → tanıtım/giriş), `https://simumav.com/api/meta` 200 (`maps_key` null).
- Oturum açıp uçuş başlat → `mp.port` → Mission Planner `TCP <sunucu> <port>`; başka bir IP'den aynı porta bağlantı reddedilir.
- `journalctl -u hepgo-simumav -f`; denetim kayıtları `simumav.db` → `audit` tablosu.
