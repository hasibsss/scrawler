"""Google Sheets client for the "Google Sheet Sync" mode.

Reads a live Google Sheet, finds rows that need work -- either newly listed
(Listing checked, Status blank) or needing an SEO backfill on a product
that's already listed (SEO checked, SEO Status blank) -- and lets the
caller write a per-row status back after each one is handled, so re-syncing
the same sheet never reprocesses a row that already succeeded or failed.
"""

import re

import gspread
from google.oauth2.service_account import Credentials

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

TRUE_VALUES = {"true", "yes", "1"}


class SheetsError(Exception):
    pass


def _client():
    creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def _extract_sheet_id(url_or_id):
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id)
    return match.group(1) if match else url_or_id.strip()


def _find_header(headers, name):
    for i, h in enumerate(headers):
        if str(h).strip().lower() == name:
            return i  # 0-indexed
    return None


def open_sheet(url_or_id, worksheet_name=None):
    gc = _client()
    sheet_id = _extract_sheet_id(url_or_id)
    try:
        spreadsheet = gc.open_by_key(sheet_id)
    except gspread.exceptions.APIError as exc:
        raise SheetsError(
            f"Couldn't open that sheet -- make sure it's shared with the service "
            f"account's email as an Editor. ({exc})"
        )
    return spreadsheet.worksheet(worksheet_name) if worksheet_name else spreadsheet.sheet1


def _get_or_create_column(worksheet, headers, name):
    idx = _find_header(headers, name.lower())
    if idx is not None:
        return idx
    idx = len(headers)
    if idx >= worksheet.col_count:
        worksheet.add_cols(idx - worksheet.col_count + 1)
    worksheet.update_cell(1, idx + 1, name)
    headers.append(name)
    return idx


def read_pending_rows(worksheet):
    """Returns (pending, status_col, seo_status_col, asin_col_name, lpn_col_name).

    pending is a list of {"sheet_row", "data", "needs_seo"} for every row where
    either (a) Listing is checked and Status is still blank, or (b) SEO is
    checked and SEO Status is still blank -- so a row already listed earlier
    can still be picked up later just to backfill SEO fields, without
    re-triggering off its (already filled-in) main Status.

    seo_status_col is None if the sheet has no "SEO" column at all (the
    feature is opt-in per sheet, not just per row).

    Raises SheetsError if required columns are missing. Creates "Status" (and
    "SEO Status", if a "SEO" column exists) automatically if not present.
    """
    values = worksheet.get_all_values()
    if not values:
        raise SheetsError("That sheet is empty.")

    headers = values[0]
    listing_idx = _find_header(headers, "listing")
    if listing_idx is None:
        raise SheetsError('No "Listing" column found. Add one with checkboxes first.')

    asin_idx = _find_header(headers, "asin")
    if asin_idx is None:
        raise SheetsError('No "ASIN" column found in that sheet.')

    lpn_idx = _find_header(headers, "lpn")
    if lpn_idx is None:
        raise SheetsError('No "LPN" column found in that sheet.')

    status_idx = _get_or_create_column(worksheet, headers, "Status")

    seo_idx = _find_header(headers, "seo")
    seo_status_idx = _get_or_create_column(worksheet, headers, "SEO Status") if seo_idx is not None else None

    def _is_true(row, idx):
        return idx is not None and idx < len(row) and row[idx].strip().lower() in TRUE_VALUES

    def _cell(row, idx):
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    pending = []
    for row_offset, row in enumerate(values[1:], start=2):
        wants_listing = _is_true(row, listing_idx) and not _cell(row, status_idx)
        wants_seo = seo_status_idx is not None and _is_true(row, seo_idx) and not _cell(row, seo_status_idx)
        if not wants_listing and not wants_seo:
            continue
        data = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        pending.append({"sheet_row": row_offset, "data": data, "needs_seo": wants_seo})

    seo_status_col = seo_status_idx + 1 if seo_status_idx is not None else None
    return pending, status_idx + 1, seo_status_col, headers[asin_idx], headers[lpn_idx]


def write_status(worksheet, sheet_row, status_col, text):
    worksheet.update_cell(sheet_row, status_col, text)
