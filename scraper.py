#!/usr/bin/env python3
"""
Amazon Bulk Book Scraper v3
Scrapes Amazon Advanced Search by month/year range.
Outputs per-month CSVs to data_1/books_YYYY-MM.csv (appends to existing).
Resumable: tracks completed slots in scraper_state.json by slot key string.

Usage:
  python scraper.py --from 2020-01 --to 2025-12
  python scraper.py --from 2024-01 --to 2024-06 --max-pages 5
  python scraper.py --from 2024-01 --to 2024-01 --discover-depth 0
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
from collections import deque
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

FORMAT_CODES = {
    'Paperback': '2656022011',
    'Hardcover': '2657022011',
    'Kindle':    '618073011',
}

TARGET_FORMATS = ['Paperback', 'Hardcover', 'Kindle']

FIELDNAMES = ['Total Reviews', 'Product Url', 'ASIN', 'Title', 'Author', 'Format', 'Publication Date', 'Publisher']

SEED_CATEGORIES = [
    ('2635',       'Business & Money'),
    ('4736',       'Self Help'),
    ('6',          'Health, Fitness & Dieting'),
    ('486994011',  'Biographies & Memoirs'),
    ('22',         'Religion & Spirituality'),
    ('4919',       'Parenting & Relationships'),
    ('75',         'Science & Math'),
    ('9',          'History'),
    ('11232',      'Politics & Social Sciences'),
    ('2642',       'Travel'),
    ('4677',       'Education & Teaching'),
    ('3',          "Children's Books"),
    ('4',          'Computers & Technology'),
    ('173507',     'Arts & Photography'),
    ('3510',       'Romance'),
    ('2501',       'Entrepreneurship'),
    ('2579',       'Leadership'),
    ('2558',       'Marketing & Sales'),
    ('2533',       'Investing'),
    ('2531',       'Personal Finance'),
    ('4507',       'Motivational'),
    ('4734',       'Anxiety & Phobias'),
    ('4744',       'Relationships'),
    ('10',         'Diet & Weight Loss'),
    ('12',         'Mental & Emotional Health'),
    ('12290',      'Christianity'),
    ('12293',      'Islam'),
    ('12291',      'Spirituality'),
    ('10672',      'Literature & Fiction'),
    ('49',         'Mystery, Thriller & Suspense'),
    ('48',         'Science Fiction & Fantasy'),
    ('47',         'Fantasy'),
    ('695398',     'Historical Fiction'),
    ('700200',     'Memoirs'),
    ('28',         'Teen & Young Adult'),
    ('173514',     'Law'),
    ('173513',     'Medical Books'),
    ('298471',     'Arts & Music'),
    ('1',          'Audible Books & Originals'),
    ('154606011',  'Cookbooks, Food & Wine'),
    ('16272',      'Crafts, Hobbies & Home'),
    ('173511',     'Sports & Outdoors'),
    ('173512',     'Engineering & Transportation'),
    ('2',          'Professional & Technical'),
    ('5',          'Comics & Graphic Novels'),
    ('25',         'Foreign Language Study'),
    ('86',         'Gay & Lesbian'),
    ('4951',       'Humor & Entertainment'),
    ('4956',       'Poetry'),
    ('4963',       'Reference'),
    ('4967',       'Test Preparation'),
    ('17',         'Drama'),
    ('4686',       'Architecture'),
    ('16',         'Short Stories'),
    ('4961',       'Photography'),
    ('4962',       'Design'),
    ('2686',       'Mind, Body & Spirit'),
    ('2701',       'Social Sciences'),
    ('173516',     'Philosophy'),
    ('173517',     'Linguistics'),
    ('17401',      'Folklore & Mythology'),
    ('3149',       'Military History'),
    ('3150',       'Ancient History'),
    ('3151',       'World History'),
    ('13996',      'True Crime'),
    ('3441',       'Nursing'),
    ('3448',       'Psychology & Counseling'),
    ('3454',       'Psychiatry'),
    ('3461',       'Alternative Medicine'),
    ('3464',       'Exercise & Fitness'),
    ('3465',       'Diets & Weight Loss'),
    ('173505',     'Accounting'),
    ('173506',     'Economics'),
    ('13690811',   'Real Estate'),
    ('2693',       'Human Resources & Personnel Management'),
    ('2694',       'Project Management'),
    ('2695',       'Small Business & Entrepreneurship'),
    ('2696',       'Sales & Selling'),
    ('2697',       'Strategic Planning'),
    ('2699',       'Industrial Relations'),
    ('2700',       'Job Hunting'),
    ('10777',      'LGBTQ+ Books'),
    ('156',        'Anthologies & Literature Collections'),
]

MAX_PAGES_PER_SLOT = 0   # 0 = unlimited
MAX_REVIEWS        = 5
DELAY_MIN          = 2.0
DELAY_MAX          = 4.0
DISCOVER_DEPTH     = 2

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.2277.128',
]

# ─── URL Builder ──────────────────────────────────────────────────────────────

def build_url(cat_id, format_code, month, year, page=1):
    rh = (
        f"n%3A{cat_id}"
        f"%2Cp_n_condition-type%3A1294423011"
        f"%2Cp_n_feature_browse-bin%3A{format_code}"
        f"%2Cp_20%3AEnglish"
    )
    return (
        f"https://www.amazon.com/s?i=stripbooks&rh={rh}"
        f"&s=date-desc-rank&p_45={month}&p_46=During&p_47={year}"
        f"&page={page}&unfiltered=1&ref=sr_adv_b"
    )

def build_category_browse_url(cat_id):
    return f"https://www.amazon.com/s?i=stripbooks&rh=n%3A{cat_id}&s=featured-rank"

# ─── HTTP ─────────────────────────────────────────────────────────────────────

SESSION = requests.Session()

def fetch_page(url, retries=4):
    for attempt in range(retries):
        try:
            headers = {
                'User-Agent':              random.choice(USER_AGENTS),
                'Accept':                  'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language':         'en-US,en;q=0.9',
                'Accept-Encoding':         'gzip, deflate, br',
                'DNT':                     '1',
                'Connection':              'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest':          'document',
                'Sec-Fetch-Mode':          'navigate',
                'Sec-Fetch-Site':          'none',
                'Cache-Control':           'max-age=0',
            }
            resp = SESSION.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                html = resp.text
                if 'robot check' in html.lower() or 'captcha' in html.lower() or 'Enter the characters' in html:
                    wait = 30 + random.uniform(10, 30)
                    log.warning(f'[CAPTCHA] sleeping {wait:.0f}s (attempt {attempt+1})')
                    time.sleep(wait)
                    continue
                return html
            elif resp.status_code in (503, 429, 403):
                wait = 15 * (attempt + 1) + random.uniform(0, 10)
                log.warning(f'[HTTP {resp.status_code}] sleeping {wait:.0f}s (attempt {attempt+1})')
                time.sleep(wait)
            else:
                log.debug(f'[HTTP {resp.status_code}] {url}')
                return None
        except requests.RequestException as e:
            log.warning(f'[NET ERROR] attempt {attempt+1}: {e}')
            time.sleep(random.uniform(3, 7))
    return None

# ─── Pagination check ─────────────────────────────────────────────────────────

def has_next_page(html):
    """Return True if there is an active next-page button."""
    soup = BeautifulSoup(html, 'html.parser')
    nxt = soup.select_one('a.s-pagination-next')
    if not nxt:
        return False
    return 's-pagination-disabled' not in nxt.get('class', [])

# ─── Category Discovery ───────────────────────────────────────────────────────

def extract_child_nodes(html):
    """Extract n: node IDs from left-nav category refinements."""
    soup = BeautifulSoup(html, 'html.parser')
    found = {}
    for a in soup.select('li[id*="n-"] a[href], .a-expander-content a[href], [data-csa-c-item-id] a[href]'):
        href = a.get('href', '')
        if not href:
            continue
        full    = urljoin('https://www.amazon.com', href)
        decoded = unquote(full)
        for m in re.finditer(r'[?&/]n[%3A:=]([0-9]{3,12})', decoded):
            nid = m.group(1)
            label = a.get_text(' ', strip=True)[:100]
            found[nid] = label or f'Node {nid}'
    return found

def discover_categories(depth=2):
    """BFS from seed categories to discover subcategories up to `depth` levels."""
    all_cats = {cat_id: name for cat_id, name in SEED_CATEGORIES}
    if depth == 0:
        return list(all_cats.items())

    q    = deque((cat_id, name, 0) for cat_id, name in SEED_CATEGORIES)
    seen = set(all_cats.keys())

    while q:
        node_id, name, level = q.popleft()
        if level >= depth:
            continue
        html = fetch_page(build_category_browse_url(node_id))
        if not html:
            continue
        for child_id, child_name in extract_child_nodes(html).items():
            if child_id in seen:
                continue
            seen.add(child_id)
            all_cats[child_id] = child_name
            q.append((child_id, child_name, level + 1))
        time.sleep(random.uniform(1.0, 2.5))

    log.info(f'[DISCOVER] {len(all_cats)} total categories (seed={len(SEED_CATEGORIES)}, depth={depth})')
    return list(all_cats.items())

# ─── HTML Parser ──────────────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'[\s,.]+\d{1,2}[,.\s]+\d{4}|'
    r'\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}|'
    r'\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)

def parse_results(html, expected_format):
    books = []
    soup  = BeautifulSoup(html, 'html.parser')
    items = soup.select('[data-component-type="s-search-result"]')

    for item in items:
        try:
            asin = item.get('data-asin', '').strip()
            if not asin or len(asin) < 10:
                continue

            # Title
            title_el = (
                item.select_one('h2 a span') or
                item.select_one('.a-size-medium.a-color-base.a-text-normal') or
                item.select_one('.a-size-base-plus.a-color-base.a-text-normal')
            )
            title = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 4:
                continue

            # Author
            author = ''
            for sel in (
                '.a-row .a-size-base+ .a-size-base',
                '.a-row a.a-link-normal[href*="/e/"]',
                '[class*="author"] a',
                '.a-row a.a-link-normal',
            ):
                el = item.select_one(sel)
                if el:
                    txt = el.get_text(strip=True)
                    if txt and txt.lower() not in ('', 'unknown'):
                        author = txt
                        break

            # Item text (normalised)
            raw_text = item.get_text(' ', strip=True)
            norm_text = re.sub(r'\s+', ' ', raw_text.replace('\u200f', ' ').replace('\xa0', ' '))

            # Format detection from item text
            lower_text = norm_text.lower()
            if 'audiobook' in lower_text or 'audible' in lower_text or 'mp3 cd' in lower_text:
                continue  # skip audiobooks

            if 'paperback' in lower_text:
                fmt = 'Paperback'
            elif 'hardcover' in lower_text or 'hardback' in lower_text:
                fmt = 'Hardcover'
            elif 'kindle' in lower_text or 'e-book' in lower_text:
                fmt = 'Kindle'
            else:
                fmt = expected_format

            # Review count
            review_count = 0
            for el in item.select('[aria-label]'):
                label = el.get('aria-label', '')
                m = re.search(r'([\d,]+)\s+rating', label, re.I)
                if m:
                    review_count = int(m.group(1).replace(',', ''))
                    break

            if review_count > MAX_REVIEWS:
                continue

            # Publication date
            pub_date = ''
            dm = _DATE_RE.search(norm_text)
            if dm:
                pub_date = dm.group(1).strip()

            books.append({
                'Total Reviews':    str(review_count),
                'Product Url':      f'https://www.amazon.com/dp/{asin}',
                'ASIN':             asin,
                'Title':            title,
                'Author':           author,
                'Format':           fmt,
                'Publication Date': pub_date,
                'Publisher':        '',
            })

        except Exception as e:
            log.debug(f'Parse error: {e}')
            continue

    return books

# ─── Per-month CSV helpers ────────────────────────────────────────────────────

def csv_path_for(data_dir, year, month):
    return os.path.join(data_dir, f'books_{year}-{month:02d}.csv')

def load_seen_asins(path):
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            asin = row.get('ASIN', '').strip()
            if asin:
                seen.add(asin)
    return seen

def append_books(path, books):
    is_new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        if is_new:
            w.writeheader()
        w.writerows(books)

# ─── State ────────────────────────────────────────────────────────────────────

def load_state(state_file):
    if os.path.exists(state_file):
        try:
            return set(json.loads(open(state_file).read()).get('done', []))
        except Exception:
            pass
    return set()

def save_state(state_file, done_slots):
    with open(state_file, 'w') as f:
        json.dump({'done': list(done_slots)}, f)

# ─── Month range ──────────────────────────────────────────────────────────────

def month_range(from_ym, to_ym):
    y, m = int(from_ym[:4]), int(from_ym[5:7])
    ey, em = int(to_ym[:4]), int(to_ym[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out

# ─── Main Scraper ─────────────────────────────────────────────────────────────

def scrape(from_ym, to_ym, data_dir, state_file):
    os.makedirs(data_dir, exist_ok=True)

    months = month_range(from_ym, to_ym)
    cats   = discover_categories(DISCOVER_DEPTH)

    total_slots = len(months) * len(cats) * len(TARGET_FORMATS)
    pages_msg   = 'unlimited' if MAX_PAGES_PER_SLOT == 0 else str(MAX_PAGES_PER_SLOT)
    log.info(f'Scraping {from_ym} → {to_ym}')
    log.info(f'{len(months)} months x {len(cats)} categories x {len(TARGET_FORMATS)} formats = {total_slots} slots')
    log.info(f'Pages/slot={pages_msg}, delay={DELAY_MIN}-{DELAY_MAX}s, max_reviews={MAX_REVIEWS}')

    done_slots = load_state(state_file)
    log.info(f'Already done: {len(done_slots)} slots')

    # Pre-load seen ASINs per month
    seen_per_month = {}
    for year, month in months:
        p = csv_path_for(data_dir, year, month)
        seen_per_month[(year, month)] = load_seen_asins(p)

    grand_total = 0
    slot_count  = 0

    try:
        for year, month in months:
            for fmt_name in TARGET_FORMATS:
                fmt_code = FORMAT_CODES[fmt_name]
                for cat_id, cat_name in cats:
                    slot_key = f'{year}-{month:02d}:{cat_id}:{fmt_name}'
                    slot_count += 1

                    if slot_key in done_slots:
                        continue

                    seen = seen_per_month[(year, month)]
                    csv_p = csv_path_for(data_dir, year, month)
                    slot_books = 0
                    page = 1

                    while True:
                        if MAX_PAGES_PER_SLOT and page > MAX_PAGES_PER_SLOT:
                            break

                        url  = build_url(cat_id, fmt_code, month, year, page)
                        html = fetch_page(url)

                        if html is None:
                            log.debug(f'  [{slot_key}] p{page}: no response — stop')
                            break

                        books = parse_results(html, fmt_name)
                        new   = [b for b in books if b['ASIN'] not in seen]

                        if new:
                            for b in new:
                                seen.add(b['ASIN'])
                            append_books(csv_p, new)
                            slot_books  += len(new)
                            grand_total += len(new)

                        log.info(
                            f'  [{year}-{month:02d}/{cat_name[:20]}/{fmt_name}] '
                            f'p{page}: +{len(new)} new (slot={slot_books}, grand={grand_total})'
                        )

                        if not has_next_page(html):
                            break

                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        page += 1

                    done_slots.add(slot_key)

                    if len(done_slots) % 20 == 0:
                        save_state(state_file, done_slots)

                    time.sleep(random.uniform(0.5, 1.5))

    except KeyboardInterrupt:
        log.info('Interrupted — progress saved.')
    finally:
        save_state(state_file, done_slots)
        log.info(f'Done. {grand_total} new books. {len(done_slots)}/{total_slots} slots complete.')

# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Amazon Bulk Book Scraper v3')
    parser.add_argument('--from',     dest='from_ym', required=True,  help='Start YYYY-MM')
    parser.add_argument('--to',       dest='to_ym',   required=True,  help='End YYYY-MM')
    parser.add_argument('--dir',      default='data_1',               help='Output directory (default: data_1)')
    parser.add_argument('--state',    default='scraper_state.json',   help='State file')
    parser.add_argument('--delay-min',    type=float, default=DELAY_MIN)
    parser.add_argument('--delay-max',    type=float, default=DELAY_MAX)
    parser.add_argument('--max-pages',    type=int,   default=MAX_PAGES_PER_SLOT)
    parser.add_argument('--max-reviews',  type=int,   default=MAX_REVIEWS)
    parser.add_argument('--discover-depth', type=int, default=DISCOVER_DEPTH)
    args = parser.parse_args()

    for ym, label in [(args.from_ym, '--from'), (args.to_ym, '--to')]:
        if not re.match(r'^\d{4}-\d{2}$', ym):
            print(f'Error: {label} must be YYYY-MM (e.g. 2024-01)')
            sys.exit(1)

    import sys as _sys
    m = _sys.modules[__name__]
    m.DELAY_MIN       = args.delay_min
    m.DELAY_MAX       = args.delay_max
    m.MAX_PAGES_PER_SLOT = args.max_pages
    m.MAX_REVIEWS     = args.max_reviews
    m.DISCOVER_DEPTH  = args.discover_depth

    scrape(args.from_ym, args.to_ym, args.dir, args.state)

if __name__ == '__main__':
    main()
