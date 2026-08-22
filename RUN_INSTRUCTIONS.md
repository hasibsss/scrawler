# How to get this app running

Give this whole file to a coding agent (Claude Code, Cursor, etc.) and ask it
to follow the steps below. No manual coding knowledge is needed.

## 1. Get the code

```
git clone https://github.com/hasibsss/scrawler.git
cd scrawler
```

(If `git` isn't installed: Windows -- https://git-scm.com/download/win ;
Linux -- `sudo apt install git`, or `sudo dnf install git`, depending on the
distro.)

## 2. Prerequisites (install these first if missing)

**Windows:**
- Python 3.10+ from https://www.python.org/downloads/ -- tick "Add
  python.exe to PATH" during install. Check with: `py --version`

**Linux:**
- `sudo apt install python3 python3-pip python3-venv` (Debian/Ubuntu), or
  the equivalent for the distro. Check with: `python3 --version`

Node.js is not required to run the app itself.

## 3. Recreate the credentials file

The Shopify API credentials are deliberately **not** in the git repo (they're
a secret, so `.gitignore` keeps them out). Create this file by hand after
cloning:

`amazon_enricher/.shopify_credentials.json`

```json
{
  "shop": "3d4tzh-aw.myshopify.com",
  "access_token": "PASTE_THE_REAL_TOKEN_HERE",
  "scope": "read_locations,write_inventory,write_products"
}
```

Ask whoever set this up originally for the real `access_token` value --
don't invent one, it has to be the real Shopify Admin API token.

## 4. Install dependencies

**Windows:**
```
py -m pip install -r requirements.txt
py -m playwright install chromium
```

**Linux:**
```
python3 -m pip install -r requirements.txt
python3 -m playwright install --with-deps chromium
```
(`--with-deps` also installs the system libraries Chromium needs -- skip it
only if those are already present.)

## 5. Start the app

**Windows:**
```
py server.py
```

**Linux:**
```
HOST=0.0.0.0 python3 server.py
```
(`HOST=0.0.0.0` makes it reachable from other machines on the network, not
just localhost -- needed when running on a server/VM instead of a personal
laptop.)

Either way this starts a local web server at:

```
http://127.0.0.1:5000        (same machine)
http://<server-ip>:5000      (from another machine on the network, Linux only)
```

On Windows it also opens that address automatically in the default browser.

## Stop the app

Close the terminal window it's running in, or press Ctrl+C inside it.

## Running it long-term on a server (Linux)

The command above (`py server.py` / `python3 server.py`) stops as soon as
the terminal closes. For a server that should keep running, use `systemd`,
`pm2`, or `nohup python3 server.py &` -- ask the coding agent to set one of
these up once the app is confirmed working with the plain command first.

## What the app does

Two tabs in the browser:
- **Matrixify Export** -- upload a Matrixify `.xlsx` sheet with an ASIN
  column, get back an enriched sheet (images/description/specs filled in
  from Amazon).
- **Push to Shopify** -- upload a sheet with ASIN + LPN columns (Price,
  Weight, Condition, UPC, EAN, SKU optional); it scrapes Amazon and creates
  or updates the matching Shopify product directly, no file download needed.
