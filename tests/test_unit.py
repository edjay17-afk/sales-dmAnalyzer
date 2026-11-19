"""Isolated unit & Flask route tests using a temporary SQLite database.

Run: python tests/test_unit.py
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as flask_app
from analyzer import analysis, db
from analyzer.pdf_report import build_par_pdf


def _seed_sample_db(con):
    # 10 days of OR sales: 2026-10-01 .. 2026-10-10 (baseline) + 2026-10-11 .. 2026-10-17 (target week)
    for day in range(1, 18):
        dt = f"2026-10-{day:02d}"
        items = [
            {'cat': '39-Rice Meals', 'code': '39000001', 'barcode': '4800000000001', 'name': 'Hot Meal Star', 'qty': 10.0, 'amt': 690.0},
            {'cat': '43-Fresh Foods', 'code': '43000002', 'barcode': '4800000000002', 'name': 'Fresh Siopao', 'qty': 6.0, 'amt': 252.0},
            {'cat': 'EX-Expenses', 'code': 'EX000001', 'barcode': '', 'name': 'Free Sticker', 'qty': 5.0, 'amt': 0.0},
        ]
        # Stockout item: sold every day in baseline (days 1..10) and only days 11..12 in target week, 0 on days 13..17
        if day <= 12:
            items.append({'cat': '43-Fresh Foods', 'code': '43000003', 'barcode': '4800000000003', 'name': 'Stockout Sandwich', 'qty': 4.0, 'amt': 200.0})
        db.save_or(con, {'date': dt, 'store': '6216-Main', 'items': items, 'warnings': []}, source=f'or_{dt}.pdf')

    # Completed BM slip on 2026-10-15:
    # - 43000002: 20 BM units vs 42 sold in target week (plus 60 sold in baseline) -> check waste rate
    # - 99000099: Uncategorized BM item (never sold in OR, 0 sales -> PAUSE)
    db.save_bm(con, {
        'doc_id': 'BM_OK_1', 'slip_id': '1', 'date': '2026-10-15', 'status': 'COMPLETED', 'store': '6216-Main',
        'items': [
            {'code': '43000002', 'name': 'Fresh Siopao', 'qty': 25.0, 'unit_cost': 28.0, 'unit_retail': 42.0, 'total_cost': 700.0, 'total_retail': 1050.0},
            {'code': '99000099', 'name': 'Mystery Mystery Item', 'qty': 2.0, 'unit_cost': 15.0, 'unit_retail': 25.0, 'total_cost': 30.0, 'total_retail': 50.0},
        ],
        'total': [730.0, 1100.0], 'warnings': [],
    }, source='bm1.pdf')

    # Draft/pending BM slip (should be ignored in BM totals, flagged in notes)
    db.save_bm(con, {
        'doc_id': 'BM_DRAFT_2', 'slip_id': '2', 'date': '2026-10-16', 'status': 'OPEN', 'store': '6216-Main',
        'items': [
            {'code': '39000001', 'name': 'Hot Meal Star', 'qty': 50.0, 'unit_cost': 40.0, 'unit_retail': 69.0, 'total_cost': 2000.0, 'total_retail': 3450.0},
        ],
        'total': [2000.0, 3450.0], 'warnings': [],
    }, source='bm2.pdf')


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.td.name, 'test.db')
        self.con = db.connect(self.db_path)
        _seed_sample_db(self.con)

    def tearDown(self):
        self.con.close()
        self.td.cleanup()

    def test_allocate_daily_pars_conserves_total(self):
        weights = [1, 1, 1, 2, 3, 2, 1]
        for total in (0, 1, 7, 13, 100):
            pars = analysis.allocate_daily_pars(total, weights)
            self.assertEqual(len(pars), 7)
            self.assertEqual(sum(pars), total)
            self.assertTrue(all(x >= 0 for x in pars))

    def test_analysis_actions_margin_stockout_and_overrides(self):
        A = analysis.analyze(self.con, '2026-10-11', '2026-10-17')
        by_code = {r['code']: r for r in A['rows']}

        # EX000001 excluded
        self.assertNotIn('EX000001', by_code)

        # Hot Meal Star: perishable, 0% waste (OPEN slip ignored), D=70 -> INCREASE
        star = by_code['39000001']
        self.assertEqual(star['action'], 'INCREASE')
        self.assertEqual(star['barcode'], '4800000000001')
        self.assertEqual(star['order'], 77)  # ceil(70 * 1.1)
        self.assertEqual(sum(star['daily_pars']), 77)

        # Fresh Siopao: has BM slip with unit_cost=28, unit_retail=42 -> 33.3% margin
        siop = by_code['43000002']
        self.assertAlmostEqual(siop['margin_pct'], (42.0 - 28.0) / 42.0, places=4)
        self.assertEqual(siop['action'], 'TRIM')  # 25 / (42 + 42 + 25) ~ 22.9%

        # Stockout Sandwich: sold 10/10 baseline days, only 2/7 target days -> 5 trailing zero days
        sand = by_code['43000003']
        self.assertTrue(sand['stockout_risk'])
        self.assertEqual(sand['trailing_zero'], 5)

        # Mystery item starts Uncategorized and PAUSE
        myst = by_code['99000099']
        self.assertEqual(myst['group'], 'Uncategorized')
        self.assertEqual(myst['action'], 'PAUSE')

        # Override category + on_hand + pack_size
        db.upsert_product_meta(self.con, '99000099', cat_override='Fresh Food')
        db.upsert_product_meta(self.con, '39000001', on_hand=15, pack_size=10)
        A2 = analysis.analyze(self.con, '2026-10-11', '2026-10-17')
        by_code2 = {r['code']: r for r in A2['rows']}
        self.assertEqual(by_code2['99000099']['group'], 'Fresh Food')
        # raw=77, on_hand=15 -> rem=62, pack=10 -> net_order=70
        self.assertEqual(by_code2['39000001']['net_order'], 70)
        self.assertEqual(sum(by_code2['39000001']['daily_pars']), 70)

        # Daily Par PDF builds cleanly
        pdf = build_par_pdf(A2)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_product_detail_and_trends(self):
        D = analysis.product_detail(self.con, '43000002', end='2026-10-17', days=30)
        self.assertEqual(D['tot_units'], 102.0)
        self.assertEqual(D['tot_bmu'], 25.0)
        self.assertIsNotNone(D['econ'])

        T = analysis.weekly_trends(self.con, end='2026-10-17', weeks=4)
        self.assertGreaterEqual(len(T['buckets']), 3)
        self.assertEqual(T['buckets'][-1]['end'], '2026-10-17')


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.td.name, 'routes.db')
        self.orig_db_path = db.DB_PATH
        db.DB_PATH = self.db_path
        con = db.connect(self.db_path)
        _seed_sample_db(con)
        db.ensure_user(con, 'tester', 'secret123')
        con.close()
        flask_app.app.config['TESTING'] = True
        self.client = flask_app.app.test_client()

    def tearDown(self):
        db.DB_PATH = self.orig_db_path
        self.td.cleanup()

    def _get_csrf(self, html):
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        return m.group(1) if m else ''

    def test_auth_csrf_and_endpoints(self):
        # Redirects when logged out
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)

        # Login page exposes CSRF token
        r = self.client.get('/login')
        self.assertEqual(r.status_code, 200)
        csrf = self._get_csrf(r.get_data(as_text=True))
        self.assertTrue(csrf)

        # POST without CSRF fails 400
        r = self.client.post('/login', data={'username': 'tester', 'password': 'secret123'})
        self.assertEqual(r.status_code, 400)

        # Valid login succeeds
        r = self.client.post('/login', data={'username': 'tester', 'password': 'secret123', 'csrf_token': csrf}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)

        for path in ('/report', '/trends', '/history', '/settings', '/product/39000001', '/report-par.pdf', '/order-list.csv', '/report.csv'):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, path)

        # Inline product meta API updates net_order
        resp = self.client.post(
            '/api/product-meta',
            json={'code': '39000001', 'on_hand': 7, 'pack_size': 5, 'raw_order': 77},
            headers={'X-CSRF-Token': csrf},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['net_order'], 70)

        # Settings save & password change
        resp = self.client.post('/settings', data={
            'csrf_token': csrf, 'baseline_days': '31', 'weekday_days': '45', 'regular_days': '6',
            'cut_rate': '25', 'cut_factor': '0.70', 'trim_rate': '10', 'trim_factor': '0.85',
            'increase_rate': '3', 'increase_min_demand': '5', 'increase_factor': '1.10',
            'perishable_cats': '39,43', 'watch_folder': '',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post('/history/delete-bm', data={'csrf_token': csrf, 'doc_id': 'BM_DRAFT_2'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Deleted BM slip BM_DRAFT_2', resp.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
