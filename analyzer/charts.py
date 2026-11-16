"""matplotlib charts for the PDF (the web page uses the inline SVG versions)."""
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

COLORS = {'Hot Meals': '#d9480f', 'Fresh Food': '#2f9e44', 'Crunch Time': '#c58a00'}
OTHER = '#7590a0'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8, 'axes.spines.top': False, 'axes.spines.right': False})


def color(name):
    return COLORS.get(name, OTHER)


def _png(fig, rect=None):
    buf = io.BytesIO()
    if rect is not None:
        fig.tight_layout(rect=rect)
    else:
        fig.tight_layout()
    fig.savefig(buf, format='png', dpi=200)
    plt.close(fig)
    return buf.getvalue()


def daily_chart(A):
    days, series = A['daily'], A['series']
    nd = len(days)
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.95))
    labels = [f"{d['label']}\n{d['wd']}" for d in days] if nd <= 10 else [d['label'].split()[1] for d in days]
    for a, key, title in ((ax[0], 'sales', 'Daily OR sales (PHP)'), (ax[1], 'bmc', 'Daily BM cost (PHP)')):
        bottom = [0.0] * nd
        for s in series:
            vals = [d[key].get(s, 0) for d in days]
            a.bar(range(nd), vals, bottom=bottom, color=color(s), width=0.65, label=s)
            bottom = [b + v for b, v in zip(bottom, vals)]
        mx = max(bottom) if max(bottom) > 0 else 1
        if nd <= 10:
            for x, t in enumerate(bottom):
                a.text(x, t + mx * 0.02, f'{t:,.0f}', ha='center', va='bottom', fontsize=6.3, fontweight='bold')
        step = max(1, nd // 12)
        a.set_xticks(range(0, nd, step) if nd > 10 else range(nd))
        a.set_xticklabels(labels[::step] if nd > 10 else labels, fontsize=6.5)
        a.set_title(title, fontsize=8.5, fontweight='bold', loc='left', pad=6)
        a.set_ylim(0, mx * 1.16)
        a.tick_params(axis='y', labelsize=6.5)
        a.yaxis.grid(True, color='#e5e7eb', lw=0.6)
        a.set_axisbelow(True)
    handles, leg_labels = ax[0].get_legend_handles_labels()
    fig.legend(handles, leg_labels, loc='upper center', ncol=min(4, len(series)), frameon=False, fontsize=7, bbox_to_anchor=(0.5, 0.995))
    return _png(fig, rect=[0, 0, 1, 0.90])


def weekday_chart(A):
    order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    c = color(A['series'][0]) if len(A['series']) == 1 else '#51616b'
    fig, ax = plt.subplots(1, 2, figsize=(7.2, 2.35))
    for a, key, title in ((ax[0], 'units', 'Avg units sold per weekday'), (ax[1], 'sales', 'Avg OR sales per weekday (PHP)')):
        vals = [v or 0 for v in A['weekday'][key]]
        a.bar(order, vals, color=c, width=0.6)
        have = [v for v in vals if v]
        if have:
            a.axhline(sum(have) / len(have), color='#374151', lw=0.8, ls='--')
        top = max(vals) if max(vals) > 0 else 1
        for x, v in enumerate(vals):
            if v:
                a.text(x, v + top * 0.025, f'{v:,.0f}', ha='center', va='bottom', fontsize=6.3, fontweight='bold')
        a.set_ylim(0, top * 1.22)
        a.set_title(title, fontsize=8.5, fontweight='bold', loc='left', pad=6)
        a.tick_params(axis='both', labelsize=7)
        a.yaxis.grid(True, color='#e5e7eb', lw=0.6)
        a.set_axisbelow(True)
    return _png(fig)
