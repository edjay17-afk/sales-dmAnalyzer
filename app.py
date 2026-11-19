"""BM & sales analyzer: upload OR Sales Monitor + Bad Merchandise PDFs, get the report for every category.

Run:  python app.py   (or double-click run.bat)   then open http://127.0.0.1:5412
Runs only on this PC (127.0.0.1). Uploaded PDFs are read in memory; only parsed lines are stored in data/analyzer.db.
"""
import csv
import glob
import hmac
import io
import math
import os
import re
import secrets
import sys
import webbrowser
from datetime import datetime, timedelta
from threading import Timer

from flask import Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import analysis, charts_svg, db, viewmodel
from analyzer.parsers import ParseError, parse_pdf
from analyzer.pdf_report import (
    build_category_pdf,
    build_fastmoving_pdf,
    build_par_pdf,
    build_pdf,
    build_products_pdf,
    build_top30_pdf,
    build_zip,
    for_group,
)

app = Flask(__name__)


def _load_secret():
    env = os.environ.get('ANALYZER_SECRET')
    if env:
        return env
    sec_path = os.path.join(db.DATA_DIR, '.secret')
    try:
        os.makedirs(db.DATA_DIR, exist_ok=True)
        if os.path.exists(sec_path):
            with open(sec_path, 'r', encoding='utf-8') as f:
                val = f.read().strip()
                if val:
                    return val
        val = secrets.token_hex(32)
        with open(sec_path, 'w', encoding='utf-8') as f:
            f.write(val)
        return val
    except OSError:
        return os.urandom(24)


app.secret_key = _load_secret()
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True
PORT = int(os.environ.get('ANALYZER_PORT', 5412))


def get_db():
    if '_db' not in g:
        g._db = db.connect()
    return g._db


@app.teardown_appcontext
def close_db(exc=None):
    con = g.pop('_db', None)
    if con is not None:
        con.close()


def _ensure_default_user():
    con = db.connect()
    try:
        if db.user_count(con) == 0:
            user = os.environ.get('ANALYZER_ADMIN_USER') or '711pardo'
            pw = os.environ.get('ANALYZER_ADMIN_PASS') or 'pardo6216'
            db.ensure_user(con, user, pw)
    finally:
        con.close()


_ensure_default_user()


def _csrf_token():
    tok = session.get('_csrf')
    if not tok:
        tok = secrets.token_urlsafe(24)
        session['_csrf'] = tok
    return tok


@app.context_processor
def inject_globals():
    return {'csrf_token': _csrf_token()}


def _safe_next(target):
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return url_for('home')


@app.before_request
def security_guard():
    if request.endpoint in ('static',) or request.endpoint is None:
        return None
    if request.method == 'POST':
        expected = session.get('_csrf') or ''
        supplied = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token') or ''
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            abort(400, 'Invalid or missing CSRF token. Reload the page and try again.')
    if request.endpoint == 'login':
        return None
    if 'user' not in session:
        nxt = request.full_path.rstrip('?') if request.query_string else request.path
        return redirect(url_for('login', next=nxt))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('home'))
    err = None
    username = ''
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        con = get_db()
        if db.verify_user(con, username, password):
            session['user'] = username
            return redirect(_safe_next(request.form.get('next') or request.args.get('next')))
        err = 'Invalid username or password.'
    return render_template('login.html', err=err, username=username, next_url=request.args.get('next', ''))


@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.template_filter('php')
def f_php(v, d=2):
    return f"PHP {v:,.{d}f}"


@app.template_filter('dfmt')
def f_dfmt(iso):
    d = datetime.strptime(iso, '%Y-%m-%d')
    return f"{d:%b} {d.day}, {d.year}"


@app.template_filter('n')
def f_n(v, d=0):
    return f"{v:,.{d}f}"


@app.template_filter('pct')
def f_pct(a, b=None):
    v = a if b is None else (0 if not b else 100.0 * a / b)
    return viewmodel.pct1(v)


