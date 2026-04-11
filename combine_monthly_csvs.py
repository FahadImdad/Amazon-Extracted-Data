#!/usr/bin/env python3
import csv
from pathlib import Path

BASE = Path(__file__).resolve().parent / 'data'
OUT = BASE / 'books_all_months.csv'
FIELDS = ['Total Reviews','Product Url','ASIN','Title','Author','Format','Publication Date','Publisher']

seen = set()
rows = []
for path in sorted(BASE.glob('books_*.csv')):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            asin = (row.get('ASIN') or '').strip()
            if not asin or asin in seen:
                continue
            seen.add(asin)
            rows.append({k: (row.get(k, '') or '').strip() for k in FIELDS})

with open(OUT, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)

print(f'Wrote {len(rows)} rows to {OUT}')
