"""Playwright-driven Amazon product page scraper.

Pulls, per ASIN: title, all gallery images (full-res, not just the thumbnail
strip), the "About this item" bullets, the specifications/product-details
table(s), rating and review count. No price -- that stays whatever is
already in the client's Matrixify sheet.
"""

import html
import json
import os
import random
import re
import time

from playwright.sync_api import TimeoutError as PWTimeout

from . import config
from .config import USER_AGENTS, VIEWPORTS
from .stealth import INIT_SCRIPT

HIRES_RE = re.compile(r'"hiRes":"(https:[^"]+)"')
LARGE_RE = re.compile(r'"large":"(https:[^"]+)"')
# Each gallery entry is normally {"hiRes": "..."|null, "thumb": "...", "large": "...", ...}.
# Some images only have "large" (hiRes is null for them) -- picking hiRes-or-large per
# entry (instead of "all hiRes, or else all large" for the whole gallery) makes sure
# those images aren't dropped just because a *different* image in the same gallery has hiRes.
IMAGE_ENTRY_RE = re.compile(r'"hiRes":(?:"([^"]*)"|null)\s*,\s*"thumb":"[^"]*"\s*,\s*"large":"([^"]+)"')

INTERSTITIAL_SELECTORS = [
    "input[data-action-type='DISMISS']",
    "button:has-text('Continue shopping')",
    "#sp-cc-accept",
    "input#continue",
    "input[name='glowDoneButton']",
    "input[aria-labelledby='GLUXConfirmClose-announce']",
]

BLOCK_MARKERS = [
    "enter the characters you see below",
    "to discuss automated access to amazon data",
]


def create_context(browser, storage_state_path=None):
    state = storage_state_path if storage_state_path and os.path.exists(storage_state_path) else None
    context = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale="en-US",
        timezone_id="America/New_York",
        storage_state=state,
    )
    context.add_init_script(INIT_SCRIPT)
    return context


def save_state(context, storage_state_path):
    if storage_state_path:
        os.makedirs(os.path.dirname(storage_state_path) or ".", exist_ok=True)
        context.storage_state(path=storage_state_path)


def _dedupe(seq):
    seen, out = set(), []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dismiss_interstitials(page):
    for sel in INTERSTITIAL_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=800):
                loc.click(timeout=2000)
                page.wait_for_timeout(400)
        except Exception:
            continue


def _detect_block(page, html):
    lowered = html.lower()
    if any(marker in lowered for marker in BLOCK_MARKERS):
        return True, "captcha_or_bot_check"
    if "validatecaptcha" in page.url.lower():
        return True, "captcha_or_bot_check"
    return False, ""


def _detect_not_found(page, html):
    lowered = html.lower()
    return "couldn't find that page" in lowered or "page not found" in lowered


COLOR_IMAGES_BLOCK_RE = re.compile(r"colorImages.{0,20000}", re.DOTALL)


def _extract_images_from_html(html):
    # Scope the search to the gallery's own data block instead of the whole
    # page -- otherwise "frequently bought together" / sponsored / recommended
    # product widgets elsewhere on the page can leak in their own hiRes
    # entries, mixing in images (and sizes) that don't belong to this product.
    match = COLOR_IMAGES_BLOCK_RE.search(html)
    if not match:
        return []
    block = match.group(0)

    urls = [hires or large for hires, large in IMAGE_ENTRY_RE.findall(block)]
    if not urls:
        # Structure didn't match the expected per-entry pattern -- fall back
        # to the blanket approach rather than returning nothing.
        urls = HIRES_RE.findall(block) or LARGE_RE.findall(block)

    return [u.replace("\\/", "/") for u in urls]


def _extract_images_from_dynamic_attr(page):
    for sel in ["#imgTagWrapperId img", "#landingImage"]:
        try:
            attr = page.locator(sel).first.get_attribute("data-a-dynamic-image")
            if attr:
                return list(json.loads(attr).keys())
        except Exception:
            continue
    return []


