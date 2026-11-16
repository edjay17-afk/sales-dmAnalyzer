"""BM & sales analyzer: upload OR Sales Monitor + Bad Merchandise PDFs, get the report for every category.

Run:  python app.py   (or double-click run.bat)   then open http://127.0.0.1:5412
Runs only on this PC (127.0.0.1). Uploaded PDFs are read in memory; only parsed lines are stored in data/analyzer.db.
"""
import csv
import io
import os
import sys
import webbrowser
from datetime import datetime, timedelta
from threading import Timer

from flask import Flask, Response, flash, redirect, render_template, request, send_file, session, url_for

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import analysis, charts_svg, db, viewmodel
from analyzer.parsers import ParseError, parse_pdf
from analyzer.pdf_report import build_pdf

app = Flask(__name__)
app.secret_key = os.environ.get('ANALYZER_SECRET') or os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True
PORT = int(os.environ.get('ANALYZER_PORT', 5412))


def _ensure_default_user():
    con = db.connect()
    try:
        db.ensure_user(con, '711pardo', 'pardo6216')
    finally:
        con.close()


_ensure_default_user()


def _safe_next(target):
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return url_for('home')


@app.before_request
def require_login():
    if request.endpoint in ('login', 'static') or request.endpoint is None:
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
        con = db.connect()
        try:
            ok = db.verify_user(con, username, password)
        finally:
            con.close()
        if ok:
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


def _default_period(con):
    dates = db.or_dates(con)
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


@app.after_request
def no_cache_html(resp):
    if resp.mimetype == 'text/html':
        resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/')
def home():
    con = db.connect()
    dstart, dend = _default_period(con)
    start = _valid_date(request.args.get('start')) or dstart
    end = _valid_date(request.args.get('end')) or dend
    return render_template('index.html', cov=db.coverage(con), start=start, end=end, strip=viewmodel.coverage_strip(con))


@app.route('/upload', methods=['POST'])
def upload():
    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        flash(('err', 'No files chosen.'))
        return redirect(url_for('home'))
    con = db.connect()
    or_dates, bm_dates = [], []
    counts = {'or_new': 0, 'or_replaced': 0, 'bm_new': 0, 'bm_replaced': 0, 'failed': 0}
    for f in files:
        name = os.path.basename(f.filename)
        if not name.lower().endswith('.pdf'):
            flash(('err', f'{name}: not a PDF, skipped.')); counts['failed'] += 1
            continue
        try:
            p = parse_pdf(io.BytesIO(f.read()))
        except ParseError as e:
            flash(('err', f'{name}: {e}.')); counts['failed'] += 1
            continue
        if p['kind'] == 'or':
            counts['or_' + db.save_or(con, p, name)] += 1
            or_dates.append(p['date'])
        else:
            counts['bm_' + db.save_bm(con, p, name)] += 1
            bm_dates.append(p['date'])
        for w in p['warnings']:
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
    con = db.connect()
    dstart, dend = _default_period(con)
    start = _valid_date(request.args.get('start')) or dstart
    end = _valid_date(request.args.get('end')) or dend
    return con, start, end, request.args.getlist('cat')


def _analyze_or_redirect(con, start, end, cat):
    if not start:
        flash(('err', 'Nothing uploaded yet.'))
        return None
    try:
        return analysis.analyze(con, start, end, cat)
    except analysis.NoData as e:
        flash(('err', str(e)))
        return None


@app.route('/report')
def report():
    con, start, end, cat = _params()
    A = _analyze_or_redirect(con, start, end, cat)
    if A is None:
        return redirect(url_for('home'))
    rows = A['rows']
    sold = [r for r in rows if r['sold'] > 0]
    S = {
        'top_bm': sorted([r for r in rows if r['bm'] > 0], key=lambda r: (-r['bmcost'], -r['bm'])),
        'low_bm': sorted([r for r in rows if r['bm'] == 1], key=lambda r: -r['bmcost']),
        'top_units': sorted(sold, key=lambda r: (-r['sold'], -r['amt'], r['name'])),
        'top_sales': sorted(sold, key=lambda r: (-r['amt'], r['name'])),
        'full': sorted(rows, key=lambda r: (-r['sold'], -r['amt'], r['name'])),
    }
    order_total = sum(r['order'] for r in rows)
    head_title, head_sub = viewmodel.headline(A)
    maxes = {'bm': max([r['bmcost'] for r in S['top_bm'][:15]] or [1]),
             'units': max([r['sold'] for r in S['top_units'][:25]] or [1]),
             'sales': max([r['amt'] for r in S['top_sales'][:15]] or [1]),
             'catsales': max([A['tot'][g]['sales'] for g in A['groups']] or [1])}
    return render_template('report.html', A=A, S=S, cov=db.coverage(con), maxes=maxes, head_title=head_title, head_sub=head_sub,
                           kpis=viewmodel.kpis(A, order_total), brief=viewmodel.order_brief(rows), cat_orders=viewmodel.category_orders(A),
                           legend=[(s, charts_svg.series_class(s)) for s in A['series']],
                           sales_svg=charts_svg.daily_svg(A, 'sales', 'Daily OR sales (PHP)'),
                           bm_svg=charts_svg.daily_svg(A, 'bmc', 'Daily BM cost (PHP)'),
                           wk_units_svg=charts_svg.weekday_svg(A, 'units', 'Average units sold per weekday'),
                           wk_sales_svg=charts_svg.weekday_svg(A, 'sales', 'Average sales per weekday (PHP)'))


@app.route('/report.pdf')
def report_pdf():
    con, start, end, cat = _params()
    A = _analyze_or_redirect(con, start, end, cat)
    if A is None:
        return redirect(url_for('home'))
    suffix = '' if A['sel'] is None else '_' + ''.join(c if c.isalnum() else '-' for c in '+'.join(A['scope_list']))[:50]
    return send_file(io.BytesIO(build_pdf(A)), mimetype='application/pdf', as_attachment=True,
                     download_name=f"BM_Sales_Analysis_{start}_to_{end}{suffix}.pdf")


@app.route('/report.csv')
def report_csv():
    con, start, end, cat = _params()
    A = _analyze_or_redirect(con, start, end, cat)
    if A is None:
        return redirect(url_for('home'))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Category', 'Item code', 'Product', 'Units sold', 'OR sales (PHP)', 'Days sold', 'Per day', 'Baseline units per week', 'BM units',
                'BM cost (PHP)', 'BM retail (PHP)', 'Waste rate %', 'Action', 'Est. received per 7 days', 'Suggested order next 7 days'])
    for r in sorted(A['rows'], key=lambda r: (r['group'], -r['sold'], r['name'])):
        w.writerow([r['group'], r['code'], r['name'], f"{r['sold']:g}", f"{r['amt']:.2f}", r['days'], f"{r['per_day']:.2f}",
                    f"{r['base_wk']:.2f}" if r['inbase'] else '', f"{r['bm']:g}", f"{r['bmcost']:.2f}", f"{r['bmretail']:.2f}",
                    f"{100 * r['rate']:.1f}", r['action'], f"{r['est_received'] * 7 / A['n']:.1f}", r['order']])
    return Response('﻿' + buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=BM_Sales_Products_{start}_to_{end}.csv'})


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
