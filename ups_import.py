#!/usr/bin/env python3
"""
UPS Tracking Import
-------------------
Reads today's UPS Excel files from Google Drive, groups shipments by Syncore
PO number, and adds a Job Log entry to each job in Syncore.

Setup:
    pip install -r requirements.txt
    cp .env.example .env        # fill in your values
    python ups_import.py

Schedule (macOS launchd or cron):
    # Run daily at 8 AM:
    # 0 8 * * * cd /path/to/project && python ups_import.py >> ups_import.log 2>&1
"""

import asyncio
import glob
import json
import os
import re
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; can set env vars manually

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables / .env file)
# ---------------------------------------------------------------------------
SYNCORE_API_KEY = os.environ.get("SYNCORE_API_KEY", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CSR_EMAIL = os.environ.get("CSR_EMAIL", "")

UPS_DRIVE_PATH = os.environ.get(
    "UPS_DRIVE_PATH",
    "/Users/kileygustafson/Library/CloudStorage/"
    "GoogleDrive-kiley@colorgraphicswa.com/Shared drives/UPS Shipping Info",
)

API_BASE = "https://api.syncore.app/v2"
HTTP_TIMEOUT = 30

# Regex: Syncore PO number  e.g. "31987-1", "32073-2"
PO_PATTERN = re.compile(r"^\d{5,6}-\d+$")


# ---------------------------------------------------------------------------
# Syncore API helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    return {
        "x-api-key": SYNCORE_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def add_job_log(job_id: int, description: str) -> dict:
    """POST a Job Log entry to a Syncore job."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{API_BASE}/orders/jobs/{job_id}/logs",
            headers=_headers(),
            json={"description": description},
        )
        resp.raise_for_status()
        return resp.json()


async def job_exists(job_id: int) -> bool:
    """Return True if the job ID is found in Syncore (searches last 13 months)."""
    today = date.today()
    date_from = (today - timedelta(days=395)).isoformat()
    date_to = today.isoformat()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # Try a direct lookup first (faster if the API supports it)
        try:
            resp = await client.get(
                f"{API_BASE}/orders/jobs/{job_id}",
                headers=_headers(),
            )
            if resp.status_code == 200:
                return True
        except httpx.HTTPStatusError:
            pass

        # Fall back: search by date range and look for matching ID
        for job_class in ("Dropship", "Store", "Corporate"):
            try:
                resp = await client.get(
                    f"{API_BASE}/orders/jobs",
                    headers=_headers(),
                    params={
                        "date_from": date_from,
                        "date_to": date_to,
                        "job_class": job_class,
                        "count": 25,
                        "page": 1,
                    },
                )
                if resp.status_code == 200:
                    jobs = resp.json().get("jobs", [])
                    if any(j.get("id") == job_id for j in jobs):
                        return True
            except Exception:
                pass

    return False


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_todays_files() -> list[str]:
    """
    Return Excel files in UPS_DRIVE_PATH whose name starts with today's date.
    Tries YYYYMMDD format (e.g. 20260225_UPS_Report.xlsx).
    """
    today = date.today()
    date_prefix = today.strftime("%Y%m%d")  # 20260225

    files: list[str] = []
    for ext in ("*.xlsx", "*.xls", "*.XLSX", "*.XLS"):
        files.extend(glob.glob(os.path.join(UPS_DRIVE_PATH, f"{date_prefix}*{ext[1:]}")))
        files.extend(glob.glob(os.path.join(UPS_DRIVE_PATH, ext)))  # also grab any *.xlsx as fallback

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    # Filter: only files whose basename starts with today's date prefix
    todays = [f for f in unique if os.path.basename(f).startswith(date_prefix)]
    return todays


def is_suboutcorex(filepath: str) -> bool:
    return "suboutcorex" in os.path.basename(filepath).lower()


# ---------------------------------------------------------------------------
# Excel parsing
# ---------------------------------------------------------------------------

def _extract_po(ref1, ref2) -> str | None:
    """Return the first value that matches the Syncore PO pattern, or None."""
    for raw in (ref1, ref2):
        val = str(raw or "").strip()
        # Handle Excel scientific notation floats  e.g. 14752000000.0 → skip
        if PO_PATTERN.match(val):
            return val
    return None


def parse_ups_file(filepath: str) -> list[dict]:
    """
    Parse a UPS Excel file.  Returns a list of dicts with keys:
        tracking  – UPS tracking number (starts with 1Z)
        ups_cost  – Neg Total Charge (float)
        po_number – Syncore PO number e.g. "31987-1" (str or None)
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError(
            "openpyxl is required. Run: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    # Locate header row and column positions
    col_tracking = col_neg_charge = col_ref1 = col_ref2 = None
    header_row_idx = None

    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        normalized = [str(c or "").strip().lower() for c in row]
        if "tracking number" in normalized:
            header_row_idx = row_idx
            col_tracking = normalized.index("tracking number")
            if "neg total charge" in normalized:
                col_neg_charge = normalized.index("neg total charge")
            if "package reference number value 1" in normalized:
                col_ref1 = normalized.index("package reference number value 1")
            if "package reference number value 2" in normalized:
                col_ref2 = normalized.index("package reference number value 2")
            break

    if header_row_idx is None:
        raise ValueError(f"Header row not found in {os.path.basename(filepath)}")

    missing = [
        name
        for name, idx in [
            ("Tracking Number", col_tracking),
            ("Neg Total Charge", col_neg_charge),
            ("Package Reference Number Value 1", col_ref1),
            ("Package Reference Number Value 2", col_ref2),
        ]
        if idx is None
    ]
    if missing:
        raise ValueError(f"Missing columns in {os.path.basename(filepath)}: {missing}")

    rows: list[dict] = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        tracking = str(row[col_tracking] or "").strip()
        if not tracking.startswith("1Z"):
            continue  # Skip blank rows or non-UPS rows

        try:
            ups_cost = float(row[col_neg_charge] or 0)
        except (TypeError, ValueError):
            ups_cost = 0.0

        po_number = _extract_po(row[col_ref1], row[col_ref2])

        rows.append(
            {
                "tracking": tracking,
                "ups_cost": ups_cost,
                "po_number": po_number,
            }
        )

    wb.close()
    return rows


def group_by_po(rows: list[dict]) -> tuple[dict, list[dict]]:
    """
    Group rows by PO number.

    Returns:
        groups   – {po_number: {po_number, job_id, tracking_numbers, total_cost}}
        no_po    – rows where no PO number was found
    """
    groups: dict[str, dict] = {}
    no_po: list[dict] = []

    for row in rows:
        po = row["po_number"]
        if not po:
            no_po.append(row)
            continue

        if po not in groups:
            job_id = int(po.split("-")[0])  # "31987" from "31987-1"
            groups[po] = {
                "po_number": po,
                "job_id": job_id,
                "tracking_numbers": [],
                "total_cost": 0.0,
            }

        groups[po]["tracking_numbers"].append(row["tracking"])
        groups[po]["total_cost"] = round(groups[po]["total_cost"] + row["ups_cost"], 2)

    return groups, no_po


# ---------------------------------------------------------------------------
# Job Log entry formatting
# ---------------------------------------------------------------------------

def build_log_entry(po_number: str, tracking_numbers: list[str], total_cost: float) -> str:
    today_str = date.today().strftime("%m/%d/%Y")
    pkg_count = len(tracking_numbers)
    pkg_label = "package" if pkg_count == 1 else "packages"
    tracking_str = "\n  ".join(tracking_numbers)

    return (
        f"UPS Tracking Import — {today_str}\n"
        f"PO: {po_number}\n"
        f"Packages: {pkg_count} {pkg_label}\n"
        f"Tracking Number(s):\n  {tracking_str}\n"
        f"UPS Shipping Cost: ${total_cost:.2f}"
    )


# ---------------------------------------------------------------------------
# Email notifications
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> None:
    """Send a plain-text email via Gmail SMTP."""
    if not all([GMAIL_USER, GMAIL_APP_PASSWORD, CSR_EMAIL]):
        print(f"[EMAIL NOT CONFIGURED — printing instead]\nSubject: {subject}\n{body}\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = CSR_EMAIL
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, CSR_EMAIL, msg.as_string())
        print(f"  ✉  Email sent to {CSR_EMAIL}: {subject}")
    except Exception as exc:
        print(f"  ✗  Email failed: {exc}")


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

async def process_file(filepath: str) -> dict:
    """
    Parse one UPS Excel file and write Job Log entries to Syncore.

    Returns a summary dict with keys:
        file, logs_added, errors, skipped_no_po
    """
    filename = os.path.basename(filepath)
    print(f"\n  [{filename}]")

    result = {
        "file": filename,
        "logs_added": 0,
        "errors": [],
        "skipped_no_po": [],
    }

    try:
        rows = parse_ups_file(filepath)
    except Exception as exc:
        result["errors"].append(f"Parse error: {exc}")
        return result

    print(f"    Rows found: {len(rows)}")

    groups, no_po = group_by_po(rows)

    if no_po:
        skipped = [r["tracking"] for r in no_po]
        print(f"    Skipped (no PO#): {len(skipped)}")
        result["skipped_no_po"] = skipped

    for po_number, group in sorted(groups.items()):
        job_id = group["job_id"]
        tracking_numbers = group["tracking_numbers"]
        total_cost = group["total_cost"]

        print(
            f"    PO {po_number} → Job #{job_id} | "
            f"{len(tracking_numbers)} pkg(s) | ${total_cost:.2f}"
        )

        log_text = build_log_entry(po_number, tracking_numbers, total_cost)

        try:
            await add_job_log(job_id, log_text)
            print(f"      ✓ Job Log added")
            result["logs_added"] += 1
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                msg = f"Job #{job_id} (PO {po_number}) not found in Syncore — manual entry required"
            else:
                msg = (
                    f"API error for Job #{job_id} (PO {po_number}): "
                    f"HTTP {exc.response.status_code}"
                )
            print(f"      ✗ {msg}")
            result["errors"].append(msg)
        except Exception as exc:
            msg = f"Unexpected error for Job #{job_id} (PO {po_number}): {exc}"
            print(f"      ✗ {msg}")
            result["errors"].append(msg)

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    today_str = date.today().strftime("%Y-%m-%d")
    print(f"{'='*55}")
    print(f"  UPS Tracking Import  —  {today_str}")
    print(f"{'='*55}")
    print(f"  Drive path : {UPS_DRIVE_PATH}")

    # Validate required config
    if not SYNCORE_API_KEY:
        print("\nERROR: SYNCORE_API_KEY is not set. Check your .env file.")
        return

    # Find today's files
    all_files = find_todays_files()
    if not all_files:
        print(f"\n  No UPS files found for {date.today().strftime('%Y%m%d')}. Nothing to do.")
        return

    print(f"  Files found : {len(all_files)}\n")

    # Split suboutcorex files from processable ones
    suboutcorex = [f for f in all_files if is_suboutcorex(f)]
    processable = [f for f in all_files if not is_suboutcorex(f)]

    # Notify CSRs about suboutcorex files
    if suboutcorex:
        names = [os.path.basename(f) for f in suboutcorex]
        print(f"  [NOTICE] Skipping {len(suboutcorex)} suboutcorex file(s): {', '.join(names)}")
        send_email(
            subject=f"UPS Import — Manual Review Required ({today_str})",
            body=(
                f"The following UPS file(s) contain 'suboutcorex' in the filename "
                f"and were NOT automatically imported. Please review them manually:\n\n"
                + "\n".join(f"  • {n}" for n in names)
                + f"\n\nLocation:\n  {UPS_DRIVE_PATH}"
            ),
        )

    if not processable:
        print("  No processable files remaining.")
        return

    # Process each file
    all_results = []
    for filepath in processable:
        result = await process_file(filepath)
        all_results.append(result)

    # Aggregate results
    total_logs = sum(r["logs_added"] for r in all_results)
    all_errors = [err for r in all_results for err in r["errors"]]

    print(f"\n{'='*55}")
    print(f"  Job Logs added : {total_logs}")
    print(f"  Errors         : {len(all_errors)}")
    print(f"{'='*55}\n")

    # Email CSRs if any errors require manual entry
    if all_errors:
        send_email(
            subject=f"UPS Import Errors — Manual Entry Required ({today_str})",
            body=(
                f"The UPS tracking import ran on {today_str} but could not automatically "
                f"add the following entries to Syncore.\n\n"
                f"Please add these manually:\n\n"
                + "\n".join(f"  • {err}" for err in all_errors)
                + "\n\nAll other entries were imported successfully."
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
