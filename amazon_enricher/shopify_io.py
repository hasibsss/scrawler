"""Reading the direct-listing input sheet and building a Shopify product
payload from it plus the Amazon scrape result.

Sheet requirements: ASIN and LPN columns are mandatory (rows missing either
are skipped). Price, Weight, Condition, UPC, EAN, SKU, Title are all optional
and, when present, are used as-is rather than overwritten by the scrape --
see matrixify_io.py's docstring-level convention, which this mirrors.
"""

import pandas as pd

from .matrixify_io import _pick_sheet, ASIN_RE
from .scraper import _build_body_html

def _find_column(columns, *names):
    for col in columns:
        if str(col).strip().lower() in names:
            return col
    return None


def read_direct_input(path, sheet=None, asin_column=None, lpn_column=None):
    sheet_name = _pick_sheet(path, sheet)
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", dtype=str)
    df = df.dropna(how="all")

    asin_col = asin_column or _find_column(df.columns, "asin")
    if not asin_col:
        raise ValueError(f"Could not find an ASIN column. Available columns: {list(df.columns)}")

    lpn_col = lpn_column or _find_column(df.columns, "lpn")
    if not lpn_col:
        raise ValueError(f"Could not find an LPN column. Available columns: {list(df.columns)}")

    df[asin_col] = df[asin_col].astype(str).str.strip().str.upper()
    df[lpn_col] = df[lpn_col].astype(str).str.strip()

    valid_asin = df[asin_col].str.match(ASIN_RE, na=False)
    valid_lpn = df[lpn_col].str.len().fillna(0) > 0
    df = df[valid_asin & valid_lpn].reset_index(drop=True)

    return df, asin_col, lpn_col, sheet_name


def _clean(value):
    text = str(value or "").strip()
    return "" if text.lower() in ("nan", "none") else text


def build_shopify_payload(row, asin_col, lpn_col, result):
    asin = row[asin_col]
    lpn = row[lpn_col]

    title_col = _find_column(row.index, "title")
    price_col = _find_column(row.index, "price", "unit retail", "retail price")
    weight_col = _find_column(row.index, "weight")
    condition_col = _find_column(row.index, "condition")
    upc_col = _find_column(row.index, "upc")
    ean_col = _find_column(row.index, "ean")
    sku_col = _find_column(row.index, "sku")

    sheet_title = _clean(row.get(title_col)) if title_col else ""
    title = result.get("title") or sheet_title

    upc = _clean(row.get(upc_col)) if upc_col else ""
    ean = _clean(row.get(ean_col)) if ean_col else ""

    body_html = _build_body_html(
        result.get("bullets") or [],
        result.get("specs") or {},
        None,
        result.get("review_count_value"),
        identifiers={"asin": asin, "upc": upc, "ean": ean},
    )

    weight_raw = _clean(row.get(weight_col)) if weight_col else ""
    weight = None
    if weight_raw:
        try:
            weight = float(weight_raw)
        except ValueError:
            weight = None

    from . import config

    specs = result.get("specs") or {}
    spec_fields = {}
    for key, value in specs.items():
        slot = config.SPECIFICATIONS_KEY_MAP.get(str(key).strip().lower())
        if slot and slot not in spec_fields:
            spec_fields[slot] = value
    spec_fields.setdefault("specifications_weight", weight_raw or None)

    payload = {
        "title": title,
        "body_html": body_html,
        "images": result.get("images") or [],
        "barcode": lpn,
        "price": _clean(row.get(price_col)) if price_col else "",
        "weight": weight,
        "sku": _clean(row.get(sku_col)) if sku_col else "",
        "condition": _clean(row.get(condition_col)) if condition_col else "",
        "rating_count": result.get("review_count_value"),
        "asin": asin,
        "ean": ean,
        "category": result.get("category") or "",
    }
    payload.update(spec_fields)
    return payload