@app.template_filter('gcls')
def f_gcls(g):
    return {'Hot Meals': 'hot', 'Fresh Food': 'fresh', 'Crunch Time': 'crunch'}.get(g, 'other')


def _default_period(con, store=None):
    dates = db.or_dates(con, store=store)
    if not dates:
        return None, None
    end = dates[-1]
    start = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=6)).strftime('%Y-%m-%d')
    return start, end


def _valid_date(s):
    try:
        datetime.strptime(s or '', '%Y-%m-%d')
        return s
    except ValueError:
        return None


def _valid_store(con, s):
    s = (s or '').strip()
    return s if s and s in db.stores(con) else None


@app.after_request
def no_cache_html(resp):
    if resp.mimetype == 'text/html':
        resp.headers['Cache-Control'] = 'no-store'
    return resp


def _ingest_pdf(con, source_bytes_or_path, name, existing_stores):
    p = parse_pdf(source_bytes_or_path)
    store = (p.get('store') or '').strip()
    if store and existing_stores and store not in existing_stores:
        p['warnings'].append(f"Store '{store}' differs from existing store(s) ({', '.join(sorted(existing_stores))})")
    if p['kind'] == 'or':
        status = db.save_or(con, p, name)
        return 'or', status, p['date'], p['warnings']
    m = re.search(r'BadMerchandise\((\d+)\)', name)
    slip_no = int(m.group(1)) if m else None
    status = db.save_bm(con, p, name, slip_no=slip_no)
    return 'bm', status, p['date'], p['warnings']


@app.route('/')
def home():
    con = get_db()
    stores = db.stores(con)
    store = _valid_store(con, request.args.get('store'))
    dstart, dend = _default_period(con, store=store)
    start = _valid_date(request.args.get('start')) or dstart
    end = _valid_date(request.args.get('end')) or dend
    return render_template(
        'index.html',
        cov=db.coverage(con, store=store),
        start=start,
        end=end,
        strip=viewmodel.coverage_strip(con, store=store),
        stores=stores,
        store=store,
        watch_folder=db.get_settings(con).get('watch_folder', ''),
    )


@app.route('/upload', methods=['POST'])
def upload():
    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        flash(('err', 'No files chosen.'))
        return redirect(url_for('home'))
    con = get_db()
    existing_stores = set(db.stores(con))
    or_dates, bm_dates = [], []
    counts = {'or_new': 0, 'or_replaced': 0, 'bm_new': 0, 'bm_replaced': 0, 'failed': 0}
    for f in files:
        name = os.path.basename(f.filename)
        if not name.lower().endswith('.pdf'):
            flash(('err', f'{name}: not a PDF, skipped.')); counts['failed'] += 1
            continue
        try:
            kind, st, dt, warns = _ingest_pdf(con, io.BytesIO(f.read()), name, existing_stores)
        except ParseError as e:
            flash(('err', f'{name}: {e}.')); counts['failed'] += 1
            continue
        counts[f'{kind}_{st}'] += 1
        (or_dates if kind == 'or' else bm_dates).append(dt)
        for w in warns:
            flash(('warn', f'{name}: {w}'))
    parts = []
    if counts['or_new'] or counts['or_replaced']:
        parts.append(f"{counts['or_new'] + counts['or_replaced']} OR day(s)")
    if counts['bm_new'] or counts['bm_replaced']:
        parts.append(f"{counts['bm_new'] + counts['bm_replaced']} BM slip(s)")
    replaced = counts['or_replaced'] + counts['bm_replaced']
    if parts:
        flash(('ok', f"Read {' and '.join(parts)}" + (f" ({replaced} already on file were replaced)." if replaced else '.')))
    dates = or_dates or bm_dates
    if not dates:
        return redirect(url_for('home'))
    return redirect(url_for('home', start=min(dates), end=max(dates)))


def _params():
    con = get_db()
    store = _valid_store(con, request.args.get('store'))
    dstart, dend = _default_period(con, store=store)
    start = _valid_date(request.args.get('start')) or dstart
    end = _valid_date(request.args.get('end')) or dend
    return con, start, end, request.args.getlist('cat'), store


