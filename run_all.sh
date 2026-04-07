#!/bin/bash
# Runs scraper month by month — each month gets its own CSV file
# Max pages = 20 (Amazon's hard limit per category/format/month slot)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/data"
mkdir -p "$OUTPUT_DIR"

FROM_YEAR=2021
TO_YEAR=2025

for year in $(seq $FROM_YEAR $TO_YEAR); do
  for month in $(seq -w 1 12); do
    YM="${year}-${month}"
    OUT="$OUTPUT_DIR/books_${YM}.csv"
    STATE="$OUTPUT_DIR/state_${YM}.json"

    # Skip if already complete (state file marked done)
    if [ -f "$STATE" ] && grep -q '"done":true' "$STATE" 2>/dev/null; then
      echo "✅ Skipping $YM (already complete)"
      continue
    fi

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📅 Scraping $YM..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    python3 "$SCRIPT_DIR/scraper.py" \
      --from "$YM" \
      --to "$YM" \
      --output "$OUT" \
      --state "$STATE" \
      --max-pages 20 \
      --max-reviews 5 \
      --delay-min 1.0 \
      --delay-max 2.5

    # Mark as done
    echo '{"done":true}' > "$STATE"

    COUNT=$(wc -l < "$OUT" 2>/dev/null || echo 0)
    echo "✅ $YM done — $COUNT books saved"
    sleep 3
  done
done

echo ""
echo "🎉 All months complete!"
echo "📊 Total books across all files:"
cat "$OUTPUT_DIR"/books_*.csv | grep -v "^asin" | wc -l
