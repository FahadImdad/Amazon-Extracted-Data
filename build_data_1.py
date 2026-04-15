#!/usr/bin/env python3
import csv
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent / 'data_1'
BASE.mkdir(parents=True, exist_ok=True)
MASTER = Path(__file__).resolve().parent / 'data' / 'books_all_months.csv'
FIELDS = ['Total Reviews','Product Url','ASIN','Title','Author','Format','Publication Date','Publisher']
MONTHS = {
    'jan': '01', 'january': '01', 'feb': '02', 'february': '02', 'mar': '03', 'march': '03',
    'apr': '04', 'april': '04', 'may': '05', 'jun': '06', 'june': '06', 'jul': '07', 'july': '07',
    'aug': '08', 'august': '08', 'sep': '09', 'sept': '09', 'september': '09', 'oct': '10', 'october': '10',
    'nov': '11', 'november': '11', 'dec': '12', 'december': '12',
}
DATE_RE = re.compile(r'\b(\d{4})[-/]?(\d{2})[-/]?(\d{2})\b')
MONTH_RE = re.compile(r'\b(' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + r')\b', re.I)
YEAR_RE = re.compile(r'\b(202[1-6])\b')
REV_RE = re.compile(r'\d+')

if not MASTER.exists():
    raise SystemExit(f'Master file not found: {MASTER}')


def month_key(date_text: str):
    s = (date_text or '').strip().lower()
    m = MONTH_RE.search(s)
    y = YEAR_RE.search(s)
    if m and y:
        return f"{y.group(1)}-{MONTHS[m.group(1).lower()]}"
    m2 = DATE_RE.search(s)
    if m2:
        y2, mo, _ = m2.groups()
        if '2021' <= y2 <= '2026':
            return f'{y2}-{mo}'
    return None


def clean_row(row):
    out = {k: (row.get(k, '') or '').strip() for k in FIELDS}
    if out['Total Reviews']:
        m = REV_RE.search(out['Total Reviews'].replace(',', ''))
        out['Total Reviews'] = m.group(0) if m else '0'
    return out

month_rows = {f'books_{y}-{m:02d}.csv': [] for y in range(2021, 2027) for m in range(1, 13)}

with open(MASTER, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        yyyymm = month_key(row.get('Publication Date', ''))
        if not yyyymm:
            continue
        name = f'books_{yyyymm}.csv'
        if name in month_rows:
            month_rows[name].append(clean_row(row))

for name, rows in month_rows.items():
    if not rows:
        continue
    seen = set()
    clean = []
    for r in rows:
        asin = r['ASIN']
        if not asin or asin in seen:
            continue
        seen.add(asin)
        clean.append(r)
    out = BASE / name
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(clean)
    print(name, len(clean))

print(f'Output written to {BASE}')
