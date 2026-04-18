#!/usr/bin/env python3
"""
data_1 Cleanup Script
Fixes all existing CSV files in data_1/ in-place.

Operations applied to every file:
  1. English-only filter
  2. review_count <= 5
  3. Skip audiobooks / CD / non-book formats
  4. Format priority: Paperback > Hardcover > Kindle (others dropped)
  5. Fix shifted/malformed columns
  6. Strict month/year validation of Publication Date
  7. Deduplicate by ASIN (keep first clean occurrence)
  8. Remove clearly bad rows (invalid ASIN, empty title)

Usage:
    python clean_data.py               # all files in ./data_1
    python clean_data.py --dir /path   # custom data_1 directory
    python clean_data.py --dry-run     # report only, no writes
    python clean_data.py --file books_2024-06.csv
"""

import argparse
import csv
import io
import re
import sys
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

FIELDS = [
    "Total Reviews", "Product Url", "ASIN", "Title",
    "Author", "Format", "Publication Date", "Publisher",
]

VALID_FORMATS = {"Paperback", "Hardcover", "Kindle"}

FORMAT_RANK = {"Paperback": 0, "Hardcover": 1, "Kindle": 2}

AUDIOBOOK_KEYWORDS = (
    "audible", "audio cd", "audio book", "audiobook",
    "mp3 cd", "cd-rom", "board book",
)

# Edition strings that betray non-English listings
NON_ENGLISH_EDITION_MARKERS = (
    "dutch edition", "french edition", "german edition",
    "spanish edition", "italian edition", "portuguese edition",
    "japanese edition", "chinese edition", "korean edition",
    "arabic edition", "russian edition", "turkish edition",
    "polish edition", "hindi edition", "urdu edition",
    "swedish edition", "norwegian edition", "danish edition",
    "finnish edition", "hebrew edition", "greek edition",
    "romanian edition", "czech edition", "hungarian edition",
    "slovak edition", "croatian edition", "catalan edition",
    "edition française", "edición", "ausgabe", "editie",
    "wydanie", "edição", "edizione",
)

# Standard Amazon ASIN pattern
ASIN_RE = re.compile(r'^[A-Z0-9]{10}$')

# Month name → number
MONTH_MAP = {
    "january": 1,  "jan": 1,
    "february": 2, "feb": 2,
    "march": 3,    "mar": 3,
    "april": 4,    "apr": 4,
    "may": 5,
    "june": 6,     "jun": 6,
    "july": 7,     "jul": 7,
    "august": 8,   "aug": 8,
    "september": 9,"sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11,"nov": 11,
    "december": 12,"dec": 12,
}

MONTH_NAMES = {v: k.title() for k, v in MONTH_MAP.items() if len(k) > 3}

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_review_count(text: str) -> int:
    cleaned = re.sub(r'[,.\s]', '', text or "")
    m = re.search(r'\d+', cleaned)
    return int(m.group()) if m else 0


def is_valid_asin(asin: str) -> bool:
    return bool(ASIN_RE.match((asin or "").strip().upper()))


def non_ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii / len(text)


def is_english(row: dict) -> bool:
    """
    Heuristic English check — no external packages needed.
    Returns False if the book is clearly non-English.
    """
    title   = (row.get("Title") or "").strip()
    pub_date = (row.get("Publication Date") or "").strip().lower()
    author  = (row.get("Author") or "").strip()

    # 1. Publication Date contains language edition marker
    for marker in NON_ENGLISH_EDITION_MARKERS:
        if marker in pub_date:
            return False

    # 2. Title has >25% non-ASCII characters (CJK, Arabic, Cyrillic, etc.)
    if non_ascii_ratio(title) > 0.25:
        return False

    # 3. ASIN looks like an ISBN-10 (all digits = almost certainly non-Amazon-native)
    asin = (row.get("ASIN") or "").strip()
    if asin.isdigit():
        return False

    return True


def is_audiobook(row: dict) -> bool:
    title = (row.get("Title") or "").lower()
    fmt   = (row.get("Format") or "").lower()
    for kw in AUDIOBOOK_KEYWORDS:
        if kw in title or kw in fmt:
            return True
    return False


def canonical_format(raw: str) -> str:
    """Map raw format string to canonical name, or '' if invalid/audiobook."""
    s = (raw or "").strip().lower()
    if "paperback" in s:
        return "Paperback"
    if "hardcover" in s or "hardback" in s:
        return "Hardcover"
    if "kindle" in s or "ebook" in s or "e-book" in s:
        return "Kindle"
    return ""


