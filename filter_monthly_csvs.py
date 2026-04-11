#!/usr/bin/env python3
import csv
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent / 'data'
FIELDS = ['Total Reviews','Product Url','ASIN','Title','Author','Format','Publication Date','Publisher']
MONTHS = {
    '01': ['jan', 'january'],
    '02': ['feb', 'february'],
    '03': ['mar', 'march'],
    '04': ['apr', 'april'],
    '05': ['may'],
    '06': ['jun', 'june'],
    '07': ['jul', 'july'],
    '08': ['aug', 'august'],
    '09': ['sep', 'sept', 'september'],
    '10': ['oct', 'october'],
    '11': ['nov', 'november'],
    '12': ['dec', 'december'],
}

def match_month(date_str, yyyymm):
    year, month = yyyymm.split('-')
    s = (date_str or '').strip().lower()
    if not s:
        return False
    if year not in s:
        return False
    return any(m in s for m in MONTHS[month])

for path in sorted(BASE.glob('books_????-??.csv')):
    yyyymm = path.stem.split('_')[-1]
    tmp = path.with_suffix('.csv.tmp')
    seen = set()
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            asin = (row.get('ASIN') or '').strip()
            if not asin or asin in seen:
                continue
            if not match_month(row.get('Publication Date', ''), yyyymm):
                continue
            seen.add(asin)
            rows.append({k: (row.get(k, '') or '').strip() for k in FIELDS})
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    print(path.name, len(rows))
