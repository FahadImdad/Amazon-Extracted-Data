#!/usr/bin/env python3
"""
Full Pipeline: Discover → Scrape → Enrich Publisher → Push GitHub
Outputs complete CSV with all fields to data_3/

Usage:
    python pipeline.py --month 2021-01
    python pipeline.py --month 2024-06 --workers 10
"""

import argparse
import csv
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

# ─── Config ───────────────────────────────────────────────────────────────────

FIELDNAMES = ['Total Reviews', 'Product Url', 'ASIN', 'Title', 'Author',
              'Format', 'Publication Date', 'Publisher']

FORMAT_CODES = {
    'Paperback': '2656022011',
    'Hardcover': '2657022011',
    'Kindle':    '618073011',
}

MAX_REVIEWS   = 5
SCRAPE_DELAY  = (2.0, 4.0)
PUB_DELAY     = (1.0, 2.0)
PUB_WORKERS   = 10
DISCOVER_DEPTH = 3
CATEGORIES_FILE = Path('categories.json')
MAX_RETRIES   = 4

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.2277.128',
]

SEED_CATEGORIES = [
    # Business & Money
    ('2635','Business & Money'), ('2501','Entrepreneurship'), ('2579','Leadership'),
    ('2558','Marketing & Sales'), ('2533','Investing'), ('2531','Personal Finance'),
    ('173505','Accounting'), ('173506','Economics'), ('13690811','Real Estate'),
    ('2693','Human Resources'), ('2694','Project Management'), ('2695','Small Business'),
    ('2696','Sales & Selling'), ('2697','Strategic Planning'), ('2700','Job Hunting'),
    ('2556','Management'), ('2557','Business Ethics'), ('2559','Advertising'),
    ('2560','E-Commerce'), ('2562','International Business'), ('2563','Business Law'),
    ('2564','Industries'), ('2567','Finance'), ('2568','Taxation'), ('2569','Negotiating'),
    ('2571','Business Writing'), ('2572','Women in Business'),
    # Self Help
    ('4736','Self Help'), ('4507','Motivational'), ('4734','Anxiety & Phobias'),
    ('4744','Relationships'), ('4740','Communication Skills'), ('4741','Creativity'),
    ('4749','Personal Transformation'), ('4750','Self-Esteem'), ('4752','Stress Management'),
    ('4753','Success'), ('4754','Time Management'),
    # Health & Fitness
    ('6','Health, Fitness & Dieting'), ('10','Diet & Weight Loss'),
    ('12','Mental & Emotional Health'), ('3441','Nursing'), ('3448','Psychology & Counseling'),
    ('3454','Psychiatry'), ('3461','Alternative Medicine'), ('3464','Exercise & Fitness'),
    ('3465','Diets & Weight Loss'), ('3466','Nutrition'), ('3467','Diseases & Ailments'),
    ('3469','Womens Health'), ('3470','Mens Health'), ('3472','Addiction & Recovery'),
    # Religion & Spirituality
    ('22','Religion & Spirituality'), ('12290','Christianity'), ('12293','Islam'),
    ('12291','Spirituality'), ('12292','Judaism'), ('12294','Buddhism'),
    ('12295','Hinduism'), ('12296','New Age'), ('12298','Occult & Paranormal'),
    ('2686','Mind, Body & Spirit'),
    # Biographies & History
    ('486994011','Biographies & Memoirs'), ('700200','Memoirs'), ('9','History'),
    ('3149','Military History'), ('3150','Ancient History'), ('3151','World History'),
    ('3152','Americas History'), ('3153','European History'), ('17401','Folklore'),
    # Fiction & Literature
    ('10672','Literature & Fiction'), ('49','Mystery, Thriller & Suspense'),
    ('48','Science Fiction & Fantasy'), ('47','Fantasy'), ('3510','Romance'),
    ('695398','Historical Fiction'), ('16','Short Stories'), ('156','Anthologies'),
    ('17','Drama'), ('4956','Poetry'), ('4687','Classics'),
    ('4688','Contemporary Fiction'), ('4691','Horror'), ('4692','Literary Fiction'),
    ('4693','Psychological Thrillers'), ('13996','True Crime'),
    # Teen & Children
    ('28','Teen & Young Adult'), ('3',"Children's Books"),
    ('4703','YA Fantasy'), ('4706','YA Romance'), ('4707','YA Science Fiction'),
    ('4704','YA Horror'), ('4705','YA Mystery'),
    # Science & Technology
    ('75','Science & Math'), ('3728','Astronomy'), ('3729','Biology'),
    ('3730','Chemistry'), ('3731','Earth Sciences'), ('3732','Mathematics'),
    ('3733','Physics'), ('3735','Environment'), ('3738','Nature & Ecology'),
    ('4','Computers & Technology'), ('3760','Programming'), ('3761','Networking'),
    ('3762','Computer Science'), ('3763','Security'), ('3767','AI & Machine Learning'),
    # Medical
    ('173513','Medical Books'), ('3440','Medicine'), ('3443','Pharmacology'),
    ('3444','Veterinary'), ('3447','Clinical'), ('3450','Neuroscience'),
    ('3451','Oncology'), ('3452','Cardiology'),
    # Education & Reference
    ('4677','Education & Teaching'), ('4967','Test Preparation'), ('4963','Reference'),
    ('25','Foreign Language Study'),
    # Arts, Crafts & Hobbies
    ('173507','Arts & Photography'), ('4961','Photography'), ('4962','Graphic Design'),
    ('4686','Architecture'), ('298471','Music'), ('154606011','Cookbooks, Food & Wine'),
    ('16272','Crafts, Hobbies & Home'), ('3861','Crafts'), ('3862','Gardening'),
    ('3863','Home Improvement'), ('3865','Pets & Animal Care'),
    # Parenting, Sports, Politics, Law
    ('4919','Parenting & Relationships'), ('173511','Sports & Outdoors'),
    ('11232','Politics & Social Sciences'), ('2701','Social Sciences'),
    ('173516','Philosophy'), ('173517','Linguistics'), ('173514','Law'),
    ('3843','Criminal Law'), ('3845','Family Law'), ('3847','Intellectual Property'),
    # Engineering & Travel
    ('173512','Engineering & Transportation'), ('3880','Automotive'),
    ('3885','Mechanical Engineering'), ('3887','Robotics & Automation'),
    ('2642','Travel'), ('3901','Americas Travel'), ('3902','Asia Travel'),
    ('3904','Europe Travel'),
    # Misc
    ('5','Comics & Graphic Novels'), ('10777','LGBTQ+ Books'), ('86','Gay & Lesbian'),
    ('4951','Humor & Entertainment'), ('3510','Romance'),
]

