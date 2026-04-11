# Amazon Bulk Book Scraper

Scrapes Amazon Advanced Search by month/year range and saves raw book data to CSV.
No email finding, just bulk data collection.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

**Scrape 2020–2025 (full historical):**
```bash
python scraper.py --from 2020-01 --to 2025-12 --output books_2020_2025.csv
```

**Scrape just 2024:**
```bash
python scraper.py --from 2024-01 --to 2024-12 --output books_2024.csv
```

**Scrape a single month:**
```bash
python scraper.py --from 2025-06 --to 2025-06 --output books_jun2025.csv
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--from` | required | Start month (YYYY-MM) |
| `--to` | required | End month (YYYY-MM) |
| `--output` | books.csv | Output CSV file |
| `--state` | scraper_state.json | State file for resuming |
| `--delay-min` | 1.5 | Min seconds between requests |
| `--delay-max` | 3.5 | Max seconds between requests |
| `--max-pages` | 0 | Max pages per category/format/month slot, 0 = unlimited |
| `--max-reviews` | 5 | Skip books with more reviews than this |
| `--discover-depth` | 2 | Recursive category discovery depth |

## Resume

If interrupted, just run the same command again — it resumes from where it left off.

## Output CSV columns

| Column | Description |
|--------|-------------|
| Total Reviews | Number of reviews |
| Product Url | Full Amazon URL |
| ASIN | Amazon ASIN |
| Title | Book title |
| Author | Author name |
| Format | Paperback / Hardcover / Kindle |
| Publication Date | Publication date string |
| Publisher | Publisher name (if found) |

## Scale estimate (2020–2025)

- 6 years × 12 months = 72 months
- recursive categories × 3 formats × unlimited pages until exhaustion
- output is deduped by ASIN per monthly CSV

## Cost

Near $0 — uses direct HTTP requests with rotating user agents.  
No Bright Data, no API keys needed.  
Amazon may occasionally block — scraper auto-retries and resumes.

## Next step

Feed the CSV into LeadGen Pro v2 email pipeline:
1. Filter: `review_count <= 5` + desired date range
2. Run email finder on filtered authors
3. Import verified emails into LeadGen dashboard
