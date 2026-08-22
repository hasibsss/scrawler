"""Google Sheets client for the "Google Sheet Sync" mode.

Reads a live Google Sheet, finds rows where the "Listing" checkbox is TRUE
and "Status" is still blank (not yet processed), and lets the caller write a
per-row status back after each one is handled -- so re-syncing the same
sheet never reprocesses a row that already succeeded or failed.
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


def read_pending_rows(worksheet):
    """Returns (pending, status_col, asin_col_name, lpn_col_name).

    pending is a list of {"sheet_row": <1-indexed row number>, "data": {header: value}}
    for every row where Listing is checked and Status is still blank.

    Raises SheetsError if required columns are missing. Creates a "Status"
    column automatically (appended at the end) if one doesn't exist yet.
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

    status_idx = _find_header(headers, "status")
    if status_idx is None:
        status_idx = len(headers)
        if status_idx >= worksheet.col_count:
            worksheet.add_cols(status_idx - worksheet.col_count + 1)
        worksheet.update_cell(1, status_idx + 1, "Status")
        headers.append("Status")

    pending = []
    for row_offset, row in enumerate(values[1:], start=2):
        checked = row[listing_idx].strip().lower() in TRUE_VALUES if listing_idx < len(row) else False
        status = row[status_idx].strip() if status_idx < len(row) else ""
        if not checked or status:
            continue
        data = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        pending.append({"sheet_row": row_offset, "data": data})

    return pending, status_idx + 1, headers[asin_idx], headers[lpn_idx]


def write_status(worksheet, sheet_row, status_col, text):
    worksheet.update_cell(sheet_row, status_col, text)