def _analyze_or_redirect(con, start, end, cat, store=None):
    if not start:
        flash(('err', 'Nothing uploaded yet.'))
        return None
    try:
        return analysis.analyze(con, start, end, cat, store=store)
    except analysis.NoData as e:
        flash(('err', str(e)))
        return None


def _top_per_cat(items, limit=30):
    counts = {}
    out = []
    for idx, r in enumerate(items):
        g = r['group']
        c = counts.get(g, 0)
        if c < limit:
            counts[g] = c + 1
            out.append({'row': r, 'top': idx < limit, 'rank': idx + 1, 'grank': c + 1})
    return out


@app.route('/report')
def report():
    con, start, end, cat, store = _params()
    A = _analyze_or_redirect(con, start, end, cat, store=store)
    if A is None:
        return redirect(url_for('home'))
    rows = A['rows']
    sold = [r for r in rows if r['sold'] > 0]
    top_bm = sorted([r for r in rows if r['bm'] > 0], key=lambda r: (-r['bmcost'], -r['bm']))
    top_units = sorted(sold, key=lambda r: (-r['sold'], -r['amt'], r['name']))
    top_sales = sorted(sold, key=lambda r: (-r['amt'], r['name']))
    S = {
        'top_bm': top_bm,
        'top_bm_cat': _top_per_cat(top_bm, 30),
        'low_bm': sorted([r for r in rows if r['bm'] == 1], key=lambda r: -r['bmcost']),
        'top_units': top_units,
        'top_units_cat': _top_per_cat(top_units, 30),
        'top_sales': top_sales,
        'top_sales_cat': _top_per_cat(top_sales, 30),
        'full': sorted(rows, key=lambda r: (-r['sold'], -r['amt'], r['name'])),
    }
    order_total = sum(r['order'] for r in rows)
    net_order_total = sum(r['net_order'] for r in rows)
    head_title, head_sub = viewmodel.headline(A)
    maxes = {'bm': max([r['bmcost'] for r in S['top_bm'][:30]] or [1]),
             'units': max([r['sold'] for r in S['top_units'][:30]] or [1]),
             'sales': max([r['amt'] for r in S['top_sales'][:30]] or [1]),
             'catsales': max([A['tot'][g]['sales'] for g in A['groups']] or [1])}
    return render_template('report.html', A=A, S=S, cov=db.coverage(con, store=store), maxes=maxes,
                           stores=db.stores(con), store=store,
                           head_title=head_title, head_sub=head_sub,
                           kpis=viewmodel.kpis(A, order_total, net_order_total),
                           brief=viewmodel.order_brief(rows),
                           cat_orders=viewmodel.category_orders(A),
                           legend=[(s, charts_svg.series_class(s)) for s in A['series']],
                           sales_svg=charts_svg.daily_svg(A, 'sales', 'Daily OR sales (PHP)'),
                           bm_svg=charts_svg.daily_svg(A, 'bmc', 'Daily BM cost (PHP)'),
                           wk_units_svg=charts_svg.weekday_svg(A, 'units', 'Average units sold per weekday'),
                           wk_sales_svg=charts_svg.weekday_svg(A, 'sales', 'Average sales per weekday (PHP)'))


@app.route('/report.pdf')
def report_pdf():
    con, start, end, cat, store = _params()
    A = _analyze_or_redirect(con, start, end, cat, store=store)
    if A is None:
        return redirect(url_for('home'))
    suffix = '' if A['sel'] is None else '_' + ''.join(c if c.isalnum() else '-' for c in '+'.join(A['scope_list']))[:50]
    return send_file(io.BytesIO(build_pdf(A)), mimetype='application/pdf', as_attachment=True,
                     download_name=f"BM_Sales_Analysis_{start}_to_{end}{suffix}.pdf")


