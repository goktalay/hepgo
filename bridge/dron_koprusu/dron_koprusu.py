"""Hepgo Dron Köprüsü — masaüstü uygulaması (Windows; Linux/macOS'ta da çalışır).

Kullanım: HEPGO › Saha Yönetimi › Dron Yönetimi › Dron Köprüleri'nde köprü ekleyin, verilen köprü kodunu
('caymaz.app/…') bu uygulamaya yapıştırıp "Başlat"a basın. Köprü sunucuya bağlanır; dron bağlantısı
(seri / UDP / TCP) ya buradan elle ya da HEPGO Canlı Uçuş'taki "Bağlan" düğmesiyle (uçuşta seçilen ayarlarla) açılır.

Komut satırı (arayüzsüz):  dron_koprusu --code caymaz.app/KEY [--link udp:0.0.0.0:14550 | --link serial:COM3:57600 | --link tcp:127.0.0.1:5760]
"""
import argparse
import asyncio
import base64
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

from kopru_core import APP_NAME, VERSION, Bridge, parse_code


# ---------------- ayar dosyası (kod Windows'ta DPAPI ile şifreli) ----------------
def _cfg_path():
    base = os.environ.get('APPDATA') or os.path.join(Path.home(), '.config')
    d = Path(base) / 'HepgoDronKoprusu'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'ayarlar.json'


def _dpapi(data, encrypt):
    if sys.platform != 'win32':
        return data
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    src = BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError('DPAPI hatası')
    res = ctypes.string_at(out.pbData, out.cbData)
    ctypes.windll.kernel32.LocalFree(out.pbData)
    return res


def load_cfg():
    try:
        c = json.loads(_cfg_path().read_text(encoding='utf-8'))
        if c.get('code_enc'):
            c['code'] = _dpapi(base64.b64decode(c['code_enc']), False).decode()
        return c
    except Exception:   # noqa: BLE001
        return {}


def save_cfg(c):
    c = dict(c)
    if c.get('code'):
        c['code_enc'] = base64.b64encode(_dpapi(c.pop('code').encode(), True)).decode()
    _cfg_path().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding='utf-8')


def parse_link(s):
    """'udp:0.0.0.0:14550' / 'serial:COM3:57600' / 'tcp:127.0.0.1:5760' → spec."""
    if not s:
        return None
    parts = s.split(':')
    t = parts[0].lower()
    if t == 'serial':
        return {'type': 'serial', 'serial': ':'.join(parts[1:-1]) if len(parts) > 2 else parts[1], 'baud': int(parts[-1]) if len(parts) > 2 else 57600}
    return {'type': t, 'host': parts[1] if len(parts) > 1 else '0.0.0.0', 'port': int(parts[2]) if len(parts) > 2 else (14550 if t == 'udp' else 5760)}


# ---------------- arayüzsüz ----------------
def run_cli(code, link):
    bridge = Bridge(code, ui=lambda ev, *a: print(time.strftime('%H:%M:%S'), ev, *a, flush=True), link_spec=parse_link(link))
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        bridge.stop()


