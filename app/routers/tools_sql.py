"""Araçlar › SQL Master (web) — masaüstü uygulamanın ana süreci + veritabanı süreci (main.ts, store.ts, secrets.ts, history.ts,
dbhost/host.ts, core/engine, core/sql, core/providers) Python'a taşındı. Arayüz static/mt/sqlmaster (orijinal renderer esbuild ile
derlenmiş); köprü bridge.js aynı IPC adlarıyla buraya gelir.

Depo: tools_mt_store('sqlmaster','store') = { folders, connections:[ConnectionProfile], settings, syncMeta } (store.json şeması);
'secrets' = { 'conn:<id>:password': 'enc:…' } (secrets.json; Fernet); 'history' = [HistoryEntry] (history.jsonl).
Sağlayıcılar: sqlite (stdlib; dosya kullanıcının sunucudaki alanında — DATA_DIR/tools/sqlmaster/<uid>/files — ya da
'caymaz.db' = uygulamanın kendi veritabanı SALT OKUNUR), mysql (pymysql kuruluysa), postgres (psycopg kuruluysa); mssql/duckdb için
sürücü yok. SSH tüneli paramiko ile (ssh2 karşılığı). Salt okunur koruması sınıflandırıcıyla (classify) + sağlayıcı kipiyle uygulanır.
"""
import base64
import csv
import hashlib
import importlib.util
import json
import re
import secrets
import socket
import sqlite3
import threading
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config
from .tools_common import check_host, check_port, new_tmp, safe_name, tmp_path, tools_user
from . import tools_common as tc
from . import tools_mt as mt

router = APIRouter(prefix='/api/tools/sql')
APP = 'sqlmaster'
LANGS = (None, 'tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru')
DEFAULT_LIMIT, DEFAULT_BATCH = 10_000, 500
SESSION_IDLE = 3600
MAX_HISTORY, MAX_SQL = 5000, 20_000
# mtweb kancaları (HEPGO'da varsayılanlar → davranış değişmez)
APP_DB_READONLY = True    # False → 'caymaz.db' istisnası kapalı (ad, kullanıcının dosya alanındaki sıradan bir dosyadır)
ALLOW_SSH_AGENT = True    # False → SSH tünelinde ajan kimlik doğrulaması reddedilir
SQLITE_GUARD = None       # callable(SqliteConn, uid) → bağlantı açılınca (yetkilendirici, sayfa tavanı, süre sınırı)
EXPORT_MAX = None         # dışa aktarma dosyası bayt tavanı
ROW_LIMIT_MAX = None      # sorgu başına satır tavanı
PUBLIC_PATH = None        # callable(str) → str; arayüze giden SQLite dosya yolu (sunucu yolu gizlenir)

try:
    import paramiko
except ImportError:   # pragma: no cover
    paramiko = None

DRIVERS = {
    'sqlite': True,
    'mysql': importlib.util.find_spec('pymysql') is not None,
    'postgres': importlib.util.find_spec('psycopg') is not None,
    'mssql': False,
    'duckdb': False,
}
# shared/providers.ts PROVIDERS ile aynı
PROVIDERS = [
    {'id': 'postgres', 'name': 'PostgreSQL', 'short': 'PG', 'kind': 'server', 'dialect': 'postgres', 'defaultPort': 5432, 'defaultUser': 'postgres', 'color': '#3b82f6'},
    {'id': 'mssql', 'name': 'SQL Server', 'short': 'MSSQL', 'kind': 'server', 'dialect': 'mssql', 'defaultPort': 1433, 'defaultUser': 'sa', 'color': '#ef4444'},
    {'id': 'mysql', 'name': 'MySQL / MariaDB', 'short': 'MySQL', 'kind': 'server', 'dialect': 'mysql', 'defaultPort': 3306, 'defaultUser': 'root', 'color': '#f97316'},
    {'id': 'sqlite', 'name': 'SQLite', 'short': 'SQLite', 'kind': 'file', 'dialect': 'sqlite', 'color': '#22d3ee', 'fileExtensions': ['db', 'sqlite', 'sqlite3', 'db3']},
    {'id': 'duckdb', 'name': 'DuckDB / Dosyalar (CSV, Parquet, JSON, Excel)', 'short': 'DuckDB', 'kind': 'file', 'dialect': 'duckdb', 'color': '#fbbf24',
     'fileExtensions': ['duckdb', 'db', 'csv', 'parquet', 'json', 'xlsx']},
]
PROVIDER_IDS = [p['id'] for p in PROVIDERS]
SSL_MODES = ['disable', 'prefer', 'require', 'verify-full']
DEFAULT_SETTINGS = {'appTheme': 'system', 'language': None, 'rowLimit': 10_000, 'previewRows': 100, 'editorFontSize': 13, 'treeWidth': 300,
                    'openAtLogin': False, 'minimizeToTray': False, 'closeToTray': False}


def provider_meta(pid):
    return next((p for p in PROVIDERS if p['id'] == pid), PROVIDERS[0])


def _one(v, lst, d):
    return v if v in lst else d


def _str(v, mx=500):
    return str(v if v is not None else '').strip()[:mx]


def _num(v, lo, hi):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return int(round(n)) if lo <= n <= hi else None


# =============================================================================================================
# Depo (store.ts) · gizli bilgiler (secrets.ts) · geçmiş (history.ts)
# =============================================================================================================
def load_store(uid):
    raw = mt.kv_get(uid, APP, 'store') or {}
    s = {'folders': [], 'connections': [], 'settings': {}, 'syncMeta': {}, **raw}
    s['settings'] = {**DEFAULT_SETTINGS, **(raw.get('settings') or {})}
    return s


def save_store(uid, s):
    mt.kv_set(uid, APP, 'store', s)


class Secrets:
    """conn:<id>:password → şifreli değer (Fernet). Referans adları secretRef ile aynı."""

    def __init__(self, uid):
        self.uid = uid
        self.data = mt.kv_get(uid, APP, 'secrets') or {}

    def get(self, ref):
        return mt.unprotect(self.data.get(ref, ''))

    def has(self, ref):
        return bool(self.data.get(ref))

    def set(self, ref, value):
        if not value:
            return self.delete(ref)
        self.data[ref] = mt.protect(value)
        self.save()

    def delete(self, ref):
        if ref in self.data:
            del self.data[ref]
            self.save()

    def delete_prefix(self, prefix):
        keys = [k for k in self.data if k.startswith(prefix)]
        for k in keys:
            del self.data[k]
        if keys:
            self.save()

    def save(self):
        mt.kv_set(self.uid, APP, 'secrets', self.data)


ref_password = lambda cid: f'conn:{cid}:password'            # noqa: E731
ref_ssh_password = lambda cid: f'conn:{cid}:sshPassword'     # noqa: E731
ref_ssh_passphrase = lambda cid: f'conn:{cid}:sshPassphrase'  # noqa: E731


def public_conn(sec, c):
    return {**c, 'hasPassword': sec.has(ref_password(c['id'])), 'hasSshPassword': sec.has(ref_ssh_password(c['id'])),
            'hasSshPassphrase': sec.has(ref_ssh_passphrase(c['id']))}


def public_store(uid, s=None, sec=None):
    s = s or load_store(uid)
    sec = sec or Secrets(uid)
    return {'folders': s['folders'], 'settings': s['settings'], 'connections': [public_conn(sec, c) for c in s['connections']]}


def find_conn(s, cid):
    return next((c for c in s['connections'] if c['id'] == cid), None)


def normalize(form, s, existing=None):
    """Form verisini doğrulayıp profile çevirir (store.ts normalize)."""
    provider = _one(form.get('provider'), PROVIDER_IDS, 'postgres')
    ssh = form.get('ssh') or {}
    ssh_host, ssh_port = _str(ssh.get('host'), 255), _num(ssh.get('port'), 1, 65535) or 22
    same_ssh = existing and existing['ssh'].get('host') == ssh_host and existing['ssh'].get('port') == ssh_port
    file_path = _str(form.get('filePath'), 1000)
    return {
        'id': existing['id'] if existing else mt.uid8(),
        'createdAt': existing['createdAt'] if existing else mt.now_ms(),
        'lastUsedAt': existing.get('lastUsedAt') if existing else None,
        'name': _str(form.get('name'), 120) or _str(form.get('host'), 120) or Path(file_path).name or provider,
        'provider': provider,
        'host': _str(form.get('host'), 255),
        'port': _num(form.get('port'), 1, 65535),
        'database': _str(form.get('database'), 255),
        'user': _str(form.get('user'), 255),
        'filePath': file_path,
        'sslMode': _one(form.get('sslMode'), SSL_MODES, 'prefer'),
        'readOnly': form.get('readOnly') is not False,
        'savePassword': form.get('savePassword') is not False,
        'color': form['color'] if re.fullmatch(r'#[0-9a-fA-F]{6}', str(form.get('color') or '')) else '#22d3ee',
        'folderId': form.get('folderId') if form.get('folderId') and any(f['id'] == form['folderId'] for f in s['folders']) else None,
        'comments': _str(form.get('comments'), 2000),
        'ssh': {'enabled': bool(ssh.get('enabled')), 'host': ssh_host, 'port': ssh_port, 'user': _str(ssh.get('user'), 255),
                'auth': _one(ssh.get('auth'), ['key', 'password', 'agent'], 'key'), 'keyPath': _str(ssh.get('keyPath'), 1000),
                'hostKey': existing['ssh'].get('hostKey') if same_ssh else None},
    }


def history_add(uid, entry):
    h = mt.kv_get(uid, APP, 'history') or []
    h.append({**entry, 'sql': redact(entry['sql'])[:MAX_SQL]})
    if len(h) > MAX_HISTORY * 1.5:
        h = h[-MAX_HISTORY:]
    mt.kv_set(uid, APP, 'history', h)


def history_list(uid, cid, limit=200):
    h = mt.kv_get(uid, APP, 'history') or []
    return [e for e in reversed(h) if e.get('connectionId') == cid][:limit]


def redact(sql):
    return re.sub(r"(password|pwd|passwd|secret|token)(\s*[=:]\s*)('[^']*'|\"[^\"]*\"|\S+)", r'\1\2***', sql, flags=re.I)


# =============================================================================================================
# SQL metin işleme: lexer.ts · split.ts · classify.ts
# =============================================================================================================
WORD_START = re.compile(r'[A-Za-z_\u0080-￿]')
WORD_CHAR = re.compile(r'[A-Za-z0-9_$\u0080-￿]')


