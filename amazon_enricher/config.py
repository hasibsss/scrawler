"""Tunable defaults for the scraper. Override most of these from the CLI (see main.py --help)."""

DEFAULT_DOMAIN = "amazon.co.uk"

# Delay between two ASIN requests, seconds (randomized within this range).
DEFAULT_MIN_DELAY = 4.0
DEFAULT_MAX_DELAY = 9.0

# Extra cooldown applied after a CAPTCHA / block is detected, before retrying.
BLOCK_COOLDOWN_SECONDS = 45.0

MAX_RETRIES_PER_ASIN = 3

PAGE_LOAD_TIMEOUT_MS = 30_000
SELECTOR_TIMEOUT_MS = 15_000

# Where the Playwright session (cookies etc.) is persisted between runs so
# Amazon sees a returning browser instead of a fresh one every time.
STORAGE_STATE_PATH = "amazon_enricher/.session_state.json"

# Shopify Admin API credentials for the "Push to Shopify" direct-listing mode.
SHOPIFY_CREDENTIALS_PATH = "amazon_enricher/.shopify_credentials.json"
SHOPIFY_API_VERSION = "2026-01"

# (namespace, key) for each product metafield, as already defined on the store
# (verified against the store's actual metafield definitions -- do not guess new ones).
SHOPIFY_METAFIELDS = {
    "sku": ("custom", "sku"),
    "lpn": ("custom", "lpn"),
    "asin": ("custom", "asin"),
    "ean": ("custom", "ean"),
    "category": ("custom", "category"),
    "condition": ("custom", "condition"),
    "rating_count": ("custom", "rating_count"),
    "specifications_style": ("custom", "specifications_style"),
    "specifications_brand": ("custom", "specifications_brand"),
    "specifications_color": ("custom", "specifications_color"),
    "specifications_material": ("custom", "specifications_material"),
    "specifications_dimensions": ("custom", "specifications_dimensions"),
    "specifications_weight": ("custom", "specifications_weight"),
    "specifications_special_feature": ("custom", "specifications_special_feature"),
}

# Amazon specs-table key (lowercased) -> metafield slot in SHOPIFY_METAFIELDS.
# Direct match only -- if the key isn't here, it's simply not mapped to a metafield
# (it still shows up in the Specifications section of the description).
SPECIFICATIONS_KEY_MAP = {
    "style": "specifications_style",
    "brand": "specifications_brand",
    "colour": "specifications_color",
    "color": "specifications_color",
    "material": "specifications_material",
    "special feature": "specifications_special_feature",
    "special features": "specifications_special_feature",
    "product dimensions": "specifications_dimensions",
    "item dimensions": "specifications_dimensions",
    "item dimensions lxwxh": "specifications_dimensions",
    "package dimensions": "specifications_dimensions",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
]

METAFIELD_ABOUT_THIS_ITEM = "Metafield: amazon.about_this_item [multi_line_text_field]"
METAFIELD_SPECIFICATIONS = "Metafield: amazon.specifications [multi_line_text_field]"

OUTPUT_COLUMNS = [
    # Only real Matrixify columns -- these actually import into Shopify as
    # data. Scrape status / failure info intentionally does NOT live in this
    # sheet -- see the separate "<output>_failures.log" file instead.
    # "Title" is handled separately from this list (see title_col in
    # matrixify_io.py) since, like Body HTML, it must only fill in when
    # blank rather than overwrite an existing value. Rating/review count are
    # folded into Body HTML's own "Rating" section instead of separate columns.
    "Image Src",
    METAFIELD_ABOUT_THIS_ITEM,
    METAFIELD_SPECIFICATIONS,
]
