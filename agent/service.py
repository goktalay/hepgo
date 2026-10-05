"""Ortak çerçeve giriş noktası — systemd bunu çalıştırır: `python -m agent.service`.

Davranış (HEPGO_INTEG=<entegrasyon> ile):
  * Yapılandırma YOKSA (ilk kurulum) → yerel yapılandırma arayüzünü (agent.localconfig, 127.0.0.1:8765)
    başlatır ve URL'yi loga yazar. Kullanıcı "Kaydet ve Bağlan" deyince agent-config.env yazılır ve
    süreç çıkar; systemd (Restart=always) yeniden başlatır, bu kez yapılandırma vardır → ajan çalışır.
  * Yapılandırma VARSA → ortak ajan döngüsünü (agent.agent) çalıştırır (auth'ta integ gönderilir).

Legacy gx10 ajanı etkilenmez: o hâlâ doğrudan `python -m agent.agent` ile (HEPGO_INTEG olmadan) çalışır.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import envcfg          # noqa: E402
from agent import profiles        # noqa: E402


def main():
    integ = envcfg.integ_name()
    if integ and integ not in profiles.names():
        print(f'HATA: bilinmeyen HEPGO_INTEG={integ!r}. Geçerli: {", ".join(profiles.names())}')
        sys.exit(2)

    # Ortama agent-config.env'i yükle (varsa).
    envcfg.load_into_environ()

    if not envcfg.has_config():
        # İlk çalıştırma: yapılandırma arayüzünü aç.
        from agent import localconfig
        label = profiles.get(integ)['name'] if integ else 'HEPGO Ajanı'
        print(f'[{label}] Yapılandırma bulunamadı — yerel ayar sayfası açılıyor.')
        localconfig.serve_until_saved()
        # serve_until_saved() yapılandırma kaydedilince döner; süreç çıkar, systemd yeniden başlatır.
        print('Yapılandırma kaydedildi; servis yeniden başlatılıyor…')
        sys.exit(0)

    # Yapılandırma var → ajanı çalıştır. agent.agent import anında ortamı okur ve döngüyü kurar.
    import asyncio
    from agent import agent
    asyncio.run(agent.run())


if __name__ == '__main__':
    main()