def tokenize(sql, d):
    out = []
    n = len(sql)
    i = 0

    def push(kind, a, b):
        t = {'kind': kind, 'start': a, 'end': b}
        if kind == 'word':
            t['upper'] = sql[a:b].upper()
        out.append(t)

    def quoted(start, close, backslash):
        j = start + 1
        while j < n:
            c = sql[j]
            if backslash and c == '\\':
                j += 2
                continue
            if c == close:
                if j + 1 < n and sql[j + 1] == close:
                    j += 2
                    continue
                return j + 1
            j += 1
        return n

    while i < n:
        c = sql[i]
        c2 = sql[i + 1] if i + 1 < n else ''
        if c in ' \t\n\r\f':
            j = i + 1
            while j < n and sql[j].isspace():
                j += 1
            push('ws', i, j); i = j; continue
        if (c == '-' and c2 == '-') or (c == '#' and d == 'mysql'):
            j = i + 1
            while j < n and sql[j] != '\n':
                j += 1
            push('comment', i, j); i = j; continue
        if c == '/' and c2 == '*':
            nested = d in ('postgres', 'duckdb')
            depth, j = 1, i + 2
            while j < n and depth > 0:
                if sql.startswith('*/', j):
                    depth -= 1; j += 2; continue
                if nested and sql.startswith('/*', j):
                    depth += 1; j += 2; continue
                j += 1
            push('comment', i, j); i = j; continue
        if c in 'Ee' and c2 == "'" and d in ('postgres', 'duckdb'):
            j = quoted(i + 1, "'", True); push('string', i, j); i = j; continue
        if c in 'Nn' and c2 == "'" and d == 'mssql':
            j = quoted(i + 1, "'", False); push('string', i, j); i = j; continue
        if c == "'":
            j = quoted(i, "'", d == 'mysql'); push('string', i, j); i = j; continue
        if c == '"':
            j = quoted(i, '"', d == 'mysql'); push('string' if d == 'mysql' else 'qident', i, j); i = j; continue
        if c == '`' and d in ('mysql', 'sqlite'):
            j = quoted(i, '`', False); push('qident', i, j); i = j; continue
        if c == '[' and d in ('mssql', 'sqlite'):
            j = quoted(i, ']', False); push('qident', i, j); i = j; continue
        if c == '$' and d in ('postgres', 'duckdb'):
            if c2.isdigit():
                j = i + 1
                while j < n and sql[j].isdigit():
                    j += 1
                push('param', i, j); i = j; continue
            m = re.match(r'\$([A-Za-z_][A-Za-z0-9_]*)?\$', sql[i:i + 64])
            if m:
                tag = m.group(0)
                close = sql.find(tag, i + len(tag))
                j = n if close < 0 else close + len(tag)
                push('string', i, j); i = j; continue
        if WORD_START.match(c):
            j = i + 1
            while j < n and WORD_CHAR.match(sql[j]):
                j += 1
            push('word', i, j); i = j; continue
        if c.isdigit() or (c == '.' and c2.isdigit()):
            j = i + 1
            while j < n and re.match(r'[0-9.eE_xXa-fA-F]', sql[j]):
                j += 1
            push('number', i, j); i = j; continue
        if (c == '@' and d in ('mssql', 'mysql')) or (c in ':?' and d == 'sqlite'):
            j = i + 1
            while j < n and (WORD_CHAR.match(sql[j]) or sql[j] == '@'):
                j += 1
            push('param', i, j); i = j; continue
        push('punct', i, i + 1)
        i += 1
    return out


BLOCK_CREATE = {'PROCEDURE', 'FUNCTION', 'TRIGGER', 'EVENT', 'PACKAGE'}
NOT_BLOCK_AFTER_BEGIN = {'TRANSACTION', 'WORK', 'DEFERRED', 'IMMEDIATE', 'EXCLUSIVE', 'TRAN', 'DISTRIBUTED'}


def _push_statement(out, sql, start, end, tokens, frm, to):
    if not any(t['kind'] not in ('ws', 'comment') for t in tokens[frm:to]):
        return
    while start < end and sql[start].isspace():
        start += 1
    while end > start and sql[end - 1].isspace():
        end -= 1
    out.append({'text': sql[start:end], 'start': start, 'end': end})


def split_statements(sql, d):
    """Betiği çalıştırılabilir ifadelere böler (split.ts): ';' (tırnak/yorum/$$ gövde/BEGIN…END hariç), MySQL DELIMITER, MSSQL GO."""
    tokens = tokenize(sql, d)
    out = []
    if d == 'mssql':
        seg_start = seg_tok = 0
        k = 0
        while k < len(tokens):
            t = tokens[k]
            if t['kind'] == 'word' and t['upper'] == 'GO':
                line_start = sql.rfind('\n', 0, t['start']) + 1
                line_end = sql.find('\n', t['end'])
                line_end = len(sql) if line_end < 0 else line_end
                before, after = sql[line_start:t['start']], re.sub(r'--.*$', '', sql[t['end']:line_end])
                if re.fullmatch(r'\s*', before) and re.fullmatch(r'\s*(\d+)?\s*;?\s*', after):
                    _push_statement(out, sql, seg_start, line_start, tokens, seg_tok, k)
                    seg_start = line_end
                    while k + 1 < len(tokens) and tokens[k + 1]['start'] < line_end:
                        k += 1
                    seg_tok = k + 1
            k += 1
        _push_statement(out, sql, seg_start, len(sql), tokens, seg_tok, len(tokens))
        return out
    delimiter = ';'
    seg_start = seg_tok = 0
    words, block_depth, is_block_create = [], 0, False

    def next_word(k):
        for j in range(k + 1, len(tokens)):
            t = tokens[j]
            if t['kind'] in ('ws', 'comment'):
                continue
            return t['upper'] if t['kind'] == 'word' else sql[t['start']:t['end']]
        return None

    k = 0
    while k < len(tokens):
        t = tokens[k]
        if t['kind'] in ('ws', 'comment', 'string', 'qident'):
            k += 1
            continue
        if d == 'mysql' and t['kind'] == 'word' and t['upper'] == 'DELIMITER' and not words:
            line_start = sql.rfind('\n', 0, t['start']) + 1
            if re.fullmatch(r'\s*', sql[line_start:t['start']]):
                line_end = sql.find('\n', t['end'])
                line_end = len(sql) if line_end < 0 else line_end
                delim = sql[t['end']:line_end].strip()
                if delim:
                    delimiter = delim
                j = k
                while j + 1 < len(tokens) and tokens[j + 1]['start'] < line_end:
                    j += 1
                seg_start, seg_tok, words, block_depth, is_block_create = line_end, j + 1, [], 0, False
                k = j + 1
                continue
        if t['kind'] == 'word':
            w = t['upper']
            if len(words) < 8:
                words.append(w)
                if words[0] == 'CREATE' and w in BLOCK_CREATE:
                    is_block_create = True
            if is_block_create and delimiter == ';':
                if w == 'BEGIN':
                    nw = next_word(k)
                    if not (nw and (nw in NOT_BLOCK_AFTER_BEGIN or nw == ';')):
                        block_depth += 1
                elif w == 'CASE' and block_depth > 0:
                    block_depth += 1
                elif w == 'END' and block_depth > 0:
                    nw = next_word(k)
                    if not (nw and nw in ('IF', 'LOOP', 'WHILE', 'REPEAT', 'FOR')):
                        block_depth -= 1
            k += 1
            continue
        if delimiter == ';':
            if t['kind'] == 'punct' and sql[t['start']] == ';' and block_depth == 0:
                _push_statement(out, sql, seg_start, t['start'], tokens, seg_tok, k)
                seg_start, seg_tok, words, block_depth, is_block_create = t['end'], k + 1, [], 0, False
        elif sql.startswith(delimiter, t['start']):
            end_pos = t['start'] + len(delimiter)
            _push_statement(out, sql, seg_start, t['start'], tokens, seg_tok, k)
            j = k
            while j + 1 < len(tokens) and tokens[j + 1]['start'] < end_pos:
                j += 1
            seg_start, seg_tok, words, block_depth, is_block_create = end_pos, j + 1, [], 0, False
            k = j
        k += 1
    _push_statement(out, sql, seg_start, len(sql), tokens, seg_tok, len(tokens))
    return out


READ_FIRST = {'SELECT', 'SHOW', 'DESCRIBE', 'DESC', 'VALUES', 'TABLE', 'SUMMARIZE', 'FROM', 'PRINT', 'HELP', 'CHECKSUM'}
SESSION_FIRST = {'USE', 'BEGIN', 'START', 'COMMIT', 'ROLLBACK', 'END', 'SAVEPOINT', 'RELEASE', 'DECLARE', 'SET', 'RESET', 'DISCARD', 'FETCH', 'CLOSE',
                 'DEALLOCATE', 'PREPARE', 'LISTEN', 'UNLISTEN', 'ABORT'}