def _extract_images_from_thumbnails(page):
    urls = []
    try:
        imgs = page.locator("#altImages li:not(.videoThumbnail):not(.videoBlock) img").all()
        for img in imgs:
            src = img.get_attribute("src")
            if src:
                urls.append(re.sub(r"\._[A-Za-z0-9,_]+_\.", "._AC_SL1500_.", src))
    except Exception:
        pass
    return urls


def _extract_title(page):
    try:
        return page.locator("#productTitle").first.inner_text().strip()
    except Exception:
        return ""


def _expand_see_more(page, container_selector):
    """Amazon hides extra rows/bullets behind a "See more" a-expander toggle
    in several sections. Clicking it (if present) reveals them in the DOM
    before we read inner_text -- otherwise anything hidden is silently
    invisible to a plain text read, not just visually collapsed.
    """
    try:
        expander = page.locator(f"{container_selector} .a-expander-header").first
        if expander.count():
            expander.click(timeout=2000)
            page.wait_for_timeout(300)
    except Exception:
        pass


def _extract_bullets(page):
    _expand_see_more(page, "#feature-bullets")
    try:
        texts = page.locator("#feature-bullets ul li span.a-list-item").all_inner_texts()
    except Exception:
        texts = []
    return [t.strip() for t in texts if t.strip() and "see more" not in t.strip().lower()]


def _extract_specifications(page):
    specs = {}

    _expand_see_more(page, "#productOverview_feature_div")
    try:
        rows = page.locator("#productOverview_feature_div table tr").all()
        for row in rows:
            cells = row.locator("td, th").all_inner_texts()
            if len(cells) >= 2:
                key, val = cells[0].strip(), cells[1].strip()
                if key and val and key not in specs:
                    specs[key] = val
    except Exception:
        pass

    for sel in ["#productDetails_techSpec_section_1 tr", "#productDetails_techSpec_section_2 tr"]:
        try:
            rows = page.locator(sel).all()
            for row in rows:
                key = row.locator("th").first.inner_text().strip()
                val = row.locator("td").first.inner_text().strip()
                if key and val and key not in specs:
                    specs[key] = val
        except Exception:
            continue

    try:
        items = page.locator(
            "#detailBullets_feature_div ul.detail-bullet-list li span.a-list-item"
        ).all_inner_texts()
        for text in items:
            cleaned = text.replace("‏", "").replace("‎", "").strip()
            if ":" in cleaned:
                key, _, val = cleaned.partition(":")
                key, val = key.strip(), val.strip()
                if key and val and key not in specs:
                    specs[key] = val
    except Exception:
        pass

    return specs


def _extract_review_count(page):
    try:
        return page.locator("#acrCustomerReviewText").first.inner_text().strip()
    except Exception:
        return ""


def _extract_category(page):
    try:
        parts = page.locator("#wayfinding-breadcrumbs_feature_div a").all_inner_texts()
        return " > ".join(p.strip() for p in parts if p.strip())
    except Exception:
        return ""


def _parse_review_count_value(review_text):
    """"(948,076)" -> 948076, for the number_integer metafield column."""
    if not review_text:
        return None
    digits = re.sub(r"[^\d]", "", review_text)
    return int(digits) if digits else None