@app.route('/report-par.pdf')
def report_par_pdf():
    con, start, end, cat, store = _params()
    A = _analyze_or_redirect(con, start, end, cat, store=store)
    if A is None:
        return redirect(url_for('home'))
    suffix = '' if A['sel'] is None else '_' + ''.join(c if c.isalnum() else '-' for c in '+'.join(A['scope_list']))[:50]
    return send_file(io.BytesIO(build_par_pdf(A)), mimetype='application/pdf', as_attachment=True,
                     download_name=f"Daily_Par_Order_Sheet_{start}_to_{end}{suffix}.pdf")


def _per_category_download(builder, stem, combined=None):
    """One PDF for a single category, or a ZIP (bulk download) with one PDF per category when several are selected.
    With ?combined=1 the selected categories come as a single PDF instead (built by `combined`, else `builder`)."""
    con, start, end, cat, store = _params()
    A = _analyze_or_redirect(con, start, end, cat, store=store)
    if A is None:
        return redirect(url_for('home'))
    suffix = '' if A['sel'] is None else '_' + ''.join(c if c.isalnum() else '-' for c in '+'.join(A['scope_list']))[:50]
    if request.args.get('combined') and len(A['groups']) > 1:
        return send_file(io.BytesIO((combined or builder)(A)), mimetype='application/pdf', as_attachment=True,
                         download_name=f"BM_Sales_{stem}_{start}_to_{end}{suffix}.pdf")
    if len(A['groups']) == 1:
        g = A['groups'][0]
        name = ''.join(c if c.isalnum() else '-' for c in g).strip('-')
        return send_file(io.BytesIO(builder(for_group(A, g))), mimetype='application/pdf', as_attachment=True,
                         download_name=f"{name}_{stem}_{start}_to_{end}.pdf")
    return send_file(io.BytesIO(build_zip(A, builder, stem)), mimetype='application/zip', as_attachment=True,
                     download_name=f"BM_Sales_{stem}_By_Category_{start}_to_{end}{suffix}.zip")


@app.route('/report-top30.pdf')
def report_top30_pdf():
    return _per_category_download(build_top30_pdf, 'Top30')


@app.route('/report-fastmoving.pdf')
def report_fastmoving_pdf():
    return _per_category_download(build_fastmoving_pdf, 'Fast_Moving')


@app.route('/report-products')
def report_products_pdf():
    return _per_category_download(lambda B: build_category_pdf(B, B['groups'][0]), 'All_Products', build_products_pdf)


@app.route('/report.csv')
def report_csv():
    con, start, end, cat, store = _params()
    A = _analyze_or_redirect(con, start, end, cat, store=store)
    if A is None:
        return redirect(url_for('home'))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        'Category', 'Item code', 'Barcode', 'Product', 'Units sold', 'OR sales (PHP)', 'Days sold', 'Per day',
        'Baseline units per week', 'BM units', 'BM cost (PHP)', 'BM retail (PHP)', 'Waste rate %',
        'Unit cost (PHP)', 'Margin %', 'Action', 'Est. received per 7 days', 'Suggested order next 7 days',
        'On hand', 'Pack size', 'Net order next 7 days', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun',
    ])
    for r in sorted(A['rows'], key=lambda r: (r['group'], -r['sold'], r['name'])):
        w.writerow([
            r['group'], r['code'], r['barcode'], r['name'], f"{r['sold']:g}", f"{r['amt']:.2f}", r['days'], f"{r['per_day']:.2f}",
            f"{r['base_wk']:.2f}" if r['inbase'] else '', f"{r['bm']:g}", f"{r['bmcost']:.2f}", f"{r['bmretail']:.2f}",
            f"{100 * r['rate']:.1f}", f"{r['unit_cost']:.2f}" if r['unit_cost'] is not None else '',
            f"{100 * r['margin_pct']:.1f}" if r['margin_pct'] is not None else '',
            r['action'], f"{r['est_received'] * 7 / A['n']:.1f}", r['order'],
            f"{r['on_hand']:g}" if r['on_hand'] is not None else '', r['pack_size'], r['net_order'],
            *r['daily_pars'],
        ])
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=BM_Sales_Products_{start}_to_{end}.csv'})


