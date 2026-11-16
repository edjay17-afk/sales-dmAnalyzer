"""Readers for the two store reports: OR Sales Monitor (one day) and Bad Merchandise slips.

Both PDFs are read by word position, then checked against the totals printed on the report.
"""
import re
from datetime import datetime

import pdfplumber



class ParseError(Exception):
    pass


def _is_code(t):
    """Item codes are 8 characters, normally all digits (expense items start with letters)."""
    return len(t) == 8 and t.isalnum() and t.upper() == t and sum(c.isdigit() for c in t) >= 6


def _num(s):
    return float(s.replace(',', ''))


def _rows(page, tol=2.5):
    words = page.extract_words()
    words.sort(key=lambda w: (round(w['top']), w['x0']))
    rows = []
    for w in words:
        if rows and abs(rows[-1][0] - w['top']) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([w['top'], [w]])
    for r in rows:
        r[1].sort(key=lambda w: w['x0'])
    return [r[1] for r in rows]


def _iso(mdy):
    return datetime.strptime(mdy, '%m/%d/%Y').strftime('%Y-%m-%d')


def detect_kind(pdf):
    text = (pdf.pages[0].extract_text() or '')[:600].upper()
    if 'OR SALES MONITOR' in text:
        return 'or'
    if 'BAD MERCHANDISE' in text:
        return 'bm'
    return None


def parse_or(pdf):
    """One-day OR Sales Monitor. Returns dict(date, store, items, warnings)."""
    out = {'kind': 'or', 'date': None, 'date_to': None, 'store': None, 'items': [], 'warnings': []}
    cat = None
    cat_totals = {}
    grand = None
    cur = None
    for page in pdf.pages:
        for ws in _rows(page):
            txt = ' '.join(w['text'] for w in ws)
            if txt.startswith('Store') and not out['store']:
                out['store'] = re.sub(r'\s*Print Date.*$', '', txt.split(':', 1)[1]).strip()
            m = re.match(r'Date From\s*:\s*(\S+)', txt)
            if m:
                out['date'] = m.group(1)
            m = re.match(r'Date To\s*:\s*(\S+)', txt)
            if m:
                out['date_to'] = m.group(1)
            m = re.match(r'Category\s*:\s*(.+)$', txt)
            if m:
                cat = m.group(1).strip()
                cur = None
                continue
            m = re.match(r'GRAND TOTAL:\s*([\d,]+)\s+([\d,\.]+)', txt)
            if m:
                grand = (_num(m.group(1)), _num(m.group(2)))
                continue
            m = re.match(r'Total:\s*([\d,]+)\s+([\d,\.]+)$', txt)
            if m and cat:
                cat_totals[cat] = (_num(m.group(1)), _num(m.group(2)))
                continue
            if ws and _is_code(ws[0]['text']) and ws[0]['x0'] < 30:
                name, qty, amt, barcode = [], None, None, ''
                for w in ws[1:]:
                    if w['x0'] < 100 and re.fullmatch(r'\d{10,14}', w['text']):
                        barcode = w['text']
                    elif w['x1'] < 478:
                        name.append(w['text'])
                    elif w['x1'] <= 500:
                        qty = _num(w['text'])
                    elif w['x1'] <= 568:
                        amt = _num(w['text'])
                cur = {'cat': cat, 'code': ws[0]['text'], 'name': ' '.join(name), 'qty': qty, 'amt': amt}
                out['items'].append(cur)
            elif (cur is not None and ws and cat and 100 < ws[0]['x0'] < 480 and all(w['x1'] < 478 for w in ws)
                  and not re.match(r'(Itemcode|Date|Store|PHILIPPINE|OR SALES|Page)', txt)):
                cur['name'] += ' ' + txt  # wrapped product name
    if not out['date']:
        raise ParseError('no "Date From" found')
    if out['date_to'] and out['date_to'] != out['date']:
        raise ParseError(f"covers {out['date']} to {out['date_to']}; upload one report per day")
    out['date'] = _iso(out['date'])
    bad = [i for i in out['items'] if i['qty'] is None or i['amt'] is None]
    if bad:
        out['warnings'].append(f"{len(bad)} line(s) with unreadable quantity/amount")
    # tie-out against the printed category totals and the grand total
    agg = {}
    for i in out['items']:
        if not i['cat']:
            continue
        a = agg.setdefault(i['cat'], [0.0, 0.0])
        a[0] += i['qty'] or 0
        a[1] += i['amt'] or 0
    for c, (q, a) in cat_totals.items():
        if c not in agg:
            out['warnings'].append(f"{c}: printed total found but no lines read")
        elif abs(agg[c][0] - q) > 0.01 or abs(agg[c][1] - a) > 0.01:
            out['warnings'].append(f"{c}: lines add to {agg[c][0]:.0f} units / {agg[c][1]:,.2f} but the report prints {q:.0f} / {a:,.2f}")
    out['items'] = [i for i in out['items'] if i['cat'] and i['qty'] is not None]
    sq = sum(i['qty'] for i in out['items']); sa = sum(i['amt'] or 0 for i in out['items'])
    if grand and (abs(sq - grand[0]) > 0.01 or abs(sa - grand[1]) > 0.01):
        out['warnings'].append(f"all lines add to {sq:.0f} units / {sa:,.2f} but the grand total is {grand[0]:.0f} / {grand[1]:,.2f}")
    if grand is None:
        out['warnings'].append('no grand total found on the report, so completeness could not be checked')
    out['checked'] = sorted(cat_totals)
    out['grand'] = grand
    if not out['items']:
        out['warnings'].append('no sales lines found')
    return out


