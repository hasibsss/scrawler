"""
Amazon ASIN enricher for Matrixify sheets.

Takes a Matrixify export (an Excel sheet that already has an ASIN column),
looks up each ASIN on Amazon, and writes back an enriched Excel file with
only real, Shopify-uploadable Matrixify columns:
  - all gallery images, semicolon-joined in an "Image Src" column
    (this is exactly the format Matrixify expects for multiple images
    on one product row)
  - "Body HTML" gets the "About this item" bullets + specifications table,
    appended after any existing description (never overwritten)
  - "About this item" bullets, specifications, rating, and review count are
    also written as real "Metafield: amazon.xxx [...]" columns (no price --
    pricing stays whatever is already in your Matrixify sheet)

Nothing diagnostic (scrape status, source URL, etc.) is written into the
sheet itself, since that has no business living on the live Shopify product.
Runs headless (no visible browser window) by default. Any ASIN that fails
leaves its data columns blank -- it is never invented or guessed -- and gets
reported two ways: printed to the console as the run finishes, and written
to a plain-text "<output>_failures.log" file next to the output workbook.

Usage:
    py main.py --input clients_export.xlsx
    py main.py --input clients_export.xlsx --output enriched.xlsx --limit 5
    py main.py --input clients_export.xlsx --asin-column "ASIN" --headed

Session cookies are saved to amazon_enricher/.session_state.json and reused
on later runs, so Amazon sees a returning browser rather than a fresh one
each time.
"""

import argparse
import random
import sys
import time

from playwright.sync_api import sync_playwright

from amazon_enricher import config
from amazon_enricher.matrixify_io import read_input, write_output
from amazon_enricher.scraper import create_context, fetch_with_retries, save_state


def parse_args():
    p = argparse.ArgumentParser(description="Enrich a Matrixify sheet with Amazon product data, ASIN by ASIN.")
    p.add_argument("--input", required=True, help="Path to the Matrixify .xlsx export")
    p.add_argument("--output", default=None, help="Path for the enriched .xlsx (default: <input>_enriched.xlsx)")
    p.add_argument("--sheet", default=None, help="Sheet name to read (default: 'Products' sheet, or the first sheet)")
    p.add_argument("--asin-column", default=None, help="Exact header name of the ASIN column (default: auto-detect)")
    p.add_argument("--domain", default=config.DEFAULT_DOMAIN, help="Amazon domain, e.g. amazon.com / amazon.co.uk")
    p.add_argument(
        "--headed", action="store_true", help="Show the browser window (default: headless, no window)"
    )
    p.add_argument("--limit", type=int, default=None, help="Only process the first N rows (useful for a test run)")
    p.add_argument("--min-delay", type=float, default=config.DEFAULT_MIN_DELAY, help="Minimum seconds between requests")
    p.add_argument("--max-delay", type=float, default=config.DEFAULT_MAX_DELAY, help="Maximum seconds between requests")
    p.add_argument("--fresh-session", action="store_true", help="Ignore any saved session and start clean")
    return p.parse_args()


def scrape_all(context, df, asin_col, domain, args, output_path):
    """Scrapes each ASIN and re-saves the output workbook after every product,
    so a run that's stopped early (or crashes) still leaves a usable file with
    whatever was completed so far -- nothing scraped is ever thrown away.
    """
    results = {}
    asins = df[asin_col].tolist()
    total = len(asins)

    for i, asin in enumerate(asins, start=1):
        print(f"[{i}/{total}] {asin} ...", end=" ", flush=True)
        result = fetch_with_retries(context, asin, domain)
        results[asin] = result

        extra = f"(images: {result.get('image_count', 0)})" if result["status"] == "ok" else ""
        print(result["status"], extra)

        write_output(df, asin_col, results, output_path)

        if i < total:
            time.sleep(random.uniform(args.min_delay, args.max_delay))

    return results


def main():
    args = parse_args()
    output_path = args.output or args.input.rsplit(".", 1)[0] + "_enriched.xlsx"

    print(f"Reading {args.input} ...")
    df, asin_col, sheet_name = read_input(args.input, sheet=args.sheet, asin_column=args.asin_column)
    print(f"Using sheet '{sheet_name}', ASIN column '{asin_col}'. {len(df)} product(s) to process.")

    if args.limit:
        df = df.head(args.limit)
        print(f"--limit set: processing only the first {len(df)} row(s).")

    storage_state_path = None if args.fresh_session else config.STORAGE_STATE_PATH

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = create_context(browser, storage_state_path)
        try:
            results = scrape_all(context, df, asin_col, args.domain, args, output_path)
        finally:
            save_state(context, config.STORAGE_STATE_PATH)
            context.close()
            browser.close()

    statuses = [r["status"] for r in results.values()]
    summary = {s: statuses.count(s) for s in set(statuses)}
    print(f"\nDone. Wrote {output_path}")
    print(f"Summary: {summary}")

    failures = {asin: r for asin, r in results.items() if r["status"] != "ok"}
    if failures:
        print(f"\n{len(failures)} ASIN(s) failed -- data columns left blank for these rows:")
        log_path = output_path.rsplit(".", 1)[0] + "_failures.log"
        with open(log_path, "w", encoding="utf-8") as f:
            for asin, r in failures.items():
                line = f"{asin}\t{r['status']}\t{r.get('notes', '')}\t{r.get('url', '')}"
                print(f"  - {asin}: {r['status']} ({r.get('notes', '')})")
                f.write(line + "\n")
        print(f"Full details logged to {log_path}. Re-run with just these ASINs once ready.")


if __name__ == "__main__":
    sys.exit(main())
