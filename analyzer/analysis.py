"""Turns stored OR sales + BM lines into the report data for any date range and any set of categories:
overview, top BM, low wastage, top selling and order suggestions."""
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape

from . import db

BASELINE_DAYS = 31
WEEKDAY_DAYS = 45
REGULAR_DAYS = 6    # a 'regular seller' sold on at least this many days of the baseline
# OR categories shown under the store's own working names (same grouping as the October reports)
GROUP_OF = {'39': 'Hot Meals', '43': 'Fresh Food', '46': 'Fresh Food'}
FOCUS = ('Hot Meals', 'Fresh Food', 'Crunch Time')          # drawn in their own colours
PRESET_HMFF = ('Hot Meals', 'Fresh Food')
# Short shelf life: a small buffer above demand is reasonable, and waste is the main cost of over-ordering.
PERISHABLE = {'25', '27', '36', '37', '39', '40', '41', '43', '46'}
EXCLUDE = {'EX'}                                            # expense items (free stickers etc.), not merchandise


class NoData(Exception):
    pass


def cat_prefix(cat):
    return cat.split('-')[0].strip()


def group_name(cat):
    p = cat_prefix(cat)
    return GROUP_OF.get(p) or re.sub(r'^[^-]*-\s*', '', cat).strip() or cat


def name_group(name):
    """Fallback for a BM product that never appears in the OR history."""
    n = name.lower()
    if re.match(r'^(sk|pk|st|ct)\b', n):
        return 'Crunch Time'
    if re.search(r'busog|hottarice|chef creation|rme |big time meal', n):
        return 'Hot Meals'
    if n.startswith(('7 fresh', '7-fresh', 'new 7 fresh')) or 'ready-to-eat' in n or 'siopao' in n or 'dimsum' in n:
        return 'Fresh Food'
    return None


def _d(s):
    return datetime.strptime(s, '%Y-%m-%d')


def _iso(d):
    return d.strftime('%Y-%m-%d')


def period_label(start, end):
    s, e = _d(start), _d(end)
    if s == e:
        return f"{s:%b} {s.day}, {s.year}"
    if (s.year, s.month) == (e.year, e.month):
        return f"{s:%b} {s.day} to {e.day}, {e.year}"
    if s.year == e.year:
        return f"{s:%b} {s.day} to {e:%b} {e.day}, {e.year}"
    return f"{s:%b} {s.day}, {s.year} to {e:%b} {e.day}, {e.year}"


def _pct(a, b):
    return 0.0 if not b else 100.0 * a / b


class Catalog:
    """Product -> category lookup built from every OR line on file (BM slips carry no category)."""
    def __init__(self, con):
        self.info = {}
        for r in con.execute('SELECT code, cat, name FROM or_lines WHERE rowid IN (SELECT MAX(rowid) FROM or_lines GROUP BY code)'):
            self.info[r['code']] = (r['cat'], r['name'])
        pref = defaultdict(Counter)
        for code, (cat, _) in self.info.items():
            pref[code[:2]][cat] += 1
        self.prefix = {p: c.most_common(1)[0][0] for p, c in pref.items()}

    def bm_group(self, code, name):
        if code in self.info:
            return group_name(self.info[code][0]), cat_prefix(self.info[code][0])
        g = name_group(name)
        if g:
            return g, {'Hot Meals': '39', 'Fresh Food': '43', 'Crunch Time': '36'}[g]
        if code[:2] in self.prefix:
            cat = self.prefix[code[:2]]
            return group_name(cat), cat_prefix(cat)
        return 'Uncategorized', '--'


def _sales(con, start, end):
    r = {}
    for l in db.or_lines(con, start, end):
        p = cat_prefix(l['cat'])
        if p in EXCLUDE:
            continue
        x = r.setdefault(l['code'], {'qty': 0.0, 'amt': 0.0, 'days': set(), 'name': l['name'], 'cat': p, 'group': group_name(l['cat'])})
        x['qty'] += l['qty']; x['amt'] += l['amt']; x['days'].add(l['date']); x['name'] = l['name']
    return r


def _bm(con, start, end, cat):
    r = {}
    for l in db.bm_lines(con, start, end):
        g, p = cat.bm_group(l['code'], l['name'])
        x = r.setdefault(l['code'], {'qty': 0.0, 'cost': 0.0, 'retail': 0.0, 'name': l['name'], 'cat': p, 'group': g})
        x['qty'] += l['qty']; x['cost'] += l['total_cost']; x['retail'] += l['total_retail']
    return r


