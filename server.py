"""
Local web app for the Amazon -> Matrixify enricher.

A real HTML/CSS/JS frontend (frontend/) backed by this Flask server: upload
a Matrixify export, watch a progress bar while each ASIN is scraped, then
download the enriched sheet once it's done. Any ASIN that fails is reported
in a failures list/log instead of guessing data for it.

Run locally with:
    py server.py
It starts on http://127.0.0.1:5000 and opens that in your default browser.

Because this is a normal Flask app (not a desktop-only wrapper), the exact
same code can later be deployed to a real server -- just run it behind a
proper WSGI server (gunicorn/waitress) instead of the built-in dev server,
and set HOST=0.0.0.0. Nothing about the request/response design has to
change to go from "runs on my PC" to "hosted for the client".
"""

import os
import random
import threading
import time
import uuid
import webbrowser

from flask import Flask, jsonify, request, send_file
from playwright.sync_api import sync_playwright
from werkzeug.utils import secure_filename

import pandas as pd

from amazon_enricher import config, sheets_client, shopify_client
from amazon_enricher.matrixify_io import read_input, write_output
from amazon_enricher.scraper import create_context, fetch_with_retries, save_state
from amazon_enricher.shopify_io import build_shopify_payload, read_direct_input

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(PROJECT_DIR, "uploads")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__, static_folder="frontend", static_url_path="")

JOBS = {}
JOBS_LOCK = threading.Lock()

DIRECT_JOBS = {}
DIRECT_JOBS_LOCK = threading.Lock()

SHEET_JOBS = {}
SHEET_JOBS_LOCK = threading.Lock()


def _new_job(total, output_path, output_filename, original_filename):
    return {
        "running": True,
        "done": False,
        "error": None,
        "current": 0,
        "total": total,
        "items": [],
        "output_path": output_path,
        "output_filename": output_filename,
        "original_filename": original_filename,
        "failures_log_path": None,
        "stop_requested": False,
    }


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/jobs", methods=["POST"])
def create_job():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Choose a Matrixify .xlsx file first."}), 400
    if not upload.filename.lower().endswith(".xlsx"):
        return jsonify({"error": "That's not a .xlsx file. Export from Matrixify as Excel."}), 400

    job_id = uuid.uuid4().hex
    safe_name = secure_filename(upload.filename) or "input.xlsx"
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{safe_name}")
    upload.save(input_path)

    asin_column = (request.form.get("asin_column") or "").strip() or None
    sheet = (request.form.get("sheet") or "").strip() or None

    try:
        df, asin_col, sheet_name = read_input(input_path, sheet=sheet, asin_column=asin_column)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if len(df) == 0:
        return jsonify({"error": "No rows with a valid-looking ASIN were found in that sheet."}), 400

    limit = request.form.get("limit")
    if limit:
        try:
            df = df.head(int(limit))
        except ValueError:
            pass

    base_name = os.path.splitext(safe_name)[0]
    output_filename = f"{base_name}_enriched.xlsx"
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}_{output_filename}")

    options = {
        "domain": (request.form.get("domain") or "").strip() or config.DEFAULT_DOMAIN,
        "min_delay": float(request.form.get("min_delay") or config.DEFAULT_MIN_DELAY),
        "max_delay": float(request.form.get("max_delay") or config.DEFAULT_MAX_DELAY),
        "headed": request.form.get("headed") in ("on", "true", "1"),
        "fresh_session": request.form.get("fresh_session") in ("on", "true", "1"),
    }

    with JOBS_LOCK:
        JOBS[job_id] = _new_job(len(df), output_path, output_filename, upload.filename)

    thread = threading.Thread(
        target=_run_job, args=(job_id, df, asin_col, output_path, options), daemon=True
    )
    thread.start()

    return jsonify(
        {
            "job_id": job_id,
            "total": len(df),
            "asin_column": asin_col,
            "sheet_name": sheet_name,
        }
    )


