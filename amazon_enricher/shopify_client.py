"""Minimal Shopify Admin GraphQL client for the "Push to Shopify" direct-listing mode.

Handles exactly what the direct-listing flow needs: find a product by its
LPN (stored in the Barcode field), then create or update it -- title, body
HTML, price/barcode/sku/weight on the default variant, the custom
metafields, and (create only) gallery images.
"""

import json
import mimetypes
import os
import re
import time

import requests

from . import config

GRAPHQL_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3


class ShopifyError(Exception):
    pass


def _load_credentials():
    with open(config.SHOPIFY_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        creds = json.load(f)
    return creds["shop"], creds["access_token"]


def get_shop_domain():
    shop, _ = _load_credentials()
    return shop


def _is_transient(exc):
    """Shopify-side hiccups (server errors, brief outages) worth retrying,
    as opposed to real problems with our request that retrying won't fix."""
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response is not None and exc.response.status_code in (500, 502, 503, 504)
    if isinstance(exc, ShopifyError):
        return "internal error" in str(exc).lower()
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def _graphql(query, variables=None):
    shop, token = _load_credentials()
    url = f"https://{shop}/admin/api/{config.SHOPIFY_API_VERSION}/graphql.json"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                json={"query": query, "variables": variables or {}},
                headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                timeout=GRAPHQL_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                raise ShopifyError(str(data["errors"]))
            return data["data"]
        except (requests.exceptions.RequestException, ShopifyError) as exc:
            if attempt < MAX_RETRIES and _is_transient(exc):
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise


def _check_user_errors(payload, mutation_name):
    errors = payload.get(mutation_name, {}).get("userErrors") or []
    if errors:
        raise ShopifyError(f"{mutation_name}: {errors}")


def find_variant_by_barcode(barcode):
    """Returns (product_gid, variant_gid) for an existing product matching this
    barcode, or (None, None) if nothing matches."""
    escaped = barcode.replace('"', '\\"')
    query = """
    query($search: String!) {
      productVariants(first: 1, query: $search) {
        edges { node { id product { id } } }
      }
    }
    """
    data = _graphql(query, {"search": f'barcode:"{escaped}"'})
    edges = data["productVariants"]["edges"]
    if not edges:
        return None, None
    node = edges[0]["node"]
    return node["product"]["id"], node["id"]


def _seo_input(payload):
    seo = {}
    if payload.get("seo_title"):
        seo["title"] = payload["seo_title"]
    if payload.get("seo_description"):
        seo["description"] = payload["seo_description"]
    return seo or None


def _create_product(payload):
    query = """
    mutation($input: ProductInput!) {
      productCreate(input: $input) {
        product { id variants(first: 1) { edges { node { id } } } }
        userErrors { field message }
      }
    }
    """
    product_input = {
        "title": payload["title"],
        "descriptionHtml": payload["body_html"],
        "status": "DRAFT",
    }
    seo = _seo_input(payload)
    if seo:
        product_input["seo"] = seo
    variables = {"input": product_input}
    data = _graphql(query, variables)
    _check_user_errors(data, "productCreate")
    product = data["productCreate"]["product"]
    variant_id = product["variants"]["edges"][0]["node"]["id"]
    return product["id"], variant_id


def _update_product(product_id, payload):
    query = """
    mutation($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id }
        userErrors { field message }
      }
    }
    """
    product_input = {
        "id": product_id,
        "title": payload["title"],
        "descriptionHtml": payload["body_html"],
    }
    seo = _seo_input(payload)
    if seo:
        product_input["seo"] = seo
    data = _graphql(query, {"input": product_input})
    _check_user_errors(data, "productUpdate")


def _update_variant(product_id, variant_id, payload):
    inventory_item = {}
    if payload.get("sku"):
        inventory_item["sku"] = payload["sku"]
    if payload.get("weight") is not None:
        inventory_item["measurement"] = {
            "weight": {"value": float(payload["weight"]), "unit": "KILOGRAMS"}
        }

    variant_input = {"id": variant_id}
    if payload.get("barcode"):
        variant_input["barcode"] = payload["barcode"]
    if payload.get("price"):
        variant_input["price"] = str(payload["price"])
    if inventory_item:
        variant_input["inventoryItem"] = inventory_item

    if len(variant_input) == 1:
        return  # nothing to set beyond the id

    query = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id }
        userErrors { field message }
      }
    }
    """
    data = _graphql(query, {"productId": product_id, "variants": [variant_input]})
    _check_user_errors(data, "productVariantsBulkUpdate")


def _metafield_value(slot, value):
    if slot == "rating_count":
        return "number_integer", str(int(value))
    # single_line_text_field rejects any value containing a newline -- scraped
    # specs and sheet cells occasionally carry one (e.g. wrapped sheet cells,
    # or an Amazon spec value built from multiple lines), so collapse them.
    text = re.sub(r"\s*\n\s*", " ", str(value)).strip()
    return "single_line_text_field", text


def _set_metafields(product_id, payload):
    metafields = []
    for slot, (namespace, key) in config.SHOPIFY_METAFIELDS.items():
        value = payload.get(slot)
        if value is None or value == "":
            continue
        mtype, mvalue = _metafield_value(slot, value)
        metafields.append(
            {"ownerId": product_id, "namespace": namespace, "key": key, "type": mtype, "value": mvalue}
        )

    if not metafields:
        return

    query = """
    mutation($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields { id }
        userErrors { field message }
      }
    }
    """
    data = _graphql(query, {"metafields": metafields})
    _check_user_errors(data, "metafieldsSet")


def _staged_upload_file(file_path):
    """Uploads a local file to Shopify's staging storage and returns the
    resourceUrl to reference it from productCreateMedia -- needed because
    Shopify fetches image URLs itself and can't reach a file that only
    exists on our own (private) server."""
    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_size = os.path.getsize(file_path)

    query = """
    mutation($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets { url resourceUrl parameters { name value } }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": [
            {
                "filename": filename,
                "mimeType": mime_type,
                "httpMethod": "POST",
                "resource": "IMAGE",
                "fileSize": str(file_size),
            }
        ]
    }
    data = _graphql(query, variables)
    _check_user_errors(data, "stagedUploadsCreate")
    target = data["stagedUploadsCreate"]["stagedTargets"][0]

    form_data = {p["name"]: p["value"] for p in target["parameters"]}
    with open(file_path, "rb") as f:
        resp = requests.post(
            target["url"], data=form_data, files={"file": (filename, f, mime_type)}, timeout=60
        )
    resp.raise_for_status()
    return target["resourceUrl"]