def _build_body_html(bullets, specs, rating, review_count, identifiers=None):
    # Plain <h3>/<ul>/<li>/<p>/<strong> only -- Shopify's rich-text editor (and
    # some themes) silently strip <table>/<details> content even though the
    # wrapper tags themselves can survive, which left the specs section
    # rendering as an empty collapsible arrow with nothing inside. These basic
    # tags are supported everywhere, so the data actually shows up.
    parts = []
    if bullets:
        items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
        parts.append(f"<ul>{items}</ul>")
    if identifiers:
        # ASIN is shown bare (no label) to match the existing Matrixify sheet
        # convention; UPC/EAN get a label since they'd otherwise be ambiguous.
        lines = []
        if identifiers.get("asin"):
            lines.append(html.escape(identifiers["asin"]))
        if identifiers.get("upc"):
            lines.append(f"UPC: {html.escape(identifiers['upc'])}")
        if identifiers.get("ean"):
            lines.append(f"EAN: {html.escape(identifiers['ean'])}")
        if lines:
            parts.append("\n".join(f"<p>{line}</p>" for line in lines))
    if specs:
        spec_items = "".join(
            f"<li><strong>{html.escape(k)}:</strong> {html.escape(v)}</li>"
            for k, v in specs.items()
        )
        parts.append(f"<h3>Specifications</h3><ul>{spec_items}</ul>")
    if rating is not None or review_count is not None:
        rating_items = []
        if rating is not None:
            rating_items.append(f"<li><strong>Average Rating:</strong> {rating} out of 5</li>")
        if review_count is not None:
            rating_items.append(f"<li><strong>Total Ratings:</strong> {review_count:,}</li>")
        parts.append(f"<h3>Rating</h3><ul>{''.join(rating_items)}</ul>")
    return "\n".join(parts)


def fetch_product(context, asin, domain, page_timeout_ms, selector_timeout_ms):
    url = f"https://www.{domain}/dp/{asin}"
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=page_timeout_ms)
        _dismiss_interstitials(page)

        html = page.content()
        blocked, reason = _detect_block(page, html)
        if blocked:
            return {"status": "blocked", "notes": reason, "url": url}

        try:
            page.wait_for_selector("#productTitle", timeout=selector_timeout_ms)
        except PWTimeout:
            html = page.content()
            if _detect_not_found(page, html):
                return {"status": "not_found", "notes": "Product page not found", "url": url}
            return {"status": "error", "notes": "Timed out waiting for product title", "url": url}

        html = page.content()
        images = _extract_images_from_html(html)
        if not images:
            images = _extract_images_from_dynamic_attr(page)
        if not images:
            images = _extract_images_from_thumbnails(page)
        images = _dedupe(images)

        specs = _extract_specifications(page)
        bullets = _extract_bullets(page)
        review_count = _parse_review_count_value(_extract_review_count(page))
        category = _extract_category(page)

        return {
            "status": "ok",
            "notes": "",
            "url": url,
            "title": _extract_title(page),
            "image_src": ";".join(images),
            "image_count": len(images),
            "about_this_item": "\n".join(f"- {b}" for b in bullets),
            "specifications": "\n".join(f"{k}: {v}" for k, v in specs.items()),
            "body_html": _build_body_html(bullets, specs, None, review_count),
            # Raw (non-string-joined) versions, for callers that need to map
            # individual fields (e.g. the direct-to-Shopify metafields) rather
            # than the pre-formatted Matrixify columns above.
            "images": images,
            "bullets": bullets,
            "specs": specs,
            "review_count_value": review_count,
            "category": category,
        }
    finally:
        page.close()


def fetch_with_retries(context, asin, domain):
    """fetch_product with the standard retry/cooldown policy applied.

    Shared by both the CLI (main.py) and the web app (server.py) so the
    two front ends can never drift on how retries/backoff behave.
    """
    result = None
    for attempt in range(1, config.MAX_RETRIES_PER_ASIN + 1):
        try:
            result = fetch_product(
                context, asin, domain, config.PAGE_LOAD_TIMEOUT_MS, config.SELECTOR_TIMEOUT_MS
            )
        except Exception as exc:
            result = {
                "status": "error",
                "notes": str(exc)[:200],
                "url": f"https://www.{domain}/dp/{asin}",
            }

        if result["status"] in ("ok", "not_found"):
            break

        if attempt < config.MAX_RETRIES_PER_ASIN:
            time.sleep(config.BLOCK_COOLDOWN_SECONDS * attempt)

    return result