# ─── HTTP ─────────────────────────────────────────────────────────────────────

SESSION = requests.Session()

def get(url, retries=MAX_RETRIES, timeout=20):
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, headers={
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
            }, timeout=timeout)
            if resp.status_code == 200:
                html = resp.text
                if 'robot check' in html.lower() or 'captcha' in html.lower():
                    wait = 40 + random.uniform(10, 30)
                    print(f'  [CAPTCHA] sleeping {wait:.0f}s', flush=True)
                    time.sleep(wait)
                    continue
                return html
            elif resp.status_code in (503, 429, 403):
                wait = 20 * (attempt + 1) + random.uniform(0, 10)
                print(f'  [HTTP {resp.status_code}] sleeping {wait:.0f}s (attempt {attempt+1})', flush=True)
                time.sleep(wait)
            else:
                return None
        except Exception as e:
            time.sleep(random.uniform(3, 7))
    return None

# ─── Category Discovery ───────────────────────────────────────────────────────

def discovery_url(cat_id):
    return (f"https://www.amazon.com/s?i=stripbooks"
            f"&rh=n%3A{cat_id}%2Cp_n_feature_browse-bin%3A2656022011"
            f"&s=date-desc-rank&p_45=1&p_46=During&p_47=2024&page=1&unfiltered=1")

def extract_nodes(html):
    soup = BeautifulSoup(html, 'html.parser')
    found = {}
    for a in soup.select('#s-refinements a[href], .a-expander-content a[href], li[id*="n-"] a[href]'):
        href = a.get('href', '')
        if not href:
            continue
        decoded = unquote(urljoin('https://www.amazon.com', href))
        for m in re.finditer(r'(?:rh=[^&]*n[%3A:])([0-9]{3,12})|[?&/]n[%3A:=]([0-9]{3,12})', decoded):
            nid = m.group(1) or m.group(2)
            if nid:
                found[nid] = a.get_text(' ', strip=True)[:80] or f'Node {nid}'
    return found

