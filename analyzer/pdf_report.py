"""A4 PDF of the analysis: overview, top BM, low wastage, top selling, order suggestions (any categories)."""
import io
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from . import viewmodel
from .analysis import _pct
from .charts import COLORS, daily_chart, weekday_chart

NAVY = colors.HexColor('#1f2937')
GRAY = colors.HexColor('#6b7280')
LINE = colors.HexColor('#e5e7eb')
ZEBRA = colors.HexColor('#f6f7f9')
TOTAL_BG = colors.HexColor('#eef0f3')
ACT_COL = {'INCREASE': '#2f9e44', 'HOLD': '#4b5563', 'TRIM': '#d9480f', 'CUT': '#c92a2a', 'PAUSE': '#7048e8'}
W_PAGE = A4[0] - 72
APPENDIX_MAX = 250


def _st(name, **kw):
    return ParagraphStyle(name, fontName=kw.pop('fontName', 'Helvetica'), **kw)


sTitle = _st('t', fontName='Helvetica-Bold', fontSize=21, leading=25, textColor=colors.HexColor('#111827'))
sSub = _st('s', fontSize=8.3, leading=11.5, textColor=GRAY)
sH = _st('h', fontName='Helvetica-Bold', fontSize=11.5, leading=15, textColor=colors.HexColor('#111827'), spaceBefore=9, spaceAfter=4, keepWithNext=True)
sH2 = _st('h2', fontName='Helvetica-Bold', fontSize=9.5, leading=12, spaceBefore=6, spaceAfter=3, keepWithNext=True)
sB = _st('b', fontSize=8, leading=11, textColor=colors.HexColor('#374151'))
sBul = _st('bul', fontSize=8.2, leading=11.4, textColor=colors.HexColor('#1f2937'), leftIndent=9, bulletIndent=0, spaceAfter=3)
sSm = _st('sm', fontSize=7, leading=9.2, textColor=GRAY)
sCell = _st('c', fontSize=7.2, leading=8.8)
sCellR = _st('cr', fontSize=7.2, leading=8.8, alignment=TA_RIGHT)
sHead = _st('hd', fontName='Helvetica-Bold', fontSize=7.2, leading=8.8, textColor=colors.white)
sHeadR = _st('hdr', fontName='Helvetica-Bold', fontSize=7.2, leading=8.8, textColor=colors.white, alignment=TA_RIGHT)
sKl = _st('kl', fontSize=7, leading=9, textColor=GRAY)
sKv = _st('kv', fontName='Helvetica-Bold', fontSize=14.5, leading=18, textColor=colors.HexColor('#111827'))
sKs = _st('ks', fontSize=6.8, leading=8.5, textColor=GRAY)

php = viewmodel.php
pct1 = viewmodel.pct1


def col(txt, hexc):
    return f'<font color="{hexc}"><b>{escape(txt)}</b></font>'


def catcell(g):
    c = COLORS.get(g)
    return Paragraph(col(g, c) if c else escape(g), sCell)


def act(a):
    return Paragraph(col(a, ACT_COL[a]), sCell)


def tbl(data, widths, aligns, total_row=False, tight=False):
    out = []
    for ri, r in enumerate(data):
        row = []
        for ci, c in enumerate(r):
            if isinstance(c, str):
                right = aligns[ci] == 'R'
                row.append(Paragraph(escape(c), (sHeadR if right else sHead) if ri == 0 else (sCellR if right else sCell)))
            else:
                row.append(c)
        out.append(row)
    t = Table(out, colWidths=widths, repeatRows=1)
    pad = 1.6 if tight else 2.6
    hpad = 3 if tight else 4
    st = [('BACKGROUND', (0, 0), (-1, 0), NAVY), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
          ('TOPPADDING', (0, 0), (-1, -1), pad), ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
          ('LEFTPADDING', (0, 0), (-1, -1), hpad), ('RIGHTPADDING', (0, 0), (-1, -1), hpad), ('LINEBELOW', (0, 1), (-1, -1), 0.3, LINE)]
    st += [('BACKGROUND', (0, i), (-1, i), ZEBRA) for i in range(2, len(out), 2)]
    if total_row:
        st.append(('BACKGROUND', (0, len(out) - 1), (-1, len(out) - 1), TOTAL_BG))
    t.setStyle(TableStyle(st))
    return t


