#!/usr/bin/env python3
"""İş Güvenliği tespit modelleri → vendor/models/ (depoya girmez; kamera servisinin çalıştığı makinede bir kez koşulur).

Kullanım:
  .venv/bin/python tools/worksafety_models.py            # eksikleri indir + doğrula
  .venv/bin/python tools/worksafety_models.py --check    # yalnız durum (indirme yok)
  .venv/bin/python tools/worksafety_models.py --from /yol/modeller   # internet yoksa: hazır dosyaları kopyala + doğrula

Model tablosu app/worksafety_detect.py::MODELS'tedir (adres, sha256, lisans). sha256 verilen dosyalar doğrulanır; uyuşmayan
indirme yerleştirilmez. Zip içinden yalnız tabloda adı geçen tek üye (ONNX) okunur; arşivdeki başka hiçbir şey açılmaz /
çalıştırılmaz. Var olan ve doğrulanan dosyaya dokunulmaz.

Ek sınıf modelleri (forklift, kaynak maskesi, emniyet kemeri…): vendor/models/ws_<ad>.onnx + ws_<ad>.labels (satır başına bir
sınıf adı) olarak elle konur; işleyici açılışta kendiliğinden yükler.
"""
import argparse
import hashlib
import io
import pathlib
import shutil
import sys
import urllib.request
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app import worksafety_detect as D  # noqa: E402

MAX_BYTES = 400 * 1024 * 1024


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def state(name, spec):
    """'ok' | 'yok' | 'bozuk' (sha256 uyuşmuyor) | 'doğrulanmadı' (tabloda sha256 yok)."""
    p = D.MODEL_DIR / name
    if not p.exists() or p.stat().st_size < 1024:
        return 'yok'
    if not spec.get('sha256'):
        return 'doğrulanmadı'
    return 'ok' if sha256(p) == spec['sha256'] else 'bozuk'


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'hepgo-worksafety-models'})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('dosya beklenenden büyük')
    return data


def place(name, spec, data):
    if spec.get('member'):   # arşivden yalnız adı verilen üye
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            hit = [i for i in z.infolist() if i.filename.rsplit('/', 1)[-1] == spec['member'] and not i.is_dir()]
            if len(hit) != 1 or hit[0].file_size > MAX_BYTES:
                raise ValueError(f'arşivde tek bir {spec["member"]} bekleniyordu')
            data = z.read(hit[0])
    if spec.get('sha256') and hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('sha256 uyuşmuyor — dosya yerleştirilmedi')
    if data[:1] != b'\x08':   # ONNX (protobuf ModelProto): ilk alan ir_version
        raise ValueError('ONNX dosyası değil')
    D.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = D.MODEL_DIR / (name + '.part')
    tmp.write_bytes(data)
    tmp.replace(D.MODEL_DIR / name)


def main():
    ap = argparse.ArgumentParser(description='İş Güvenliği tespit modellerini indirir / doğrular')
    ap.add_argument('--check', action='store_true', help='yalnız durumu yaz')
    ap.add_argument('--from', dest='src', help='modellerin hazır bulunduğu dizin (indirmek yerine kopyala)')
    a = ap.parse_args()
    bad = 0
    for name, spec in D.MODELS.items():
        st = state(name, spec)
        if st in ('yok', 'bozuk') and not a.check:
            try:
                if a.src:
                    src = pathlib.Path(a.src) / name
                    if not src.is_file():
                        raise ValueError(f'{src} yok')
                    if spec.get('sha256') and sha256(src) != spec['sha256']:
                        raise ValueError('sha256 uyuşmuyor — dosya yerleştirilmedi')
                    D.MODEL_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, D.MODEL_DIR / name)
                else:
                    place(name, spec, fetch(spec['url']))
                st = state(name, spec) + ' (yeni)'
            except Exception as e:   # noqa: BLE001 — biri düşse de ötekiler denensin
                st = f'{st} — {e}'
        if st.startswith(('yok', 'bozuk')):
            bad += 1
        print(f'{name:18s} {spec["role"]:24s} {spec["license"]:11s} {st}')
    extra = sorted(p.name for p in D.MODEL_DIR.glob('ws_*.onnx')) if D.MODEL_DIR.exists() else []
    if extra:
        print('Ek sınıf modelleri:', ', '.join(extra))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