def parse_bm(pdf):
    """One Bad Merchandise slip. Quantities and values are returned as positive numbers."""
    out = {'kind': 'bm', 'doc_id': None, 'slip_id': None, 'date': None, 'status': None, 'store': None,
           'items': [], 'total': None, 'warnings': []}
    for page in pdf.pages:
        for ws in _rows(page):
            txt = ' '.join(w['text'] for w in ws)
            if txt.startswith('Store') and not out['store']:
                out['store'] = re.sub(r'\s*Print Date.*$', '', txt.split(':', 1)[1]).strip()
            m = re.search(r'BM Slip ID\s*:\s*(\d+)', txt)
            if m:
                out['slip_id'] = m.group(1)
            m = re.search(r'BM Slip Date\s*:\s*(\S+)', txt)
            if m:
                out['date'] = m.group(1)
            m = re.search(r'Document ID\s*:\s*(\S+)', txt)
            if m:
                out['doc_id'] = m.group(1)
            m = re.search(r'Status\s*:\s*(\S+)', txt)
            if m:
                out['status'] = m.group(1)
            if txt.startswith('TOTAL:'):
                out['total'] = [_num(w['text']) for w in ws[1:]]
                continue
            if len(ws) >= 3 and re.fullmatch(r'\d+', ws[0]['text']) and ws[0]['x0'] < 45 and _is_code(ws[1]['text']):
                name, qty, nums = [], None, []
                for w in ws[2:]:
                    if w['x0'] < 355:
                        name.append(w['text'])
                    elif w['x0'] < 395 and qty is None:
                        qty = _num(w['text'])
                    else:
                        nums.append(_num(w['text']))
                if qty is None or len(nums) != 4:
                    out['warnings'].append(f"line {ws[0]['text']} ({' '.join(name)}) could not be read")
                    continue
                out['items'].append({'code': ws[1]['text'], 'name': ' '.join(name), 'qty': abs(qty),
                                     'unit_cost': abs(nums[0]), 'unit_retail': abs(nums[1]),
                                     'total_cost': abs(nums[2]), 'total_retail': abs(nums[3])})
    if not out['date'] or not out['doc_id']:
        raise ParseError('not a readable BM slip (no date / document id)')
    out['date'] = _iso(out['date'])
    out['doc_id'] = out['doc_id'].strip()
    if out['total'] and out['items']:
        sc = sum(i['total_cost'] for i in out['items']); sr = sum(i['total_retail'] for i in out['items'])
        if abs(sc - abs(out['total'][0])) > 0.01 or (len(out['total']) > 1 and abs(sr - abs(out['total'][1])) > 0.01):
            out['warnings'].append(f"lines add to {sc:,.2f} / {sr:,.2f} but the slip prints {out['total']}")
    elif not out['items']:
        out['warnings'].append('no item lines read')
    return out


def parse_pdf(source):
    """source: path or file-like. Returns parsed dict for an OR day or a BM slip."""
    try:
        with pdfplumber.open(source) as pdf:
            kind = detect_kind(pdf)
            if kind == 'or':
                return parse_or(pdf)
            if kind == 'bm':
                return parse_bm(pdf)
    except ParseError:
        raise
    except Exception as e:  # corrupt / not a PDF
        raise ParseError(f'could not open as PDF ({type(e).__name__})')
    raise ParseError('not an OR Sales Monitor or Bad Merchandise report')