def parse_pub_month_year(date_str: str) -> tuple:
    """
    Try to extract (year, month) from a publication date string.
    Returns (year: int, month: int) or (None, None) if unparseable.

    Handles: "Jun 30, 2024", "June 2024", "2024-06-15", "2024-06", "Jan 2021"
    """
    s = (date_str or "").strip().lower()
    if not s:
        return None, None

    # ISO format: 2024-06-15 or 2024-06
    m = re.match(r'(\d{4})-(\d{2})', s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # "Jun 30, 2024" or "June 2024" or "30 Jun 2024"
    year_m = re.search(r'\b(20\d{2})\b', s)
    if year_m:
        year = int(year_m.group(1))
        for name, num in MONTH_MAP.items():
            if name in s:
                return year, num

    return None, None


def try_fix_shifted(raw_fields: list):
    """
    Attempt to repair a row where columns appear shifted.
    Returns a fixed dict or None if unfixable.
    """
    # Strategy: find the ASIN (10-char alphanumeric) and realign around it
    asin_idx = None
    for i, val in enumerate(raw_fields):
        if ASIN_RE.match((val or "").strip().upper()):
            asin_idx = i
            break

    if asin_idx is None:
        return None  # can't find ASIN, drop row

    # Expected: Total Reviews(0), Product Url(1), ASIN(2), Title(3), Author(4),
    #           Format(5), Publication Date(6), Publisher(7)
    expected_asin_col = 2
    shift = asin_idx - expected_asin_col

    if shift == 0:
        return None  # not shifted

    shifted = raw_fields[shift:] + [""] * shift if shift > 0 else [""] * abs(shift) + raw_fields
    if len(shifted) < len(FIELDS):
        shifted += [""] * (len(FIELDS) - len(shifted))

    row = {FIELDS[i]: (shifted[i] or "").strip() for i in range(len(FIELDS))}

    # Validate the repaired row
    if is_valid_asin(row["ASIN"]) and row.get("Title"):
        return row
    return None


def clean_row(raw: dict) -> dict:
    return {k: (raw.get(k) or "").strip() for k in FIELDS}


def month_filename_key(filename: str) -> tuple:
    """Extract (year, month) from filename like 'books_2024-06.csv'."""
    m = re.search(r'(\d{4})-(\d{2})', filename)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

# ── Per-file processing ───────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.total = self.kept = 0
        self.dropped_non_english = 0
        self.dropped_reviews = 0
        self.dropped_audiobook = 0
        self.dropped_format = 0
        self.dropped_bad_date = 0
        self.dropped_bad_asin = 0
        self.dropped_no_title = 0
        self.dropped_duplicate = 0
        self.fixed_shifted = 0

    def summary(self) -> str:
        dropped = self.total - self.kept
        lines = [
            f"  total={self.total}  kept={self.kept}  dropped={dropped}",
            f"  reasons: non-english={self.dropped_non_english}  "
            f"reviews>{5}={self.dropped_reviews}  "
            f"audiobook={self.dropped_audiobook}  "
            f"format={self.dropped_format}",
            f"           bad-date={self.dropped_bad_date}  "
            f"bad-asin={self.dropped_bad_asin}  "
            f"no-title={self.dropped_no_title}  "
            f"duplicate={self.dropped_duplicate}  "
            f"shifted-fixed={self.fixed_shifted}",
        ]
        return "\n".join(lines)


def process_file(path: Path, dry_run: bool) -> Stats:
    st = Stats()
    file_year, file_month = month_filename_key(path.name)

    # Read raw CSV, handle encoding issues
    try:
        raw_text = path.read_bytes().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [READ ERROR] {e}", flush=True)
        return st

    reader = csv.DictReader(io.StringIO(raw_text))
    # If header is missing expected fields, try raw list approach
    if not reader.fieldnames or "ASIN" not in reader.fieldnames:
        reader = csv.reader(io.StringIO(raw_text))
        rows_raw = list(reader)
        if not rows_raw:
            return st
        # Try to use first row as header or assume FIELDS order
        header = rows_raw[0]
        if "ASIN" in header:
            rows_dicts = [
                {header[i]: (rows_raw[j][i] if i < len(rows_raw[j]) else "")
                 for i in range(len(header))}
                for j in range(1, len(rows_dicts))
            ]
        else:
            rows_dicts = [
                {FIELDS[i]: (r[i] if i < len(r) else "") for i in range(len(FIELDS))}
                for r in rows_raw
            ]
    else:
        rows_dicts = list(reader)

    seen_asins: set = set()
    output_rows: list = []

    for raw_row in rows_dicts:
        st.total += 1
        row = clean_row(raw_row)

        # ── Fix shifted columns ─────────────────────────────────────────────
        if not is_valid_asin(row.get("ASIN", "")):
            raw_vals = list(raw_row.values())
            fixed = try_fix_shifted(raw_vals)
            if fixed:
                row = fixed
                st.fixed_shifted += 1
            else:
                st.dropped_bad_asin += 1
                continue

        asin  = row["ASIN"].upper()
        title = row.get("Title", "")

        # ── Drop no title ───────────────────────────────────────────────────
        if not title:
            st.dropped_no_title += 1
            continue

        # ── English filter ──────────────────────────────────────────────────
        if not is_english(row):
            st.dropped_non_english += 1
            continue

        # ── Audiobook filter ────────────────────────────────────────────────
        if is_audiobook(row):
            st.dropped_audiobook += 1
            continue

        # ── Format filter ───────────────────────────────────────────────────
        fmt = canonical_format(row.get("Format", ""))
        if not fmt:
            st.dropped_format += 1
            continue
        row["Format"] = fmt

        # ── Review filter ───────────────────────────────────────────────────
        reviews = parse_review_count(row.get("Total Reviews", "0"))
        if reviews > 5:
            st.dropped_reviews += 1
            continue
        row["Total Reviews"] = str(reviews)

        # ── Month/year validation ───────────────────────────────────────────
        if file_year and file_month:
            pub_year, pub_month = parse_pub_month_year(row.get("Publication Date", ""))
            if pub_year is None:
                # Can't parse date — drop (strict mode)
                st.dropped_bad_date += 1
                continue
            if pub_year != file_year or pub_month != file_month:
                st.dropped_bad_date += 1
                continue

        # ── Deduplicate ─────────────────────────────────────────────────────
        if asin in seen_asins:
            st.dropped_duplicate += 1
            continue
        seen_asins.add(asin)

        output_rows.append(row)
        st.kept += 1

    # ── Sort by Format priority ─────────────────────────────────────────────
    output_rows.sort(key=lambda r: FORMAT_RANK.get(r["Format"], 99))

    # ── Write back ──────────────────────────────────────────────────────────
    if not dry_run:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(output_rows)

    return st

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clean and filter data_1/ CSV files")
    parser.add_argument("--dir",     default="data_1", help="data_1 directory path")
    parser.add_argument("--file",    default="",       help="Single file name to process")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    args = parser.parse_args()

    data_dir = Path(args.dir)
    if not data_dir.exists():
        print(f"[ERROR] Directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    if args.file:
        files = [data_dir / args.file]
    else:
        files = sorted(data_dir.glob("books_*.csv"))

    if not files:
        print(f"[ERROR] No CSV files found in {data_dir}", file=sys.stderr)
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"[START] {len(files)} file(s) — mode: {mode}\n", flush=True)

    grand = Stats()

    for path in files:
        if not path.exists():
            print(f"[SKIP] {path.name} — not found", flush=True)
            continue

        print(f"[FILE] {path.name}", flush=True)
        st = process_file(path, dry_run=args.dry_run)

        print(st.summary(), flush=True)
        print(flush=True)

        grand.total              += st.total
        grand.kept               += st.kept
        grand.dropped_non_english+= st.dropped_non_english
        grand.dropped_reviews    += st.dropped_reviews
        grand.dropped_audiobook  += st.dropped_audiobook
        grand.dropped_format     += st.dropped_format
        grand.dropped_bad_date   += st.dropped_bad_date
        grand.dropped_bad_asin   += st.dropped_bad_asin
        grand.dropped_no_title   += st.dropped_no_title
        grand.dropped_duplicate  += st.dropped_duplicate
        grand.fixed_shifted      += st.fixed_shifted

    print("=" * 60, flush=True)
    print("[TOTAL]", flush=True)
    print(grand.summary(), flush=True)
    if args.dry_run:
        print("\n[DRY RUN] No files were modified.", flush=True)


if __name__ == "__main__":
    main()
