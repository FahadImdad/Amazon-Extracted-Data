#!/usr/bin/env python3
"""
Amazon Bulk Book Scraper
Scrapes Amazon Advanced Search by month/year range
Stores raw book data to CSV or PostgreSQL
No email finding — just bulk data collection

Usage:
  python scraper.py --from 2020-01 --to 2025-12 --output books.csv
  python scraper.py --from 2024-01 --to 2024-06 --db postgresql://...
"""

import argparse
import csv
import time
import random
import re
import os
import sys
import json
import logging
from datetime import datetime
from itertools import product

import requests
from bs4 import BeautifulSoup

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Amazon Advanced Search format codes
FORMAT_CODES = {
    'Paperback':     '2656022011',
    'Hardcover':     '2657022011',
    'Kindle':        '618073011',
    'Board Book':    '2657832011',
    'School Binding':'2658022011',
}

# Target formats (in priority order)
TARGET_FORMATS = ['Paperback', 'Hardcover', 'Kindle']

# Amazon category nodes (same as LeadGen Pro v2)
CATEGORIES = [
    ('2635',       'Business & Money'),
    ('4736',       'Self Help'),
    ('6',          'Health & Fitness'),
    ('486994011',  'Biographies'),
    ('22',         'Religion & Spirituality'),
    ('4919',       'Parenting'),
    ('75',         'Science & Math'),
    ('9',          'History'),
    ('11232',      'Politics & Social'),
    ('2642',       'Travel'),
    ('4677',       'Education'),
    ('3',          'Children'),
    ('4',          'Computers & Tech'),
    ('173507',     'Arts & Photography'),
    ('3510',       'Romance'),
    ('2501',       'Entrepreneurship'),
    ('2579',       'Leadership'),
    ('2558',       'Marketing'),
    ('2533',       'Investing'),
    ('2531',       'Personal Finance'),
    ('4507',       'Motivational'),
    ('4734',       'Anxiety & Phobias'),
    ('4744',       'Relationships'),
    ('10',         'Diet & Weight Loss'),
    ('12',         'Mental Health'),
    ('12290',      'Christianity'),
    ('12293',      'Islam'),
    ('12291',      'Spirituality'),
    ('10672',      'Literature & Fiction'),
    ('49',         'Mystery & Thriller'),
    ('48',         'Science Fiction'),
    ('47',         'Fantasy'),
    ('695398',     'Historical Fiction'),
    ('700200',     'Memoirs'),
    ('28',         'Teen & Young Adult'),
    ('173514',     'Law'),
    ('173513',     'Medical'),
    ('298471',     'Music'),
]

MAX_PAGES_PER_SLOT = 5   # Pages per category/format/month combo
MAX_REVIEWS        = 5   # Skip books with more than this many reviews
DELAY_MIN          = 1.5 # Min seconds between requests
DELAY_MAX          = 3.5 # Max seconds between requests

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
]

# ─── URL Builder ──────────────────────────────────────────────────────────────

def build_url(cat_id, format_code, month, year, page=1):
    """Build Amazon Advanced Search URL for a specific category/format/month/year."""
    rh = f"n%3A{cat_id}%2Cp_n_condition-type%3A1294423011%2Cp_n_feature_browse-bin%3A{format_code}%2Cp_20%3AEnglish"
    return (
        f"https://www.amazon.com/s?i=stripbooks&rh={rh}"
        f"&s=date-desc-rank&p_45={month}&p_46=During&p_47={year}"
        f"&page={page}&unfiltered=1&ref=sr_adv_b"
    )

# ─── HTML Parser ──────────────────────────────────────────────────────────────

