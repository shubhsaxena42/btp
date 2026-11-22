"""SQLite access helpers (per-request connection, numbering, settings)."""
import os
import re
import shutil
import sqlite3
from datetime import date as _date, datetime

from flask import g, has_app_context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, 'schema.sql')
_standalone = None  # connection used outside an app context (scripts, tests)


def db_path():
    p = os.environ.get('ERP_DB')
    if p:
        return p
    bundled = os.path.join(ROOT, 'erp.db')
    if os.environ.get('VERCEL'):
        tmp = '/tmp/erp.db'
        if not os.path.exists(tmp) and os.path.exists(bundled):
            shutil.copyfile(bundled, tmp)
        return tmp
    return bundled


def _connect():
    path = db_path()
    is_new = not os.path.exists(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    if is_new:
        with open(SCHEMA_PATH, encoding='utf-8') as f:
            conn.executescript(f.read())
        conn.commit()
    return conn


def get_db():
    global _standalone
    if has_app_context():
        if 'db' not in g:
            g.db = _connect()
        return g.db
    if _standalone is None:
        _standalone = _connect()
    return _standalone


def close_db(exc=None):
    conn = g.pop('db', None)
    if conn is not None:
        try:
            conn.rollback()
        finally:
            conn.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def scalar(sql, args=(), default=None):
    row = get_db().execute(sql, args).fetchone()
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql, args=()):
    return get_db().execute(sql, args).lastrowid


def commit():
    get_db().commit()


def rollback():
    get_db().rollback()


def setting(key, default=None):
    v = scalar('SELECT value FROM settings WHERE key = ?', (key,))
    return default if v is None else v


def today():
    return _date.today().isoformat()


def _to_date(d):
    if d is None or d == '':
        return _date.today()
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, _date):
        return d
    return datetime.strptime(str(d)[:10], '%Y-%m-%d').date()


def fy(date=None):
    """Indian financial year (April-March) of a date, e.g. '2026-27'."""
    d = _to_date(date)
    start = d.year if d.month >= 4 else d.year - 1
    return '%d-%02d' % (start, (start + 1) % 100)


def _max_seq(table, col, prefix):
    rows = query('SELECT %s AS v FROM %s WHERE %s LIKE ?' % (col, table, col),
                 (prefix.replace('%', r'\%') + '%',))
    best = 0
    pat = re.compile(r'^' + re.escape(prefix) + r'(\d+)$')
    for r in rows:
        m = pat.match(r['v'] or '')
        if m:
            best = max(best, int(m.group(1)))
    return best


_KINDS = {
    'purchase': ('purchase', 'purchase_no', 'PUR-', 4),
    'work_order': ('work_order', 'wo_no', 'WO-', 4),
    'consignment': ('consignment', 'cn_no', 'CN-', 4),
    'member': ('member', 'code', 'M-', 3),
    'customer': ('customer', 'code', 'C-', 3),
    'raw_material': ('raw_material', 'code', 'RM-', 3),
}


def next_number(kind, date=None):
    if kind == 'invoice':
        prefix = 'INV/%s/' % fy(date)
        return '%s%04d' % (prefix, _max_seq('sale', 'invoice_no', prefix) + 1)
    if kind not in _KINDS:
        raise ValueError('Unknown number kind: %s' % kind)
    table, col, prefix, width = _KINDS[kind]
    return '%s%0*d' % (prefix, width, _max_seq(table, col, prefix) + 1)
