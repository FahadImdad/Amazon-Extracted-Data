# Amazon Bulk Book Scraper

Scrapes Amazon Advanced Search by month/year range and saves raw book data to CSV.  
No email finding — just cheap bulk data collection.

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
| `--max-pages` | 5 | Max pages per category/format/month slot |
| `--max-reviews` | 5 | Skip books with more reviews than this |

## Resume

If interrupted, just run the same command again — it resumes from where it left off.

## Output CSV columns

| Column | Description |
|--------|-------------|
| asin | Amazon ASIN |
| title | Book title |
| author | Author name |
| publish_date | Publication date string |
| review_count | Number of reviews |
| book_format | Paperback / Hardcover / Kindle |
| publisher | Publisher name (if found) |
| amazon_url | Full Amazon URL |

## Scale estimate (2020–2025)

- 6 years × 12 months = 72 months
- × 38 categories × 3 formats = **8,208 slots**
- × 5 pages × ~20 books = **~820,000 books max**
- Filtered to ≤5 reviews → **~50,000–100,000 qualified leads**
- At ~2 sec/request → ~16,000 seconds (~4-5 hours total)

## Cost

Near $0 — uses direct HTTP requests with rotating user agents.  
No Bright Data, no API keys needed.  
Amazon may occasionally block — scraper auto-retries and resumes.

## Next step

Feed the CSV into LeadGen Pro v2 email pipeline:
1. Filter: `review_count <= 5` + desired date range
2. Run email finder on filtered authors
3. Import verified emails into LeadGen dashboard
