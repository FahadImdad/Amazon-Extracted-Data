#!/usr/bin/env python3
import csv
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / 'data'
OUT = BASE / 'data_1'
OUT.mkdir(parents=True, exist_ok=True)
FIELDS = ['Total Reviews','Product Url','ASIN','Title','Author','Format','Publication Date','Publisher']
VALID_FORMATS = {'Paperback','Hardcover','Kindle','Board Book','School Binding'}
MONTH_RE = re.compile(r'books_(202[1-6])-(0[1-9]|1[0-2])$')
DATE_OK_RE = re.compile(r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|202[1-6])\b', re.I)
ASIN_RE = re.compile(r'^(?:B0[0-9A-Z]{8}|[0-9]{9}[0-9X]|[0-9]{10})$')

# Clear existing outputs first.
for p in OUT.glob('books_*.csv'):
    p.unlink()

month_files = sorted([p for p in SRC.glob('books_*.csv') if p.name != 'books_all_months.csv'])
for src in month_files:
    m = MONTH_RE.search(src.stem)
    if not m:
        continue
    out = OUT / src.name
    seen = set()
    rows = []
    with open(src, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = {k: (row.get(k, '') or '').strip() for k in FIELDS}
            asin = r['ASIN']
            pub = r['Publication Date'].strip()
            if not asin or not ASIN_RE.match(asin):
                continue
            if asin in seen:
                continue
            if pub.lower() in {'', 'by', '|', 'unknown'}:
                continue
            if r['Format'] and r['Format'] not in VALID_FORMATS:
                r['Format'] = ''
            seen.add(asin)
            rows.append(r)
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(out.name, len(rows))

print('done')
