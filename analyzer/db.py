"""SQLite storage. Parsed lines are kept, not the PDFs. Re-uploading a day or slip replaces it."""
import os
import sqlite3
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DB_PATH = os.environ.get('ANALYZER_DB') or os.path.join(DATA_DIR, 'analyzer.db')

DEFAULT_SETTINGS = {
    'baseline_days': '31',
    'weekday_days': '45',
    'regular_days': '6',
    'cut_rate': '0.25',
    'cut_factor': '0.70',
    'trim_rate': '0.10',
    'trim_factor': '0.85',
    'increase_rate': '0.03',
    'increase_min_demand': '5',
    'increase_factor': '1.10',
    'perishable_cats': '25,27,36,37,39,40,41,43,46',
    'watch_folder': '',
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS or_days (date TEXT PRIMARY KEY, store TEXT, source TEXT, uploaded_at TEXT, warnings TEXT);
CREATE TABLE IF NOT EXISTS or_lines (date TEXT, cat TEXT, code TEXT, name TEXT, qty REAL, amt REAL, barcode TEXT);
CREATE INDEX IF NOT EXISTS ix_or_lines_date ON or_lines(date);
CREATE INDEX IF NOT EXISTS ix_or_lines_code ON or_lines(code);
CREATE TABLE IF NOT EXISTS bm_slips (doc_id TEXT PRIMARY KEY, slip_id TEXT, slip_no INTEGER, date TEXT, status TEXT, store TEXT,
                                     total_cost REAL, total_retail REAL, source TEXT, uploaded_at TEXT, warnings TEXT);
CREATE TABLE IF NOT EXISTS bm_lines (doc_id TEXT, code TEXT, name TEXT, qty REAL, unit_cost REAL, unit_retail REAL, total_cost REAL, total_retail REAL);
CREATE INDEX IF NOT EXISTS ix_bm_lines_doc ON bm_lines(doc_id);
CREATE INDEX IF NOT EXISTS ix_bm_lines_code ON bm_lines(code);
CREATE INDEX IF NOT EXISTS ix_bm_slips_date ON bm_slips(date);
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS product_meta (code TEXT PRIMARY KEY, barcode TEXT, cat_override TEXT, pack_size INTEGER DEFAULT 1, on_hand REAL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def _migrate(con):
    cols = {r['name'] for r in con.execute('PRAGMA table_info(or_lines)')}
    if 'barcode' not in cols:
        con.execute('ALTER TABLE or_lines ADD COLUMN barcode TEXT')
        con.commit()


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def save_or(con, p, source=''):
    """Returns 'new' or 'replaced'."""
    existed = con.execute('SELECT 1 FROM or_days WHERE date=?', (p['date'],)).fetchone() is not None
    con.execute('DELETE FROM or_lines WHERE date=?', (p['date'],))
    con.execute('DELETE FROM or_days WHERE date=?', (p['date'],))
    con.execute('INSERT INTO or_days VALUES (?,?,?,?,?)', (p['date'], p.get('store'), source, _now(), '; '.join(p['warnings'])))
    con.executemany(
        'INSERT INTO or_lines (date, cat, code, name, qty, amt, barcode) VALUES (?,?,?,?,?,?,?)',
        [(p['date'], i['cat'], i['code'], i['name'], i['qty'], i['amt'] or 0, i.get('barcode') or None) for i in p['items']],
    )
    barcodes = [(i['code'], i['barcode'], _now()) for i in p['items'] if i.get('barcode')]
    if barcodes:
        con.executemany(
            'INSERT INTO product_meta (code, barcode, updated_at) VALUES (?,?,?) '
            'ON CONFLICT(code) DO UPDATE SET barcode=excluded.barcode, updated_at=excluded.updated_at',
            barcodes,
        )
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


def stores(con):
    rows = con.execute(
        'SELECT DISTINCT store FROM or_days WHERE store IS NOT NULL AND store<>"" '
        'UNION SELECT DISTINCT store FROM bm_slips WHERE store IS NOT NULL AND store<>"" ORDER BY store'
    ).fetchall()
    return [r[0] for r in rows]


def or_dates(con, store=None):
    if store:
        return [r[0] for r in con.execute('SELECT date FROM or_days WHERE store=? ORDER BY date', (store,))]
    return [r[0] for r in con.execute('SELECT date FROM or_days ORDER BY date')]


def or_lines(con, start, end, store=None):
    if store:
        return con.execute(
            'SELECT l.* FROM or_lines l JOIN or_days d ON d.date=l.date '
            'WHERE l.date BETWEEN ? AND ? AND d.store=?',
            (start, end, store),
        ).fetchall()
    return con.execute('SELECT * FROM or_lines WHERE date BETWEEN ? AND ?', (start, end)).fetchall()


def bm_lines(con, start, end, completed_only=True, store=None):
    q = ('SELECT s.date, s.doc_id, s.slip_no, s.status, s.store, l.* FROM bm_lines l JOIN bm_slips s ON s.doc_id=l.doc_id '
         'WHERE s.date BETWEEN ? AND ?')
    params = [start, end]
    if completed_only:
        q += " AND UPPER(COALESCE(s.status,'COMPLETED'))='COMPLETED'"
    if store:
        q += ' AND s.store=?'
        params.append(store)
    return con.execute(q, params).fetchall()


def bm_slips(con, start, end, store=None):
    if store:
        return con.execute('SELECT * FROM bm_slips WHERE date BETWEEN ? AND ? AND store=? ORDER BY date, doc_id', (start, end, store)).fetchall()
    return con.execute('SELECT * FROM bm_slips WHERE date BETWEEN ? AND ? ORDER BY date, doc_id', (start, end)).fetchall()


def or_days_list(con, store=None):
    q = ('SELECT d.*, (SELECT COUNT(*) FROM or_lines l WHERE l.date=d.date) AS line_count, '
         '(SELECT COALESCE(SUM(amt),0) FROM or_lines l WHERE l.date=d.date AND l.cat NOT LIKE "EX-%") AS sales_total '
         'FROM or_days d')
    if store:
        return con.execute(q + ' WHERE d.store=? ORDER BY d.date DESC', (store,)).fetchall()
    return con.execute(q + ' ORDER BY d.date DESC').fetchall()


def bm_slips_list(con, store=None):
    q = 'SELECT s.*, (SELECT COUNT(*) FROM bm_lines l WHERE l.doc_id=s.doc_id) AS line_count FROM bm_slips s'
    if store:
        return con.execute(q + ' WHERE s.store=? ORDER BY s.date DESC, s.doc_id DESC', (store,)).fetchall()
    return con.execute(q + ' ORDER BY s.date DESC, s.doc_id DESC').fetchall()


def delete_or_day(con, date):
    cur = con.execute('DELETE FROM or_days WHERE date=?', (date,))
    con.execute('DELETE FROM or_lines WHERE date=?', (date,))
    con.commit()
    return cur.rowcount > 0


def delete_bm_slip(con, doc_id):
    cur = con.execute('DELETE FROM bm_slips WHERE doc_id=?', (doc_id,))
    con.execute('DELETE FROM bm_lines WHERE doc_id=?', (doc_id,))
    con.commit()
    return cur.rowcount > 0


def coverage(con, store=None):
    if store:
        d = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM or_days WHERE store=?', (store,)).fetchone()
        b = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM bm_slips WHERE store=?', (store,)).fetchone()
    else:
        d = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM or_days').fetchone()
        b = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM bm_slips').fetchone()
    return {'or_days': d[0], 'or_min': d[1], 'or_max': d[2], 'bm_slips': b[0], 'bm_min': b[1], 'bm_max': b[2]}


def get_product_meta(con):
    return {r['code']: dict(r) for r in con.execute('SELECT * FROM product_meta')}


def upsert_product_meta(con, code, cat_override=..., pack_size=..., on_hand=...):
    cur = con.execute('SELECT * FROM product_meta WHERE code=?', (code,)).fetchone()
    existing = dict(cur) if cur else {}
    co = existing.get('cat_override') if cat_override is ... else (cat_override or None)
    ps = existing.get('pack_size', 1) if pack_size is ... else max(1, int(pack_size or 1))
    oh = existing.get('on_hand') if on_hand is ... else on_hand
    bc = existing.get('barcode')
    con.execute(
        'INSERT INTO product_meta (code, barcode, cat_override, pack_size, on_hand, updated_at) VALUES (?,?,?,?,?,?) '
        'ON CONFLICT(code) DO UPDATE SET cat_override=excluded.cat_override, pack_size=excluded.pack_size, '
        'on_hand=excluded.on_hand, updated_at=excluded.updated_at',
        (code, bc, co, ps, oh, _now()),
    )
    con.commit()


def get_settings(con):
    out = dict(DEFAULT_SETTINGS)
    for r in con.execute('SELECT key, value FROM settings'):
        if r['key'] in out and r['value'] is not None:
            out[r['key']] = r['value']
    return out


def save_settings(con, updates):
    for k, v in updates.items():
        if k in DEFAULT_SETTINGS:
            con.execute('INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, str(v)))
    con.commit()


def ensure_user(con, username, password):
    """Create user if it does not exist yet."""
    if con.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone() is None:
        con.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)',
                    (username, generate_password_hash(password), _now()))
        con.commit()


def user_count(con):
    return con.execute('SELECT COUNT(*) FROM users').fetchone()[0]


def verify_user(con, username, password):
    """Return True when username exists and password matches its stored hash."""
    row = con.execute('SELECT password_hash FROM users WHERE username=?', (username,)).fetchone()
    return bool(row and check_password_hash(row['password_hash'], password))


def update_password(con, username, new_password):
    cur = con.execute('UPDATE users SET password_hash=? WHERE username=?', (generate_password_hash(new_password), username))
    con.commit()
    return cur.rowcount > 0
