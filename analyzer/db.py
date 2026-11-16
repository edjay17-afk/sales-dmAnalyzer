"""SQLite storage. Parsed lines are kept, not the PDFs. Re-uploading a day or slip replaces it."""
import os
import sqlite3
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DB_PATH = os.environ.get('ANALYZER_DB') or os.path.join(DATA_DIR, 'analyzer.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS or_days (date TEXT PRIMARY KEY, store TEXT, source TEXT, uploaded_at TEXT, warnings TEXT);
CREATE TABLE IF NOT EXISTS or_lines (date TEXT, cat TEXT, code TEXT, name TEXT, qty REAL, amt REAL);
CREATE INDEX IF NOT EXISTS ix_or_lines_date ON or_lines(date);
CREATE TABLE IF NOT EXISTS bm_slips (doc_id TEXT PRIMARY KEY, slip_id TEXT, slip_no INTEGER, date TEXT, status TEXT, store TEXT,
                                     total_cost REAL, total_retail REAL, source TEXT, uploaded_at TEXT, warnings TEXT);
CREATE TABLE IF NOT EXISTS bm_lines (doc_id TEXT, code TEXT, name TEXT, qty REAL, unit_cost REAL, unit_retail REAL, total_cost REAL, total_retail REAL);
CREATE INDEX IF NOT EXISTS ix_bm_lines_doc ON bm_lines(doc_id);
CREATE INDEX IF NOT EXISTS ix_bm_slips_date ON bm_slips(date);
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT);
"""


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def save_or(con, p, source=''):
    """Returns 'new' or 'replaced'."""
    existed = con.execute('SELECT 1 FROM or_days WHERE date=?', (p['date'],)).fetchone() is not None
    con.execute('DELETE FROM or_lines WHERE date=?', (p['date'],))
    con.execute('DELETE FROM or_days WHERE date=?', (p['date'],))
    con.execute('INSERT INTO or_days VALUES (?,?,?,?,?)', (p['date'], p.get('store'), source, _now(), '; '.join(p['warnings'])))
    con.executemany('INSERT INTO or_lines VALUES (?,?,?,?,?,?)',
                    [(p['date'], i['cat'], i['code'], i['name'], i['qty'], i['amt'] or 0) for i in p['items']])
    con.commit()
    return 'replaced' if existed else 'new'


def save_bm(con, p, source='', slip_no=None):
    existed = con.execute('SELECT 1 FROM bm_slips WHERE doc_id=?', (p['doc_id'],)).fetchone() is not None
    con.execute('DELETE FROM bm_lines WHERE doc_id=?', (p['doc_id'],))
    con.execute('DELETE FROM bm_slips WHERE doc_id=?', (p['doc_id'],))
    tc = abs(p['total'][0]) if p.get('total') else sum(i['total_cost'] for i in p['items'])
    tr = abs(p['total'][1]) if p.get('total') and len(p['total']) > 1 else sum(i['total_retail'] for i in p['items'])
    con.execute('INSERT INTO bm_slips VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (p['doc_id'], p.get('slip_id'), slip_no, p['date'], p.get('status'), p.get('store'), tc, tr, source, _now(), '; '.join(p['warnings'])))
    con.executemany('INSERT INTO bm_lines VALUES (?,?,?,?,?,?,?,?)',
                    [(p['doc_id'], i['code'], i['name'], i['qty'], i['unit_cost'], i['unit_retail'], i['total_cost'], i['total_retail']) for i in p['items']])
    con.commit()
    return 'replaced' if existed else 'new'


def or_dates(con):
    return [r[0] for r in con.execute('SELECT date FROM or_days ORDER BY date')]


def or_lines(con, start, end):
    return con.execute('SELECT * FROM or_lines WHERE date BETWEEN ? AND ?', (start, end)).fetchall()


def bm_lines(con, start, end, completed_only=True):
    q = ('SELECT s.date, s.doc_id, s.slip_no, s.status, l.* FROM bm_lines l JOIN bm_slips s ON s.doc_id=l.doc_id '
         'WHERE s.date BETWEEN ? AND ?')
    if completed_only:
        q += " AND UPPER(COALESCE(s.status,'COMPLETED'))='COMPLETED'"
    return con.execute(q, (start, end)).fetchall()


def bm_slips(con, start, end):
    return con.execute('SELECT * FROM bm_slips WHERE date BETWEEN ? AND ? ORDER BY date, doc_id', (start, end)).fetchall()


def coverage(con):
    d = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM or_days').fetchone()
    b = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM bm_slips').fetchone()
    return {'or_days': d[0], 'or_min': d[1], 'or_max': d[2], 'bm_slips': b[0], 'bm_min': b[1], 'bm_max': b[2]}


def ensure_user(con, username, password):
    """Create user if it does not exist yet."""
    if con.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone() is None:
        con.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)',
                    (username, generate_password_hash(password), _now()))
        con.commit()


def verify_user(con, username, password):
    """Return True when username exists and password matches its stored hash."""
    row = con.execute('SELECT password_hash FROM users WHERE username=?', (username,)).fetchone()
    return bool(row and check_password_hash(row['password_hash'], password))