def _run_job(job_id, df, asin_col, output_path, options):
    results = {}
    storage_state_path = None if options["fresh_session"] else config.STORAGE_STATE_PATH
    browser = None
    context = None

    try:
        with sync_playwright() as p:
            # New-headless-mode Chromium ("chrome-headless-shell") has been seen to
            # hang on browser.close() on some Windows setups. Forcing legacy headless
            # avoids that -- it's the regular chrome.exe binary, just headless.
            launch_args = ["--headless=old"] if not options["headed"] else []
            browser = p.chromium.launch(headless=not options["headed"], args=launch_args)
            context = create_context(browser, storage_state_path)

            asins = df[asin_col].tolist()
            total = len(asins)

            for i, asin in enumerate(asins, start=1):
                with JOBS_LOCK:
                    if JOBS[job_id]["stop_requested"]:
                        break

                result = fetch_with_retries(context, asin, options["domain"])
                results[asin] = result

                write_output(df, asin_col, results, output_path)

                with JOBS_LOCK:
                    JOBS[job_id]["current"] = i
                    JOBS[job_id]["items"].append(
                        {
                            "asin": asin,
                            "status": result["status"],
                            "title": result.get("title", ""),
                            "image_count": result.get("image_count", 0),
                            "notes": result.get("notes", ""),
                        }
                    )

                if i < total:
                    time.sleep(random.uniform(options["min_delay"], options["max_delay"]))

            # Everything scraped so far is already saved to disk (write_output ran
            # after every product). Mark the job done for the user right now --
            # browser teardown below is best-effort and must never block the user
            # from seeing results / downloading, even if it hangs.
            _finish_job(job_id, results, output_path)

            try:
                save_state(context, config.STORAGE_STATE_PATH)
            except Exception:
                pass
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["error"] = str(exc)
        _finish_job(job_id, results, output_path)
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass


def _finish_job(job_id, results, output_path):
    with JOBS_LOCK:
        if JOBS[job_id]["done"]:
            return

    failures = {a: r for a, r in results.items() if r["status"] != "ok"}
    failures_log_path = None
    if failures:
        failures_log_path = output_path.rsplit(".", 1)[0] + "_failures.log"
        with open(failures_log_path, "w", encoding="utf-8") as f:
            for asin, r in failures.items():
                f.write(f"{asin}\t{r['status']}\t{r.get('notes', '')}\t{r.get('url', '')}\n")

    with JOBS_LOCK:
        JOBS[job_id]["running"] = False
        JOBS[job_id]["done"] = True
        JOBS[job_id]["failures_log_path"] = failures_log_path


@app.route("/api/jobs/<job_id>")
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job"}), 404
        return jsonify(
            {
                "running": job["running"],
                "done": job["done"],
                "error": job["error"],
                "current": job["current"],
                "total": job["total"],
                "items": job["items"],
                "has_output": job["done"] and os.path.isfile(job["output_path"]),
                "has_failures": bool(job["failures_log_path"]),
            }
        )


@app.route("/api/jobs/<job_id>/stop", methods=["POST"])
def stop_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job"}), 404
        job["stop_requested"] = True
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>/download")
def download_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or not os.path.isfile(job["output_path"]):
        return jsonify({"error": "No output file for that job yet."}), 404
    return send_file(job["output_path"], as_attachment=True, download_name=job["output_filename"])


