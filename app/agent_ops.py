"""Fabrika ajanı operasyonları — ortak kayıt defteri.

Bu op'lar fabrika-yerel kaynaklara (Mikro ERP, PDKS, yazıcılar) erişir. HEM 'local' modda (merkez ve cihazlar
aynı makinede; doğrudan) HEM 'remote' modda (fabrikadaki ajan çalıştırır) aynı fonksiyonlar kullanılır.
Her op, ilgili modülün DOĞRUDAN (_..._direct) implementasyonunu çağırır — böylece yönlendirme döngüsü olmaz.

Her op: fn(args: dict) -> JSON-serileştirilebilir sonuç. Bloklayıcı olabilir (ağ/DB).
"""
import time


def _ping(args):
    return {'pong': True, 'ts': time.time()}


# --- Mikro ERP (MSSQL) ---
def _mikro_query(args):
    from . import mikro
    return mikro._query_direct(args['sql'], args.get('params'), args.get('db'))


def _mikro_ping(args):
    from . import mikro
    return mikro.ping()          # query() üstüne kurulu; ajanda yerel çalışır


def _mikro_databases(args):
    from . import mikro
    return mikro.databases()


# --- PDKS (Firebird) ---
def _pdks_personnel(args):
    from . import pdks
    return pdks._fetch_personnel_direct()


def _pdks_attendance(args):
    from . import pdks
    return pdks._daily_attendance_direct(args.get('date_from'), args.get('date_to'))


def _pdks_test(args):
    from . import pdks
    ok, msg = pdks._test_direct()
    return {'ok': ok, 'message': msg}


# --- Yazıcılar (Moonraker) ---
def _printer_probe(args):
    from . import printer_driver
    return printer_driver._probe_direct(args['ip'])


def _printer_send(args):
    from . import printer_send
    return printer_send.agent_send(args)


OPS = {
    'ping': _ping,
    'mikro.query': _mikro_query,
    'mikro.ping': _mikro_ping,
    'mikro.databases': _mikro_databases,
    'pdks.personnel': _pdks_personnel,
    'pdks.attendance': _pdks_attendance,
    'pdks.test': _pdks_test,
    'printer.probe': _printer_probe,
    'printer.send': _printer_send,
}


def register(name, fn):
    OPS[name] = fn
