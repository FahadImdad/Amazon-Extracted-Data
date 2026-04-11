#!/usr/bin/env python3
"""
Discover deeper Amazon browse nodes from existing seed categories.

This does NOT scrape books. It explores Amazon links for additional child/category
node IDs so the main scraper can later cover more of the catalog.

Usage:
  python discover_categories.py --depth 2 --output discovered_categories.json
"""

import argparse
import json
import random
import re
import time
from collections import deque
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

from scraper import CATEGORIES, USER_AGENTS

SESSION = requests.Session()


def build_seed_url(cat_id: str) -> str:
    return f"https://www.amazon.com/s?i=stripbooks&rh=n%3A{cat_id}&s=featured-rank&ref=sr_pg_1"


def fetch(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
            r = SESSION.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and "captcha" not in r.text.lower():
                return r.text
            time.sleep(random.uniform(2, 5))
        except requests.RequestException:
            time.sleep(random.uniform(2, 5))
    return None


def extract_nodes(html: str):
    soup = BeautifulSoup(html, "html.parser")
    found = {}

    for a in soup.select("a[href]"):
        href = a.get("href", "")
        text = a.get_text(" ", strip=True)
        if not href or not text:
            continue
        full = urljoin("https://www.amazon.com", href)
        decoded = unquote(full)

        for match in re.finditer(r"(?:[?&]|rh=|/|^)n:?([0-9]{2,})", decoded):
            node_id = match.group(1)
            if node_id:
                found[node_id] = text[:120]

        rh_match = re.search(r"rh=[^\s]*n:([0-9]{2,})", decoded)
        if rh_match:
            found[rh_match.group(1)] = text[:120]

    return found


def discover(depth: int):
    seed_map = {cat_id: name for cat_id, name in CATEGORIES}
    queue = deque((cat_id, name, 0) for cat_id, name in CATEGORIES)
    seen = set(seed_map.keys())
    discovered = {cat_id: {"name": name, "source": "seed", "depth": 0} for cat_id, name in CATEGORIES}

    while queue:
        node_id, name, level = queue.popleft()
        if level >= depth:
            continue

        html = fetch(build_seed_url(node_id))
        if not html:
            continue

        children = extract_nodes(html)
        for child_id, child_name in children.items():
            if child_id in seen:
                continue
            seen.add(child_id)
            discovered[child_id] = {
                "name": child_name or f"Node {child_id}",
                "source": node_id,
                "depth": level + 1,
            }
            queue.append((child_id, child_name or f"Node {child_id}", level + 1))

        time.sleep(random.uniform(1.5, 3.0))

    return discovered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--output", default="discovered_categories.json")
    args = ap.parse_args()

    found = discover(args.depth)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=2, ensure_ascii=False)

    print(f"Discovered {len(found)} total nodes")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
