"""Display-ready pieces for the web page (plain-language headline, key figures, order brief, coverage strip)."""
from datetime import datetime, timedelta

from . import db
from .analysis import _pct


def php(v, d=2):
    return f"PHP {v:,.{d}f}"


def pct1(v):
    """Percent with 2 decimals when small (all-category BM rates are well under 1%)."""
    return f"{v:.2f}%" if v < 1 else f"{v:.1f}%"


def _delta(cur, prev, good_when):
    """Returns dict(text, tone) comparing cur vs prev. good_when: 'down' or 'up'."""
    if not prev:
        return None
    ch = 100.0 * (cur - prev) / prev
    if abs(ch) < 0.5:
        return {'text': 'flat vs previous', 'tone': 'flat'}
    up = ch > 0
    tone = 'good' if (up and good_when == 'up') or (not up and good_when == 'down') else 'bad'
    return {'text': f"{ch:+.1f}% vs previous", 'tone': tone}


def headline(A):
    T, tot, b = A['T'], A['tot'], A['base']
    cur = _pct(T['bmr'], T['sales'])
    if T['bmc'] == 0:
        extra = f" Over the 31 days before there was {php(b['T']['bmc'])} of BM." if b and b['T']['bmc'] else ''
        return 'No bad merchandise was recorded in this period.', f"OR sales were {php(T['sales'], 0)} across {T['units']:,.0f} units.{extra}"
    title = f"Bad merchandise cost {php(T['bmc'])}, which is {pct1(cur)} of sales."
    parts = []
    if b:
        old = _pct(b['T']['bmr'], b['T']['sales'])
        if abs(cur - old) < 0.15:
            parts.append(f"That is about the same as the 31 days before ({pct1(old)}).")
        elif cur < old:
            parts.append(f"That is lower than the 31 days before ({pct1(old)}).")
        else:
            parts.append(f"That is higher than the 31 days before ({pct1(old)}).")
    if T['bmc'] > 0 and T['sales'] > 0 and len(A['groups']) > 1:
        bg = max(A['groups'], key=lambda g: tot[g]['bmc'])
        parts.append(f"{bg} is {_pct(tot[bg]['sales'], T['sales']):.0f}% of sales and {_pct(tot[bg]['bmc'], T['bmc']):.0f}% of the loss.")
    return title, ' '.join(parts)


def kpis(A, order_total):
    T, prev, b = A['T'], A['prev'], A['base']
    pv = prev['T'] if prev else None
    base_pct = f" (baseline {pct1(_pct(b['T']['bmu'], b['T']['units']))})" if b else ''
    n_orders = sum(1 for r in A['rows'] if r['order'] > 0)
    return [
        {'label': 'BM loss at cost', 'value': php(T['bmc']), 'sub': f"Retail value {php(T['bmr'])}", 'delta': _delta(T['bmc'], pv['bmc'] if pv else None, 'down')},
        {'label': 'Units written off', 'value': f"{T['bmu']:,.0f}", 'sub': f"{pct1(_pct(T['bmu'], T['units']))} of units sold{base_pct}", 'delta': None},
        {'label': 'OR sales', 'value': php(T['sales'], 0), 'sub': f"{T['units']:,.0f} units, {T['skus']:,.0f} products in {len(A['groups'])} categor{'ies' if len(A['groups']) != 1 else 'y'}",
         'delta': _delta(T['sales'], pv['sales'] if pv else None, 'up')},
        {'label': 'Suggested order, next 7 days', 'value': f"{order_total:,.0f} units", 'sub': f"Across {n_orders:,} products", 'delta': None},
    ]


def order_brief(rows):
    inc = sorted([r for r in rows if r['action'] == 'INCREASE'], key=lambda r: -r['order'])
    tc = sorted([r for r in rows if r['action'] in ('TRIM', 'CUT')], key=lambda r: -r['bmcost'])
    pz = sorted([r for r in rows if r['action'] == 'PAUSE'], key=lambda r: -r['bmcost'])
    return {'inc': inc, 'tc': tc, 'pz': pz}


def category_orders(A):
    """Per category: product count, expected weekly demand, suggested order, est. received (perishables only)."""
    out = {}
    for r in A['rows']:
        x = out.setdefault(r['group'], {'products': 0, 'demand': 0.0, 'order': 0, 'est': 0.0, 'perishable': r['perishable']})
        x['products'] += 1 if r['sold'] > 0 else 0
        x['demand'] += r['D']; x['order'] += r['order']; x['est'] += r['est_received'] * 7.0 / A['n']
    return [(g, out[g]) for g in A['groups'] if g in out]


def coverage_strip(con, days=70):
    dates = set(db.or_dates(con))
    if not dates:
        return None
    end = max(dates)
    bm = {r[0]: r[1] for r in con.execute('SELECT date, COUNT(*) FROM bm_slips GROUP BY date')}
    e = datetime.strptime(end, '%Y-%m-%d')
    s = max(e - timedelta(days=days - 1), datetime.strptime(min(dates), '%Y-%m-%d'))
    cells = [None] * s.weekday()  # pad so rows are Mon..Sun
    d = s
    while d <= e:
        iso = d.strftime('%Y-%m-%d')
        cells.append({'date': iso, 'label': f"{d:%a %b} {d.day}", 'or': iso in dates, 'bm': bm.get(iso, 0), 'month': d.day == 1})
        d += timedelta(days=1)
    missing = [c['label'] for c in cells if c and not c['or']]
    return {'cells': cells, 'missing': missing, 'start': f"{s:%b} {s.day}", 'end': f"{e:%b} {e.day}"}
