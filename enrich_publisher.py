#!/usr/bin/env python3
"""
Publisher Enrichment — Direct Amazon HTTP (no Bright Data)
Reads data_1/ CSVs, fetches each Amazon product page, extracts Publisher.
Writes enriched files to data_2/ (data_1 untouched).
Auto-pushes to GitHub after each file completes.
Resumable via publisher_cache.json — safe to kill and restart.

Usage:
    python enrich_publisher.py                        # all files
    python enrich_publisher.py --file books_2024-06.csv
    python enrich_publisher.py --workers 15 --delay 1.0
"""

import argparse
import csv
import json
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

FIELDS = [
    "Total Reviews", "Product Url", "ASIN", "Title",
    "Author", "Format", "Publication Date", "Publisher",
]

CACHE_FILE = Path(__file__).parent / "publisher_cache.json"
CACHE_LOCK = threading.Lock()
MAX_RETRIES = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.2277.128",
]

_cache: dict = {}


def load_cache():
    global _cache
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            _cache = {}
    print(f"[CACHE] {len(_cache):,} ASINs already resolved", flush=True)


def flush_cache():
    with CACHE_LOCK:
        CACHE_FILE.write_text(json.dumps(_cache))


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "DNT":                       "1",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Cache-Control":             "max-age=0",
    })
    return s


def _parse_publisher(soup: BeautifulSoup) -> str:
    # Method 1: detail bullets
    for li in soup.select("#detailBullets_feature_div li"):
        raw = li.get_text(" ", strip=True)
        raw = raw.replace("\u200f", "").replace("\u200e", "").replace("\u200b", "")
        if re.search(r'\bPublisher\b', raw, re.I) and ":" in raw:
            val = raw.split(":", 1)[1].strip()
            val = re.sub(r'\s*\(.*?\)\s*$', '', val).strip()
            if val and val.lower() != "publisher":
                return val

    # Method 2: newer attribute rows
    for row in soup.select(".rpi-attribute-content"):
        label = row.select_one(".rpi-attribute-label span")
        value = row.select_one(".rpi-attribute-value span")
        if label and value and "publisher" in label.get_text(strip=True).lower():
            val = re.sub(r'\s*\(.*?\)\s*$', '', value.get_text(strip=True)).strip()
            if val:
                return val

    # Method 3: product details table
    for sel in ("#productDetailsTable", "table.prodDetTable", "#detailsListWrapper"):
        for tr in soup.select(f"{sel} tr"):
            cells = tr.select("td, th")
            if len(cells) >= 2 and "publisher" in cells[0].get_text(strip=True).lower():
                val = re.sub(r'\s*\(.*?\)\s*$', '', cells[1].get_text(strip=True)).strip()
                if val:
                    return val

    # Method 4: dt/dd pairs
    for dt in soup.select("dt.a-text-bold"):
        if "publisher" in dt.get_text(strip=True).lower():
            dd = dt.find_next_sibling("dd")
            if dd:
                val = re.sub(r'\s*\(.*?\)\s*$', '', dd.get_text(strip=True)).strip()
                if val:
                    return val

    return ""


def fetch_publisher(session: requests.Session, asin: str, delay: float) -> str:
    url = f"https://www.amazon.com/dp/{asin}"
    for attempt in range(MAX_RETRIES):
        try:
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                if "captcha" in r.text.lower() or "robot check" in r.text.lower():
                    time.sleep(30 + random.uniform(10, 30))
                    continue
                return _parse_publisher(BeautifulSoup(r.text, "lxml"))
            elif r.status_code in (429, 503, 403):
                time.sleep(20 * (attempt + 1) + random.uniform(0, 10))
            else:
                return ""
        except Exception:
            time.sleep(random.uniform(3, 7))
    return ""


def worker(work_q, result_q, delay, wid):
    session = make_session()
    while True:
        item = work_q.get()
        if item is None:
            work_q.task_done()
            break
        asin = item
        with CACHE_LOCK:
            if asin in _cache:
                result_q.put((asin, _cache[asin], False))
                work_q.task_done()
                continue
        publisher = fetch_publisher(session, asin, delay)
        with CACHE_LOCK:
            _cache[asin] = publisher
        result_q.put((asin, publisher, True))
        work_q.task_done()
        time.sleep(random.uniform(delay * 0.8, delay * 1.3))