def parse_html(html, expected_format):
    """Parse Amazon search results HTML and return list of book dicts."""
    books = []
    soup = BeautifulSoup(html, 'html.parser')
    results = soup.select('[data-component-type="s-search-result"]')

    for item in results:
        try:
            asin = item.get('data-asin', '').strip()
            if not asin:
                continue

            # Title
            title_el = item.select_one('h2 a span') or item.select_one('.a-size-medium') or item.select_one('.a-size-base-plus')
            title = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 5:
                continue

            # Author
            author_el = (
                item.select_one('.a-row .a-size-base+ .a-size-base') or
                item.select_one('[class*="author"] .a-link-normal') or
                item.select_one('.a-row a.a-link-normal')
            )
            author = author_el.get_text(strip=True) if author_el else 'Unknown'
            if author.lower() in ('unknown', ''):
                continue

            # Publication date
            date_el = item.select_one('.a-color-secondary .a-size-base') or item.select_one('[class*="publication"]')
            pub_date = date_el.get_text(strip=True) if date_el else ''

            # Review count
            review_el = item.select_one('[aria-label*="ratings"]') or item.select_one('[aria-label*="stars"]')
            review_count = 0
            if review_el:
                label = review_el.get('aria-label', '')
                m = re.search(r'([\d,]+)\s+rating', label)
                if m:
                    review_count = int(m.group(1).replace(',', ''))

            # Skip if too many reviews
            if review_count > MAX_REVIEWS:
                continue

            # Format detection
            item_text = item.get_text()
            fmt = 'Unknown'
            if 'Audiobook' in item_text or 'Audible' in item_text:
                fmt = 'Audiobook'
            elif 'Kindle' in item_text:
                fmt = 'Kindle'
            elif 'Hardcover' in item_text:
                fmt = 'Hardcover'
            elif 'Paperback' in item_text:
                fmt = 'Paperback'
            else:
                fmt = expected_format

            # Skip audiobooks
            if fmt == 'Audiobook':
                continue

            # Publisher (try to find in item text)
            publisher = ''
            pub_match = re.search(r'(?:Publisher|Published by)[:\s]+([A-Za-z][^\n]{2,50})', item_text)
            if pub_match:
                publisher = pub_match.group(1).strip()[:60]

            books.append({
                'asin':         asin,
                'title':        title,
                'author':       author,
                'publish_date': pub_date,
                'review_count': review_count,
                'book_format':  fmt,
                'publisher':    publisher,
                'amazon_url':   f'https://www.amazon.com/dp/{asin}',
            })

        except Exception as e:
            log.debug(f'Parse error on item: {e}')
            continue

    return books

# ─── HTTP Fetch ───────────────────────────────────────────────────────────────

SESSION = requests.Session()
_ua_idx = 0

def fetch_page(url, retries=3):
    """Fetch a page with rotating user agents and retries."""
    global _ua_idx
    for attempt in range(retries):
        try:
            ua = USER_AGENTS[_ua_idx % len(USER_AGENTS)]
            _ua_idx += 1
            headers = {
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
            }
            resp = SESSION.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                # Check if Amazon blocked us
                if 'To discuss automated access' in html or 'robot check' in html.lower() or 'captcha' in html.lower():
                    log.warning(f'Blocked by Amazon on attempt {attempt+1}')
                    time.sleep(random.uniform(5, 10))
                    continue
                if 'a-size-medium' not in html and 's-search-result' not in html:
                    log.debug(f'No results on page (may be empty)')
                    return None  # Empty page
                return html
            elif resp.status_code == 503:
                log.warning(f'503 on attempt {attempt+1}, retrying...')
                time.sleep(random.uniform(3, 7))
            else:
                log.warning(f'HTTP {resp.status_code} on attempt {attempt+1}')
                time.sleep(random.uniform(2, 4))
        except requests.RequestException as e:
            log.warning(f'Request error on attempt {attempt+1}: {e}')
            time.sleep(random.uniform(2, 5))
    return None

# ─── Month Range Generator ────────────────────────────────────────────────────

def month_range(from_ym, to_ym):
    """Generate list of (year, month) tuples from YYYY-MM to YYYY-MM inclusive."""
    y, m = int(from_ym[:4]), int(from_ym[5:7])
    ey, em = int(to_ym[:4]), int(to_ym[5:7])
    months = []
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months

# ─── CSV Writer ───────────────────────────────────────────────────────────────

FIELDNAMES = ['Total Reviews', 'Product Url', 'ASIN', 'Title', 'Author', 'Format', 'Publication Date', 'Publisher']

def open_csv(path):
    """Open CSV file and return (file_handle, writer, seen_asins)."""
    seen = set()
    file_exists = os.path.exists(path)
    if file_exists:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen.add(row['asin'])
        log.info(f'Resuming — loaded {len(seen)} existing ASINs from {path}')

    fh = open(path, 'a', newline='', encoding='utf-8')
    writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
    if not file_exists:
        writer.writeheader()
    return fh, writer, seen

# ─── Progress State ───────────────────────────────────────────────────────────

def load_state(state_file):
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {}

def save_state(state_file, state):
    with open(state_file, 'w') as f:
        json.dump(state, f)

# ─── Main Scraper ─────────────────────────────────────────────────────────────

