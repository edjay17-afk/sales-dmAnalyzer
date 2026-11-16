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
    """Returns PDF bytes."""
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

    # ------------------------------------------------------------ overview
    ncal = A['n_cal']
    days_txt = f"{n} day{'s' if n != 1 else ''}" + ('' if n == ncal else f" (of {ncal} calendar days)")
    story += [Paragraph(escape(title).replace('&amp;', '&amp;'), sTitle),
              Paragraph(f"{'All ' + str(len(groups)) + ' categories' if A['sel'] is None else escape(', '.join(A['scope_list']) if len(A['scope_list']) <= 6 else A['scope_label']) + ' (' + str(len(groups)) + ' categor' + ('ies' if len(groups) != 1 else 'y') + ')'} | {A['slips']} BM slips | OR Sales Monitor for {days_txt}", sSub), Spacer(1, 7)]
    head_title, head_sub = viewmodel.headline(A)
    story.append(Paragraph(f"<b>{escape(head_title)}</b> {escape(head_sub)}", _st('v', fontName='Helvetica', fontSize=10.5, leading=14, textColor=colors.HexColor('#111827'))))
    story.append(Spacer(1, 7))

    kp = viewmodel.kpis(A, order_total)
    cells = [[Paragraph(k['label'], sKl), Paragraph(k['value'], sKv), Paragraph(escape(k['sub'] + (f"  ({k['delta']['text']})" if k['delta'] else '')), sKs)] for k in kp]
    tiles = Table([cells], colWidths=[W_PAGE / 4] * 4)
    tiles.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.5, LINE), ('INNERGRID', (0, 0), (-1, -1), 0.5, LINE), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f9fafb')),
                               ('LEFTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(tiles)

    br = A['base_range']
    base_txt = f" The baseline is the {A['base_days']} days of OR history before this period ({br[0]} to {br[1]})." if base else ''
    fixed = [
        "<b>Categories.</b> Every OR category is analysed. Hot Meals are category 39 Rice Meals and Fresh Food is categories 43 and 46 combined, as in the October reports. BM slips carry no category, so each BM product takes the category it is sold under on the OR reports.",
        f"<b>Checks.</b> Each OR report is tied to its printed category and grand totals, and each BM slip to its printed total.{escape(base_txt)} Products are matched by item code. Expense items are not counted.",
        "<b>Reading BM vs sales.</b> BM comes from earlier deliveries, so a product can show more BM than units sold in the same period. BM % on products selling under 5 a week swings widely, so treat those as flags.",
        "<b>No stock or delivery data.</b> Ordering figures are estimates from sales and BM history. Count what is on hand before ordering."]
    story.append(Paragraph('Data notes &amp; assumptions', sH))
    for b in [escape(x) for x in A['notes']] + fixed:
        story.append(Paragraph(b, sBul, bulletText='•'))

    story.append(Paragraph('By category', sH))
    d = [['Category', 'Products sold', 'Units sold', 'OR sales', 'BM units', 'BM cost', 'BM % of units', 'BM % of sales*', 'Baseline BM % units']]
    for g in groups:
        t = tot[g]
        d.append([catcell(g), f"{t['skus']:,.0f}", f"{t['units']:,.0f}", php(t['sales'], 0), f"{t['bmu']:.0f}", php(t['bmc']), pct1(_pct(t['bmu'], t['units'])), pct1(_pct(t['bmr'], t['sales'])),
                  pct1(_pct(base['groups'][g]['bmu'], base['groups'][g]['units'])) if base and g in base['groups'] else '-'])
    d.append([Paragraph('<b>Total</b>', sCell), f"{T['skus']:,.0f}", f"{T['units']:,.0f}", php(T['sales'], 0), f"{T['bmu']:.0f}", php(T['bmc']), pct1(_pct(T['bmu'], T['units'])), pct1(_pct(T['bmr'], T['sales'])),
              pct1(_pct(base['T']['bmu'], base['T']['units'])) if base else '-'])
    story.append(tbl(d, [118, 42, 42, 64, 36, 62, 44, 44, 71], ['L'] + ['R'] * 8, total_row=True, tight=True))
    story.append(Paragraph('*BM retail value divided by OR sales, both at selling price. Ordered by sales.', sSm))

    story.append(Paragraph(f"This period vs. previous {ncal} days and baseline", sH))
    ch = [['', A['label'], 'Previous period', 'Change', 'Baseline, same length']]
    for key, lbl, money in (('units', 'Units sold', False), ('sales', 'OR sales', True), ('bmu', 'BM units', False), ('bmc', 'BM cost', True)):
        f = (lambda v: php(v, 0)) if money else (lambda v: f"{v:,.0f}")
        cur = T[key]; pv = prev['T'][key] if prev else None; bl = base['T_wk'][key] * n / 7 if base else None
        ch.append([lbl, f(cur), f(pv) if pv is not None else '-', f"{_pct(cur - pv, pv):+.1f}%" if pv else '-', f(bl) if bl is not None else '-'])
    story.append(tbl(ch, [140, 92, 92, 70, 129], ['L', 'R', 'R', 'R', 'R']))
    story.append(Paragraph(f"Previous period = the {ncal} days right before the start" + (f" ({prev['days']} with OR data)." if prev else ' (no OR data on file).') + ' Baseline totals are scaled to the same length.', sSm))
    story.append(PageBreak())

    # ------------------------------------------------------------ daily + stands out
    story += [Paragraph('Daily sales and bad merchandise', sH), Image(io.BytesIO(daily_chart(A)), width=W_PAGE, height=W_PAGE * 2.95 / 7.2)]
    dd = [['Date', 'Units sold', 'OR sales', 'BM units', 'BM cost', 'BM retail', 'BM % of sales']]
    for dy in A['daily']:
        dd.append([f"{dy['wd']} {dy['label']}", f"{dy['units']:,.0f}" if dy['has_or'] else 'no OR', php(dy['sales_total'], 0) if dy['has_or'] else 'no OR', f"{dy['bmu']:.0f}",
                   php(dy['bmc_total']), php(dy['bmr']), pct1(_pct(dy['bmr'], dy['sales_total']))])
    dd.append([f'Total, {n} days', f"{T['units']:,.0f}", php(T['sales'], 0), f"{T['bmu']:.0f}", php(T['bmc']), php(T['bmr']), pct1(_pct(T['bmr'], T['sales']))])
    story.append(tbl(dd, [80, 66, 80, 60, 80, 80, 77], ['L'] + ['R'] * 6, total_row=True, tight=len(dd) > 14))
    story.append(Paragraph('What stands out', sH))
    for b in A['bullets']:
        story.append(Paragraph(b, sBul, bulletText='•'))
    story.append(PageBreak())

    # ------------------------------------------------------------ top BM + low wastage
    top_bm = sorted([r for r in rows if r['bm'] > 0], key=lambda r: (-r['bmcost'], -r['bm']))
    story.append(Paragraph('Top bad merchandise (by cost)', sH))
    story.append(Paragraph(f"The 15 costliest of {len(top_bm)} products with BM in this period.", sB))
    d = [['Product', 'Category', 'BM units', 'BM cost', 'Units sold', 'BM / sold', 'Base BM', 'Base sold']]
    for r in top_bm[:15]:
        d.append([r['name'], catcell(r['group']), f"{r['bm']:.0f}", php(r['bmcost']), f"{r['sold']:.0f}", pct1(_pct(r['bm'], r['sold'])) if r['sold'] else 'no sales',
                  f"{r['base_bm']:.0f}" if r['inbase'] else '-', f"{r['base_sold']:.0f}" if r['inbase'] else '-'])
    if len(d) == 1:
        d.append(['No BM in this period', '', '', '', '', '', '', ''])
    story.append(tbl(d, [150, 78, 38, 58, 44, 50, 52, 53], ['L', 'L'] + ['R'] * 6))
    story.append(Paragraph('BM / sold compares BM units with units sold for that product in this period. Base columns cover the 31 days before the period.', sSm))

    low = sorted([r for r in rows if r['bm'] == 1], key=lambda r: -r['bmcost'])
    story += [Paragraph('Lowest-wastage products (1 BM unit this period)', sH),
              Paragraph(f'Products written off exactly once, sorted by cost. "Sold" shows how much each one moved. {len(low)} products; the 25 costliest are shown.', sB), Spacer(1, 3)]
    d = [['Product', 'Category', 'BM cost', 'BM retail', 'Units sold']]
    for r in low[:25]:
        d.append([r['name'], catcell(r['group']), php(r['bmcost']), php(r['bmretail']), f"{r['sold']:.0f}"])
    if low:
        d.append([Paragraph(f'<b>All {len(low)} products</b>', sCell), '', php(sum(r['bmcost'] for r in low)), php(sum(r['bmretail'] for r in low)), ''])
    else:
        d.append(['None', '', '', '', ''])
    story.append(tbl(d, [208, 100, 70, 70, 75], ['L', 'L', 'R', 'R', 'R'], total_row=bool(low), tight=True))
    story.append(PageBreak())

    # ------------------------------------------------------------ top selling
    story.append(Paragraph('Top selling', sH))
    by_units = sorted(sold, key=lambda r: (-r['sold'], -r['amt'], r['name']))
    by_sales = sorted(sold, key=lambda r: (-r['amt'], r['name']))
    story.append(Paragraph('By units sold, top 25', sH2))
    d = [['#', 'Product', 'Category', 'Sold', 'OR sales', 'Days', 'Per day', 'Base / day', 'BM']]
    for i, r in enumerate(by_units[:25], 1):
        d.append([str(i), r['name'], catcell(r['group']), f"{r['sold']:,.0f}", php(r['amt'], 0), f"{r['days']}/{n}", f"{r['per_day']:.1f}", f"{r['base_day']:.1f}" if r['inbase'] and r['base_day'] is not None else 'new', f"{r['bm']:.0f}" if r['bm'] else '-'])
    story.append(tbl(d, [18, 180, 84, 35, 56, 33, 35, 48, 34], ['L', 'L', 'L'] + ['R'] * 6, tight=True))
    story.append(Paragraph('By sales value, top 15', sH2))
    d = [['#', 'Product', 'Category', 'OR sales', 'Sold', 'Days', 'BM']]
    for i, r in enumerate(by_sales[:15], 1):
        d.append([str(i), r['name'], catcell(r['group']), php(r['amt'], 0), f"{r['sold']:,.0f}", f"{r['days']}/{n}", f"{r['bm']:.0f}" if r['bm'] else '-'])
    story.append(tbl(d, [18, 210, 96, 72, 46, 42, 39], ['L', 'L', 'L', 'R', 'R', 'R', 'R'], tight=True))
    story.append(PageBreak())

    # ------------------------------------------------------------ order suggestions
    story.append(Paragraph('Ordering suggestions for the next 7 days', sH))
    story.append(Paragraph(
        "<b>How these were worked out.</b> Expected weekly demand = the average of this period's units sold (scaled to 7 days) and the product's baseline weekly rate over the 31 days before the period "
        "(counted from its first sale if it started later). New products use this period only. The waste rate blends BM against units sold plus BM. "
        "<b>INCREASE</b> (short shelf life categories only: Crunch Time, Rice Meals, Fresh and Hot Foods, Bread and Bakery, Donuts, Dairy, Hotdog, City Cafe): waste under 3% and 5+ units a week, demand +10%. "
        "<b>HOLD</b>: demand as is. <b>TRIM</b>: waste 10-25%, demand -15%. <b>CUT</b>: waste 25%+ with BM in the period, demand -30%. <b>PAUSE</b>: 0 sold, do not reorder until you check why. "
        "<b>Estimates only</b>: no delivery or stock data, so count on-hand before ordering.", sB))
    story.append(Paragraph('Suggested order by category', sH2))
    d = [['Category', 'Products sold', 'Expected demand / week', 'Suggested order, next 7 days', 'Received last period (est.)', 'Change']]
    for g, x in viewmodel.category_orders(A):
        d.append([catcell(g), f"{x['products']:,.0f}", f"{x['demand']:,.0f}", f"{x['order']:,.0f}", f"{x['est']:,.0f}" if x['perishable'] else '-',
                  f"{_pct(x['order'] - x['est'], x['est']):+.1f}%" if x['perishable'] and x['est'] else '-'])
    story.append(tbl(d, [130, 60, 90, 100, 90, 53], ['L'] + ['R'] * 5, tight=True))
    story.append(Paragraph('Received = units sold + BM scaled to 7 days, which assumes stock on hand did not change. That only holds for short shelf life categories, so it is shown for those only.', sSm))
    story += [Paragraph('Day-of-week guide', sH2), Image(io.BytesIO(weekday_chart(A)), width=W_PAGE, height=W_PAGE * 2.35 / 7.2),
              Paragraph(f"Averages over the last {A['weekday_days']} days with OR data, for {escape(A['scope_label'].lower())}. Small differences: use them to shape daily par, not to cut the week.", sSm)]
    story.append(PageBreak())

    brief = viewmodel.order_brief(rows)
    story.append(Paragraph(col('INCREASE / keep full stock', ACT_COL['INCREASE']) + f" - top 12 of {len(brief['inc'])} products", sH2))
    d = [['Product', 'Category', 'Sold', 'Baseline / wk', 'BM', 'Days sold', 'Order next 7d']]
    for r in brief['inc'][:12]:
        d.append([r['name'], catcell(r['group']), f"{r['sold']:.0f}", f"{r['base_wk']:.1f}" if r['inbase'] else 'new', f"{r['bm']:.0f}", f"{r['days']}/{n}", f"{r['order']}"])
    if len(d) == 1:
        d.append(['None', '', '', '', '', '', ''])
    story.append(tbl(d, [170, 90, 40, 56, 30, 56, 81], ['L', 'L', 'R', 'R', 'R', 'R', 'R'], tight=True))

    story.append(Paragraph(col('TRIM / CUT', ACT_COL['TRIM']) + f" - high waste rate, 25 costliest of {len(brief['tc'])}", sH2))
    d = [['Product', 'Category', 'Action', 'Sold', 'BM', 'Base sold', 'Base BM', 'Waste', 'Est. received', 'Order 7d']]
    for r in brief['tc'][:25]:
        d.append([r['name'], catcell(r['group']), act(r['action']), f"{r['sold']:.0f}", f"{r['bm']:.0f}", f"{r['base_sold']:.0f}", f"{r['base_bm']:.0f}", f"{100 * r['rate']:.0f}%", f"{r['est_received']:.0f}", f"{r['order']}"])
    if len(d) == 1:
        d.append(['None'] + [''] * 9)
    story.append(tbl(d, [136, 72, 42, 30, 28, 40, 38, 34, 53, 50], ['L', 'L', 'L'] + ['R'] * 7, tight=True))
    story.append(Paragraph('Waste rate = BM / (sold + BM), blended with the baseline. Items under 5 a week are small samples. If a product is on a fixed display minimum, lower the minimum instead of the order.', sSm))

    story.append(Paragraph(col('PAUSE / check before reordering', ACT_COL['PAUSE']) + f" - sold 0 but written off, {len(brief['pz'])} products", sH2))
    d = [['Product', 'Category', 'BM', 'BM cost', 'Base sold', 'Base BM', 'Prev. period sold']]
    for r in brief['pz'][:15]:
        d.append([r['name'], catcell(r['group']), f"{r['bm']:.0f}", php(r['bmcost']), f"{r['base_sold']:.0f}", f"{r['base_bm']:.0f}", f"{r['prev']:.0f}"])
    if len(d) == 1:
        d.append(['None'] + [''] * 6)
    story.append(tbl(d, [180, 90, 30, 60, 50, 50, 63], ['L', 'L'] + ['R'] * 5, tight=True))

    ns = A['notsold']
    d = [['Product', 'Category', 'Base units', 'Base days sold', 'Base BM', 'Prev. period sold']]
    for x in ns[:12]:
        d.append([x['name'], catcell(x['group']), f"{x['base_units']:.0f}", f"{x['base_days']}/{A['base_days']}", f"{x['base_bm']:.0f}", f"{x['prev']:.0f}"])
    if not ns:
        d.append(['None'] + [''] * 5)
    story.append(KeepTogether([
        Paragraph('Regular sellers with no sales in this period', sH2),
        Paragraph(f"{len(ns):,} products that sold on 6+ days of the baseline but not once in this period. Confirm whether they are still listed, out of stock, or no longer ordered before adding them back. The 12 with the most baseline units:", sB),
        Spacer(1, 3),
        tbl(d, [190, 90, 55, 65, 50, 73], ['L', 'L'] + ['R'] * 4, tight=True),
    ]))

    # ------------------------------------------------------------ appendix: every product (when it fits)
    full = sorted(rows, key=lambda r: (-r['sold'], -r['amt'], r['name']))
    if len(full) <= APPENDIX_MAX:
        story.append(PageBreak())
        story.append(Paragraph(f"Every product: sales, BM and ordering guide ({len(full)} products)", sH))
        story.append(Paragraph("Ranked by units sold. 'Per day' = units / days in the period. 'Base / day' = baseline units per day on sale. 'new' = not in the baseline. 'Order 7d' = suggested units for the next 7 days (estimate).", sB))
        story.append(Spacer(1, 3))
        d = [['#', 'Product', 'Category', 'Sold', 'OR sales PHP', 'Days', 'Per day', 'Base / day', 'BM', 'BM cost PHP', 'Action', 'Order 7d']]
        for i, r in enumerate(full, 1):
            d.append([str(i), r['name'], catcell(r['group']), f"{r['sold']:,.0f}", f"{r['amt']:,.0f}", f"{r['days']}/{n}", f"{r['per_day']:.1f}",
                      f"{r['base_day']:.1f}" if r['inbase'] and r['base_day'] is not None else 'new', f"{r['bm']:.0f}" if r['bm'] else '-', f"{r['bmcost']:,.2f}" if r['bm'] else '-', act(r['action']), f"{r['order']}"])
        story.append(tbl(d, [18, 128, 62, 28, 42, 26, 28, 34, 26, 44, 44, 43], ['L', 'L', 'L'] + ['R'] * 7 + ['L', 'R'], tight=True))
    else:
        story.append(Spacer(1, 6))
        story.append(Paragraph('Every product', sH))
        story.append(Paragraph(f"This report covers {len(full):,} products, too many to print usefully. Use <b>Export CSV</b> on the report page for every product with its action and suggested order, "
                               "or pick a single category in the report to get the full printed list for it.", sB))

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=40, title=title)
    doc.addPageTemplates([PageTemplate(id='p', frames=[Frame(36, 40, A4[0] - 72, A4[1] - 76, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=footer)])
    doc.build(story)
    return buf.getvalue()