def _keep(d, sel):
    return d if sel is None else {k: v for k, v in d.items() if v['group'] in sel}


def _group_tots(sales, bm):
    t = defaultdict(lambda: {'units': 0.0, 'sales': 0.0, 'bmu': 0.0, 'bmc': 0.0, 'bmr': 0.0, 'skus': 0, 'bm_products': 0})
    for v in sales.values():
        x = t[v['group']]; x['units'] += v['qty']; x['sales'] += v['amt']; x['skus'] += 1 if v['qty'] > 0 else 0
    for v in bm.values():
        x = t[v['group']]; x['bmu'] += v['qty']; x['bmc'] += v['cost']; x['bmr'] += v['retail']; x['bm_products'] += 1 if v['qty'] > 0 else 0
    return dict(t)


def _sum(tots, groups=None):
    keys = ('units', 'sales', 'bmu', 'bmc', 'bmr', 'skus', 'bm_products')
    return {k: sum(v[k] for g, v in tots.items() if groups is None or g in groups) for k in keys}


def parse_scope(arg, available):
    """arg: None, a string, or a list of strings. Items may be 'all', 'hmff' (Hot Meals + Fresh Food), a category name,
    or a comma list of names. Returns None for all categories, else the set of chosen category names."""
    avail = set(available)
    tokens = []
    for a in ([arg] if isinstance(arg, str) else (arg or [])):
        tokens += [a] if a in avail else [t.strip() for t in a.split(',')]
    chosen = set()
    for t in tokens:
        if t == 'hmff':
            chosen |= set(PRESET_HMFF)
        elif t in avail:
            chosen.add(t)
    chosen &= avail
    if not chosen or chosen == avail:
        return None
    return chosen


def scope_label(sel):
    if sel is None:
        return 'All categories'
    names = sorted(sel)
    if len(names) <= 3:
        return ' + '.join(names)
    return f"{len(names)} categories"


