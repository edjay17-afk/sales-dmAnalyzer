"""One-off: load the PDFs already on disk (Oct + Nov 2026) into the analyzer database.

Usage: python seed_history.py
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import db
from analyzer.parsers import ParseError, parse_pdf

BASE = r"C:\Users\User\Downloads\New folder (6)"
OR_GLOBS = [BASE + r"\orsalesforoctober2026\*.pdf", BASE + r"\orsalesfornovember142026\*.pdf", BASE + r"\OR Sales Monitor*.pdf"]
BM_GLOBS = [BASE + r"\fwdbmforoctober1312026\BadMerchandise(*).pdf", BASE + r"\BadMerchandise(*).pdf"]

con = db.connect()
n_or = n_bm = 0
for pattern in OR_GLOBS:
    for f in sorted(glob.glob(pattern)):
        try:
            p = parse_pdf(f)
            if p['kind'] != 'or':
                print('skip (not OR):', f); continue
            db.save_or(con, p, os.path.basename(f)); n_or += 1
            if p['warnings']:
                print('OR warning', p['date'], p['warnings'])
        except ParseError as e:
            print('FAILED', os.path.basename(f), e)
for pattern in BM_GLOBS:
    for f in sorted(glob.glob(pattern)):
        try:
            p = parse_pdf(f)
            if p['kind'] != 'bm':
                print('skip (not BM):', f); continue
            no = int(re.search(r'BadMerchandise\((\d+)\)', f).group(1))
            db.save_bm(con, p, os.path.basename(f), slip_no=no); n_bm += 1
            if p['warnings']:
                print('BM warning', no, p['warnings'])
        except ParseError as e:
            print('FAILED', os.path.basename(f), e)
print('OR days loaded:', n_or, '| BM slips loaded:', n_bm)
print(db.coverage(con))
