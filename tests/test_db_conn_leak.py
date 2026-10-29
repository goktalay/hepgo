"""Veritabanı bağlantı sızıntısı (29.10 Merkez + demo kiracılar 502): `with db.connect() as conn` bloğu bitince bağlantı
kapanmalı; blok dışında conn kullanan kod olmamalı (statik tarama); commit/rollback davranışı korunmalı."""
import ast
import gc
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_ENV_FILE='/nonexistent.env')

from app import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / 'app'


class _Scope(ast.NodeVisitor):
    def __init__(self):
        self.binds, self.loads, self.withs = {}, [], []

    def visit_FunctionDef(self, n):   # iç işlevler ayrı kapsam
        pass
    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_Name(self, n):
        if isinstance(n.ctx, ast.Store):
            self.binds.setdefault(n.id, []).append(n.lineno)
        elif isinstance(n.ctx, ast.Load):
            self.loads.append((n.id, n.lineno))

    def visit_With(self, n):
        for it in n.items:
            c = it.context_expr
            if (isinstance(c, ast.Call) and getattr(c.func, 'attr', getattr(c.func, 'id', None)) == 'connect'
                    and isinstance(it.optional_vars, ast.Name)):
                self.withs.append((it.optional_vars.id, n.lineno, n.end_lineno))
        self.generic_visit(n)
    visit_AsyncWith = visit_With


def used_after_with(src):
    """`with ...connect() as x:` bloğundan sonra, araya yeni atama girmeden x'i kullanan satırlar."""
    tree = ast.parse(src)
    out = []
    for fn in [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        v = _Scope()
        for st in fn.body:
            v.visit(st)
        for name, start, end in v.withs:
            for ln, line in v.loads:
                if ln == name and line > end and max([b for b in v.binds.get(name, []) if b <= line] + [0]) == start:
                    out.append((start, line))
    return out


def main():
    # 1) tarayıcının kendisi: bilinen hatalı ve doğru örnekler
    bad = 'def f():\n    with db.connect() as conn:\n        pass\n    return conn.execute("x")\n'
    good = 'def f():\n    with db.connect() as conn:\n        pass\n    with db.connect() as conn:\n        return conn.execute("x")\n'
    assert used_after_with(bad) == [(2, 4)] and used_after_with(good) == [], (used_after_with(bad), used_after_with(good))
    # 2) uygulamada bloktan sonra bağlantı kullanan yer yok
    found = [f'{p.relative_to(ROOT.parent)}:{a}→{b}' for p in sorted(ROOT.rglob('*.py'))
             for a, b in used_after_with(p.read_text(encoding='utf-8'))]
    assert not found, found
    # 3) çalışma anı: blok bitince kapanır, çöp toplayıcı beklenmez; commit ve rollback korunur
    db.init()
    gc.collect()
    gc.disable()
    try:
        base = db.leak_report(min_age=0)[0]
        for _ in range(50):
            with db.connect() as conn:
                conn.execute('SELECT 1').fetchone()
        assert db.leak_report(min_age=0)[0] == base, db.leak_report(min_age=0)
        try:
            conn.execute('SELECT 1')
            raise AssertionError('blok sonrası bağlantı açık kaldı')
        except sqlite3.ProgrammingError:
            pass
        with db.connect() as conn:
            conn.execute("INSERT INTO app_kv (k, v) VALUES ('sizinti-test', '1')")
        try:
            with db.connect() as conn:
                conn.execute("INSERT INTO app_kv (k, v) VALUES ('sizinti-geri', '1')")
                raise RuntimeError('geri al')
        except RuntimeError:
            pass
        with db.connect() as conn:
            ks = {r[0] for r in conn.execute("SELECT k FROM app_kv WHERE k LIKE 'sizinti-%'")}
        assert ks == {'sizinti-test'}, ks
        # get_db (istek bağımlılığı) da kapatır
        g = db.get_db()
        c = next(g)
        try:
            next(g)
        except StopIteration:
            pass
        assert db.leak_report(min_age=0)[0] == base
        # açıkça bırakılan bağlantı raporda kod yeriyle görünür
        keep = db.connect()
        total, old, sites = db.leak_report(min_age=0)
        assert total == base + 1 and sites, sites
        keep.close()
        del c
    finally:
        gc.enable()
    print('Bağlantı sızıntısı testleri geçti.')


if __name__ == '__main__':
    main()