def analyze(con, start, end, scope=None):
    s, e = _d(start), _d(end)
    if e < s:
        raise NoData('End date is before start date.')
    n_cal = (e - s).days + 1
    all_or = set(db.or_dates(con))
    cal = [_iso(s + timedelta(i)) for i in range(n_cal)]
    have = [x for x in cal if x in all_or]
    missing = [x for x in cal if x not in all_or]
    if not have:
        raise NoData(f'No OR sales data on file for {period_label(start, end)}.')
    n = len(have)
    f = 7.0 / n  # scale to a 7-day week

    cat = Catalog(con)
    sales_all = _sales(con, start, end)
    bm_all = _bm(con, start, end, cat)
    all_groups = sorted(_group_tots(sales_all, bm_all).items(), key=lambda kv: -kv[1]['sales'])
    available = [g for g, _ in all_groups]
    sel = parse_scope(scope, available)
    sales, bm = _keep(sales_all, sel), _keep(bm_all, sel)

    # ---- baseline (31 days before the period) and previous window (same length right before)
    bs, be = _iso(s - timedelta(days=BASELINE_DAYS)), _iso(s - timedelta(days=1))
    bdates = sorted(x for x in all_or if bs <= x <= be)
    bn = len(bdates)
    base_ok = bn >= 7
    bsales = _keep(_sales(con, bs, be), sel) if base_ok else {}
    bbm = _keep(_bm(con, bs, be, cat), sel) if base_ok else {}
    ps, pe = _iso(s - timedelta(days=n_cal)), _iso(s - timedelta(days=1))
    pdates = [x for x in all_or if ps <= x <= pe]
    psales = _keep(_sales(con, ps, pe), sel) if pdates else {}
    pbm = _keep(_bm(con, ps, pe, cat), sel) if pdates else {}

    # ---- per-product rows with the ordering model (products are matched by item code)
    rows = []
    for code in set(sales) | set(bm):
        sv, bv = sales.get(code), bm.get(code)
        src = sv or bv
        S = sv['qty'] if sv else 0.0
        B = bv['qty'] if bv else 0.0
        So = bsales[code]['qty'] if code in bsales else 0.0
        Bo = bbm[code]['qty'] if code in bbm else 0.0
        inbase = base_ok and (code in bsales or code in bbm)
        win = bn
        if code in bsales and bsales[code]['days']:
            first = min(bsales[code]['days'])
            idx = bdates.index(first) if first in bdates else 0
            if idx > 6:
                win = bn - idx
        S_wk, B_wk = S * f, B * f
        O = So * 7.0 / win if inbase else 0.0
        Bo_w = Bo * 7.0 / win if inbase else 0.0
        D = 0.5 * S_wk + 0.5 * O if inbase else S_wk
        denom = (S_wk + B_wk) + (O + Bo_w)
        rate = (B_wk + Bo_w) / denom if denom > 0 else 0.0
        perish = src['cat'] in PERISHABLE
        if S == 0:
            act, order = 'PAUSE', 0
        else:
            if rate >= 0.25 and B >= 1: act, fac = 'CUT', 0.7
            elif rate >= 0.10: act, fac = 'TRIM', 0.85
            elif perish and rate < 0.03 and D >= 5: act, fac = 'INCREASE', 1.10
            else: act, fac = 'HOLD', 1.0
            o = D * fac
            order = max(1, math.ceil(round(o, 6))) if act == 'INCREASE' else max(1, int(o + 0.5))
        rows.append({'code': code, 'name': src['name'], 'group': src['group'], 'cat': src['cat'], 'perishable': perish,
                     'sold': S, 'amt': sv['amt'] if sv else 0.0, 'days': len(sv['days']) if sv else 0, 'per_day': S / n,
                     'bm': B, 'bmcost': bv['cost'] if bv else 0.0, 'bmretail': bv['retail'] if bv else 0.0,
                     'base_sold': So, 'base_bm': Bo, 'base_wk': O, 'base_day': (So / win) if inbase else None, 'inbase': inbase,
                     'prev': psales[code]['qty'] if code in psales else 0.0, 'D': D, 'rate': rate, 'action': act, 'order': order,
                     'est_received': S + B})

    # ---- totals
    tot = _group_tots(sales, bm)
    groups = sorted(tot, key=lambda g: -tot[g]['sales'])
    T = _sum(tot)
    T['groups'] = len(groups)

    # ---- daily (stacked by focus groups + everything else)
    series = list(groups) if len(groups) == 1 else [g for g in FOCUS if g in tot] + (['Other categories'] if any(g not in FOCUS for g in groups) else [])
    ser_of = lambda g: g if g in series else 'Other categories'
    daily = {d: {'sales': defaultdict(float), 'bmc': defaultdict(float), 'units': 0.0, 'bmu': 0.0, 'bmr': 0.0} for d in cal}
    for l in db.or_lines(con, start, end):
        p = cat_prefix(l['cat'])
        if p in EXCLUDE:
            continue
        g = group_name(l['cat'])
        if sel is None or g in sel:
            x = daily[l['date']]; x['sales'][ser_of(g)] += l['amt']; x['units'] += l['qty']
    slips = db.bm_slips(con, start, end)
    slip_ids = set(); lines_n = 0
    for l in db.bm_lines(con, start, end):
        g, _p = cat.bm_group(l['code'], l['name'])
        if sel is None or g in sel:
            x = daily[l['date']]; x['bmc'][ser_of(g)] += l['total_cost']; x['bmu'] += l['qty']; x['bmr'] += l['total_retail']
            slip_ids.add(l['doc_id']); lines_n += 1
    daily_rows = [{'date': d, 'label': f"{_d(d):%b} {_d(d).day}", 'wd': _d(d).strftime('%a'), 'has_or': d in all_or,
                   'sales': dict(daily[d]['sales']), 'bmc': dict(daily[d]['bmc']), 'units': daily[d]['units'],
                   'sales_total': sum(daily[d]['sales'].values()), 'bmc_total': sum(daily[d]['bmc'].values()),
                   'bmu': daily[d]['bmu'], 'bmr': daily[d]['bmr']} for d in cal]

    # ---- baseline & previous comparison
    base = None
    if base_ok:
        base = _group_tots(bsales, bbm)
        bt = _sum(base)
        base = {'groups': base, 'T': bt, 'T_wk': {k: v * 7.0 / bn for k, v in bt.items()},
                'wk': {g: {k: v * 7.0 / bn for k, v in x.items()} for g, x in base.items()}}
    prev = None
    if pdates:
        pt = _group_tots(psales, pbm)
        prev = {'groups': pt, 'T': _sum(pt), 'days': len(pdates)}

    # ---- weekday pattern (units and sales) from recent history, same category scope
    ws_ = _iso(e - timedelta(days=WEEKDAY_DAYS - 1))
    wu, wsales, wdates = defaultdict(float), defaultdict(float), set()
    for l in db.or_lines(con, ws_, end):
        if cat_prefix(l['cat']) in EXCLUDE:
            continue
        if sel is None or group_name(l['cat']) in sel:
            k = (_d(l['date']).weekday(), l['date'])
            wu[k] += l['qty']; wsales[k] += l['amt']
        wdates.add(l['date'])
    wcount = [0] * 7
    for dd in wdates:
        wcount[_d(dd).weekday()] += 1
    weekday = {'units': [], 'sales': []}
    for i in range(7):
        us = [v for (w, _), v in wu.items() if w == i]
        ss = [v for (w, _), v in wsales.items() if w == i]
        weekday['units'].append(sum(us) / wcount[i] if wcount[i] else None)
        weekday['sales'].append(sum(ss) / wcount[i] if wcount[i] else None)

    # ---- sold in baseline but not this period
    notsold = []
    for code, v in bsales.items():
        if code not in sales and len(v['days']) >= REGULAR_DAYS:
            notsold.append({'code': code, 'group': v['group'], 'name': v['name'], 'base_units': v['qty'], 'base_days': len(v['days']),
                            'base_bm': bbm[code]['qty'] if code in bbm else 0.0, 'prev': psales[code]['qty'] if code in psales else 0.0})
    notsold.sort(key=lambda x: -x['base_units'])

    # ---- notes
    notes = []
    if missing:
        notes.append(f"No OR report on file for {', '.join(f'{_d(x):%b} {_d(x).day}' for x in missing)}. Those days are not counted, so sales are for {n} of {n_cal} days and weekly figures are scaled to 7 days.")
    badstat = [x for x in slips if (x['status'] or 'COMPLETED').upper() != 'COMPLETED']
    if badstat:
        notes.append(f"{len(badstat)} slip(s) are not COMPLETED and were left out: {', '.join(x['doc_id'] for x in badstat)}.")
    no_or_bm = sorted({x['date'] for x in slips if x['date'] not in all_or})
    if no_or_bm:
        notes.append(f"BM slips exist for {', '.join(f'{_d(x):%b} {_d(x).day}' for x in no_or_bm)} but there is no OR report for those days.")
    for r in con.execute('SELECT date, warnings FROM or_days WHERE date BETWEEN ? AND ? AND warnings<>?', (start, end, '')):
        notes.append(f"OR {r['date']}: {r['warnings']}")
    for r in con.execute('SELECT doc_id, date, warnings FROM bm_slips WHERE date BETWEEN ? AND ? AND warnings<>?', (start, end, '')):
        notes.append(f"BM slip {r['doc_id']} ({r['date']}): {r['warnings']}")
    if not base_ok:
        notes.append(f"Only {bn} day(s) of OR history before {period_label(start, end).split(' to ')[0]}, so there is no baseline yet. Order suggestions use this period only and comparisons to the baseline are hidden.")
    unc = [r for r in rows if r['group'] == 'Uncategorized']
    if unc:
        notes.append(f"{len(unc)} BM product(s) could not be matched to a category (never sold on the OR reports on file) and are listed as Uncategorized.")

    A = {'start': start, 'end': end, 'label': period_label(start, end), 'n_cal': n_cal, 'n': n, 'missing': missing,
         'scope_list': sorted(sel) if sel else [], 'scope_label': scope_label(sel), 'sel': sel, 'all_groups': [(g, t['sales']) for g, t in all_groups],
         'rows': rows, 'tot': tot, 'groups': groups, 'T': T, 'series': series, 'daily': daily_rows, 'base': base, 'base_days': bn,
         'base_range': (bdates[0], bdates[-1]) if bdates else None, 'prev': prev, 'weekday': weekday, 'weekday_n': wcount,
         'weekday_days': len(wdates), 'notsold': notsold, 'notes': notes, 'slips': len(slip_ids), 'bm_lines': lines_n,
         'cat_prefix_perishable': sorted(PERISHABLE)}
    A['bullets'] = _bullets(A)
    return A