@app.route('/order-list.csv')
def order_list_csv():
    con, start, end, cat, store = _params()
    A = _analyze_or_redirect(con, start, end, cat, store=store)
    if A is None:
        return redirect(url_for('home'))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Category', 'Item code', 'Barcode', 'Product', 'Action', 'Raw 7d', 'On hand', 'Pack size',
                'Net order 7d', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])
    items = [r for r in A['rows'] if r['net_order'] > 0 or r['action'] == 'PAUSE']
    for r in sorted(items, key=lambda r: (r['group'], -r['net_order'], r['name'])):
        w.writerow([
            r['group'], r['code'], r['barcode'], r['name'], r['action'], r['order'],
            f"{r['on_hand']:g}" if r['on_hand'] is not None else '', r['pack_size'], r['net_order'],
            *r['daily_pars'],
        ])
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=Order_List_{start}_to_{end}.csv'})


@app.route('/api/product-meta', methods=['POST'])
def api_product_meta():
    con = get_db()
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()
    if not code:
        return jsonify({'ok': False, 'error': 'Missing product code.'}), 400
    kwargs = {}
    if 'cat_override' in data:
        kwargs['cat_override'] = (data.get('cat_override') or '').strip() or None
    if 'pack_size' in data:
        try:
            kwargs['pack_size'] = max(1, int(data['pack_size']))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid pack size.'}), 400
    if 'on_hand' in data:
        oh_raw = data['on_hand']
        if oh_raw in ('', None):
            kwargs['on_hand'] = None
        else:
            try:
                kwargs['on_hand'] = max(0.0, float(oh_raw))
            except (TypeError, ValueError):
                return jsonify({'ok': False, 'error': 'Invalid on-hand count.'}), 400
    db.upsert_product_meta(con, code, **kwargs)
    meta = db.get_product_meta(con).get(code, {})
    resp = {'ok': True, 'code': code, 'on_hand': meta.get('on_hand'), 'pack_size': meta.get('pack_size', 1), 'cat_override': meta.get('cat_override')}
    if 'raw_order' in data:
        try:
            raw_order = max(0, int(data['raw_order']))
        except (TypeError, ValueError):
            raw_order = 0
        ps = max(1, int(meta.get('pack_size') or 1))
        oh = meta.get('on_hand')
        if raw_order == 0:
            net = 0
        else:
            rem = max(0.0, raw_order - oh) if oh is not None else float(raw_order)
            net = 0 if rem <= 0 else (int(math.ceil(rem / ps) * ps) if ps > 1 else int(math.ceil(rem)))
        resp['net_order'] = net
    return jsonify(resp)


@app.route('/product/<code>', methods=['GET', 'POST'])
def product_page(code):
    con = get_db()
    store = _valid_store(con, request.args.get('store'))
    end = _valid_date(request.args.get('end'))
    try:
        days = min(180, max(14, int(request.args.get('days', 90))))
    except ValueError:
        days = 90
    if request.method == 'POST':
        cat_ov = (request.form.get('cat_override') or '').strip() or None
        try:
            pack_size = max(1, int(request.form.get('pack_size') or 1))
        except ValueError:
            pack_size = 1
        oh_s = (request.form.get('on_hand') or '').strip()
        try:
            on_hand = max(0.0, float(oh_s)) if oh_s != '' else None
        except ValueError:
            on_hand = None
        db.upsert_product_meta(con, code, cat_override=cat_ov, pack_size=pack_size, on_hand=on_hand)
        flash(('ok', f'Saved settings for {code}.'))
        return redirect(url_for('product_page', code=code, end=end, days=days, store=store))
    try:
        D = analysis.product_detail(con, code, end=end, days=days, store=store)
    except analysis.NoData as e:
        flash(('err', str(e)))
        return redirect(url_for('home'))
    return render_template(
        'product.html',
        D=D,
        store=store,
        daily_svg=charts_svg.product_daily_svg(D, 'Daily units sold & BM'),
        wk_svg=charts_svg.product_weekday_svg(D, 'Average units sold per weekday'),
    )