def git_push(repo_dir: Path, filename: str):
    try:
        subprocess.run(["git", "add", f"data_2/{filename}", "publisher_cache.json"],
                       cwd=repo_dir, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_dir, capture_output=True
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", f"Enrich publisher: {filename}"],
                cwd=repo_dir, check=True, capture_output=True
            )
            subprocess.run(["git", "push"], cwd=repo_dir, check=True, capture_output=True)
            print(f"[GIT] Pushed {filename}", flush=True)
        else:
            print(f"[GIT] No changes to push for {filename}", flush=True)
    except Exception as e:
        print(f"[GIT] Push failed: {e}", flush=True)


def enrich_file(src_path: Path, out_path: Path, num_workers: int, delay: float) -> tuple:
    rows = []
    with open(src_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({k: (row.get(k) or "").strip() for k in FIELDS})

    if not rows:
        return 0, 0, 0

    by_asin    = {r["ASIN"]: r for r in rows if r.get("ASIN")}
    need_fetch = [a for a, r in by_asin.items() if not r.get("Publisher") and a not in _cache]
    already    = len(by_asin) - len(need_fetch)

    # Apply cache to rows that don't have publisher yet
    for asin, row in by_asin.items():
        if not row.get("Publisher") and asin in _cache:
            row["Publisher"] = _cache[asin]

    if not need_fetch:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return len(rows), 0, already

    work_q   = queue.Queue()
    result_q = queue.Queue()
    for asin in need_fetch:
        work_q.put(asin)
    for _ in range(num_workers):
        work_q.put(None)

    threads = [threading.Thread(target=worker, args=(work_q, result_q, delay, i), daemon=True)
               for i in range(num_workers)]
    for t in threads:
        t.start()

    fetched = cached = 0
    total_need = len(need_fetch)

    while fetched + cached < total_need:
        asin, publisher, was_fetched = result_q.get()
        if asin in by_asin:
            by_asin[asin]["Publisher"] = publisher
        if was_fetched:
            fetched += 1
            print(f"    [{fetched}/{total_need}] {asin}: {publisher or '(not found)'}", flush=True)
            if fetched % 50 == 0:
                flush_cache()
        else:
            cached += 1

    for t in threads:
        t.join()
    flush_cache()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    return len(rows), fetched, already + cached


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-dir",  default="data_1")
    parser.add_argument("--out-dir", default="data_2")
    parser.add_argument("--file",    default="")
    parser.add_argument("--workers", type=int,   default=15)
    parser.add_argument("--delay",   type=float, default=1.0)
    parser.add_argument("--no-push", action="store_true", help="Disable auto GitHub push")
    args = parser.parse_args()

    repo_dir = Path(__file__).parent
    in_dir   = Path(args.in_dir)
    out_dir  = Path(args.out_dir)

    if not in_dir.exists():
        sys.exit(f"[ERROR] Not found: {in_dir}")

    files = [in_dir / args.file] if args.file else sorted(in_dir.glob("books_*.csv"))
    if not files:
        sys.exit("[ERROR] No CSVs found")

    # Skip files already done in out_dir
    pending = []
    for f in files:
        out_p = out_dir / f.name
        if out_p.exists():
            print(f"[SKIP] {f.name} already in {out_dir}/", flush=True)
        else:
            pending.append(f)

    if not pending:
        print("[DONE] All files already enriched.", flush=True)
        return

    load_cache()

    total_rows = sum(
        max(sum(1 for _ in open(f, encoding="utf-8", errors="replace")) - 1, 0)
        for f in pending if f.exists()
    )
    rate     = args.workers / args.delay
    eta_hrs  = (total_rows / rate) / 3600
    print(f"[CONFIG] {len(pending)} files | {total_rows:,} rows | {args.workers} workers | delay={args.delay}s", flush=True)
    print(f"[ETA]    ~{eta_hrs:.1f}h total (cached rows are instant)", flush=True)
    print(f"[OUT]    Enriched files → {out_dir}/\n", flush=True)

    gt = gf = gc = 0
    for path in pending:
        if not path.exists():
            continue
        out_path = out_dir / path.name
        print(f"[FILE] {path.name}", flush=True)
        t, f, c = enrich_file(path, out_path, args.workers, args.delay)
        gt += t; gf += f; gc += c
        print(f"       {t} rows | {f} fetched | {c} cached → {out_path}", flush=True)

        if not args.no_push:
            git_push(repo_dir, path.name)
        print(flush=True)

    print("=" * 55, flush=True)
    print(f"[DONE] {gt:,} rows | {gf:,} fetched | {gc:,} cached", flush=True)


if __name__ == "__main__":
    main()