def _bullets(A):
    rows, tot, T, n = A['rows'], A['tot'], A['T'], A['n']
    out = []
    b = A['base']
    if b and (T['bmr'] or b['T']['bmr']):
        bT = b['T']
        cur, old = _pct(T['bmr'], T['sales']), _pct(bT['bmr'], bT['sales'])
        if abs(cur - old) < 0.15:
            head = 'BM is about the same as the baseline.'
        else:
            head = f"BM is {'lower' if cur < old else 'higher'} than the baseline."
        out.append(f"<b>{head}</b> BM retail value was {cur:.2f}% of OR sales in this period versus {old:.2f}% over the 31 days before it. "
                   f"BM was {_pct(T['bmu'], T['units']):.2f}% of units sold (baseline {_pct(bT['bmu'], bT['units']):.2f}%).")
    if T['bmc'] > 0 and len(A['groups']) > 1:
        bg = max(A['groups'], key=lambda g: tot[g]['bmc'])
        out.append(f"<b>{escape(bg)} has the biggest loss.</b> {escape(bg)} is {_pct(tot[bg]['sales'], T['sales']):.0f}% of sales but {_pct(tot[bg]['bmc'], T['bmc']):.0f}% of BM cost "
                   f"(PHP {tot[bg]['bmc']:,.2f} from {tot[bg]['bmu']:.0f} units).")
        worst = [g for g in A['groups'] if tot[g]['units'] >= 30 and tot[g]['bmu'] > 0]
        if worst:
            wg = max(worst, key=lambda g: _pct(tot[g]['bmu'], tot[g]['units']))
            if wg != bg:
                out.append(f"<b>Highest BM rate: {escape(wg)}.</b> {tot[wg]['bmu']:.0f} BM units against {tot[wg]['units']:,.0f} sold ({_pct(tot[wg]['bmu'], tot[wg]['units']):.1f}%).")
    top = sorted([r for r in rows if r['sold'] > 0], key=lambda r: -r['sold'])[:5]
    if top:
        t5 = sum(r['sold'] for r in top)
        out.append(f"<b>Top 5 products are {_pct(t5, T['units']):.0f}% of units sold.</b> Leaders: {', '.join(escape(r['name']) for r in top[:3])}. "
                   f"Together the top 5 had {sum(r['bm'] for r in top):.0f} BM unit(s).")
    days_bm = sorted([d for d in A['daily'] if d['bmc_total'] > 0], key=lambda d: -d['bmc_total'])
    if len(days_bm) >= 2 and T['bmc'] > 0:
        a, c = days_bm[0], days_bm[1]
        out.append(f"<b>Heaviest BM days.</b> {a['wd']} {a['label']} (PHP {a['bmc_total']:,.2f}) and {c['wd']} {c['label']} (PHP {c['bmc_total']:,.2f}) make up {_pct(a['bmc_total'] + c['bmc_total'], T['bmc']):.0f}% of the period's BM cost.")
    rep = sorted([r for r in rows if r['bm'] >= 1 and r['base_bm'] >= 1 and r['rate'] >= 0.25], key=lambda r: -r['bmcost'])[:3]
    if rep:
        parts = '; '.join(f"{escape(r['name'])}: {r['bm']:.0f} BM vs {r['sold']:.0f} sold now, {r['base_bm']:.0f} BM vs {r['base_sold']:.0f} sold before" for r in rep)
        out.append(f"<b>Repeat offenders.</b> {parts}.")
    if A['prev'] and A['prev']['T']['units']:
        p = A['prev']['T']
        out.append(f"<b>Versus the previous {A['n_cal']} days.</b> Units sold {_pct(T['units'] - p['units'], p['units']):+.1f}%, OR sales {_pct(T['sales'] - p['sales'], p['sales']):+.1f}%, {('BM cost ' + format(_pct(T['bmc'] - p['bmc'], p['bmc']), '+.1f') + '%.') if p['bmc'] else 'No BM in the previous period.'}")
    pz = [r for r in rows if r['action'] == 'PAUSE']
    if pz or A['notsold']:
        lead = (f"{len(pz)} product(s) sold 0 but were written off: " + ', '.join(escape(r['name']) for r in sorted(pz, key=lambda r: -r['bmcost'])[:3]) + '. ') if pz else ''
        out.append(f"<b>Items to check on the shelf.</b> {lead}"
                   f"{len(A['notsold'])} regular seller(s) (sold on {REGULAR_DAYS}+ days of the baseline) did not sell at all this period; they may be delisted or out of stock.")
    return out