@app.route('/trends')
def trends():
    con = get_db()
    store = _valid_store(con, request.args.get('store'))
    end = _valid_date(request.args.get('end'))
    try:
        weeks = min(26, max(4, int(request.args.get('weeks', 12))))
    except ValueError:
        weeks = 12
    cat = request.args.getlist('cat')
    try:
        T = analysis.weekly_trends(con, end=end, weeks=weeks, scope=cat, store=store)
    except analysis.NoData as e:
        flash(('err', str(e)))
        return redirect(url_for('home'))
    return render_template(
        'trends.html',
        T=T,
        cov=db.coverage(con, store=store),
        stores=db.stores(con),
        store=store,
        legend=[(s, charts_svg.series_class(s)) for s in T['series']],
        sales_svg=charts_svg.trend_svg(T, 'sales', 'Weekly OR sales (PHP)'),
        bm_svg=charts_svg.trend_svg(T, 'bmc', 'Weekly BM cost (PHP)'),
        rate_svg=charts_svg.trend_rate_svg(T, 'Weekly BM % of sales'),
    )


@app.route('/history')
def history():
    con = get_db()
    store = _valid_store(con, request.args.get('store'))
    or_list = db.or_days_list(con, store=store)
    bm_list = db.bm_slips_list(con, store=store)
    cfg = db.get_settings(con)
    cat = analysis.Catalog(con)
    uncat = []
    seen = set()
    for r in con.execute('SELECT l.code, l.name, COUNT(*) AS slips, SUM(l.qty) AS qty, SUM(l.total_cost) AS cost FROM bm_lines l GROUP BY l.code ORDER BY cost DESC'):
        grp, _ = cat.bm_group(r['code'], r['name'])
        if grp == 'Uncategorized' and r['code'] not in seen:
            seen.add(r['code'])
            uncat.append(dict(r))
    avail_groups = sorted({analysis.group_name(r[0]) for r in con.execute('SELECT DISTINCT cat FROM or_lines') if analysis.cat_prefix(r[0]) not in analysis.EXCLUDE} | set(analysis.FOCUS))
    return render_template(
        'history.html',
        cov=db.coverage(con, store=store),
        stores=db.stores(con),
        store=store,
        or_days=or_list,
        bm_slips=bm_list,
        uncat=uncat,
        avail_groups=avail_groups,
        watch_folder=cfg.get('watch_folder', ''),
    )


@app.route('/history/delete-or', methods=['POST'])
def history_delete_or():
    con = get_db()
    dt = _valid_date(request.form.get('date'))
    if dt and db.delete_or_day(con, dt):
        flash(('ok', f'Deleted OR day {dt}.'))
    else:
        flash(('err', 'OR day not found.'))
    return redirect(url_for('history'))


@app.route('/history/delete-bm', methods=['POST'])
def history_delete_bm():
    con = get_db()
    doc_id = (request.form.get('doc_id') or '').strip()
    if doc_id and db.delete_bm_slip(con, doc_id):
        flash(('ok', f'Deleted BM slip {doc_id}.'))
    else:
        flash(('err', 'BM slip not found.'))
    return redirect(url_for('history'))


@app.route('/history/map-category', methods=['POST'])
def history_map_category():
    con = get_db()
    code = (request.form.get('code') or '').strip()
    grp = (request.form.get('cat_override') or '').strip() or None
    if code:
        db.upsert_product_meta(con, code, cat_override=grp)
        flash(('ok', f'Mapped {code} to {grp or "auto"}.'))
    return redirect(request.referrer or url_for('history'))