def discover_categories():
    if CATEGORIES_FILE.exists():
        cats = json.loads(CATEGORIES_FILE.read_text())
        print(f'[DISCOVER] Loaded {len(cats):,} categories from cache', flush=True)
        return [(c['id'], c['name']) for c in cats]

    print(f'[DISCOVER] BFS depth={DISCOVER_DEPTH} from {len(SEED_CATEGORIES)} seeds...', flush=True)
    all_cats = {cid: name for cid, name in SEED_CATEGORIES}
    q    = deque((cid, name, 0) for cid, name in SEED_CATEGORIES)
    seen = set(all_cats.keys())
    fetched = 0

    while q:
        nid, name, level = q.popleft()
        if level >= DISCOVER_DEPTH:
            continue
        html = get(discovery_url(nid))
        fetched += 1
        if not html:
            time.sleep(random.uniform(3, 6))
            continue
        for child_id, child_name in extract_nodes(html).items():
            if child_id in seen:
                continue
            seen.add(child_id)
            all_cats[child_id] = child_name
            q.append((child_id, child_name, level + 1))
        print(f'  [L{level}] {name[:35]:<35} total={len(all_cats):,} queue={len(q):,}', flush=True)
        if fetched % 50 == 0:
            _save_cats(all_cats)
        time.sleep(random.uniform(2, 4))

    _save_cats(all_cats)
    print(f'[DISCOVER] Done: {len(all_cats):,} categories saved', flush=True)
    return list(all_cats.items())

def _save_cats(cats):
    CATEGORIES_FILE.write_text(json.dumps([{'id': k, 'name': v} for k, v in cats.items()], indent=2))

# ─── Scraper ──────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'[\s,.]+\d{1,2}[,.\s]+\d{4}|'
    r'\d{4}-\d{2}-\d{2})', re.I)

def search_url(cat_id, fmt_code, month, year, page=1):
    rh = (f"n%3A{cat_id}"
          f"%2Cp_n_condition-type%3A1294423011"
          f"%2Cp_n_feature_browse-bin%3A{fmt_code}"
          f"%2Cp_20%3AEnglish")
    return (f"https://www.amazon.com/s?i=stripbooks&rh={rh}"
            f"&s=date-desc-rank&p_45={month}&p_46=During&p_47={year}"
            f"&page={page}&unfiltered=1&ref=sr_adv_b")

def has_next(html):
    soup = BeautifulSoup(html, 'html.parser')
    nxt  = soup.select_one('a.s-pagination-next')
    return bool(nxt and 's-pagination-disabled' not in nxt.get('class', []))

def parse_books(html, fmt_name):
    books = []
    soup  = BeautifulSoup(html, 'html.parser')
    for item in soup.select('[data-component-type="s-search-result"]'):
        try:
            asin = item.get('data-asin', '').strip()
            if not asin or len(asin) < 10:
                continue

            title_el = (item.select_one('h2 a span') or
                        item.select_one('.a-size-medium.a-color-base.a-text-normal') or
                        item.select_one('.a-size-base-plus.a-color-base.a-text-normal'))
            title = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 4:
                continue

            author = ''
            for sel in ('.a-row .a-size-base+ .a-size-base',
                        '.a-row a.a-link-normal[href*="/e/"]',
                        '[class*="author"] a',
                        '.a-row a.a-link-normal'):
                el = item.select_one(sel)
                if el:
                    t = el.get_text(strip=True)
                    if t:
                        author = t
                        break

            norm = re.sub(r'\s+', ' ', item.get_text(' ', strip=True)
                          .replace('\u200f', ' ').replace('\xa0', ' '))
            lower = norm.lower()

            if any(x in lower for x in ('audiobook', 'audible', 'mp3 cd', 'audio cd')):
                continue

            if 'paperback' in lower:    fmt = 'Paperback'
            elif 'hardcover' in lower:  fmt = 'Hardcover'
            elif 'kindle' in lower:     fmt = 'Kindle'
            else:                       fmt = fmt_name

            reviews = 0
            for el in item.select('[aria-label]'):
                m = re.search(r'([\d,]+)\s+rating', el.get('aria-label', ''), re.I)
                if m:
                    reviews = int(m.group(1).replace(',', ''))
                    break
            if reviews > MAX_REVIEWS:
                continue

            pub_date = ''
            dm = _DATE_RE.search(norm)
            if dm:
                pub_date = dm.group(1).strip()

            books.append({
                'Total Reviews':    str(reviews),
                'Product Url':      f'https://www.amazon.com/dp/{asin}',
                'ASIN':             asin,
                'Title':            title,
                'Author':           author,
                'Format':           fmt,
                'Publication Date': pub_date,
                'Publisher':        '',
            })
        except Exception:
            continue
    return books

