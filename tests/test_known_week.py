"""Checks the analyzer against figures verified by hand against the PDFs.

Run after seeding:  python tests/test_known_week.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analyzer import analysis, db
from analyzer.pdf_report import build_pdf

con = db.connect()
bad = 0


def check(label, got, want, tol=0.005):
    global bad
    ok = abs(got - want) < tol
    bad += not ok
    print(('ok   ' if ok else 'FAIL '), label, got, '(expected', want, ')')


# 1) Hot Meals + Fresh Food for Nov 8-14, verified by hand (same figures as the report built earlier)
A = analysis.analyze(con, '2026-11-08', '2026-11-14', 'hmff')
T, tot = A['T'], A['tot']
for label, got, want in [
    ('HMFF days with OR data', A['n'], 7), ('HMFF BM units', T['bmu'], 36), ('HMFF BM cost', round(T['bmc'], 2), 1570.57), ('HMFF BM retail', round(T['bmr'], 2), 2272.00),
    ('HMFF OR sales', T['sales'], 49800.0), ('HMFF units sold', T['units'], 822),
    ('Hot Meals units', tot['Hot Meals']['units'], 216), ('Hot Meals sales', tot['Hot Meals']['sales'], 16419.0), ('Hot Meals BM units', tot['Hot Meals']['bmu'], 17),
    ('Hot Meals BM cost', round(tot['Hot Meals']['bmc'], 2), 886.94), ('Fresh Food units', tot['Fresh Food']['units'], 606), ('Fresh Food sales', tot['Fresh Food']['sales'], 33381.0),
    ('Fresh Food BM units', tot['Fresh Food']['bmu'], 19), ('Fresh Food BM cost', round(tot['Fresh Food']['bmc'], 2), 683.63)]:
    check(label, got, want)
siop = next(r for r in A['rows'] if r['name'] == '7-Fresh Siopao Budget Asado')
assert siop['sold'] == 92 and siop['amt'] == 3864 and siop['days'] == 7, siop

# 2) Every category: sales must equal the grand totals printed on each daily OR report
#    (sum of the 7 printed GRAND TOTAL lines: 12,608 units incl. 'expense items', PHP 623,251.75)
AA = analysis.analyze(con, '2026-11-08', '2026-11-14')
ex_units = con.execute("SELECT COALESCE(SUM(qty),0) FROM or_lines WHERE date BETWEEN '2026-11-08' AND '2026-11-14' AND cat LIKE 'EX-%'").fetchone()[0]
check('ALL OR sales vs printed grand totals', round(AA['T']['sales'], 2), 623251.75)
check('ALL units vs printed grand totals', AA['T']['units'] + ex_units, 12608)
check('HM+FF sales are inside the all-category total', AA['tot']['Hot Meals']['sales'] + AA['tot']['Fresh Food']['sales'], 49800.0)
check('Crunch Time BM units (earlier report: 29)', AA['tot']['Crunch Time']['bmu'], 29)
print('categories:', len(AA['groups']), '| products:', len(AA['rows']), '| notes:', AA['notes'])


# 2b) several categories at once
S1 = analysis.analyze(con, '2026-11-08', '2026-11-14', ['Hot Meals', 'Crunch Time', 'Dairy'])
parts = [analysis.analyze(con, '2026-11-08', '2026-11-14', [g]) for g in ('Hot Meals', 'Crunch Time', 'Dairy')]
check('multi: sales = sum of the single categories', round(S1['T']['sales'], 2), round(sum(x['T']['sales'] for x in parts), 2))
check('multi: BM cost = sum of the single categories', round(S1['T']['bmc'], 2), round(sum(x['T']['bmc'] for x in parts), 2))
check('multi: exactly the 3 chosen categories', len(S1['groups']), 3)
check('multi: legacy "hmff" string equals the list form', analysis.analyze(con, '2026-11-08', '2026-11-14', 'hmff')['T']['sales'], analysis.analyze(con, '2026-11-08', '2026-11-14', ['Hot Meals', 'Fresh Food'])['T']['sales'])
allnames = [g for g, _ in AA['all_groups']]
check('multi: ticking every category = all categories', analysis.analyze(con, '2026-11-08', '2026-11-14', allnames)['T']['sales'], AA['T']['sales'])
build_pdf(S1)

# 3) every OR day on file ties out (no parse warnings)
warn = con.execute("SELECT date, warnings FROM or_days WHERE warnings<>''").fetchall()
for r in warn:
    print('WARN', r['date'], r['warnings'])
check('OR days with parse warnings', len(warn), 0)

# 4) PDF builds for all categories and for a single category
for scope in (None, 'Hot Meals'):
    pdf = build_pdf(analysis.analyze(con, '2026-11-08', '2026-11-14', scope))
    assert pdf[:4] == b'%PDF' and len(pdf) > 20000
    print('pdf ok for scope', scope or 'all', len(pdf), 'bytes')
print('FAILED' if bad else 'ALL OK')
sys.exit(1 if bad else 0)
