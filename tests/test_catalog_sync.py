"""Veilox modül kataloğu ile uygulamanın modülleri (app/auth.py MODULE_ROLES) birebir aynı olmalı: yeni modül eklenip
katalog unutulursa, modül kısıtlı firmalara o modül hiç verilemez. Çalıştırma: .venv/bin/python -m tests.test_catalog_sync
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_ENV_FILE='/dev/null')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'central' / 'veilox_server'))

from app import auth  # noqa: E402
from veilox.modules_catalog import MODULE_KEYS  # noqa: E402


def main():
    app_mods, cat = set(auth.MODULE_ROLES), set(MODULE_KEYS)
    assert app_mods == cat, f'katalogda eksik: {sorted(app_mods - cat)} · uygulamada yok: {sorted(cat - app_mods)}'
    assert len(MODULE_KEYS) == len(cat), 'katalogda tekrar eden anahtar var'
    print('Modül kataloğu uyumlu.')


if __name__ == '__main__':
    main()
