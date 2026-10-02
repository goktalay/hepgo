# Fabrika Ajanı (dağıtık entegrasyon)

Merkez buluta taşındığında Mikro ERP, PDKS ve yazıcılar fabrika LAN'ında kalır.
Bu ajan fabrikada çalışır, merkeze **dışa doğru** WSS bağlanır ve cihaz op'larını yerelde çalıştırır
(fabrikada açık port gerekmez).

## Kurulum (fabrikadaki makinede, caymazbuild kökünden)
`.env` (ya da ortam) içinde fabrika cihaz bilgileri + ajan ayarları:

    CAYMAZ_AGENT_CENTRAL_URL=wss://caymaz.app/ws/agent
    CAYMAZ_AGENT_KEY=<merkezdeki CAYMAZ_AGENT_KEY ile AYNI>
    # Fabrika cihazları:
    CAYMAZ_MIKRO_HOST=192.168.1.100
    CAYMAZ_MIKRO_PORT=1433
    CAYMAZ_MIKRO_DB=MikroDB_V16_FIRMA
    CAYMAZ_MIKRO_USER=...
    CAYMAZ_MIKRO_PASSWORD=...
    CAYMAZ_PDKS_HOST=192.168.1.100
    CAYMAZ_PDKS_PORT=3050
    CAYMAZ_PDKS_DB=\\192.168.1.100\MPremium\PDKS.GDB
    CAYMAZ_PDKS_USER=...
    CAYMAZ_PDKS_PASSWORD=...

## Çalıştırma
    .venv/bin/python -m agent.agent

systemd servisi olarak da çalıştırılabilir (fabrikadaki makinede).

## Merkez tarafı
Merkez sunucuda `CAYMAZ_AGENT_MODE=remote` ve aynı `CAYMAZ_AGENT_KEY` tanımlı olmalı.
Mikro/PDKS/yazıcı op'ları otomatik olarak bu ajana yönlenir. Kamera/yüz tanıma ayrı
(camera_service) yine fabrikada çalışır. Uçuş logu analizi ajan gerektirmez (yüklenen dosya işlenir).
