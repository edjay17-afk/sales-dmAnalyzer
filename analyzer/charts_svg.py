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
    """Average per weekday. metric: 'units' or 'sales'."""
    order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    vals = [v or 0 for v in A['weekday'][metric]]
    have = [v for v in vals if v]
    avg = sum(have) / len(have) if have else 0
    step, top = _nice(max(vals) if vals else 0)
    h = 200
    iw, ih = W - PL - PR, h - PT - 26
    slot = iw / 7
    bw = min(46, slot * 0.64)
    cls = series_class(A['series'][0]) if len(A['series']) == 1 else 'b-all'
    y = lambda v: PT + ih - ih * v / top
    out = [f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" aria-label="{escape(title)}">']
    t = 0
    while t <= top + 1e-9:
        out.append(f'<line class="grid" x1="{PL}" x2="{W-PR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="ax" x="{PL-6}" y="{y(t)+4:.1f}" text-anchor="end">{_fmt(t)}</text>')
        t += step
    for i, (name, v) in enumerate(zip(order, vals)):
        cx = PL + slot * (i + 0.5)
        out.append(f'<g><title>{name}: {v:,.0f} on average</title>')
        if v:
            out.append(f'<rect class="{cls}" x="{cx-bw/2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{ih*v/top:.1f}" rx="1"/>')
            out.append(f'<text class="val" x="{cx:.1f}" y="{y(v)-5:.1f}" text-anchor="middle">{v:,.0f}</text>')
        out.append(f'<text class="ax" x="{cx:.1f}" y="{h-8}" text-anchor="middle">{name}</text></g>')
    if avg:
        out.append(f'<line class="avg" x1="{PL}" x2="{W-PR}" y1="{y(avg):.1f}" y2="{y(avg):.1f}"/>')
    out.append('</svg>')
    return ''.join(out)