DML_IN_CTE = {'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'UPSERT'}
MSSQL_STRONG = {'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE', 'EXEC', 'EXECUTE', 'GRANT', 'REVOKE', 'DENY', 'BACKUP',
                'RESTORE', 'DBCC', 'BULK', 'RECONFIGURE', 'SHUTDOWN', 'KILL', 'ENABLE', 'DISABLE'}
EXPLAIN_OPTS = {'ANALYZE', 'ANALYSE', 'VERBOSE', 'COSTS', 'BUFFERS', 'FORMAT', 'TIMING', 'SUMMARY', 'SETTINGS', 'WAL', 'JSON', 'TEXT', 'XML', 'YAML', 'TRUE',
                'FALSE', 'ON', 'OFF', 'QUERY', 'PLAN', 'GENERIC_PLAN', 'MEMORY', 'SERIALIZE'}


def classify(sql, d):
    """read · session · write — bilinmeyen her şey write (classify.ts)."""
    toks = [t for t in tokenize(sql, d) if t['kind'] not in ('ws', 'comment')]
    ws, puncts, depth = [], [], 0
    for t in toks:
        if t['kind'] == 'punct':
            ch = sql[t['start']]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
            puncts.append((ch, depth))
        elif t['kind'] == 'word':
            ws.append((t['upper'], depth))
    if not ws:
        return {'kind': 'read', 'keyword': ''}
    first = ws[0][0]
    uppers = [w for w, _ in ws]
    has = lambda w: w in uppers   # noqa: E731
    has_seq = lambda a, b: any(uppers[i] == a and i + 1 < len(uppers) and uppers[i + 1] == b for i in range(len(uppers)))   # noqa: E731

    def select_into():
        idx = next((i for i, (w, dp) in enumerate(ws) if w == 'INTO' and dp == 0), -1)
        if idx < 0 or 'SELECT' not in uppers[:idx]:
            return False
        if d == 'mysql':
            return idx + 1 < len(uppers) and uppers[idx + 1] in ('OUTFILE', 'DUMPFILE')
        return True

    def select_like(kw):
        if select_into():
            return {'kind': 'write', 'keyword': 'SELECT INTO'}
        for i, w in enumerate(uppers):
            if w == 'FOR' and i + 1 < len(uppers) and uppers[i + 1] in ('UPDATE', 'SHARE', 'NO', 'KEY'):
                return {'kind': 'write', 'keyword': 'FOR UPDATE'}
        if d == 'mysql' and has_seq('LOCK', 'IN'):
            return {'kind': 'write', 'keyword': 'LOCK IN SHARE MODE'}
        return {'kind': 'read', 'keyword': kw}

    if d == 'mssql':
        for i, w in enumerate(uppers):
            if w in MSSQL_STRONG and not (w == 'UPDATE' and i > 0 and uppers[i - 1] == 'FOR'):
                return {'kind': 'write', 'keyword': w}
        if select_into():
            return {'kind': 'write', 'keyword': 'INTO'}
    if first == 'WITH':
        dml = next((w for w in uppers if w in DML_IN_CTE), None)
        return {'kind': 'write', 'keyword': dml} if dml else select_like('WITH')
    if first in ('SELECT', 'FROM', 'TABLE', 'VALUES'):
        return select_like(first)
    if first == 'EXPLAIN':
        if not (has('ANALYZE') or has('ANALYSE')):
            return {'kind': 'read', 'keyword': 'EXPLAIN'}
        inner = next((w for w in uppers[1:] if w not in EXPLAIN_OPTS), None)
        if inner in ('SELECT', 'WITH', 'VALUES', 'TABLE'):
            if inner == 'WITH' and any(w in DML_IN_CTE for w in uppers):
                return {'kind': 'write', 'keyword': 'EXPLAIN ANALYZE'}
            return {'kind': 'read', 'keyword': 'EXPLAIN'}
        return {'kind': 'write', 'keyword': 'EXPLAIN ANALYZE'}
    if first == 'PRAGMA':
        writes = any(ch == '=' for ch, _ in puncts) or (len(uppers) > 1 and uppers[1] in ('OPTIMIZE', 'INCREMENTAL_VACUUM', 'WAL_CHECKPOINT', 'SHRINK_MEMORY'))
        return {'kind': 'write' if writes else 'read', 'keyword': 'PRAGMA'}
    if first == 'COPY':
        return {'kind': 'read' if has_seq('TO', 'STDOUT') else 'write', 'keyword': 'COPY'}
    if first in READ_FIRST:
        return {'kind': 'read', 'keyword': first}
    if first in SESSION_FIRST:
        if has('WRITE') or has('DEFAULT_TRANSACTION_READ_ONLY') or has('TRANSACTION_READ_ONLY'):
            return {'kind': 'write', 'keyword': f'{first} … READ WRITE'}
        if first == 'SET' and (has('GLOBAL') or has('PERSIST') or has('PERSIST_ONLY') or (d == 'mysql' and has('PASSWORD'))):
            return {'kind': 'write', 'keyword': 'SET GLOBAL'}
        return {'kind': 'session', 'keyword': first}
    return {'kind': 'write', 'keyword': first}


def qualified(name, d):
    if d == 'mysql':
        return '`' + name.replace('`', '``') + '`'
    if d == 'mssql':
        return '[' + name.replace(']', ']]') + ']'
    return '"' + name.replace('"', '""') + '"'


# =============================================================================================================
# Hücre değerleri (values.ts)
# =============================================================================================================
def to_cell(v):
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, int):
        return v if -(2 ** 53) < v < 2 ** 53 else str(v)
    if isinstance(v, float):
        return v if v == v and v not in (float('inf'), float('-inf')) else str(v)
    if isinstance(v, Decimal):
        return float(v) if abs(v) < 10 ** 15 else str(v)
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S') + (f'.{v.microsecond // 1000:03d}' if v.microsecond else '')
    if isinstance(v, (date, dtime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        s = '0x' + b[:256].hex()
        return f'{s}… ({len(b)} bayt)' if len(b) > 256 else s
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


NUMERIC_RE = re.compile(r'INT|REAL|FLOA|DOUB|NUM|DEC|BIT|SERIAL|MONEY', re.I)


# =============================================================================================================
# Sağlayıcılar (core/providers): sqlite · mysql · postgres
# =============================================================================================================
class Cancelled(Exception):
    pass


class SqliteConn:
    capabilities = {'dialect': 'sqlite', 'kind': 'file', 'databases': True, 'schemas': False, 'materializedViews': False, 'functions': False,
                    'procedures': False, 'triggers': True, 'sequences': False, 'types': False, 'indexes': True, 'cancel': 'native', 'readOnly': 'connection'}

    def __init__(self, cfg, uid):
        fp = (cfg.get('filePath') or '').strip()
        self.label = fp or ':memory:'
        self.app_db = False
        self.started = time.time()
        self.path = None
        if not fp:
            uri, ro_forced = ':memory:', False
        elif APP_DB_READONLY and fp in ('caymaz.db', Path(config.DB_PATH).name, str(config.DB_PATH)):
            # Uygulamanın kendi veritabanı yalnız salt okunur açılır
            uri, ro_forced, self.app_db = f'file:{config.DB_PATH}?mode=ro', True, True
        else:
            p = mt.resolve(mt.files_root(APP, uid), fp)
            if cfg.get('readOnly') and not p.exists():
                raise ValueError(f'Dosya bulunamadı: {fp}')
            p.parent.mkdir(parents=True, exist_ok=True)
            uri, ro_forced = str(p), False
            self.path = p
        self.db = sqlite3.connect(uri, uri=uri.startswith('file:'), check_same_thread=False, isolation_level=None, timeout=15)
        self.db.execute('PRAGMA foreign_keys = ON')
        self.read_only = bool(cfg.get('readOnly')) or ro_forced
        if self.read_only:
            self.db.execute('PRAGMA query_only = ON')
        if SQLITE_GUARD:
            SQLITE_GUARD(self, uid)

    def _all(self, sql, *params):
        cur = self.db.execute(sql, params)
        cols = [c[0] for c in cur.description or []]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def server_info(self):
        v = self.db.execute('select sqlite_version()').fetchone()[0]
        return {'product': f'SQLite {v}', 'version': v, 'database': self.label}

    def set_read_only(self, on):
        if self.app_db and not on:
            raise ValueError('Uygulamanın veritabanı yalnız salt okunur açılabilir')
        self.read_only = on
        self.db.execute(f"PRAGMA query_only = {'ON' if on else 'OFF'}")

    def query(self, sql, database, limit, batch, cancel):
        self.started = time.time()
        cur = self.db.execute(sql)
        if not cur.description:
            cmd = (re.match(r'\w+', sql.strip()) or re.match(r'', '')).group(0).upper() or 'OK'
            affected = cur.rowcount if cmd in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE') else None
            yield {'type': 'command', 'command': cmd, 'rowsAffected': affected}
            return
        cols = [{'name': c[0], 'type': '', 'numeric': False} for c in cur.description]
        yield {'type': 'columns', 'columns': cols}
        total = 0
        lim = limit if limit and limit > 0 else float('inf')
        typed = False
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            if not typed:   # kolon türünü ilk satırdan belirle (ızgara sayısalları sağa yaslar)
                typed = True
                for i, v in enumerate(rows[0]):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        cols[i]['numeric'] = True
                        cols[i]['type'] = 'INTEGER' if isinstance(v, int) else 'REAL'
                    elif isinstance(v, str):
                        cols[i]['type'] = 'TEXT'
                    elif isinstance(v, bytes):
                        cols[i]['type'] = 'BLOB'
            out = []
            for r in rows:
                if total >= lim:
                    if out:
                        yield {'type': 'rows', 'rows': out}
                    yield {'type': 'end', 'rowCount': total, 'truncated': True}
                    return
                out.append([to_cell(v) for v in r])
                total += 1
            yield {'type': 'rows', 'rows': out}
            if cancel.is_set():
                break
        yield {'type': 'end', 'rowCount': total, 'truncated': False}

    def cancel(self):
        self.db.interrupt()

    def get_children(self, parent):
        if not parent:
            dbs = [d for d in self._all('PRAGMA database_list') if d['name'] != 'temp']
            return [{'id': f"db:{d['name']}", 'kind': 'database', 'name': d['name'],
                     'detail': (PUBLIC_PATH(d['file']) if PUBLIC_PATH and d['file'] else d['file']) or None, 'hasChildren': True,
                     'path': {'database': d['name'], 'schema': d['name']}} for d in dbs]
        p = parent['path']
        schema = p.get('schema') or 'main'
        master = f"{qualified(schema, 'sqlite')}.sqlite_master"
        if parent['kind'] == 'database':
            counts = {r['type']: r['n'] for r in self._all(f"select type, count(*) n from {master} where name not like 'sqlite_%' group by type")}
            out = []
            for f in ('tables', 'views', 'triggers', 'indexes'):
                n = counts.get(f[:-1].replace('indexe', 'index'), 0)
                out.append({'id': f"{parent['id']}/f:{f}", 'kind': 'folder', 'name': f, 'count': n, 'hasChildren': n > 0,
                            'path': {'database': p.get('database'), 'schema': schema, 'folder': f}})
            return out
        if parent['kind'] == 'folder' and not p.get('table'):
            typ = {'tables': 'table', 'views': 'view', 'triggers': 'trigger', 'indexes': 'index'}.get(p.get('folder') or '', 'table')
            rows = self._all(f"select name, tbl_name tbl from {master} where type = ? and name not like 'sqlite_%' order by name", typ)
            return [{'id': f"{parent['id']}/{typ}:{r['name']}", 'kind': typ, 'name': r['name'], 'detail': r['tbl'] if typ in ('trigger', 'index') else None,
                     'hasChildren': typ in ('table', 'view'), 'openAs': 'data' if typ in ('table', 'view') else 'code',
                     'path': {'database': p.get('database'), 'schema': schema, 'name': r['name'], 'table': r['tbl'] if typ in ('trigger', 'index') else None}} for r in rows]
        if parent['kind'] in ('table', 'view'):
            folders = ['columns', 'indexes', 'triggers'] if parent['kind'] == 'table' else ['columns']
            return [{'id': f"{parent['id']}/f:{f}", 'kind': 'folder', 'name': f, 'hasChildren': True,
                     'path': {'database': p.get('database'), 'schema': schema, 'table': p.get('name'), 'folder': f}} for f in folders]
        if parent['kind'] == 'folder' and p.get('table'):
            if p.get('folder') == 'columns':
                rows = self._all('select name, type, "notnull", pk from pragma_table_info(?, ?)', p['table'], schema)
                return [{'id': f"{parent['id']}/c:{r['name']}", 'kind': 'column', 'name': r['name'],
                         'detail': f"{r['type'] or 'ANY'}{' NOT NULL' if r['notnull'] else ''}{' · PK' if r['pk'] else ''}", 'hasChildren': False,
                         'path': {'database': p.get('database'), 'schema': schema, 'table': p['table'], 'name': r['name']}} for r in rows]
            typ = 'index' if p.get('folder') == 'indexes' else 'trigger'
            rows = self._all(f"select name from {master} where type = ? and tbl_name = ? and name not like 'sqlite_%' order by name", typ, p['table'])
            return [{'id': f"{parent['id']}/{typ}:{r['name']}", 'kind': typ, 'name': r['name'], 'hasChildren': False, 'openAs': 'code',
                     'path': {'database': p.get('database'), 'schema': schema, 'table': p['table'], 'name': r['name']}} for r in rows]
        return []

    def get_object_ddl(self, node):
        schema = node['path'].get('schema') or 'main'
        master = f"{qualified(schema, 'sqlite')}.sqlite_master"
        name = node['path'].get('name') or node['name']
        rows = self._all(f'select sql from {master} where name = ?', name)
        ddl = (rows[0]['sql'] + ';') if rows and rows[0]['sql'] else ''
        if node['kind'] == 'table':
            for e in self._all(f"select sql from {master} where tbl_name = ? and type in ('index','trigger') and sql is not null order by type, name", name):
                ddl += f"\n\n{e['sql']};"
        return ddl

    def get_columns(self, p):
        rows = self._all('select name, type from pragma_table_info(?, ?)', p.get('table') or p.get('name') or '', p.get('schema') or 'main')
        return [{'name': r['name'], 'type': r['type'] or 'ANY', 'numeric': bool(NUMERIC_RE.search(r['type'] or ''))} for r in rows]

    def get_completion_schema(self, database=None):
        tables = {}
        for d in self._all('PRAGMA database_list'):
            if d['name'] == 'temp':
                continue
            rows = self._all(f"select m.name t, p.name c from {qualified(d['name'], 'sqlite')}.sqlite_master m join pragma_table_info(m.name, ?) p "
                             f"where m.type in ('table','view') and m.name not like 'sqlite_%' order by m.name, p.cid", d['name'])
            for r in rows:
                tables.setdefault(d['name'], {}).setdefault(r['t'], []).append(r['c'])
        return {'tables': tables, 'defaultSchema': 'main'}

    def close(self):
        self.db.close()


class DbApiConn:
    """DB-API ortak akış mantığı (MySQL / PostgreSQL)."""
    dialect = ''

    def _cursor(self):
        return self.cn.cursor()

    def query(self, sql, database, limit, batch, cancel):
        if database and database != self.current_db:
            self.use_database(database)
        cur = self._cursor()
        try:
            cur.execute(sql)
            if cur.description is None:
                cmd = (re.match(r'\w+', sql.strip()) or re.match(r'', '')).group(0).upper() or 'OK'
                yield {'type': 'command', 'command': cmd, 'rowsAffected': cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else None}
                self._commit()
                return
            cols = [{'name': c[0], 'type': self.type_name(c), 'numeric': self.is_numeric(c)} for c in cur.description]
            yield {'type': 'columns', 'columns': cols}
            total = 0
            lim = limit if limit and limit > 0 else float('inf')
            while True:
                rows = cur.fetchmany(batch)
                if not rows:
                    break
                out = []
                for r in rows:
                    if total >= lim:
                        if out:
                            yield {'type': 'rows', 'rows': out}
                        yield {'type': 'end', 'rowCount': total, 'truncated': True}
                        return
                    out.append([to_cell(v) for v in r])
                    total += 1
                yield {'type': 'rows', 'rows': out}
                if cancel.is_set():
                    break
            yield {'type': 'end', 'rowCount': total, 'truncated': False}
            self._commit()
        finally:
            try:
                cur.close()
            except Exception:   # noqa: BLE001
                pass

    def _commit(self):
        try:
            self.cn.commit()
        except Exception:   # noqa: BLE001
            pass

    def _rows(self, sql, params=()):
        cur = self._cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()
            self._commit()


class MysqlConn(DbApiConn):
    capabilities = {'dialect': 'mysql', 'kind': 'server', 'databases': True, 'schemas': False, 'materializedViews': False, 'functions': True,
                    'procedures': True, 'triggers': True, 'sequences': False, 'types': False, 'indexes': True, 'cancel': 'native', 'readOnly': 'session'}
    dialect = 'mysql'

    def __init__(self, cfg):
        if not DRIVERS['mysql']:
            raise ValueError('MySQL sürücüsü (pymysql) bu sunucuda kurulu değil')
        import pymysql
        self.pymysql = pymysql
        ssl_mode = (cfg.get('ssl') or {}).get('mode', 'prefer')
        kw = {'host': cfg.get('host') or 'localhost', 'port': int(cfg.get('port') or 3306), 'user': cfg.get('user') or '', 'password': cfg.get('password') or '',
              'database': cfg.get('database') or None, 'connect_timeout': 20, 'read_timeout': 600, 'charset': 'utf8mb4', 'autocommit': False, 'program_name': 'SQL Master'}
        if ssl_mode in ('require', 'verify-full'):
            kw['ssl'] = {'check_hostname': ssl_mode == 'verify-full'}
        self.hostaddr = cfg.get('hostaddr')
        self.cn = self._open({k: v for k, v in kw.items() if k != 'program_name'})
        self.current_db = cfg.get('database') or None
        self.tls = ssl_mode in ('require', 'verify-full')
        self.set_read_only(bool(cfg.get('readOnly')))

    def _open(self, kw):
        """mtweb: NET kancasının doğruladığı IP'ye soket önceden açılır (defer_connect); TLS ad doğrulaması host adıyla."""
        if not self.hostaddr:
            return self.pymysql.connect(**kw)
        cn = self.pymysql.connect(**kw, defer_connect=True)
        sock = socket.create_connection((self.hostaddr, int(kw['port'])), timeout=kw.get('connect_timeout') or 20)
        try:
            cn.connect(sock)
        except Exception:
            sock.close()
            raise
        return cn

    def type_name(self, c):
        return {0: 'DECIMAL', 1: 'TINYINT', 2: 'SMALLINT', 3: 'INT', 4: 'FLOAT', 5: 'DOUBLE', 7: 'TIMESTAMP', 8: 'BIGINT', 9: 'MEDIUMINT', 10: 'DATE', 11: 'TIME',
                12: 'DATETIME', 13: 'YEAR', 15: 'VARCHAR', 16: 'BIT', 245: 'JSON', 246: 'DECIMAL', 252: 'BLOB/TEXT', 253: 'VARCHAR', 254: 'CHAR'}.get(c[1], str(c[1]))

    def is_numeric(self, c):
        return c[1] in (0, 1, 2, 3, 4, 5, 8, 9, 16, 246)

    def server_info(self):
        v = self._rows('select version()')[0][0]
        return {'product': ('MariaDB ' if 'MariaDB' in v else 'MySQL ') + v.split('-')[0], 'version': v, 'database': self.current_db, 'user': None, 'tls': self.tls}

    def set_read_only(self, on):
        self._rows(f"SET SESSION TRANSACTION {'READ ONLY' if on else 'READ WRITE'}")

    def use_database(self, db):
        self.cn.select_db(db)
        self.current_db = db

    def cancel(self):
        try:
            k = self._open(dict(host=self.cn.host, port=self.cn.port, user=self.cn.user, password=self.cn.password.decode() if isinstance(self.cn.password, bytes) else self.cn.password,
                                connect_timeout=5))
            k.kill(self.cn.thread_id())
            k.close()
        except Exception:   # noqa: BLE001
            pass

    def get_children(self, parent):
        if not parent:
            rows = self._rows("select schema_name from information_schema.schemata where schema_name not in ('information_schema','performance_schema','sys') order by 1")
            return [{'id': f'db:{r[0]}', 'kind': 'database', 'name': r[0], 'hasChildren': True, 'path': {'database': r[0], 'schema': r[0]}} for r in rows]
        p = parent['path']
        db = p.get('database')
        if parent['kind'] == 'database':
            out = []
            for f, q in (('tables', "select count(*) from information_schema.tables where table_schema=%s and table_type='BASE TABLE'"),
                         ('views', "select count(*) from information_schema.views where table_schema=%s"),
                         ('procedures', "select count(*) from information_schema.routines where routine_schema=%s and routine_type='PROCEDURE'"),
                         ('functions', "select count(*) from information_schema.routines where routine_schema=%s and routine_type='FUNCTION'"),
                         ('triggers', "select count(*) from information_schema.triggers where trigger_schema=%s")):
                n = self._rows(q, (db,))[0][0]
                out.append({'id': f"{parent['id']}/f:{f}", 'kind': 'folder', 'name': f, 'count': n, 'hasChildren': n > 0, 'path': {'database': db, 'schema': db, 'folder': f}})
            return out
        if parent['kind'] == 'folder' and not p.get('table'):
            f = p.get('folder')
            if f in ('tables', 'views'):
                rows = self._rows("select table_name, table_rows from information_schema.tables where table_schema=%s and table_type=%s order by 1",
                                  (db, 'BASE TABLE' if f == 'tables' else 'VIEW'))
                kind = 'table' if f == 'tables' else 'view'
                return [{'id': f"{parent['id']}/{kind}:{r[0]}", 'kind': kind, 'name': r[0], 'detail': f'~{r[1]} satır' if r[1] is not None and kind == 'table' else None,
                         'hasChildren': True, 'openAs': 'data', 'path': {'database': db, 'schema': db, 'name': r[0]}} for r in rows]
            if f in ('procedures', 'functions'):
                rows = self._rows("select routine_name from information_schema.routines where routine_schema=%s and routine_type=%s order by 1", (db, f[:-1].upper()))
                kind = f[:-1]
                return [{'id': f"{parent['id']}/{kind}:{r[0]}", 'kind': kind, 'name': r[0], 'hasChildren': False, 'openAs': 'code', 'path': {'database': db, 'schema': db, 'name': r[0]}} for r in rows]
            if f == 'triggers':
                rows = self._rows("select trigger_name, event_object_table from information_schema.triggers where trigger_schema=%s order by 1", (db,))
                return [{'id': f"{parent['id']}/trigger:{r[0]}", 'kind': 'trigger', 'name': r[0], 'detail': r[1], 'hasChildren': False, 'openAs': 'code',
                         'path': {'database': db, 'schema': db, 'name': r[0], 'table': r[1]}} for r in rows]
        if parent['kind'] in ('table', 'view'):
            folders = ['columns', 'indexes', 'triggers'] if parent['kind'] == 'table' else ['columns']
            return [{'id': f"{parent['id']}/f:{f}", 'kind': 'folder', 'name': f, 'hasChildren': True, 'path': {'database': db, 'schema': db, 'table': p.get('name'), 'folder': f}} for f in folders]
        if parent['kind'] == 'folder' and p.get('table'):
            if p.get('folder') == 'columns':
                rows = self._rows("select column_name, column_type, is_nullable, column_key from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position", (db, p['table']))
                return [{'id': f"{parent['id']}/c:{r[0]}", 'kind': 'column', 'name': r[0], 'detail': f"{r[1]}{' NOT NULL' if r[2] == 'NO' else ''}{' · PK' if r[3] == 'PRI' else ''}",
                         'hasChildren': False, 'path': {'database': db, 'schema': db, 'table': p['table'], 'name': r[0]}} for r in rows]
            if p.get('folder') == 'indexes':
                rows = self._rows("select distinct index_name from information_schema.statistics where table_schema=%s and table_name=%s order by 1", (db, p['table']))
                return [{'id': f"{parent['id']}/index:{r[0]}", 'kind': 'index', 'name': r[0], 'hasChildren': False, 'openAs': 'code', 'path': {'database': db, 'schema': db, 'table': p['table'], 'name': r[0]}} for r in rows]
            rows = self._rows("select trigger_name from information_schema.triggers where trigger_schema=%s and event_object_table=%s order by 1", (db, p['table']))
            return [{'id': f"{parent['id']}/trigger:{r[0]}", 'kind': 'trigger', 'name': r[0], 'hasChildren': False, 'openAs': 'code', 'path': {'database': db, 'schema': db, 'table': p['table'], 'name': r[0]}} for r in rows]
        return []

    def get_object_ddl(self, node):
        p = node['path']
        q = lambda s: qualified(s, 'mysql')   # noqa: E731
        full = f"{q(p.get('database'))}.{q(p.get('name') or node['name'])}"
        kind = node['kind']
        if kind in ('table', 'view'):
            return self._rows(f'SHOW CREATE {kind.upper()} {full}')[0][1] + ';'
        if kind in ('procedure', 'function', 'trigger'):
            return self._rows(f'SHOW CREATE {kind.upper()} {full}')[0][2] + ';'
        if kind == 'index':
            rows = self._rows("select column_name, non_unique from information_schema.statistics where table_schema=%s and table_name=%s and index_name=%s order by seq_in_index",
                              (p.get('database'), p.get('table'), p.get('name')))
            cols = ', '.join(q(r[0]) for r in rows)
            uniq = '' if not rows or rows[0][1] else 'UNIQUE '
            return f"CREATE {uniq}INDEX {q(p.get('name'))} ON {q(p.get('database'))}.{q(p.get('table'))} ({cols});"
        return ''

    def get_columns(self, p):
        rows = self._rows("select column_name, column_type from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position",
                          (p.get('database') or self.current_db, p.get('table') or p.get('name')))
        return [{'name': r[0], 'type': r[1], 'numeric': bool(NUMERIC_RE.search(r[1]))} for r in rows]

    def get_completion_schema(self, database=None):
        db = database or self.current_db
        tables = {}
        if db:
            for t, c in self._rows("select table_name, column_name from information_schema.columns where table_schema=%s order by table_name, ordinal_position", (db,)):
                tables.setdefault(db, {}).setdefault(t, []).append(c)
        return {'tables': tables, 'defaultSchema': db}

    def close(self):
        self.cn.close()


class PostgresConn(DbApiConn):
    capabilities = {'dialect': 'postgres', 'kind': 'server', 'databases': True, 'schemas': True, 'materializedViews': True, 'functions': True,
                    'procedures': True, 'triggers': True, 'sequences': True, 'types': True, 'indexes': True, 'cancel': 'native', 'readOnly': 'session'}
    dialect = 'postgres'

    def __init__(self, cfg):
        if not DRIVERS['postgres']:
            raise ValueError('PostgreSQL sürücüsü (psycopg) bu sunucuda kurulu değil')
        import psycopg
        self.psycopg = psycopg
        self.cfg = cfg
        self.current_db = cfg.get('database') or 'postgres'
        self.cn = self._connect(self.current_db)
        self.set_read_only(bool(cfg.get('readOnly')))

    def _connect(self, db):
        cfg = self.cfg
        extra = {'hostaddr': cfg['hostaddr']} if cfg.get('hostaddr') else {}   # mtweb: doğrulanmış IP (host yalnız TLS adı)
        return self.psycopg.connect(host=cfg.get('host') or 'localhost', port=int(cfg.get('port') or 5432), user=cfg.get('user') or '', password=cfg.get('password') or '',
                                    dbname=db, connect_timeout=20, sslmode=(cfg.get('ssl') or {}).get('mode', 'prefer'), application_name='SQL Master', autocommit=True, **extra)

    def type_name(self, c):
        return getattr(c, 'type_display', None) or str(getattr(c, 'type_code', ''))

    def is_numeric(self, c):
        return bool(NUMERIC_RE.search(self.type_name(c)))

    def server_info(self):
        v = self._rows('show server_version')[0][0]
        tls = False
        try:
            tls = bool(self.cn.pgconn.ssl_in_use())
        except Exception:   # noqa: BLE001
            pass
        return {'product': f'PostgreSQL {v}', 'version': v, 'database': self.current_db, 'user': self.cfg.get('user'), 'tls': tls}

    def set_read_only(self, on):
        self.read_only = on
        self._rows(f"SET default_transaction_read_only = {'on' if on else 'off'}")

    def use_database(self, db):
        self.cn.close()
        self.current_db = db
        self.cn = self._connect(db)
        self.set_read_only(getattr(self, 'read_only', True))

    def cancel(self):
        try:
            self.cn.cancel()
        except Exception:   # noqa: BLE001
            pass

    def _node(self, parent, kind, name, detail=None, has_children=False, open_as=None, **path):
        n = {'id': f"{parent['id']}/{kind}:{name}", 'kind': kind, 'name': name, 'hasChildren': has_children, 'path': {**parent['path'], **path}}
        if detail:
            n['detail'] = detail
        if open_as:
            n['openAs'] = open_as
        return n

    def get_children(self, parent):
        if not parent:
            rows = self._rows('select datname from pg_database where not datistemplate order by 1')
            return [{'id': f'db:{r[0]}', 'kind': 'database', 'name': r[0], 'hasChildren': True, 'path': {'database': r[0]}} for r in rows]
        p = parent['path']
        if p.get('database') and p['database'] != self.current_db:
            self.use_database(p['database'])
        if parent['kind'] == 'database':
            rows = self._rows("select nspname from pg_namespace where nspname not like 'pg\\_%' and nspname <> 'information_schema' order by (nspname <> 'public'), 1")
            return [self._node(parent, 'schema', r[0], has_children=True, schema=r[0]) for r in rows]
        sch = p.get('schema')
        if parent['kind'] == 'schema':
            counts = {k: self._rows(q, (sch,))[0][0] for k, q in (
                ('tables', "select count(*) from pg_tables where schemaname=%s"), ('views', "select count(*) from pg_views where schemaname=%s"),
                ('matviews', "select count(*) from pg_matviews where schemaname=%s"),
                ('functions', "select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname=%s and p.prokind in ('f','a','w')"),
                ('procedures', "select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname=%s and p.prokind='p'"),
                ('sequences', "select count(*) from information_schema.sequences where sequence_schema=%s"),
                ('types', "select count(*) from pg_type t join pg_namespace n on n.oid=t.typnamespace where n.nspname=%s and t.typtype in ('e','c','d') and t.typrelid=0 or (t.typtype='c' and n.nspname=%s and exists(select 1 from pg_class c where c.oid=t.typrelid and c.relkind='c'))"))}
            return [{**self._node(parent, 'folder', f, has_children=counts[f] > 0, folder=f), 'count': counts[f]} for f in counts]
        if parent['kind'] == 'folder' and not p.get('table'):
            f = p.get('folder')
            if f in ('tables', 'views', 'matviews'):
                src = {'tables': ('pg_tables', 'tablename'), 'views': ('pg_views', 'viewname'), 'matviews': ('pg_matviews', 'matviewname')}[f]
                kind = {'tables': 'table', 'views': 'view', 'matviews': 'matview'}[f]
                rows = self._rows(f"select {src[1]} from {src[0]} where schemaname=%s order by 1", (sch,))
                return [self._node(parent, kind, r[0], has_children=True, open_as='data', name=r[0]) for r in rows]
            if f in ('functions', 'procedures'):
                rows = self._rows("select p.proname, p.oid::text, pg_get_function_identity_arguments(p.oid) from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
                                  "where n.nspname=%s and p.prokind " + ("in ('f','a','w')" if f == 'functions' else "='p'") + " order by 1", (sch,))
                return [self._node(parent, f[:-1], r[0], detail=f'({r[2]})', open_as='code', name=r[0], objectId=r[1]) for r in rows]
            if f == 'sequences':
                rows = self._rows("select sequence_name from information_schema.sequences where sequence_schema=%s order by 1", (sch,))
                return [self._node(parent, 'sequence', r[0], open_as='code', name=r[0]) for r in rows]
            if f == 'types':
                rows = self._rows("select t.typname, t.typtype from pg_type t join pg_namespace n on n.oid=t.typnamespace where n.nspname=%s and t.typtype in ('e','d') order by 1", (sch,))
                return [self._node(parent, 'type', r[0], detail={'e': 'enum', 'd': 'domain'}.get(r[1]), open_as='code', name=r[0]) for r in rows]
        if parent['kind'] in ('table', 'view', 'matview'):
            folders = ['columns', 'indexes', 'triggers', 'constraints'] if parent['kind'] == 'table' else ['columns', 'indexes'] if parent['kind'] == 'matview' else ['columns']
            return [self._node(parent, 'folder', f, has_children=True, table=p.get('name'), folder=f) for f in folders]
        if parent['kind'] == 'folder' and p.get('table'):
            f = p.get('folder')
            if f == 'columns':
                rows = self._rows("select a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, exists(select 1 from pg_index i where i.indrelid=a.attrelid and a.attnum = any(i.indkey) and i.indisprimary) "
                                  "from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s and a.attnum>0 and not a.attisdropped order by a.attnum", (sch, p['table']))
                return [self._node(parent, 'column', r[0], detail=f"{r[1]}{' NOT NULL' if r[2] else ''}{' · PK' if r[3] else ''}", name=r[0]) for r in rows]
            if f == 'indexes':
                rows = self._rows("select indexname from pg_indexes where schemaname=%s and tablename=%s order by 1", (sch, p['table']))
                return [self._node(parent, 'index', r[0], open_as='code', name=r[0]) for r in rows]
            if f == 'triggers':
                rows = self._rows("select t.tgname from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s and not t.tgisinternal order by 1", (sch, p['table']))
                return [self._node(parent, 'trigger', r[0], open_as='code', name=r[0]) for r in rows]
            if f == 'constraints':
                rows = self._rows("select conname, contype from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s order by 1", (sch, p['table']))
                return [self._node(parent, 'constraint', r[0], detail={'p': 'PRIMARY KEY', 'f': 'FOREIGN KEY', 'u': 'UNIQUE', 'c': 'CHECK'}.get(r[1]), open_as='code', name=r[0]) for r in rows]
        return []

    def get_object_ddl(self, node):
        p = node['path']
        q = lambda s: qualified(s, 'postgres')   # noqa: E731
        sch, name = p.get('schema'), p.get('name') or node['name']
        kind = node['kind']
        if kind == 'table':
            cols = self._rows("select a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(d.adbin, d.adrelid) from pg_attribute a "
                              "join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum "
                              "where n.nspname=%s and c.relname=%s and a.attnum>0 and not a.attisdropped order by a.attnum", (sch, name))
            lines = [f"  {q(c[0])} {c[1]}{' NOT NULL' if c[2] else ''}{' DEFAULT ' + c[3] if c[3] else ''}" for c in cols]
            cons = self._rows("select conname, pg_get_constraintdef(k.oid) from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s order by contype", (sch, name))
            lines += [f'  CONSTRAINT {q(k[0])} {k[1]}' for k in cons]
            ddl = f"CREATE TABLE {q(sch)}.{q(name)} (\n" + ',\n'.join(lines) + '\n);'
            for i in self._rows("select indexdef from pg_indexes where schemaname=%s and tablename=%s", (sch, name)):
                ddl += f'\n\n{i[0]};'
            return ddl
        if kind in ('view', 'matview'):
            r = self._rows('select pg_get_viewdef(%s::regclass, true)', (f'{q(sch)}.{q(name)}',))
            return f"CREATE {'MATERIALIZED ' if kind == 'matview' else ''}VIEW {q(sch)}.{q(name)} AS\n{r[0][0]}"
        if kind in ('function', 'procedure'):
            r = self._rows('select pg_get_functiondef(%s::oid)', (p.get('objectId'),)) if p.get('objectId') else []
            return (r[0][0] + ';') if r else ''
        if kind == 'index':
            r = self._rows("select indexdef from pg_indexes where schemaname=%s and indexname=%s", (sch, name))
            return (r[0][0] + ';') if r else ''
        if kind == 'trigger':
            r = self._rows("select pg_get_triggerdef(t.oid) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s and t.tgname=%s", (sch, p.get('table'), name))
            return (r[0][0] + ';') if r else ''
        if kind == 'constraint':
            r = self._rows("select pg_get_constraintdef(k.oid) from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname=%s and c.relname=%s and conname=%s", (sch, p.get('table'), name))
            return f"ALTER TABLE {q(sch)}.{q(p.get('table'))} ADD CONSTRAINT {q(name)} {r[0][0]};" if r else ''
        if kind == 'sequence':
            r = self._rows("select start_value, minimum_value, maximum_value, increment from information_schema.sequences where sequence_schema=%s and sequence_name=%s", (sch, name))
            return f"CREATE SEQUENCE {q(sch)}.{q(name)} START {r[0][0]} MINVALUE {r[0][1]} MAXVALUE {r[0][2]} INCREMENT {r[0][3]};" if r else ''
        if kind == 'type':
            r = self._rows("select string_agg(quote_literal(enumlabel), ', ' order by enumsortorder) from pg_enum e join pg_type t on t.oid=e.enumtypid join pg_namespace n on n.oid=t.typnamespace where n.nspname=%s and t.typname=%s", (sch, name))
            return f"CREATE TYPE {q(sch)}.{q(name)} AS ENUM ({r[0][0]});" if r and r[0][0] else ''
        return ''

    def get_columns(self, p):
        rows = self._rows("select column_name, data_type from information_schema.columns where table_schema=%s and table_name=%s order by ordinal_position",
                          (p.get('schema') or 'public', p.get('table') or p.get('name')))
        return [{'name': r[0], 'type': r[1], 'numeric': bool(NUMERIC_RE.search(r[1]))} for r in rows]

    def get_completion_schema(self, database=None):
        if database and database != self.current_db:
            self.use_database(database)
        tables = {}
        for s, t, c in self._rows("select table_schema, table_name, column_name from information_schema.columns where table_schema not like 'pg\\_%' and table_schema <> 'information_schema' order by 1,2,ordinal_position"):
            tables.setdefault(s, {}).setdefault(t, []).append(c)
        return {'tables': tables, 'defaultSchema': 'public'}

    def close(self):
        self.cn.close()


# --- SSH tüneli (core/engine/open.ts openTunnel; paramiko ile) --------------------------------------------------------
class Tunnel:
    def __init__(self, cfg, uid):
        if paramiko is None:
            raise ValueError('SSH tüneli için paramiko paketi kurulu değil')
        ssh = cfg['ssh']
        host, port = check_host(ssh.get('host')), check_port(ssh.get('port') or 22)
        if not ALLOW_SSH_AGENT and ssh.get('auth') == 'agent':
            raise tc.NetDenied('SSH ajanı ile kimlik doğrulama web sürümünde kapalı; anahtar ya da parola kullanın')
        target, target_port = cfg.get('host') or 'localhost', int(cfg.get('port') or 0)
        timeout = cfg.get('connectTimeoutMs', 20000) / 1000
        if tc.NET_GUARD:
            # mtweb: önce SSH sunucusu, sonra tünel hedefi yerelde doğrulanır (hedef IP olarak istenir; SSH sunucusu ad çözmez);
            # ikisi de geçerse doğrulanan IP'ye bağlanılır
            ssh_ip = tc.net_target(host, port, uid, APP)
            target = tc.net_target(target, target_port, uid, APP, 'data')
            sock = socket.create_connection((ssh_ip, port), timeout=timeout)
        else:
            sock = socket.create_connection((host, port), timeout=timeout)
        self.tr = paramiko.Transport(sock)
        self.tr.set_keepalive(15)
        self.tr.start_client(timeout=20)
        key = self.tr.get_remote_server_key()
        self.fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if ssh.get('hostKey') and ssh['hostKey'] != self.fingerprint:
            self.tr.close()
            raise ValueError(f"SSH sunucu anahtarı değişti (kayıtlı {ssh['hostKey']}, gelen {self.fingerprint}). Güvenlik için bağlantı reddedildi.")
        user = check_host(ssh.get('user') or 'root')
        try:
            if ssh.get('auth') == 'key':
                kp = (ssh.get('keyPath') or '').strip()
                kf = mt.resolve(mt.app_dir(APP, uid, 'keys'), kp) if kp else None
                if not kf or not kf.is_file():
                    raise ValueError(f"Anahtar dosyası okunamadı: {kp or '(boş)'}")
                self.tr.auth_publickey(user, paramiko.PKey.from_path(kf, passphrase=ssh.get('passphrase') or None))
            elif ssh.get('auth') == 'agent':
                agent = paramiko.Agent()
                keys = agent.get_keys()
                if not keys:
                    raise ValueError('SSH ajanında anahtar yok')
                self.tr.auth_publickey(user, keys[0])
            else:
                self.tr.auth_password(user, ssh.get('password') or '')
        except paramiko.AuthenticationException:
            self.tr.close()
            raise ValueError('All configured authentication methods failed') from None
        self.target = (target, target_port)
        self.srv = socket.socket()
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(8)
        self.host, self.port = '127.0.0.1', self.srv.getsockname()[1]
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.alive:
            try:
                s, addr = self.srv.accept()
            except OSError:
                break
            try:
                ch = self.tr.open_channel('direct-tcpip', self.target, addr)
            except Exception:   # noqa: BLE001
                s.close()
                continue
            threading.Thread(target=self._pump, args=(s, ch), daemon=True).start()
            threading.Thread(target=self._pump, args=(ch, s), daemon=True).start()

    @staticmethod
    def _pump(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except Exception:   # noqa: BLE001
            pass
        finally:
            try:
                b.close()
            except Exception:   # noqa: BLE001
                pass

    def close(self):
        self.alive = False
        try:
            self.srv.close()
        finally:
            self.tr.close()


def open_connection(cfg, uid):
    """Bağlantı açma (open.ts): gerekiyorsa önce SSH tüneli, sonra sağlayıcı.
    mtweb (NET kancası): doğrudan bağlantıda hedef doğrulanır ve sürücü IP'ye bağlanır (MySQL hazır soket, PG hostaddr);
    tünelde SSH sunucusu ve tünel hedefi doğrulanır (veritabanı istemcisi yalnız yerel tünel ucuna bağlanır)."""
    provider = cfg['provider']
    if provider in ('mssql', 'duckdb'):
        raise ValueError({'mssql': 'SQL Server sürücüsü bu sunucuda kurulu değil', 'duckdb': 'DuckDB sürücüsü bu sunucuda kurulu değil'}[provider])
    if provider == 'sqlite':
        return SqliteConn(cfg, uid), None
    tunnel = None
    if (cfg.get('ssh') or {}).get('enabled'):
        tunnel = Tunnel({**cfg, 'port': cfg.get('port') or provider_meta(provider)['defaultPort']}, uid)
        cfg = {**cfg, 'host': tunnel.host, 'port': tunnel.port}
    elif tc.NET_GUARD:
        port = int(cfg.get('port') or provider_meta(provider)['defaultPort'])
        cfg = {**cfg, 'port': port, 'host': cfg.get('host') or 'localhost',
               'hostaddr': tc.net_target(cfg.get('host') or 'localhost', port, uid, APP)}
    try:
        conn = MysqlConn(cfg) if provider == 'mysql' else PostgresConn(cfg)
    except Exception:
        if tunnel:
            tunnel.close()
        raise
    if tunnel:
        orig_close = conn.close

        def close():
            try:
                orig_close()
            finally:
                tunnel.close()
        conn.close = close
    return conn, (tunnel.fingerprint if tunnel else None)


def friendly_error(err):
    """Sürücü/ağ hatalarını kullanıcı dostu metne çevirir (errors.ts); veritabanının kendi mesajı korunur."""
    if isinstance(err, HTTPException):
        return err.detail
    if isinstance(err, tc.NetDenied):
        return str(err)
    msg = redact(str(err) or err.__class__.__name__)
    low = msg.lower()
    if 'refused' in low:
        return 'Bağlantı reddedildi: sunucu bu portta dinlemiyor ya da güvenlik duvarı engelliyor.'
    if 'name or service not known' in low or 'getaddrinfo' in low or 'nodename' in low or 'temporary failure in name' in low:
        return 'Sunucu adı çözümlenemedi.'
    if 'timed out' in low or 'timeout' in low:
        return f'Zaman aşımı ({msg})'
    if 'connection reset' in low:
        return 'Bağlantı karşı tarafça kapatıldı.'
    if 'unreachable' in low:
        return 'Sunucuya erişilemiyor (ağ yolu yok).'
    if 'all configured authentication methods failed' in low:
        return 'SSH kimlik doğrulaması başarısız (anahtar / parola kabul edilmedi).'
    if 'self-signed certificate' in low or 'certificate verify failed' in low:
        return f'TLS sertifikası doğrulanamadı: {msg}'
    return msg


# =============================================================================================================
# Oturum (main.ts ConnSession + dbhost) ve yürütücü (executor.ts)
# =============================================================================================================
class Session:
    def __init__(self, uid, profile_id, read_only):
        self.uid, self.profile_id = uid, profile_id
        self.conn = None
        self.read_only = read_only
        self.runs = {}          # runId -> cancel Event
        self.events = []        # (seq, ch, data)
        self.seq = 0
        self.lock = threading.RLock()
        self.exec_lock = threading.Lock()   # bağlantıda aynı anda tek çalıştırma
        self.last = self.created = time.time()
        self.release = None                 # mtweb: eşzamanlı oturum yeri

    def send(self, ch, data):
        with self.lock:
            self.seq += 1
            self.events.append((self.seq, ch, data))
            if len(self.events) > 5000:
                del self.events[:2500]

    def events_since(self, since):
        with self.lock:
            return self.seq, [{'ch': ch, 'data': d} for s, ch, d in self.events if s > since]

    def need(self):
        if not self.conn:
            raise HTTPException(400, 'Bağlantı açık değil')
        return self.conn

    def execute(self, run_id, req):
        cancel = threading.Event()
        self.runs[run_id] = cancel
        started = time.time()
        errors, cancelled, rows = 0, False, 0
        try:
            with self.exec_lock:
                for ev in execute_script(self.need(), {**req, 'readOnly': self.read_only}, cancel):
                    if ev['type'] == 'done':
                        errors, cancelled = ev['errors'], ev['cancelled']
                    elif ev['type'] == 'rows':
                        rows += len(ev['rows'])
                    self.send('db:event', {'runId': run_id, 'ev': ev})
            history_add(self.uid, {'at': int(started * 1000), 'connectionId': self.profile_id, 'database': req.get('database'), 'sql': req['sql'],
                                   'ms': int((time.time() - started) * 1000), 'ok': not errors, 'rows': rows})
            return {'errors': errors, 'cancelled': cancelled}
        except Exception as err:   # noqa: BLE001
            history_add(self.uid, {'at': int(started * 1000), 'connectionId': self.profile_id, 'database': req.get('database'), 'sql': req['sql'],
                                   'ms': int((time.time() - started) * 1000), 'ok': False})
            raise HTTPException(400, friendly_error(err)) from None
        finally:
            self.runs.pop(run_id, None)

    def cancel(self, run_id):
        c = self.runs.get(run_id)
        if not c:
            return
        c.set()
        try:
            self.need().cancel()
        except Exception:   # noqa: BLE001
            pass

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:   # noqa: BLE001
                pass
            self.conn = None
        rel, self.release = self.release, None
        if rel:
            rel()


def error_message(e):
    msg = str(e) or e.__class__.__name__
    diag = getattr(e, 'diag', None)
    if diag is not None:
        if getattr(diag, 'message_detail', None):
            msg += f'\n{diag.message_detail}'
        if getattr(diag, 'message_hint', None):
            msg += f'\nİpucu: {diag.message_hint}'
    return redact(msg)


def execute_script(conn, req, cancel):
    """Betik yürütücü (executor.ts): ifadelere böl, salt okunur korumasını uygula, akışla çalıştır."""
    started = time.time()
    d = conn.capabilities['dialect']
    statements = split_statements(req['sql'], d)
    kinds = [classify(s['text'], d) for s in statements]
    preview = lambda s: s[:400] + '…' if len(s) > 400 else s   # noqa: E731
    if req.get('readOnly') and not req.get('allowWrite'):
        blocked = [{'index': i, 'keyword': k['keyword'], 'text': preview(s['text'])} for i, (s, k) in enumerate(zip(statements, kinds)) if k['kind'] == 'write']
        if blocked:
            yield {'type': 'blocked', 'statements': blocked}
            yield {'type': 'done', 'ms': int((time.time() - started) * 1000), 'cancelled': False, 'errors': 0}
            return
    unlock = req.get('readOnly') and req.get('allowWrite') and any(k['kind'] == 'write' for k in kinds)
    errors = 0
    try:
        if unlock:
            conn.set_read_only(False)
        for index, st in enumerate(statements):
            if cancel.is_set():
                break
            yield {'type': 'statement', 'index': index, 'total': len(statements), 'text': preview(st['text']), 'start': st['start'], 'end': st['end'], 'kind': kinds[index]['kind']}
            t0 = time.time()
            try:
                for ev in conn.query(st['text'], req.get('database'), req.get('limit') or DEFAULT_LIMIT, req.get('batchSize') or DEFAULT_BATCH, cancel):
                    ms = int((time.time() - t0) * 1000)
                    if ev['type'] == 'columns':
                        yield {'type': 'columns', 'index': index, 'columns': ev['columns']}
                    elif ev['type'] == 'rows':
                        yield {'type': 'rows', 'index': index, 'rows': ev['rows']}
                    elif ev['type'] == 'end':
                        yield {'type': 'end', 'index': index, 'rowCount': ev['rowCount'], 'truncated': ev['truncated'], 'ms': ms}
                    elif ev['type'] == 'command':
                        yield {'type': 'command', 'index': index, 'rowsAffected': ev['rowsAffected'], 'command': ev['command'], 'ms': ms}
                    elif ev['type'] == 'notice':
                        yield {'type': 'notice', 'index': index, 'message': ev['message']}
                    if cancel.is_set():
                        break
            except Exception as e:   # noqa: BLE001
                if cancel.is_set():
                    break
                errors += 1
                yield {'type': 'error', 'index': index, 'message': error_message(e), 'start': st['start'], 'end': st['end']}
                if req.get('stopOnError') is not False:
                    break
    finally:
        if unlock:
            try:
                conn.set_read_only(True)
            except Exception:   # noqa: BLE001
                pass
    yield {'type': 'done', 'ms': int((time.time() - started) * 1000), 'cancelled': cancel.is_set(), 'errors': errors}


def export_query(conn, sql, fmt, database, path, cancel, on_progress):
    """Sorgu sonucunu belleğe almadan dosyaya akıtır (export.ts): CSV / TSV / JSON Lines / JSON."""
    rows = 0
    columns = []
    sep = '\t' if fmt == 'tsv' else ','
    with open(path, 'w', encoding='utf-8', newline='') as out:
        writer = csv.writer(out, delimiter=sep, lineterminator='\r\n') if fmt in ('csv', 'tsv') else None
        if fmt == 'csv':
            out.write('﻿')
        if fmt == 'json':
            out.write('[')
        first = True
        for ev in conn.query(sql, database, 0, 500, cancel):
            if ev['type'] == 'columns':
                columns = ev['columns']
                if writer:
                    writer.writerow([c['name'] for c in columns])
            elif ev['type'] == 'rows':
                for r in ev['rows']:
                    if writer:
                        writer.writerow(['' if v is None else v for v in r])
                    else:
                        obj = {c['name']: r[i] for i, c in enumerate(columns)}
                        if fmt == 'jsonl':
                            out.write(json.dumps(obj, ensure_ascii=False) + '\n')
                        else:
                            out.write(('\n' if first else ',\n') + json.dumps(obj, ensure_ascii=False))
                        first = False
                rows += len(ev['rows'])
                on_progress(rows)
                if EXPORT_MAX and out.tell() > EXPORT_MAX:
                    raise ValueError(f'Dışa aktarma boyut sınırı aşıldı (en çok {EXPORT_MAX // (1024 * 1024)} MB)')
            if cancel.is_set():
                break
        if fmt == 'json':
            out.write('\n]\n')
    return {'rows': rows, 'bytes': Path(path).stat().st_size, 'cancelled': cancel.is_set()}


SESSIONS: dict[str, Session] = {}


def _sweep():
    now = time.time()
    for k, s in list(SESSIONS.items()):
        if now - s.last > SESSION_IDLE:
            s.close()
            SESSIONS.pop(k, None)


def get_session(sid, user) -> Session:
    _sweep()
    s = SESSIONS.get(sid or '')
    if not s or s.uid != user['id']:
        raise HTTPException(404, 'Bağlantı oturumu bulunamadı; yeniden bağlanın')
    s.last = time.time()
    return s


def resolve_config(uid, c, sec, password=None):
    """Profil + gizli bilgiler → çözülmüş bağlantı yapılandırması (yalnız bellekte)."""
    meta = provider_meta(c['provider'])
    ssh = c.get('ssh') or {}
    return {'provider': c['provider'], 'host': c.get('host'), 'port': c.get('port') or meta.get('defaultPort'), 'database': c.get('database'), 'user': c.get('user'),
            'password': password if password is not None else sec.get(ref_password(c['id'])), 'filePath': c.get('filePath'), 'ssl': {'mode': c.get('sslMode', 'prefer')},
            'readOnly': c.get('readOnly', True), 'appName': 'SQL Master',
            'ssh': {**ssh, 'passphrase': sec.get(ref_ssh_passphrase(c['id'])), 'password': sec.get(ref_ssh_password(c['id']))} if ssh.get('enabled') else None}


def wrap(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as err:   # noqa: BLE001
        raise HTTPException(400, friendly_error(err)) from None


# =============================================================================================================
# HTTP
# =============================================================================================================
class Body(BaseModel):
    model_config = {'extra': 'allow'}


def _b(body: Body) -> dict:
    return body.model_dump()


def _with_store(uid, s, sec=None, **extra):
    return {'store': public_store(uid, s, sec), **extra}


@router.get('/drivers')
def drivers(user=Depends(tools_user)):
    return DRIVERS


@router.get('/providers')
def providers(user=Depends(tools_user)):
    return PROVIDERS


@router.get('/store')
def get_store(user=Depends(tools_user)):
    return public_store(user['id'])


@router.post('/settings')
def set_settings(body: Body, user=Depends(tools_user)):
    uid = user['id']
    patch = _b(body).get('patch') or {}
    s = load_store(uid)
    if 'language' in patch:
        patch['language'] = _one(patch['language'], LANGS, None)
    if 'appTheme' in patch:
        patch['appTheme'] = _one(patch['appTheme'], ['dark', 'light', 'system'], 'system')
    for k, lo, hi, d in (('rowLimit', 100, 1_000_000, 10_000), ('previewRows', 10, 100_000, 100), ('editorFontSize', 9, 24, 13), ('treeWidth', 120, 1200, 300)):
        if k in patch:
            patch[k] = _num(patch[k], lo, hi) or d
    s['settings'].update(patch)
    save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/save')
def conn_save(body: Body, user=Depends(tools_user)):
    uid = user['id']
    form = _b(body).get('form') or {}
    s, sec = load_store(uid), Secrets(uid)
    existing = find_conn(s, form.get('id')) if form.get('id') else None
    p = normalize(form, s, existing)
    if existing:
        existing.update(p)
    else:
        s['connections'].append(p)
    if not p['savePassword'] or form.get('clearPassword'):
        sec.delete(ref_password(p['id']))
    if form.get('password') and p['savePassword']:
        sec.set(ref_password(p['id']), form['password'])
    if form.get('sshPassword'):
        sec.set(ref_ssh_password(p['id']), form['sshPassword'])
    if form.get('sshPassphrase'):
        sec.set(ref_ssh_passphrase(p['id']), form['sshPassphrase'])
    if p['ssh']['auth'] != 'password':
        sec.delete(ref_ssh_password(p['id']))
    save_store(uid, s)
    return _with_store(uid, s, sec, id=p['id'])


@router.post('/conn/delete')
def conn_delete(body: Body, user=Depends(tools_user)):
    uid = user['id']
    cid = _b(body).get('id')
    s, sec = load_store(uid), Secrets(uid)
    s['connections'] = [c for c in s['connections'] if c['id'] != cid]
    sec.delete_prefix(f'conn:{cid}:')
    for k, ses in list(SESSIONS.items()):
        if ses.uid == uid and ses.profile_id == cid:
            ses.close()
            SESSIONS.pop(k, None)
    save_store(uid, s)
    return _with_store(uid, s, sec)


@router.post('/conn/duplicate')
def conn_duplicate(body: Body, user=Depends(tools_user)):
    uid = user['id']
    s, sec = load_store(uid), Secrets(uid)
    c = find_conn(s, _b(body).get('id'))
    if c:
        copy = {**json.loads(json.dumps(c)), 'id': mt.uid8(), 'name': c['name'] + ' (kopya)', 'createdAt': mt.now_ms(), 'lastUsedAt': None}
        s['connections'].append(copy)
        for ref in (ref_password, ref_ssh_password, ref_ssh_passphrase):
            v = sec.get(ref(c['id']))
            if v:
                sec.set(ref(copy['id']), v)
        save_store(uid, s)
    return _with_store(uid, s, sec)


@router.post('/conn/move')
def conn_move(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    c = find_conn(s, b.get('id'))
    if c:
        c['folderId'] = b.get('folderId') if b.get('folderId') and any(f['id'] == b['folderId'] for f in s['folders']) else None
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/test')
def conn_test(body: Body, user=Depends(tools_user)):
    uid = user['id']
    form = _b(body).get('form') or {}
    s, sec = load_store(uid), Secrets(uid)
    started = time.time()
    try:
        existing = find_conn(s, form.get('id')) if form.get('id') else None
        profile = normalize(form, s, existing)
        if existing and profile['ssh']['host'] == existing['ssh'].get('host'):
            profile['ssh']['hostKey'] = existing['ssh'].get('hostKey')
        if existing:
            profile['id'] = existing['id']
        password = form.get('password') or (sec.get(ref_password(existing['id'])) if existing and not form.get('clearPassword') else '')
        cfg = resolve_config(uid, profile, sec, password)
        if form.get('sshPassword') and cfg.get('ssh'):
            cfg['ssh']['password'] = form['sshPassword']
        if form.get('sshPassphrase') and cfg.get('ssh'):
            cfg['ssh']['passphrase'] = form['sshPassphrase']
        conn, fp = open_connection(cfg, uid)
        try:
            info = conn.server_info()
        finally:
            conn.close()
        return {'ok': True, 'ms': int((time.time() - started) * 1000), 'info': info, 'sshFingerprint': fp, 'firstSsh': bool(fp) and not profile['ssh'].get('hostKey')}
    except Exception as err:   # noqa: BLE001
        return {'ok': False, 'message': friendly_error(err)}


@router.post('/folder/save')
def folder_save(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    f = next((x for x in s['folders'] if x['id'] == b.get('id')), None) if b.get('id') else None
    if not f:
        f = {'id': mt.uid8(), 'name': '', 'parentId': b.get('parentId') or None}
        s['folders'].append(f)
    f['name'] = _str(b.get('name'), 120)
    save_store(uid, s)
    return _with_store(uid, s, id=f['id'])


@router.post('/folder/move')
def folder_move(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    p = b.get('parentId')
    while p:
        if p == b.get('id'):
            return _with_store(uid, s, ok=False)
        p = next((x for x in s['folders'] if x['id'] == p), {}).get('parentId')
    f = next((x for x in s['folders'] if x['id'] == b.get('id')), None)
    if f:
        f['parentId'] = b.get('parentId') or None
    save_store(uid, s)
    return _with_store(uid, s, ok=True)


@router.post('/folder/delete')
def folder_delete(body: Body, user=Depends(tools_user)):
    uid = user['id']
    fid = _b(body).get('id')
    s = load_store(uid)
    f = next((x for x in s['folders'] if x['id'] == fid), None)
    if f:
        for c in s['connections']:
            if c.get('folderId') == fid:
                c['folderId'] = f.get('parentId')
        for sub in s['folders']:
            if sub.get('parentId') == fid:
                sub['parentId'] = f.get('parentId')
        s['folders'] = [x for x in s['folders'] if x['id'] != fid]
        save_store(uid, s)
    return _with_store(uid, s)


# --- bağlantı penceresi ---------------------------------------------------------------------------------------
@router.get('/cw/info')
def cw_info(id: str, user=Depends(tools_user)):   # noqa: A002
    uid = user['id']
    s, sec = load_store(uid), Secrets(uid)
    c = find_conn(s, id)
    if not c:
        raise HTTPException(404, 'Bağlantı bulunamadı')
    return {'connection': public_conn(sec, c), 'needsPassword': provider_meta(c['provider'])['kind'] == 'server' and not c.get('savePassword', True), 'settings': s['settings']}


@router.post('/cw/connect')
def cw_connect(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    if b.get('prev'):
        old = SESSIONS.pop(b['prev'], None)
        if old and old.uid == uid:
            old.close()
    s, sec = load_store(uid), Secrets(uid)
    c = find_conn(s, b.get('id'))
    if not c:
        return {'ok': False, 'message': 'Bağlantı bulunamadı'}
    try:
        release = tc.conn_slot(uid, APP)
    except Exception as err:   # noqa: BLE001 — eşzamanlı oturum sınırı (mtweb)
        return {'ok': False, 'message': friendly_error(err)}
    try:
        cfg = resolve_config(uid, c, sec, b.get('password') if b.get('password') else None)
        conn, fp = open_connection(cfg, uid)
    except Exception as err:   # noqa: BLE001
        release()
        return {'ok': False, 'message': friendly_error(err)}
    if fp and not c['ssh'].get('hostKey'):
        c['ssh']['hostKey'] = fp
    c['lastUsedAt'] = mt.now_ms()
    save_store(uid, s)
    ses = Session(uid, c['id'], c.get('readOnly', True))
    ses.conn = conn
    ses.release = release
    sid = secrets.token_urlsafe(12)
    SESSIONS[sid] = ses
    try:
        info = conn.server_info()
    except Exception as err:   # noqa: BLE001
        info = {'product': c['provider'], 'version': '', 'database': c.get('database'), 'note': friendly_error(err)}
    return {'ok': True, 'sid': sid, 'info': info, 'readOnly': ses.read_only}


@router.post('/cw/close')
def cw_close(body: Body, user=Depends(tools_user)):
    s = SESSIONS.pop(_b(body).get('sid') or '', None)
    if s and s.uid == user['id']:
        s.close()
    return {'ok': True}


@router.get('/db/events')
def db_events(sid: str, since: int = 0, user=Depends(tools_user)):
    s = SESSIONS.get(sid)
    if not s or s.uid != user['id']:
        return {'seq': since, 'events': [], 'gone': True}
    s.last = time.time()
    seq, events = s.events_since(since)
    return {'seq': seq, 'events': events}


@router.post('/db/children')
def db_children(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.need().get_children(b.get('node')))


@router.post('/db/ddl')
def db_ddl(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.need().get_object_ddl(b.get('node')))


@router.post('/db/columns')
def db_columns(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.need().get_columns(b.get('path') or {}))


@router.post('/db/completion')
def db_completion(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.need().get_completion_schema(b.get('database')))


@router.post('/db/execute')
def db_execute(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    req = b.get('req') or {}
    if not isinstance(req.get('sql'), str):
        raise HTTPException(400, 'SQL metni yok')
    settings = load_store(user['id'])['settings']
    req['limit'] = req.get('limit') or settings.get('rowLimit') or DEFAULT_LIMIT
    if ROW_LIMIT_MAX:
        try:
            req['limit'] = max(1, min(int(req['limit']), ROW_LIMIT_MAX))
        except (TypeError, ValueError):
            req['limit'] = ROW_LIMIT_MAX
    return s.execute(str(b.get('runId') or secrets.token_hex(4)), req)


@router.post('/db/cancel')
def db_cancel(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    s.cancel(b.get('runId'))
    return {'ok': True}


@router.post('/db/setReadOnly')
def db_set_read_only(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    on = bool(b.get('on'))

    def do():
        s.need().set_read_only(on)
        s.read_only = on
        return {'on': on}
    return wrap(do)


@router.post('/db/export')
def db_export(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    fmt = _one(b.get('format'), ['csv', 'tsv', 'jsonl', 'json'], 'csv')
    name = safe_name(f"{b.get('defaultName') or 'sorgu'}.{fmt}")
    token, path = new_tmp(name)
    run_id = str(b.get('runId') or secrets.token_hex(4))
    cancel = threading.Event()
    s.runs[run_id] = cancel

    def do():
        with s.exec_lock:
            r = export_query(s.need(), b.get('sql') or '', fmt, b.get('database'), path, cancel, lambda n: s.send('db:progress', {'runId': run_id, 'rows': n}))
        return {**r, 'token': token, 'fileName': name}
    try:
        return wrap(do)
    finally:
        s.runs.pop(run_id, None)


@router.get('/db/download')
def db_download(token: str, user=Depends(tools_user)):
    p = tmp_path(token)
    if not p:
        raise HTTPException(404, 'Dosya bulunamadı ya da süresi doldu')
    return FileResponse(p, filename=token.split('__', 1)[1])


@router.get('/history')
def history(id: str, user=Depends(tools_user)):   # noqa: A002
    return history_list(user['id'], id)