def scrape(from_ym, to_ym, output_csv, state_file):
    months    = month_range(from_ym, to_ym)
    formats   = [(name, FORMAT_CODES[name]) for name in TARGET_FORMATS]
    cats      = CATEGORIES

    total_slots = len(months) * len(cats) * len(formats)
    log.info(f'📚 Scraping {from_ym} → {to_ym}')
    log.info(f'📅 {len(months)} months × {len(cats)} categories × {len(formats)} formats = {total_slots} slots')
    log.info(f'📄 Up to {MAX_PAGES_PER_SLOT} pages/slot = {total_slots * MAX_PAGES_PER_SLOT * 20:,} max books')

    fh, writer, seen_asins = open_csv(output_csv)
    state = load_state(state_file)
    start_slot = state.get('slot', 0)

    slot_num   = 0
    total_saved = len(seen_asins)
    total_skipped_reviews = 0

    try:
        for (year, month), (fmt_name, fmt_code), (cat_id, cat_name) in product(months, formats, cats):
            slot_num += 1
            if slot_num <= start_slot:
                continue

            slot_label = f'[{year}-{month:02d} / {cat_name} / {fmt_name}]'
            log.info(f'📂 Slot {slot_num}/{total_slots}: {slot_label}')

            slot_books = 0
            for page in range(1, MAX_PAGES_PER_SLOT + 1):
                url = build_url(cat_id, fmt_code, month, year, page)
                html = fetch_page(url)

                if html is None:
                    log.debug(f'  Page {page}: empty/blocked — stopping slot')
                    break

                books = parse_html(html, fmt_name)
                new_books = [b for b in books if b['asin'] not in seen_asins]

                if not new_books and page == 1:
                    log.debug(f'  Page {page}: 0 books — empty slot')
                    break
                elif not new_books:
                    log.debug(f'  Page {page}: no new books — stopping slot')
                    break

                for book in new_books:
                    seen_asins.add(book['asin'])
                    writer.writerow({
                        'Total Reviews':   book['review_count'],
                        'Product Url':     book['amazon_url'],
                        'ASIN':            book['asin'],
                        'Title':           book['title'],
                        'Author':          book['author'],
                        'Format':          book['book_format'],
                        'Publication Date':book['publish_date'],
                        'Publisher':       book['publisher'],
                    })
                    slot_books += 1
                    total_saved += 1

                fh.flush()
                log.info(f'  Page {page}: +{len(new_books)} books (slot total: {slot_books}, grand total: {total_saved})')

                # Stop early if page has fewer than 10 results (near end of results)
                if len(books) < 10:
                    break

                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            # Save state after each slot
            save_state(state_file, {'slot': slot_num})

            # Brief pause between slots
            time.sleep(random.uniform(0.5, 1.5))

    except KeyboardInterrupt:
        log.info(f'\n⏸ Interrupted at slot {slot_num}. Resume with same command.')
    finally:
        fh.close()
        log.info(f'\n✅ Done! {total_saved} books saved to {output_csv}')
        log.info(f'📊 State saved — run again to resume from slot {slot_num}')

# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Amazon Bulk Book Scraper')
    parser.add_argument('--from',   dest='from_ym', required=True, help='Start month (YYYY-MM), e.g. 2020-01')
    parser.add_argument('--to',     dest='to_ym',   required=True, help='End month (YYYY-MM), e.g. 2025-12')
    parser.add_argument('--output', default='books.csv',           help='Output CSV file (default: books.csv)')
    parser.add_argument('--state',  default='scraper_state.json',  help='State file for resuming (default: scraper_state.json)')
    parser.add_argument('--delay-min', type=float, default=DELAY_MIN, help='Min delay between requests (seconds)')
    parser.add_argument('--delay-max', type=float, default=DELAY_MAX, help='Max delay between requests (seconds)')
    parser.add_argument('--max-pages', type=int,   default=MAX_PAGES_PER_SLOT, help='Max pages per slot (default: 5)')
    parser.add_argument('--max-reviews', type=int, default=MAX_REVIEWS, help='Skip books with more reviews than this (default: 5)')

    args = parser.parse_args()

    # Validate date format
    for ym, label in [(args.from_ym, '--from'), (args.to_ym, '--to')]:
        if not re.match(r'^\d{4}-\d{2}$', ym):
            print(f'Error: {label} must be YYYY-MM format (e.g. 2024-01)')
            sys.exit(1)

    import sys as _sys
    _mod = _sys.modules[__name__]
    _mod.DELAY_MIN          = args.delay_min
    _mod.DELAY_MAX          = args.delay_max
    _mod.MAX_PAGES_PER_SLOT = args.max_pages
    _mod.MAX_REVIEWS        = args.max_reviews

    scrape(args.from_ym, args.to_ym, args.output, args.state)

if __name__ == '__main__':
    main()
