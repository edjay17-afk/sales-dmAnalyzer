"""Inline SVG charts. Colours come from CSS variables."""
import math
from html import escape

W, H = 560, 230
PL, PR, PT, PB = 46, 10, 22, 36

SERIES_CLASS = {'Hot Meals': 'b-hot', 'Fresh Food': 'b-fresh', 'Crunch Time': 'b-crunch'}


def series_class(name):
    return SERIES_CLASS.get(name, 'b-other')


def _nice(mx):
    if mx <= 0:
        return 1, 1
    raw = mx / 4
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * p:
            step = m * p
            break
    return step, step * math.ceil(mx / step)


def _fmt(v):
    if v >= 1_000_000:
        return f"{v/1_000_000:g}M"
    return f"{v/1000:g}k" if v >= 1000 else f"{v:g}"


def daily_svg(A, key, title):
    """Stacked daily bars. key: 'sales' or 'bmc'. Series are the main groups plus 'Other categories'."""
    days, series = A['daily'], A['series']
    n = len(days)
    tops = [d[key + '_total'] for d in days]
    if not tops or max(tops) <= 0:
        return '<p class="empty">Nothing recorded in this period.</p>'
    step, top = _nice(max(tops))
    iw, ih = W - PL - PR, H - PT - PB
    slot = iw / n
    bw = min(46, slot * 0.66)
    y = lambda v: PT + ih - ih * v / top
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    t = 0
    while t <= top + 1e-9:
        out.append(f'<line class="grid" x1="{PL}" x2="{W-PR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="ax" x="{PL-6}" y="{y(t)+4:.1f}" text-anchor="end">{_fmt(t)}</text>')
        t += step
    for i, d in enumerate(days):
        cx = PL + slot * (i + 0.5)
        tip = f"{d['wd']} {d['label']}: " + ', '.join(f"{s} {d[key].get(s, 0):,.0f}" for s in series) + f" (total {d[key + '_total']:,.0f})"
        out.append(f'<g><title>{escape(tip)}</title>')
        acc = 0.0
        for s in series:
            v = d[key].get(s, 0)
            if v > 0:
                out.append(f'<rect class="{series_class(s)}" x="{cx-bw/2:.1f}" y="{y(acc+v):.1f}" width="{bw:.1f}" height="{max(ih*v/top, 0.8):.1f}" rx="1"/>')
                acc += v
        if n <= 10:
            out.append(f'<text class="val" x="{cx:.1f}" y="{y(acc)-5:.1f}" text-anchor="middle">{d[key + "_total"]:,.0f}</text>')
        lab = d['wd'] if n <= 10 else (d['label'].split()[1] if (i % max(1, n // 12) == 0) else '')
        out.append(f'<text class="ax" x="{cx:.1f}" y="{H-PB+14}" text-anchor="middle">{lab}</text>')
        if n <= 10:
            out.append(f'<text class="ax sub" x="{cx:.1f}" y="{H-PB+27}" text-anchor="middle">{d["label"]}</text>')
        out.append('</g>')
    out.append('</svg>')
    return ''.join(out)


def weekday_svg(A, metric, title):
    """Average per weekday. metric: 'units', 'sales', or 'bmc'."""
    order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    vals = [v or 0 for v in A['weekday'][metric]]
    cls = 'b-waste' if metric == 'bmc' else (series_class(A['series'][0]) if len(A['series']) == 1 else 'b-all')
    return _weekday_bars(order, vals, cls, title)


def _weekday_bars(order, vals, cls, title):
    have = [v for v in vals if v]
    avg = sum(have) / len(have) if have else 0
    step, top = _nice(max(vals) if vals else 0)
    h = 200
    iw, ih = W - PL - PR, h - PT - 26
    slot = iw / 7
    bw = min(46, slot * 0.64)
    y = lambda v: PT + ih - ih * v / top
    out = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" aria-label="{escape(title)}">']
    t = 0
    while t <= top + 1e-9:
        out.append(f'<line class="grid" x1="{PL}" x2="{W-PR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="ax" x="{PL-6}" y="{y(t)+4:.1f}" text-anchor="end">{_fmt(t)}</text>')
        t += step
    for i, (name, v) in enumerate(zip(order, vals)):
        cx = PL + slot * (i + 0.5)
        out.append(f'<g><title>{name}: {v:,.1f} on average</title>')
        if v:
            out.append(f'<rect class="{cls}" x="{cx-bw/2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{ih*v/top:.1f}" rx="1"/>')
            lbl = f"{v:,.0f}" if v >= 10 else f"{v:.1f}"
            out.append(f'<text class="val" x="{cx:.1f}" y="{y(v)-5:.1f}" text-anchor="middle">{lbl}</text>')
        out.append(f'<text class="ax" x="{cx:.1f}" y="{h-8}" text-anchor="middle">{name}</text></g>')
    if avg:
        out.append(f'<line class="avg" x1="{PL}" x2="{W-PR}" y1="{y(avg):.1f}" y2="{y(avg):.1f}"/>')
    out.append('</svg>')
    return ''.join(out)


def product_daily_svg(D, title):
    """Daily units sold (bars) and BM units (red markers/bars) for a single product."""
    days = D['daily']
    n = len(days)
    mx = max([max(d['qty'], d['bmu']) for d in days] or [0])
    if mx <= 0:
        return '<p class="empty">No sales or BM recorded in this window.</p>'
    step, top = _nice(mx)
    iw, ih = W - PL - PR, H - PT - PB
    slot = iw / n
    bw = max(1.8, min(18, slot * 0.7))
    cls = series_class(D['group'])
    y = lambda v: PT + ih - ih * v / top
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    t = 0
    while t <= top + 1e-9:
        out.append(f'<line class="grid" x1="{PL}" x2="{W-PR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="ax" x="{PL-6}" y="{y(t)+4:.1f}" text-anchor="end">{_fmt(t)}</text>')
        t += step
    stride = max(1, n // 10)
    for i, d in enumerate(days):
        cx = PL + slot * (i + 0.5)
        tip = f"{d['wd']} {d['label']}: {d['qty']:g} sold" + (f", {d['bmu']:g} BM" if d['bmu'] else '') + ('' if d['has_or'] else ' (no OR report)')
        out.append(f'<g><title>{escape(tip)}</title>')
        if not d['has_or']:
            out.append(f'<rect class="b-missing" x="{cx-bw/2:.1f}" y="{PT}" width="{bw:.1f}" height="{ih}"/>')
        if d['qty'] > 0:
            out.append(f'<rect class="{cls}" x="{cx-bw/2:.1f}" y="{y(d["qty"]):.1f}" width="{bw:.1f}" height="{max(ih*d["qty"]/top, 1.0):.1f}" rx="1"/>')
        if d['bmu'] > 0:
            out.append(f'<rect class="b-waste" x="{cx-bw/2:.1f}" y="{y(d["bmu"]):.1f}" width="{bw:.1f}" height="{max(ih*d["bmu"]/top, 2.0):.1f}" rx="1"/>')
        if i % stride == 0 or i == n - 1:
            out.append(f'<text class="ax" x="{cx:.1f}" y="{H-PB+14}" text-anchor="middle">{d["label"]}</text>')
        out.append('</g>')
    out.append('</svg>')
    return ''.join(out)


def product_weekday_svg(D, title):
    order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    return _weekday_bars(order, D['weekday_avg'], series_class(D['group']), title)


def trend_svg(T, key, title):
    """Stacked weekly bars across T['buckets']. key: 'sales' or 'bmc'."""
    buckets, series = T['buckets'], T['series']
    n = len(buckets)
    if not n:
        return '<p class="empty">No data in this trend window.</p>'
    tops = [b[key + '_total'] for b in buckets]
    if max(tops) <= 0:
        return '<p class="empty">Nothing recorded in this window.</p>'
    step, top = _nice(max(tops))
    iw, ih = W - PL - PR, H - PT - PB
    slot = iw / n
    bw = min(44, slot * 0.65)
    y = lambda v: PT + ih - ih * v / top
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    t = 0
    while t <= top + 1e-9:
        out.append(f'<line class="grid" x1="{PL}" x2="{W-PR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="ax" x="{PL-6}" y="{y(t)+4:.1f}" text-anchor="end">{_fmt(t)}</text>')
        t += step
    stride = max(1, n // 8)
    for i, b in enumerate(buckets):
        cx = PL + slot * (i + 0.5)
        tip = f"{b['label']}: {b[key + '_total']:,.0f} ({b['or_days']}/7 OR days)"
        out.append(f'<g><title>{escape(tip)}</title>')
        acc = 0.0
        for s in series:
            v = b[key].get(s, 0)
            if v > 0:
                out.append(f'<rect class="{series_class(s)}" x="{cx-bw/2:.1f}" y="{y(acc+v):.1f}" width="{bw:.1f}" height="{max(ih*v/top, 0.8):.1f}" rx="1"/>')
                acc += v
        if n <= 10:
            out.append(f'<text class="val" x="{cx:.1f}" y="{y(acc)-5:.1f}" text-anchor="middle">{_fmt(b[key + "_total"])}</text>')
        if i % stride == 0 or i == n - 1:
            out.append(f'<text class="ax" x="{cx:.1f}" y="{H-PB+14}" text-anchor="middle">{b["short"]}</text>')
        out.append('</g>')
    out.append('</svg>')
    return ''.join(out)


def trend_rate_svg(T, title):
    """Weekly BM retail as % of OR sales line + dots chart."""
    buckets = T['buckets']
    n = len(buckets)
    if not n or max(b['bm_pct_sales'] for b in buckets) <= 0:
        return '<p class="empty">No BM % data in this window.</p>'
    vals = [b['bm_pct_sales'] for b in buckets]
    step, top = _nice(max(vals))
    iw, ih = W - PL - PR, H - PT - PB
    slot = iw / n
    y = lambda v: PT + ih - ih * v / top
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    t = 0
    while t <= top + 1e-9:
        out.append(f'<line class="grid" x1="{PL}" x2="{W-PR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="ax" x="{PL-6}" y="{y(t)+4:.1f}" text-anchor="end">{t:.2g}%</text>')
        t += step
    pts = [(PL + slot * (i + 0.5), y(b['bm_pct_sales']), b) for i, b in enumerate(buckets)]
    path = ' '.join(('M' if i == 0 else 'L') + f'{x:.1f},{yy:.1f}' for i, (x, yy, _) in enumerate(pts))
    out.append(f'<path class="trend-line" d="{path}" fill="none"/>')
    stride = max(1, n // 8)
    for i, (cx, cy, b) in enumerate(pts):
        tip = f"{b['label']}: {b['bm_pct_sales']:.2f}% of sales ({b['bmu']:,.0f} BM units)"
        out.append(f'<g><title>{escape(tip)}</title><circle class="trend-dot" cx="{cx:.1f}" cy="{cy:.1f}" r="4"/>')
        if n <= 10:
            out.append(f'<text class="val" x="{cx:.1f}" y="{cy-8:.1f}" text-anchor="middle">{b["bm_pct_sales"]:.2f}%</text>')
        if i % stride == 0 or i == n - 1:
            out.append(f'<text class="ax" x="{cx:.1f}" y="{H-PB+14}" text-anchor="middle">{b["short"]}</text>')
        out.append('</g>')
    out.append('</svg>')
    return ''.join(out)