# ---------------- arayüz (tkinter) ----------------
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    cfg = load_cfg()
    events = queue.Queue()
    state = {'bridge': None, 'thread': None}

    root = tk.Tk()
    root.title(f'{APP_NAME} {VERSION}')
    root.geometry('620x560')
    root.minsize(520, 460)
    try:
        ico = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'kopru.ico'
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:   # noqa: BLE001
        pass
    style = ttk.Style()
    try:
        style.theme_use('vista' if sys.platform == 'win32' else 'clam')
    except Exception:   # noqa: BLE001
        pass
    pad = {'padx': 10, 'pady': 4}

    # Köprü kodu
    f1 = ttk.LabelFrame(root, text=' Köprü kodu ')
    f1.pack(fill='x', **pad)
    code_var = tk.StringVar(value=cfg.get('code', ''))
    code_ent = ttk.Entry(f1, textvariable=code_var, show='•')
    code_ent.pack(side='left', fill='x', expand=True, padx=8, pady=8)
    show_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(f1, text='Göster', variable=show_var, command=lambda: code_ent.config(show='' if show_var.get() else '•')).pack(side='left')
    start_btn = ttk.Button(f1, text='Başlat')
    start_btn.pack(side='left', padx=8)
    ttk.Label(root, text="HEPGO › Saha Yönetimi › Dron Yönetimi › Dron Köprüleri'nde köprü ekleyince verilen kodu yapıştırın.",
              foreground='#667').pack(anchor='w', padx=12)

    # Durum
    f2 = ttk.LabelFrame(root, text=' Durum ')
    f2.pack(fill='x', **pad)
    srv_var, link_var, stat_var = tk.StringVar(value='Sunucu: bağlı değil'), tk.StringVar(value='Dron: bağlantı yok'), tk.StringVar(value='')
    srv_lbl = ttk.Label(f2, textvariable=srv_var)
    srv_lbl.pack(anchor='w', padx=8, pady=(6, 0))
    ttk.Label(f2, textvariable=link_var).pack(anchor='w', padx=8)
    ttk.Label(f2, textvariable=stat_var, foreground='#667').pack(anchor='w', padx=8, pady=(0, 6))

    # Dron bağlantısı (elle)
    f3 = ttk.LabelFrame(root, text=' Dron bağlantısı (elle; HEPGO Canlı Uçuş › Bağlan da kullanılabilir) ')
    f3.pack(fill='x', **pad)
    lk = cfg.get('link') or {'type': 'udp', 'host': '0.0.0.0', 'port': 14550}
    type_var = tk.StringVar(value={'udp': 'UDP', 'tcp': 'TCP', 'serial': 'Seri'}[lk.get('type', 'udp')])
    host_var, port_var = tk.StringVar(value=lk.get('host', '0.0.0.0')), tk.StringVar(value=str(lk.get('port', 14550)))
    ser_var, baud_var = tk.StringVar(value=lk.get('serial', '')), tk.StringVar(value=str(lk.get('baud', 57600)))
    sysid_var = tk.StringVar(value=str(lk.get('sysid') or ''))
    row = ttk.Frame(f3)
    row.pack(fill='x', padx=8, pady=6)
    ttk.Combobox(row, textvariable=type_var, values=['UDP', 'TCP', 'Seri'], width=6, state='readonly').pack(side='left')
    net = ttk.Frame(row)
    ttk.Label(net, text=' Adres').pack(side='left')
    ttk.Entry(net, textvariable=host_var, width=16).pack(side='left', padx=4)
    ttk.Label(net, text='Port').pack(side='left')
    ttk.Entry(net, textvariable=port_var, width=7).pack(side='left', padx=4)
    ser = ttk.Frame(row)
    ttk.Label(ser, text=' Port').pack(side='left')
    ser_cb = ttk.Combobox(ser, textvariable=ser_var, width=14)
    ser_cb.pack(side='left', padx=4)
    ttk.Label(ser, text='Baud').pack(side='left')
    ttk.Combobox(ser, textvariable=baud_var, values=['57600', '115200', '921600', '38400'], width=8).pack(side='left', padx=4)

    def ports():
        try:
            from serial.tools import list_ports
            ser_cb['values'] = [p.device for p in list_ports.comports()]
        except Exception:   # noqa: BLE001
            ser_cb['values'] = []
    ttk.Button(ser, text='↻', width=3, command=ports).pack(side='left')
    ttk.Label(row, text=' sysid').pack(side='left')
    ttk.Entry(row, textvariable=sysid_var, width=4).pack(side='left', padx=4)

    def show_kind(*_):
        net.pack_forget(); ser.pack_forget()
        (ser if type_var.get() == 'Seri' else net).pack(side='left', after=row.winfo_children()[0])
        if type_var.get() == 'Seri':
            ports()
    type_var.trace_add('write', show_kind)
    show_kind()
    row2 = ttk.Frame(f3)
    row2.pack(fill='x', padx=8, pady=(0, 8))
    link_btn = ttk.Button(row2, text='Drona bağlan')
    link_btn.pack(side='left')
    unlink_btn = ttk.Button(row2, text='Bağlantıyı kes')
    unlink_btn.pack(side='left', padx=6)
    log_btn = ttk.Button(row2, text='Uçuş logu gönder (.bin)…')
    log_btn.pack(side='right')

    # Günlük
    f4 = ttk.LabelFrame(root, text=' Günlük ')
    f4.pack(fill='both', expand=True, **pad)
    logbox = tk.Text(f4, height=10, state='disabled', font=('Consolas', 9) if sys.platform == 'win32' else ('monospace', 9))
    logbox.pack(fill='both', expand=True, padx=6, pady=6)

    def log(s):
        logbox.configure(state='normal')
        logbox.insert('end', f"{time.strftime('%H:%M:%S')}  {s}\n")
        if int(logbox.index('end-1c').split('.')[0]) > 500:
            logbox.delete('1.0', '50.0')
        logbox.see('end')
        logbox.configure(state='disabled')

    def link_spec():
        t = {'UDP': 'udp', 'TCP': 'tcp', 'Seri': 'serial'}[type_var.get()]
        s = {'type': t}
        if t == 'serial':
            s.update(serial=ser_var.get().strip(), baud=int(baud_var.get() or 57600))
        else:
            s.update(host=host_var.get().strip() or '0.0.0.0', port=int(port_var.get() or (14550 if t == 'udp' else 5760)))
        if sysid_var.get().strip():
            s['sysid'] = int(sysid_var.get())
        return s

    def ui(ev, *a):
        events.put((ev, a))

    def start():
        b = state['bridge']
        if b is not None:
            b.stop()
            state['bridge'] = None
            start_btn.config(text='Başlat')
            srv_var.set('Sunucu: durduruldu')
            return
        try:
            parse_code(code_var.get())
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        cfg['code'] = code_var.get().strip()
        save_cfg(cfg)
        bridge = Bridge(cfg['code'], ui=ui)
        state['bridge'] = bridge
        start_btn.config(text='Durdur')

        def runner():
            asyncio.run(bridge.run())
            ui('ended')
        state['thread'] = threading.Thread(target=runner, daemon=True)
        state['thread'].start()

    def do_link():
        b = state['bridge']
        if b is None:
            messagebox.showinfo(APP_NAME, 'Önce köprüyü başlatın')
            return
        try:
            spec = link_spec()
        except ValueError:
            messagebox.showerror(APP_NAME, 'Port/baud/sysid sayı olmalı')
            return
        cfg['link'] = spec
        save_cfg({**cfg})
        b.open_link_threadsafe(spec)

    def do_unlink():
        if state['bridge']:
            state['bridge'].close_link_threadsafe()

    def do_log():
        b = state['bridge']
        if b is None:
            return
        p = filedialog.askopenfilename(title='Uçuş logu', filetypes=[('ArduPilot log', '*.bin *.BIN *.log *.LOG')])
        if not p:
            return
        fut = b.send_log_threadsafe(p)

        def done(f):
            try:
                ui('log', f'Log tamam (#{f.result()})')
            except Exception as e:   # noqa: BLE001
                ui('log', f'Log gönderilemedi: {e}')
        fut.add_done_callback(done)

    start_btn.config(command=start)
    link_btn.config(command=do_link)
    unlink_btn.config(command=do_unlink)
    log_btn.config(command=do_log)

    def pump():
        while True:
            try:
                ev, a = events.get_nowait()
            except queue.Empty:
                break
            if ev == 'server':
                st, detail = a
                text = {'connecting': 'bağlanıyor…', 'connected': 'BAĞLI', 'retry': 'koptu, yeniden deneniyor', 'fatal': 'HATA', 'stopped': 'durdu'}.get(st, st)
                srv_var.set(f'Sunucu: {text} — {detail}' if detail else f'Sunucu: {text}')
                srv_lbl.config(foreground={'connected': '#1a7f37', 'fatal': '#c62828', 'retry': '#b26a00'}.get(st, ''))
                log(f'Sunucu {text}: {detail}')
                if st == 'fatal':
                    messagebox.showerror(APP_NAME, detail)
            elif ev == 'link':
                st, detail = a
                link_var.set(f"Dron: {({'open': 'BAĞLI', 'closed': 'bağlantı yok', 'lost': 'BAĞLANTI KOPTU', 'error': 'HATA'}).get(st, st)} — {detail}")
                log(f'Dron bağlantısı {st}: {detail}')
            elif ev == 'stats':
                s = a[0]
                age = time.time() - (s.get('last_rx') or 0)
                stat_var.set(f"Dron sysid: {s.get('drone') or '—'} · alınan çerçeve: {s.get('rx')} · gönderilen paket: {s.get('tx')}"
                             + (f' · son veri {int(age)} sn önce' if s.get('last_rx') else ''))
            elif ev == 'log':
                log(a[0])
            elif ev == 'ended':
                start_btn.config(text='Başlat')
                state['bridge'] = None
        root.after(200, pump)

    root.after(200, pump)
    if cfg.get('code') and cfg.get('autostart', True):
        root.after(500, start)

    def on_close():
        if state['bridge']:
            state['bridge'].stop()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', on_close)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(prog='dron_koprusu', description=f'{APP_NAME} — HEPGO dron köprüsü')
    ap.add_argument('--code', help='Köprü kodu (alan-adı/anahtar); verilirse arayüzsüz çalışır')
    ap.add_argument('--link', help='Dron bağlantısı: udp:0.0.0.0:14550 | serial:COM3:57600 | tcp:127.0.0.1:5760')
    ap.add_argument('--version', action='version', version=VERSION)
    a = ap.parse_args()
    if a.code:
        run_cli(a.code, a.link)
    else:
        run_gui()


if __name__ == '__main__':
    main()