def _add_images(product_id, image_urls, local_image_paths=None):
    media_sources = list(image_urls or [])
    for file_path in local_image_paths or []:
        try:
            media_sources.append(_staged_upload_file(file_path))
        except Exception as exc:
            raise ShopifyError(f"Uploading {file_path}: {exc}")

    if not media_sources:
        return
    media = [{"originalSource": url, "mediaContentType": "IMAGE"} for url in media_sources]
    query = """
    mutation($productId: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $productId, media: $media) {
        media { alt }
        mediaUserErrors { field message }
      }
    }
    """
    data = _graphql(query, {"productId": product_id, "media": media})
    errors = data.get("productCreateMedia", {}).get("mediaUserErrors") or []
    if errors:
        raise ShopifyError(f"productCreateMedia: {errors}")


def push_product(payload):
    """Creates or updates a Shopify product from a payload built by shopify_io.py.

    Matches on payload["barcode"] (the LPN). Returns
    {"status": "created"|"updated", "product_id": "gid://..."}.
    """
    barcode = payload["barcode"]
    existing_product_id, existing_variant_id = find_variant_by_barcode(barcode)

    if existing_product_id:
        _update_product(existing_product_id, payload)
        _update_variant(existing_product_id, existing_variant_id, payload)
        _set_metafields(existing_product_id, payload)
        # local_images (e.g. warehouse photos) are added here too, not just on
        # create -- unlike the Amazon gallery, they don't already exist on the
        # product, so there's nothing to duplicate.
        _add_images(existing_product_id, [], payload.get("local_images") or [])
        return {"status": "updated", "product_id": existing_product_id}

    product_id, variant_id = _create_product(payload)
    _update_variant(product_id, variant_id, payload)
    _set_metafields(product_id, payload)
    _add_images(product_id, payload.get("images") or [], payload.get("local_images") or [])
    return {"status": "created", "product_id": product_id}