@app.route('/history/scan', methods=['POST'])
def history_scan():
    con = get_db()
    folder = (request.form.get('folder') or db.get_settings(con).get('watch_folder') or '').strip()
    rescan = bool(request.form.get('rescan'))
    if not folder or not os.path.isdir(folder):
        flash(('err', 'Watch folder does not exist on this PC. Check the folder path in Settings.'))
        return redirect(request.referrer or url_for('history'))
    db.save_settings(con, {'watch_folder': folder})
    known_sources = set()
    if not rescan:
        known_sources = {r[0] for r in con.execute('SELECT source FROM or_days UNION SELECT source FROM bm_slips') if r[0]}
    existing_stores = set(db.stores(con))
    pdfs = sorted(glob.glob(os.path.join(folder, '*.pdf')))
    added = skipped = failed = 0
    for path in pdfs:
        name = os.path.basename(path)
        if not rescan and name in known_sources:
            skipped += 1
            continue
        try:
            _kind, _st, _dt, warns = _ingest_pdf(con, path, name, existing_stores)
            added += 1
            for w in warns:
                flash(('warn', f'{name}: {w}'))
        except ParseError as e:
            failed += 1
            flash(('err', f'{name}: {e}.'))
    flash(('ok', f'Folder scan finished: {added} imported, {skipped} already on file, {failed} failed.'))
    return redirect(request.referrer or url_for('history'))


@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    con = get_db()
    if request.method == 'POST':
        if request.form.get('reset'):
            db.save_settings(con, db.DEFAULT_SETTINGS)
            flash(('ok', 'Model settings reset to defaults.'))
            return redirect(url_for('settings_page'))
        try:
            updates = {
                'baseline_days': str(max(7, min(180, int(request.form.get('baseline_days', 31))))),
                'weekday_days': str(max(7, min(180, int(request.form.get('weekday_days', 45))))),
                'regular_days': str(max(1, min(60, int(request.form.get('regular_days', 6))))),
                'cut_rate': f"{max(0.01, min(1.0, float(request.form.get('cut_rate', 25)) / 100.0)):.4f}",
                'cut_factor': f"{max(0.1, min(1.0, float(request.form.get('cut_factor', 0.70)))):.2f}",
                'trim_rate': f"{max(0.01, min(1.0, float(request.form.get('trim_rate', 10)) / 100.0)):.4f}",
                'trim_factor': f"{max(0.1, min(1.0, float(request.form.get('trim_factor', 0.85)))):.2f}",
                'increase_rate': f"{max(0.0, min(0.5, float(request.form.get('increase_rate', 3)) / 100.0)):.4f}",
                'increase_min_demand': f"{max(1.0, float(request.form.get('increase_min_demand', 5))):.1f}",
                'increase_factor': f"{max(1.0, min(2.0, float(request.form.get('increase_factor', 1.10)))):.2f}",
                'perishable_cats': ','.join(x.strip() for x in request.form.get('perishable_cats', '').split(',') if x.strip()),
                'watch_folder': (request.form.get('watch_folder') or '').strip(),
            }
            if float(updates['trim_rate']) >= float(updates['cut_rate']):
                raise ValueError('Trim waste % must be lower than Cut waste %.')
        except ValueError as e:
            flash(('err', f'Invalid setting: {e}'))
            return redirect(url_for('settings_page'))
        db.save_settings(con, updates)
        flash(('ok', 'Settings saved.'))
        return redirect(url_for('settings_page'))
    cfg = db.get_settings(con)
    return render_template('settings.html', cfg=cfg)


@app.route('/settings/password', methods=['POST'])
def change_password():
    con = get_db()
    user = session['user']
    cur_pw = request.form.get('current_password') or ''
    new_pw = request.form.get('new_password') or ''
    confirm_pw = request.form.get('confirm_password') or ''
    if not db.verify_user(con, user, cur_pw):
        flash(('err', 'Current password is incorrect.'))
    elif len(new_pw) < 6:
        flash(('err', 'New password must be at least 6 characters.'))
    elif new_pw != confirm_pw:
        flash(('err', 'New passwords do not match.'))
    else:
        db.update_password(con, user, new_pw)
        flash(('ok', 'Password updated.'))
    return redirect(url_for('settings_page'))


if __name__ == '__main__':
    import socket
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(('127.0.0.1', PORT)) == 0:
            print(f'Something is already running on http://127.0.0.1:{PORT}. If it is the analyzer, just open that address.')
            if '--no-browser' not in sys.argv:
                webbrowser.open(f'http://127.0.0.1:{PORT}')
            sys.exit(1)
    if '--no-browser' not in sys.argv:
        Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