def scrape_month(year, month, cats, out_csv, state_file):
    done = set(json.loads(Path(state_file).read_text()).get('done', [])) if Path(state_file).exists() else set()
    seen = set()
    if out_csv.exists():
        with open(out_csv, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('ASIN'):
                    seen.add(row['ASIN'])
    print(f'\n[SCRAPE] {year}-{month:02d} | {len(cats)} categories | {len(seen)} existing ASINs', flush=True)

    total = 0
    slots = len(cats) * len(FORMAT_CODES)
    done_count = 0

    for cat_id, cat_name in cats:
        for fmt_name, fmt_code in FORMAT_CODES.items():
            key = f'{cat_id}:{fmt_name}'
            done_count += 1
            if key in done:
                continue
            page = 1
            slot_new = 0
            while True:
                html = get(search_url(cat_id, fmt_code, month, year, page))
                if not html:
                    break
                books = parse_books(html, fmt_name)
                new   = [b for b in books if b['ASIN'] not in seen]
                if new:
                    for b in new:
                        seen.add(b['ASIN'])
                    _append(out_csv, new)
                    slot_new += len(new)
                    total    += len(new)
                if new or page == 1:
                    print(f'  [{done_count}/{slots}] {cat_name[:25]}/{fmt_name} p{page}: +{len(new)} (total={total})', flush=True)
                if not has_next(html):
                    break
                time.sleep(random.uniform(*SCRAPE_DELAY))
                page += 1
            done.add(key)
            if len(done) % 10 == 0:
                Path(state_file).write_text(json.dumps({'done': list(done)}))
            time.sleep(random.uniform(0.5, 1.5))

    Path(state_file).write_text(json.dumps({'done': list(done)}))
    print(f'\n[SCRAPE] Done: {total} new books saved to {out_csv}', flush=True)
    return total

def _append(path, rows):
    is_new = not path.exists()
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        if is_new:
            w.writeheader()
        w.writerows(rows)

# ─── Publisher Enrichment ─────────────────────────────────────────────────────

_PUB_CACHE: dict = {}
_PUB_LOCK = threading.Lock()
PUB_CACHE_FILE = Path('publisher_cache.json')

def load_pub_cache():
    global _PUB_CACHE
    if PUB_CACHE_FILE.exists():
        try:
            _PUB_CACHE = json.loads(PUB_CACHE_FILE.read_text())
        except Exception:
            _PUB_CACHE = {}
    print(f'[PUB] Cache: {len(_PUB_CACHE):,} ASINs', flush=True)

def save_pub_cache():
    with _PUB_LOCK:
        PUB_CACHE_FILE.write_text(json.dumps(_PUB_CACHE))

def parse_publisher(soup):
    for li in soup.select('#detailBullets_feature_div li'):
        raw = li.get_text(' ', strip=True).replace('\u200f','').replace('\u200e','').replace('\u200b','')
        if re.search(r'\bPublisher\b', raw, re.I) and ':' in raw:
            val = re.sub(r'\s*\(.*?\)\s*$', '', raw.split(':', 1)[1].strip())
            if val and val.lower() != 'publisher':
                return val
    for row in soup.select('.rpi-attribute-content'):
        label = row.select_one('.rpi-attribute-label span')
        value = row.select_one('.rpi-attribute-value span')
        if label and value and 'publisher' in label.get_text(strip=True).lower():
            val = re.sub(r'\s*\(.*?\)\s*$', '', value.get_text(strip=True)).strip()
            if val:
                return val
    for sel in ('#productDetailsTable', 'table.prodDetTable', '#detailsListWrapper'):
        for tr in soup.select(f'{sel} tr'):
            cells = tr.select('td, th')
            if len(cells) >= 2 and 'publisher' in cells[0].get_text(strip=True).lower():
                val = re.sub(r'\s*\(.*?\)\s*$', '', cells[1].get_text(strip=True)).strip()
                if val:
                    return val
    for dt in soup.select('dt.a-text-bold'):
        if 'publisher' in dt.get_text(strip=True).lower():
            dd = dt.find_next_sibling('dd')
            if dd:
                val = re.sub(r'\s*\(.*?\)\s*$', '', dd.get_text(strip=True)).strip()
                if val:
                    return val
    return ''

def fetch_publisher(asin):
    with _PUB_LOCK:
        if asin in _PUB_CACHE:
            return _PUB_CACHE[asin]
    html = get(f'https://www.amazon.com/dp/{asin}', retries=3, timeout=30)
    pub  = parse_publisher(BeautifulSoup(html, 'lxml')) if html else ''
    with _PUB_LOCK:
        _PUB_CACHE[asin] = pub
    return pub

def pub_worker(wq, rq, delay):
    while True:
        asin = wq.get()
        if asin is None:
            wq.task_done()
            break
        pub = fetch_publisher(asin)
        rq.put((asin, pub))
        wq.task_done()
        time.sleep(random.uniform(delay * 0.8, delay * 1.3))

def enrich_publishers(csv_path, num_workers, delay):
    rows = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        rows = [{k: (r.get(k) or '').strip() for k in FIELDNAMES} for r in csv.DictReader(f)]

    need = [r['ASIN'] for r in rows if r['ASIN'] and not r.get('Publisher')]
    print(f'\n[PUB] {len(rows)} rows | {len(need)} need publisher fetch', flush=True)

    if not need:
        print('[PUB] All publishers already filled', flush=True)
        return

    wq = queue.Queue()
    rq = queue.Queue()
    for asin in need:
        wq.put(asin)
    for _ in range(num_workers):
        wq.put(None)

    threads = [threading.Thread(target=pub_worker, args=(wq, rq, delay), daemon=True)
               for _ in range(num_workers)]
    for t in threads:
        t.start()

    by_asin  = {r['ASIN']: r for r in rows}
    fetched  = 0
    total    = len(need)

    while fetched < total:
        asin, pub = rq.get()
        if asin in by_asin:
            by_asin[asin]['Publisher'] = pub
        fetched += 1
        print(f'  [{fetched}/{total}] {asin}: {pub or "(not found)"}', flush=True)
        if fetched % 100 == 0:
            save_pub_cache()
            _write_csv(csv_path, rows)

    for t in threads:
        t.join()
    save_pub_cache()
    _write_csv(csv_path, rows)
    filled = sum(1 for r in rows if r.get('Publisher'))
    print(f'[PUB] Done: {filled}/{len(rows)} rows have Publisher', flush=True)

def _write_csv(path, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

# ─── Git Push ─────────────────────────────────────────────────────────────────

def git_push(repo_dir, month_str):
    try:
        subprocess.run(['git', 'add', f'data_3/books_{month_str}.csv', 'publisher_cache.json', 'categories.json'],
                       cwd=repo_dir, check=True, capture_output=True)
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=repo_dir, capture_output=True)
        if r.returncode != 0:
            subprocess.run(['git', 'commit', '-m', f'data_3: complete pipeline for {month_str}'],
                           cwd=repo_dir, check=True, capture_output=True)
            subprocess.run(['git', 'push'], cwd=repo_dir, check=True, capture_output=True)
            print(f'[GIT] Pushed data_3/books_{month_str}.csv', flush=True)
    except Exception as e:
        print(f'[GIT] Push failed: {e}', flush=True)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--month',   required=True, help='YYYY-MM')
    parser.add_argument('--out-dir', default='data_3')
    parser.add_argument('--workers', type=int, default=PUB_WORKERS)
    parser.add_argument('--pub-delay', type=float, default=1.0)
    parser.add_argument('--no-push', action='store_true')
    args = parser.parse_args()

    if not re.match(r'^\d{4}-\d{2}$', args.month):
        sys.exit('--month must be YYYY-MM')

    year  = int(args.month[:4])
    month = int(args.month[5:7])
    repo  = Path(__file__).parent
    out   = repo / args.out_dir
    out.mkdir(exist_ok=True)
    csv_p = out / f'books_{args.month}.csv'
    state = repo / f'pipeline_state_{args.month}.json'

    print(f'{"="*60}', flush=True)
    print(f'PIPELINE: {args.month} → {csv_p}', flush=True)
    print(f'{"="*60}\n', flush=True)

    # Step 1: Discover categories
    cats = discover_categories()
    print(f'[CONFIG] {len(cats)} categories × 3 formats × all pages\n', flush=True)

    # Step 2: Scrape
    scrape_month(year, month, cats, csv_p, str(state))

    # Step 3: Enrich publisher
    load_pub_cache()
    enrich_publishers(csv_p, args.workers, args.pub_delay)

    # Step 4: Push to GitHub
    if not args.no_push:
        git_push(repo, args.month)

    # Summary
    with open(csv_p, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    filled = sum(1 for r in rows if r.get('Publisher'))
    print(f'\n{"="*60}', flush=True)
    print(f'COMPLETE: {len(rows):,} books in {csv_p.name}', flush=True)
    print(f'Publisher filled: {filled:,}/{len(rows):,}', flush=True)
    print(f'{"="*60}', flush=True)

if __name__ == '__main__':
    main()