@app.route("/api/jobs/<job_id>/failures")
def download_failures(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or not job["failures_log_path"] or not os.path.isfile(job["failures_log_path"]):
        return jsonify({"error": "No failures log for that job."}), 404
    return send_file(job["failures_log_path"], as_attachment=True)


def _new_direct_job(total):
    return {
        "running": True,
        "done": False,
        "error": None,
        "current": 0,
        "total": total,
        "items": [],
        "failures_log_path": None,
        "stop_requested": False,
        "shop_admin_url": None,
    }


@app.route("/api/direct-jobs", methods=["POST"])
def create_direct_job():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Choose an .xlsx file first."}), 400
    if not upload.filename.lower().endswith(".xlsx"):
        return jsonify({"error": "That's not a .xlsx file."}), 400

    job_id = uuid.uuid4().hex
    safe_name = secure_filename(upload.filename) or "input.xlsx"
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{safe_name}")
    upload.save(input_path)

    asin_column = (request.form.get("asin_column") or "").strip() or None
    lpn_column = (request.form.get("lpn_column") or "").strip() or None
    sheet = (request.form.get("sheet") or "").strip() or None

    try:
        df, asin_col, lpn_col, sheet_name = read_direct_input(
            input_path, sheet=sheet, asin_column=asin_column, lpn_column=lpn_column
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if len(df) == 0:
        return jsonify({"error": "No rows with both a valid ASIN and an LPN were found in that sheet."}), 400

    limit = request.form.get("limit")
    if limit:
        try:
            df = df.head(int(limit))
        except ValueError:
            pass

    options = {
        "domain": (request.form.get("domain") or "").strip() or config.DEFAULT_DOMAIN,
        "min_delay": float(request.form.get("min_delay") or config.DEFAULT_MIN_DELAY),
        "max_delay": float(request.form.get("max_delay") or config.DEFAULT_MAX_DELAY),
        "headed": request.form.get("headed") in ("on", "true", "1"),
    }

    with DIRECT_JOBS_LOCK:
        DIRECT_JOBS[job_id] = _new_direct_job(len(df))

    thread = threading.Thread(
        target=_run_direct_job, args=(job_id, df, asin_col, lpn_col, options), daemon=True
    )
    thread.start()

    return jsonify(
        {
            "job_id": job_id,
            "total": len(df),
            "asin_column": asin_col,
            "lpn_column": lpn_col,
            "sheet_name": sheet_name,
        }
    )


def _run_direct_job(job_id, df, asin_col, lpn_col, options):
    results = []
    browser = None
    context = None

    try:
        with sync_playwright() as p:
            launch_args = ["--headless=old"] if not options["headed"] else []
            browser = p.chromium.launch(headless=not options["headed"], args=launch_args)
            context = create_context(browser, config.STORAGE_STATE_PATH)

            asins = df[asin_col].tolist()
            total = len(asins)

            for i, (_, row) in enumerate(df.iterrows(), start=1):
                with DIRECT_JOBS_LOCK:
                    if DIRECT_JOBS[job_id]["stop_requested"]:
                        break

                asin = row[asin_col]
                scrape_result = fetch_with_retries(context, asin, options["domain"])

                item = {"asin": asin, "lpn": row[lpn_col]}
                if scrape_result["status"] != "ok":
                    item.update(status=scrape_result["status"], notes=scrape_result.get("notes", ""))
                else:
                    try:
                        payload = build_shopify_payload(row, asin_col, lpn_col, scrape_result)
                        push_result = shopify_client.push_product(payload)
                        item.update(status=push_result["status"], title=payload["title"])
                    except Exception as exc:
                        item.update(status="error", notes=str(exc)[:200])

                results.append(item)

                with DIRECT_JOBS_LOCK:
                    DIRECT_JOBS[job_id]["current"] = i
                    DIRECT_JOBS[job_id]["items"].append(item)

                if i < total:
                    time.sleep(random.uniform(options["min_delay"], options["max_delay"]))

            _finish_direct_job(job_id, results)

            try:
                save_state(context, config.STORAGE_STATE_PATH)
            except Exception:
                pass
    except Exception as exc:
        with DIRECT_JOBS_LOCK:
            DIRECT_JOBS[job_id]["error"] = str(exc)
        _finish_direct_job(job_id, results)
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass


def _finish_direct_job(job_id, results):
    with DIRECT_JOBS_LOCK:
        if DIRECT_JOBS[job_id]["done"]:
            return

    failures = [r for r in results if r["status"] not in ("created", "updated")]
    failures_log_path = None
    if failures:
        failures_log_path = os.path.join(OUTPUT_DIR, f"{job_id}_direct_failures.log")
        with open(failures_log_path, "w", encoding="utf-8") as f:
            for r in failures:
                f.write(f"{r['asin']}\t{r['lpn']}\t{r['status']}\t{r.get('notes', '')}\n")

    shop = shopify_client.get_shop_domain()

    with DIRECT_JOBS_LOCK:
        DIRECT_JOBS[job_id]["running"] = False
        DIRECT_JOBS[job_id]["done"] = True
        DIRECT_JOBS[job_id]["failures_log_path"] = failures_log_path
        DIRECT_JOBS[job_id]["shop_admin_url"] = f"https://{shop}/admin/products"


@app.route("/api/direct-jobs/<job_id>")
def direct_job_status(job_id):
    with DIRECT_JOBS_LOCK:
        job = DIRECT_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job"}), 404
        return jsonify(
            {
                "running": job["running"],
                "done": job["done"],
                "error": job["error"],
                "current": job["current"],
                "total": job["total"],
                "items": job["items"],
                "has_failures": bool(job["failures_log_path"]),
                "shop_admin_url": job["shop_admin_url"],
            }
        )


@app.route("/api/direct-jobs/<job_id>/stop", methods=["POST"])
def stop_direct_job(job_id):
    with DIRECT_JOBS_LOCK:
        job = DIRECT_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job"}), 404
        job["stop_requested"] = True
    return jsonify({"ok": True})


@app.route("/api/direct-jobs/<job_id>/failures")
def download_direct_failures(job_id):
    with DIRECT_JOBS_LOCK:
        job = DIRECT_JOBS.get(job_id)
    if not job or not job["failures_log_path"] or not os.path.isfile(job["failures_log_path"]):
        return jsonify({"error": "No failures log for that job."}), 404
    return send_file(job["failures_log_path"], as_attachment=True)


def _new_sheet_job(total):
    return {
        "running": True,
        "done": False,
        "error": None,
        "current": 0,
        "total": total,
        "items": [],
        "stop_requested": False,
        "shop_admin_url": None,
    }


@app.route("/api/sheet-jobs", methods=["POST"])
def create_sheet_job():
    payload = request.get_json(silent=True) or {}
    sheet_url = (payload.get("sheet_url") or "").strip()
    if not sheet_url:
        return jsonify({"error": "Paste a Google Sheet link first."}), 400

    worksheet_name = (payload.get("worksheet_name") or "").strip() or None

    try:
        worksheet = sheets_client.open_sheet(sheet_url, worksheet_name)
        pending, status_col, seo_status_col, asin_col_name, lpn_col_name = sheets_client.read_pending_rows(
            worksheet
        )
    except sheets_client.SheetsError as exc:
        return jsonify({"error": str(exc)}), 400

    if not pending:
        return jsonify(
            {"error": "No rows found with Listing checked (or SEO checked) and the matching status still blank."}
        ), 400

    limit = payload.get("limit")
    if limit:
        try:
            pending = pending[: int(limit)]
        except ValueError:
            pass

    options = {
        "domain": (payload.get("domain") or "").strip() or config.DEFAULT_DOMAIN,
        "min_delay": float(payload.get("min_delay") or config.DEFAULT_MIN_DELAY),
        "max_delay": float(payload.get("max_delay") or config.DEFAULT_MAX_DELAY),
        "headed": bool(payload.get("headed")),
    }

    job_id = uuid.uuid4().hex
    with SHEET_JOBS_LOCK:
        SHEET_JOBS[job_id] = _new_sheet_job(len(pending))

    thread = threading.Thread(
        target=_run_sheet_job,
        args=(job_id, worksheet, pending, status_col, seo_status_col, asin_col_name, lpn_col_name, options),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id, "total": len(pending)})


def _run_sheet_job(job_id, worksheet, pending, status_col, seo_status_col, asin_col_name, lpn_col_name, options):
    browser = None
    context = None

    try:
        with sync_playwright() as p:
            launch_args = ["--headless=old"] if not options["headed"] else []
            browser = p.chromium.launch(headless=not options["headed"], args=launch_args)
            context = create_context(browser, config.STORAGE_STATE_PATH)

            total = len(pending)
            for i, entry in enumerate(pending, start=1):
                with SHEET_JOBS_LOCK:
                    if SHEET_JOBS[job_id]["stop_requested"]:
                        break

                row = pd.Series(entry["data"])
                asin = row.get(asin_col_name, "")
                lpn = row.get(lpn_col_name, "")
                sheet_row = entry["sheet_row"]

                item = {"asin": asin, "lpn": lpn}
                scrape_result = fetch_with_retries(context, asin, options["domain"])
                if scrape_result["status"] != "ok":
                    item.update(status=scrape_result["status"], notes=scrape_result.get("notes", ""))
                    status_text = f"Failed: {scrape_result['status']}"
                else:
                    try:
                        product_payload = build_shopify_payload(row, asin_col_name, lpn_col_name, scrape_result)
                        push_result = shopify_client.push_product(product_payload)
                        item.update(status=push_result["status"], title=product_payload["title"])
                        status_text = "Listed" if push_result["status"] == "created" else "Updated"
                    except Exception as exc:
                        item.update(status="error", notes=str(exc)[:200])
                        status_text = f"Failed: {str(exc)[:100]}"

                try:
                    sheets_client.write_status(worksheet, sheet_row, status_col, status_text)
                    if entry["needs_seo"] and seo_status_col:
                        seo_text = "Done" if status_text in ("Listed", "Updated") else status_text
                        sheets_client.write_status(worksheet, sheet_row, seo_status_col, seo_text)
                except Exception:
                    pass  # the Shopify side already succeeded/failed -- don't lose that over a sheet-write hiccup

                with SHEET_JOBS_LOCK:
                    SHEET_JOBS[job_id]["current"] = i
                    SHEET_JOBS[job_id]["items"].append(item)

                if i < total:
                    time.sleep(random.uniform(options["min_delay"], options["max_delay"]))

            _finish_sheet_job(job_id)

            try:
                save_state(context, config.STORAGE_STATE_PATH)
            except Exception:
                pass
    except Exception as exc:
        with SHEET_JOBS_LOCK:
            SHEET_JOBS[job_id]["error"] = str(exc)
        _finish_sheet_job(job_id)
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass


def _finish_sheet_job(job_id):
    shop = shopify_client.get_shop_domain()
    with SHEET_JOBS_LOCK:
        SHEET_JOBS[job_id]["running"] = False
        SHEET_JOBS[job_id]["done"] = True
        SHEET_JOBS[job_id]["shop_admin_url"] = f"https://{shop}/admin/products"


@app.route("/api/sheet-jobs/<job_id>")
def sheet_job_status(job_id):
    with SHEET_JOBS_LOCK:
        job = SHEET_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job"}), 404
        return jsonify(
            {
                "running": job["running"],
                "done": job["done"],
                "error": job["error"],
                "current": job["current"],
                "total": job["total"],
                "items": job["items"],
                "shop_admin_url": job["shop_admin_url"],
            }
        )


@app.route("/api/sheet-jobs/<job_id>/stop", methods=["POST"])
def stop_sheet_job(job_id):
    with SHEET_JOBS_LOCK:
        job = SHEET_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job"}), 404
        job["stop_requested"] = True
    return jsonify({"ok": True})


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))

    if host in ("127.0.0.1", "localhost"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    app.run(host=host, port=port, threaded=True)
