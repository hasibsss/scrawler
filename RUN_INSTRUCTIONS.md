# How to start this app

Give this whole file to a coding agent (Claude Code, Cursor, etc.) and ask it
to follow the steps below. No manual coding knowledge is needed.

## Prerequisites (install these first if missing)

- **Python 3.10 or newer** -- download from https://www.python.org/downloads/
  During install, tick the box "Add python.exe to PATH" (Windows installer).
  Check it's installed by running: `py --version`

That's the only runtime this app needs. (Node.js is not required to run the
app itself.)

## One-time setup (only needed the first time, or on a new machine)

Run these commands from the project's root folder (the folder this file is in):

```
py -m pip install -r requirements.txt
py -m playwright install chromium
```

Confirm this file exists (it holds the Shopify API credentials the app needs
to push products): `amazon_enricher/.shopify_credentials.json`
If it's missing, stop and ask -- the app cannot talk to Shopify without it.

## Start the app

```
py server.py
```

This starts a local web server and opens it automatically in the default
browser at:

```
http://127.0.0.1:5000
```

If the browser doesn't open by itself, open that address manually.

## Stop the app

Close the terminal window it's running in, or press Ctrl+C inside it.

## What the app does

Two tabs in the browser:
- **Matrixify Export** -- upload a Matrixify `.xlsx` sheet with an ASIN
  column, get back an enriched sheet (images/description/specs filled in
  from Amazon).
- **Push to Shopify** -- upload a sheet with ASIN + LPN columns (Price,
  Weight, Condition, UPC, EAN, SKU optional); it scrapes Amazon and creates
  or updates the matching Shopify product directly, no file download needed.