def build_pdf(A):
    """Returns concise, detailed A4 PDF bytes (6 focused tables across ~4-5 pages)."""
    rows, tot, T, n, groups = A['rows'], A['tot'], A['T'], A['n'], A['groups']
    base, prev = A['base'], A['prev']
    title = f"BM & Sales Analysis - {A['label']}"
    story = []

    def footer(c, doc):
        c.saveState(); c.setFont('Helvetica', 6.8); c.setFillColor(GRAY)
        c.drawString(36, 22, f"{title} - {A['scope_label']}")
        c.drawRightString(A4[0] - 36, 22, f'Page {doc.page}')
        c.restoreState()

    sold = [r for r in rows if r['sold'] > 0]
    order_total = sum(r['order'] for r in rows)
    cat_orders = {g: x for g, x in viewmodel.category_orders(A)}

    # ------------------------------------------------------------ Page 1: Executive Summary & Unified Category Table
    ncal = A['n_cal']
    days_txt = f"{n} day{'s' if n != 1 else ''}" + ('' if n == ncal else f" (of {ncal} calendar days)")
    story += [
        Paragraph(escape(title), sTitle),
        Paragraph(f"{'All ' + str(len(groups)) + ' categories' if A['sel'] is None else escape(', '.join(A['scope_list']) if len(A['scope_list']) <= 6 else A['scope_label']) + ' (' + str(len(groups)) + ' categor' + ('ies' if len(groups) != 1 else 'y') + ')'} | {A['slips']} BM slips | OR Sales Monitor for {days_txt}", sSub),
        Spacer(1, 6),
    ]
    head_title, head_sub = viewmodel.headline(A)
    story.append(Paragraph(f"<b>{escape(head_title)}</b> {escape(head_sub)}", _st('v', fontName='Helvetica', fontSize=10.2, leading=13.5, textColor=colors.HexColor('#111827'))))
    story.append(Spacer(1, 6))

    kp = viewmodel.kpis(A, order_total)
    cells = [[Paragraph(k['label'], sKl), Paragraph(k['value'], sKv), Paragraph(escape(k['sub'] + (f"  ({k['delta']['text']})" if k['delta'] else '')), sKs)] for k in kp]
    tiles = Table([cells], colWidths=[W_PAGE / 4] * 4)
    tiles.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, LINE), ('INNERGRID', (0, 0), (-1, -1), 0.5, LINE),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9fafb')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(tiles)

    if A['notes']:
        story.append(Paragraph('Data checks', sH2))
        for x in A['notes']:
            story.append(Paragraph(escape(x), sBul, bulletText='•'))

    story.append(Paragraph('Category summary &amp; 7-day order', sH))
    d = [['Category', 'SKUs', 'Units sold', 'OR sales', 'BM units', 'BM cost', 'BM % sales*', 'Base BM %', 'Order 7d']]
    for g in groups:
        t = tot[g]
        co = cat_orders.get(g, {})
        d.append([
            catcell(g), f"{t['skus']:,.0f}", f"{t['units']:,.0f}", php(t['sales'], 0),
            f"{t['bmu']:.0f}", php(t['bmc']), pct1(_pct(t['bmr'], t['sales'])),
            pct1(_pct(base['groups'][g]['bmu'], base['groups'][g]['units'])) if base and g in base['groups'] else '-',
            f"{co.get('order', 0):,.0f}",
        ])
    d.append([
        Paragraph('<b>Total</b>', sCell), f"{T['skus']:,.0f}", f"{T['units']:,.0f}", php(T['sales'], 0),
        f"{T['bmu']:.0f}", php(T['bmc']), pct1(_pct(T['bmr'], T['sales'])),
        pct1(_pct(base['T']['bmu'], base['T']['units'])) if base else '-',
        f"{order_total:,.0f}",
    ])
    story.append(tbl(d, [118, 34, 48, 64, 40, 60, 48, 53, 58], ['L'] + ['R'] * 8, total_row=True, tight=True))
    story.append(Paragraph('*BM retail value / OR sales. Ordered by sales. Count stock on hand before ordering (no delivery/stock data).', sSm))

    story.append(Paragraph(f"Period comparison (vs. previous {ncal} days &amp; baseline)", sH))
    ch = [['Metric', A['label'], 'Previous period', 'Change', 'Baseline, same length']]
    for key, lbl, money in (('units', 'Units sold', False), ('sales', 'OR sales', True), ('bmu', 'BM units', False), ('bmc', 'BM cost', True)):
        f = (lambda v: php(v, 0)) if money else (lambda v: f"{v:,.0f}")
        cur = T[key]; pv = prev['T'][key] if prev else None; bl = base['T_wk'][key] * n / 7 if base else None
        ch.append([lbl, f(cur), f(pv) if pv is not None else '-', f"{_pct(cur - pv, pv):+.1f}%" if pv else '-', f(bl) if bl is not None else '-'])
    story.append(tbl(ch, [135, 95, 95, 70, 128], ['L', 'R', 'R', 'R', 'R'], tight=True))
    story.append(PageBreak())

    # ------------------------------------------------------------ Page 2: Daily Trend & Key Takeaways
    story += [Paragraph('Daily sales &amp; bad merchandise', sH), Image(io.BytesIO(daily_chart(A)), width=W_PAGE, height=W_PAGE * 2.95 / 7.2)]
    dd = [['Date', 'Units sold', 'OR sales', 'BM units', 'BM cost', 'BM retail', 'BM % of sales']]
    for dy in A['daily']:
        dd.append([
            f"{dy['wd']} {dy['label']}",
            f"{dy['units']:,.0f}" if dy['has_or'] else 'no OR',
            php(dy['sales_total'], 0) if dy['has_or'] else 'no OR',
            f"{dy['bmu']:.0f}", php(dy['bmc_total']), php(dy['bmr']),
            pct1(_pct(dy['bmr'], dy['sales_total'])),
        ])
    dd.append([f'Total, {n} days', f"{T['units']:,.0f}", php(T['sales'], 0), f"{T['bmu']:.0f}", php(T['bmc']), php(T['bmr']), pct1(_pct(T['bmr'], T['sales']))])
    story.append(tbl(dd, [80, 66, 80, 60, 80, 80, 77], ['L'] + ['R'] * 6, total_row=True, tight=len(dd) > 14))
    story.append(Paragraph('Key takeaways', sH))
    for b in A['bullets']:
        story.append(Paragraph(b, sBul, bulletText='•'))
    story.append(PageBreak())

    # ------------------------------------------------------------ Page 3: Wastage & Top Sellers
    top_bm = sorted([r for r in rows if r['bm'] > 0], key=lambda r: (-r['bmcost'], -r['bm']))
    low = [r for r in rows if r['bm'] == 1]
    story.append(Paragraph('Top bad merchandise (top 15 by cost)', sH))
    story.append(Paragraph(
        f"{len(top_bm)} products had BM in this period ({len(low)} had only 1 unit written off, totaling {php(sum(r['bmcost'] for r in low))} cost).",
        sB,
    ))
    d = [['Product', 'Category', 'BM', 'BM cost', 'Sold', 'BM / sold', 'Base BM / sold']]
    for r in top_bm[:15]:
        base_txt = f"{r['base_bm']:.0f} / {r['base_sold']:.0f}" if r['inbase'] else '-'
        d.append([r['name'], catcell(r['group']), f"{r['bm']:.0f}", php(r['bmcost']), f"{r['sold']:.0f}",
                  pct1(_pct(r['bm'], r['sold'])) if r['sold'] else 'no sales', base_txt])
    if len(d) == 1:
        d.append(['No BM in this period', '', '', '', '', '', ''])
    story.append(tbl(d, [168, 86, 32, 60, 44, 55, 78], ['L', 'L'] + ['R'] * 5, tight=True))

    by_units = sorted(sold, key=lambda r: (-r['sold'], -r['amt'], r['name']))
    by_sales = sorted(sold, key=lambda r: (-r['amt'], r['name']))
    story.append(Paragraph('Top selling products', sH))
    story.append(Paragraph('Top 15 by units sold (with OR sales, daily pace, and BM).', sB))
    d = [['#', 'Product', 'Category', 'Sold', 'OR sales', 'Days', 'Per day', 'Base / day', 'BM']]
    for i, r in enumerate(by_units[:15], 1):
        d.append([str(i), r['name'], catcell(r['group']), f"{r['sold']:,.0f}", php(r['amt'], 0), f"{r['days']}/{n}",
                  f"{r['per_day']:.1f}", f"{r['base_day']:.1f}" if r['inbase'] and r['base_day'] is not None else 'new',
                  f"{r['bm']:.0f}" if r['bm'] else '-'])
    story.append(tbl(d, [18, 180, 84, 35, 56, 33, 35, 48, 34], ['L', 'L', 'L'] + ['R'] * 6, tight=True))

    top_unit_codes = {r['code'] for r in by_units[:15]}
    extra_sales = [r for r in by_sales[:12] if r['code'] not in top_unit_codes][:6]
    if extra_sales:
        story.append(Paragraph('Additional high-value sellers (by OR sales)', sH2))
        d = [['Product', 'Category', 'OR sales', 'Sold', 'Days', 'BM']]
        for r in extra_sales:
            d.append([r['name'], catcell(r['group']), php(r['amt'], 0), f"{r['sold']:,.0f}", f"{r['days']}/{n}", f"{r['bm']:.0f}" if r['bm'] else '-'])
        story.append(tbl(d, [220, 100, 74, 46, 42, 41], ['L', 'L', 'R', 'R', 'R', 'R'], tight=True))
    story.append(PageBreak())

    # ------------------------------------------------------------ Page 4: Actionable 7-Day Order Guide
    story.append(Paragraph('7-day order action plan', sH))
    story.append(Paragraph(
        "<b>Actions:</b> <b>PAUSE</b> = 0 sold with BM (check before ordering). <b>CUT</b> = 25%+ waste (-30%). "
        "<b>TRIM</b> = 10-25% waste (-15%). <b>INCREASE</b> = fresh/perishable with &lt;3% waste &amp; 5+/wk (+10%). Count stock on hand first.",
        sB,
    ))
    story.append(Image(io.BytesIO(weekday_chart(A)), width=W_PAGE, height=W_PAGE * 2.35 / 7.2))
    story.append(Paragraph(f"Weekday averages over the last {A['weekday_days']} OR days ({escape(A['scope_label'].lower())}).", sSm))

    brief = viewmodel.order_brief(rows)
    action_rows = brief['pz'][:10] + brief['tc'][:18] + brief['inc'][:12]
    story.append(Paragraph(f"Priority products to adjust ({len(brief['pz'])} pause, {len(brief['tc'])} trim/cut, {len(brief['inc'])} increase)", sH2))
    d = [['Product', 'Category', 'Action', 'Sold', 'BM', 'Waste %', 'Base / wk', 'Order 7d']]
    for r in action_rows:
        d.append([
            r['name'], catcell(r['group']), act(r['action']), f"{r['sold']:.0f}", f"{r['bm']:.0f}" if r['bm'] else '-',
            f"{100 * r['rate']:.0f}%" if r['rate'] else '-',
            f"{r['base_wk']:.1f}" if r['inbase'] else 'new',
            'Hold' if r['action'] == 'PAUSE' else f"{r['order']}",
        ])
    if len(d) == 1:
        d.append(['All products on HOLD (no adjustments needed)'] + [''] * 7)
    story.append(tbl(d, [168, 84, 46, 36, 32, 44, 52, 61], ['L', 'L', 'L'] + ['R'] * 5, tight=True))

    ns = A['notsold']
    if ns:
        d = [['Product', 'Category', 'Base units', 'Base days', 'Prev. sold']]
        for x in ns[:8]:
            d.append([x['name'], catcell(x['group']), f"{x['base_units']:.0f}", f"{x['base_days']}/{A['base_days']}", f"{x['prev']:.0f}"])
        story.append(KeepTogether([
            Paragraph(f"Regular sellers with no sales ({len(ns):,} total, top 8)", sH2),
            tbl(d, [220, 108, 65, 65, 65], ['L', 'L', 'R', 'R', 'R'], tight=True),
        ]))

    # ------------------------------------------------------------ Appendix (when filtered to <= APPENDIX_MAX products)
    full = sorted(rows, key=lambda r: (-r['sold'], -r['amt'], r['name']))
    if len(full) <= APPENDIX_MAX:
        story.append(PageBreak())
        story.append(Paragraph(f"Every product: sales, BM and ordering guide ({len(full)} products)", sH))
        story.append(Paragraph("Ranked by units sold. 'Order 7d' = suggested units for the next 7 days (estimate).", sB))
        story.append(Spacer(1, 3))
        d = [['#', 'Product', 'Category', 'Sold', 'OR sales PHP', 'Days', 'Per day', 'Base / day', 'BM', 'BM cost PHP', 'Action', 'Order 7d']]
        for i, r in enumerate(full, 1):
            d.append([str(i), r['name'], catcell(r['group']), f"{r['sold']:,.0f}", f"{r['amt']:,.0f}", f"{r['days']}/{n}", f"{r['per_day']:.1f}",
                      f"{r['base_day']:.1f}" if r['inbase'] and r['base_day'] is not None else 'new', f"{r['bm']:.0f}" if r['bm'] else '-', f"{r['bmcost']:,.2f}" if r['bm'] else '-', act(r['action']), f"{r['order']}"])
        story.append(tbl(d, [18, 128, 62, 28, 42, 26, 28, 34, 26, 44, 44, 43], ['L', 'L', 'L'] + ['R'] * 7 + ['L', 'R'], tight=True))
    else:
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"Note: This report covers {len(full):,} products. Use <b>Export CSV</b> on the report page for every product, or <b>Top 30 PDF</b> for top 30 per category.",
            sSm,
        ))

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=40, title=title)
    doc.addPageTemplates([PageTemplate(id='p', frames=[Frame(36, 40, A4[0] - 72, A4[1] - 76, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=footer)])
    doc.build(story)
    return buf.getvalue()


def build_top30_pdf(A):
    """Returns PDF bytes containing Top 30 BM and Top 30 Selling for each category in A['groups']."""
    rows, tot, n, groups = A['rows'], A['tot'], A['n'], A['groups']
    title = f"Top 30 by Category - {A['label']}"
    story = []

    def footer(c, doc):
        c.saveState(); c.setFont('Helvetica', 6.8); c.setFillColor(GRAY)
        c.drawString(36, 22, f"{title} - {A['scope_label']}")
        c.drawRightString(A4[0] - 36, 22, f'Page {doc.page}')
        c.restoreState()

    story += [
        Paragraph(escape(title), sTitle),
        Paragraph(f"{len(groups)} categor{'ies' if len(groups) != 1 else 'y'} | Top 30 Bad Merchandise &amp; Top 30 Selling per category", sSub),
        Spacer(1, 8),
    ]

    for gi, g in enumerate(groups):
        if gi > 0:
            story.append(PageBreak())
        t = tot[g]
        c_hex = COLORS.get(g)
        g_head = col(g, c_hex) if c_hex else escape(g)
        story.append(Paragraph(g_head, sH))
        story.append(Paragraph(
            f"OR sales: <b>{php(t['sales'], 0)}</b> ({t['units']:,.0f} units, {t['skus']:,.0f} products) | "
            f"BM: <b>{t['bmu']:,.0f}</b> units ({php(t['bmc'])} cost, {pct1(_pct(t['bmr'], t['sales']))} of sales)",
            sB,
        ))

        g_rows = [r for r in rows if r['group'] == g]
        g_bm = sorted([r for r in g_rows if r['bm'] > 0], key=lambda r: (-r['bmcost'], -r['bm']))[:30]
        g_sold = [r for r in g_rows if r['sold'] > 0]
        g_units = sorted(g_sold, key=lambda r: (-r['sold'], -r['amt'], r['name']))[:30]
        g_sales = sorted(g_sold, key=lambda r: (-r['amt'], r['name']))[:30]

        story.append(Paragraph(f'Top {len(g_bm)} bad merchandise (by cost)', sH2))
        if g_bm:
            d = [['#', 'Product', 'BM units', 'BM cost', 'Units sold', 'BM / sold', 'Base BM', 'Base sold']]
            for i, r in enumerate(g_bm, 1):
                d.append([str(i), r['name'], f"{r['bm']:.0f}", php(r['bmcost']), f"{r['sold']:.0f}",
                          pct1(_pct(r['bm'], r['sold'])) if r['sold'] else 'no sales',
                          f"{r['base_bm']:.0f}" if r['inbase'] else '-', f"{r['base_sold']:.0f}" if r['inbase'] else '-'])
            story.append(tbl(d, [18, 198, 42, 62, 46, 52, 52, 53], ['L', 'L'] + ['R'] * 6, tight=True))
        else:
            story.append(Paragraph('No bad merchandise recorded in this category.', sSm))

        story.append(Paragraph(f'Top {len(g_units)} selling by units', sH2))
        if g_units:
            d = [['#', 'Product', 'Sold', 'OR sales', 'Days', 'Per day', 'Base / day', 'BM']]
            for i, r in enumerate(g_units, 1):
                d.append([str(i), r['name'], f"{r['sold']:,.0f}", php(r['amt'], 0), f"{r['days']}/{n}",
                          f"{r['per_day']:.1f}", f"{r['base_day']:.1f}" if r['inbase'] and r['base_day'] is not None else 'new',
                          f"{r['bm']:.0f}" if r['bm'] else '-'])
            story.append(tbl(d, [18, 232, 40, 64, 38, 42, 52, 37], ['L', 'L'] + ['R'] * 6, tight=True))
        else:
            story.append(Paragraph('No units sold in this category.', sSm))

        story.append(Paragraph(f'Top {len(g_sales)} selling by sales value', sH2))
        if g_sales:
            d = [['#', 'Product', 'OR sales', 'Sold', 'Days', 'BM']]
            for i, r in enumerate(g_sales, 1):
                d.append([str(i), r['name'], php(r['amt'], 0), f"{r['sold']:,.0f}", f"{r['days']}/{n}", f"{r['bm']:.0f}" if r['bm'] else '-'])
            story.append(tbl(d, [18, 286, 80, 50, 45, 44], ['L', 'L', 'R', 'R', 'R', 'R'], tight=True))
        else:
            story.append(Paragraph('No sales recorded in this category.', sSm))

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=40, title=title)
    doc.addPageTemplates([PageTemplate(id='p', frames=[Frame(36, 40, A4[0] - 72, A4[1] - 76, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=footer)])
    doc.build(story)
    return buf.getvalue()
