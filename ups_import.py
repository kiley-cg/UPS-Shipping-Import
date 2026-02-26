#!/usr/bin/env python3
"""
UPS Tracking Import
-------------------
Reads today's UPS Excel files from Google Drive (via the Drive API),
groups shipments by Syncore PO number, and adds a Job Log entry to each
job in Syncore.

Runs as a scheduled GitHub Actions workflow — no local machine required.

Setup:
    pip install -r requirements.txt
    # Set GitHub Actions secrets (see README for the full list)
    # Trigger manually: Actions tab → UPS Tracking Import → Run workflow

Local testing:
    cp .env.example .env   # fill in all values including GOOGLE_* vars
    python ups_import.py
"""

import asyncio
import glob
import io
import json
import os
import re
import smtplib
import tempfile
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env vars can be set directly

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SYNCORE_USERNAME = os.environ.get("SYNCORE_USERNAME", "")
SYNCORE_PASSWORD = os.environ.get("SYNCORE_PASSWORD", "")
SYNCORE_WEB_BASE = "https://www.ateasesystems.net"

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CSR_EMAIL = os.environ.get("CSR_EMAIL", "")

# Google Drive — set via GitHub Actions secrets or .env
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# Local fallback path (only used when GOOGLE_SERVICE_ACCOUNT_JSON is not set)
LOCAL_UPS_PATH = os.environ.get(
    "UPS_DRIVE_PATH",
    "/Users/kileygustafson/Library/CloudStorage/"
    "GoogleDrive-kiley@colorgraphicswa.com/Shared drives/UPS Shipping Info",
)

HTTP_TIMEOUT = 30

# Regex: Syncore PO number  e.g. "31987-1", "32073-2"
PO_PATTERN = re.compile(r"^\d{5,6}-\d+$")

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


# ---------------------------------------------------------------------------
# Google Drive file download
# ---------------------------------------------------------------------------

def _drive_service():
    """Build and return an authenticated Google Drive API service object."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download_todays_files(tmp_dir: str) -> list[str]:
    """
    Download today's UPS Excel files from Google Drive to tmp_dir.
    Returns a list of local file paths.

    Falls back to the local filesystem path if GOOGLE_SERVICE_ACCOUNT_JSON
    is not set (useful for local testing with Google Drive synced to disk).
    """
    date_prefix = date.today().strftime("%Y%m%d")  # e.g. 20260225

    # ── Local fallback ────────────────────────────────────────────────────
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        print(f"  [Drive API not configured — using local path: {LOCAL_UPS_PATH}]")
        files: list[str] = []
        for ext in ("xlsx", "xls", "XLSX", "XLS", "csv", "CSV"):
            files.extend(glob.glob(os.path.join(LOCAL_UPS_PATH, f"{date_prefix}*.{ext}")))
        # Deduplicate
        seen: set[str] = set()
        return [f for f in files if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]

    # ── Google Drive API ──────────────────────────────────────────────────
    if not GOOGLE_DRIVE_FOLDER_ID:
        raise RuntimeError(
            "GOOGLE_DRIVE_FOLDER_ID is not set. "
            "Add it as a GitHub Actions secret or to your .env file."
        )

    from googleapiclient.http import MediaIoBaseDownload

    service = _drive_service()

    query = (
        f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents"
        f" and name contains '{date_prefix}'"
        f" and mimeType != 'application/vnd.google-apps.folder'"
        f" and trashed = false"
    )

    response = (
        service.files()
        .list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    drive_files = response.get("files", [])
    excel_files = [
        f for f in drive_files if f["name"].lower().endswith((".xlsx", ".xls", ".csv"))
    ]

    if not excel_files:
        return []

    downloaded: list[str] = []
    for file_info in excel_files:
        dest_path = os.path.join(tmp_dir, file_info["name"])
        request = service.files().get_media(
            fileId=file_info["id"],
            supportsAllDrives=True,
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        with open(dest_path, "wb") as fh:
            fh.write(buffer.getvalue())
        print(f"  Downloaded: {file_info['name']}")
        downloaded.append(dest_path)

    return downloaded


# ---------------------------------------------------------------------------
# Syncore web session helpers
# ---------------------------------------------------------------------------

async def syncore_login(client: httpx.AsyncClient) -> bool:
    """Log in to Syncore and store session cookies in client.

    Returns True on success, False on failure.
    """
    login_url = f"{SYNCORE_WEB_BASE}/Account/Login"
    try:
        resp = await client.get(login_url)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [Syncore] Could not reach login page: {exc}")
        return False

    # Extract the anti-forgery token embedded in the login form
    match = re.search(
        r'<input[^>]+name="__RequestVerificationToken"[^>]+value="([^"]+)"',
        resp.text,
    ) or re.search(
        r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"',
        resp.text,
    )
    if not match:
        print("  [Syncore] Could not find CSRF token on login page")
        return False

    resp = await client.post(
        login_url,
        data={
            "UserName": SYNCORE_USERNAME,
            "Password": SYNCORE_PASSWORD,
            "__RequestVerificationToken": match.group(1),
        },
    )

    final_url = str(resp.url)
    print(f"  [Syncore] Post-login redirect URL: {final_url}")
    if "/Account/Login" in final_url:
        print("  [Syncore] Login failed — check SYNCORE_USERNAME / SYNCORE_PASSWORD")
        return False
    if any(seg in final_url for seg in ("/Account/Two", "/Account/MFA", "/Account/Send", "/Account/Verify")):
        print(
            "  [Syncore] Login blocked by MFA — use a service account with MFA disabled"
        )
        return False

    print("  [Syncore] Logged in successfully")
    return True


async def add_tracker_entry(
    client: httpx.AsyncClient, job_id: int, description: str
) -> None:
    """POST a tracker entry to a Syncore job via the web UI endpoint."""
    resp = await client.post(
        f"{SYNCORE_WEB_BASE}/Job/AddTrackerEntryAsync",
        data={"JobId": job_id, "TextColor": 1, "Description": description},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        raise RuntimeError(
            "Syncore returned HTML instead of JSON — session may have expired or MFA is required"
        )


# ---------------------------------------------------------------------------
# Excel parsing
# ---------------------------------------------------------------------------

def _extract_po(ref1, ref2) -> str | None:
    """Return the first value matching the Syncore PO pattern, or None."""
    for raw in (ref1, ref2):
        val = str(raw or "").strip()
        # Skip Excel scientific notation floats (e.g. "1.4752e+10")
        if PO_PATTERN.match(val):
            return val
    return None


def _parse_csv_file(filepath: str) -> list[dict]:
    """Parse a UPS CSV file. Returns same format as the Excel parser."""
    import csv

    col_tracking = col_neg_charge = col_ref1 = col_ref2 = None

    with open(filepath, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        rows_raw = list(reader)

    # Find header row
    header_row_idx = None
    for i, row in enumerate(rows_raw):
        normalized = [str(c or "").strip().lower() for c in row]
        if "tracking number" in normalized:
            header_row_idx = i
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
    for row in rows_raw[header_row_idx + 1:]:
        if len(row) <= col_tracking:
            continue
        tracking = str(row[col_tracking] or "").strip()
        if not tracking.startswith("1Z"):
            continue

        try:
            ups_cost = float(row[col_neg_charge] or 0)
        except (TypeError, ValueError, IndexError):
            ups_cost = 0.0

        ref1 = row[col_ref1] if col_ref1 < len(row) else None
        ref2 = row[col_ref2] if col_ref2 < len(row) else None
        po_number = _extract_po(ref1, ref2)
        rows.append({"tracking": tracking, "ups_cost": ups_cost, "po_number": po_number})

    return rows


def parse_ups_file(filepath: str) -> list[dict]:
    """
    Parse a UPS Excel or CSV file.  Returns a list of dicts with keys:
        tracking  – UPS tracking number (starts with 1Z)
        ups_cost  – Neg Total Charge (float)
        po_number – Syncore PO number e.g. "31987-1" (str or None)
    """
    if filepath.lower().endswith(".csv"):
        return _parse_csv_file(filepath)

    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl is required. Run: pip install openpyxl")

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

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
            continue

        try:
            ups_cost = float(row[col_neg_charge] or 0)
        except (TypeError, ValueError):
            ups_cost = 0.0

        po_number = _extract_po(row[col_ref1], row[col_ref2])
        rows.append({"tracking": tracking, "ups_cost": ups_cost, "po_number": po_number})

    wb.close()
    return rows


def group_by_po(rows: list[dict]) -> tuple[dict, list[dict]]:
    """
    Group rows by PO number.

    Returns:
        groups  – {po_number: {po_number, job_id, tracking_numbers, total_cost}}
        no_po   – rows where no Syncore PO number was found
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
    """Send a plain-text notification email via Gmail SMTP."""
    if not all([GMAIL_USER, GMAIL_APP_PASSWORD, CSR_EMAIL]):
        print(f"[EMAIL NOT CONFIGURED]\nSubject: {subject}\n{body}\n")
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

async def process_file(filepath: str, client: httpx.AsyncClient) -> dict:
    """
    Parse one UPS Excel file and write tracker entries to Syncore.

    Returns a summary dict: {file, logs_added, manual_entries, errors, skipped_no_po}
    """
    filename = os.path.basename(filepath)
    print(f"\n  [{filename}]")

    result: dict = {
        "file": filename,
        "logs_added": 0,
        "manual_entries": [],  # jobs the CSR must add to Syncore manually
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
            await add_tracker_entry(client, job_id, log_text)
            print(f"      ✓ Tracker entry added")
            result["logs_added"] += 1
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200].strip()
            msg = (
                f"HTTP {exc.response.status_code} for Job #{job_id} (PO {po_number})"
            )
            print(f"      ✗ {msg} — added to manual entry email")
            if detail:
                print(f"        Syncore says: {detail}")
            result["manual_entries"].append({
                "job_id": job_id,
                "po_number": po_number,
                "log_text": log_text,
            })
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

    if not SYNCORE_USERNAME or not SYNCORE_PASSWORD:
        print("\nERROR: SYNCORE_USERNAME and/or SYNCORE_PASSWORD are not set.")
        return

    # Log in to Syncore once; reuse the session for all jobs
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT, follow_redirects=True
    ) as syncore_client:
        logged_in = await syncore_login(syncore_client)
        if not logged_in:
            send_email(
                subject=f"UPS Import Failed — Syncore Login Error ({today_str})",
                body=(
                    "The UPS import could not log in to Syncore.\n\n"
                    "Check that SYNCORE_USERNAME and SYNCORE_PASSWORD are correct."
                ),
            )
            return

        # Download today's files to a temp directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                all_files = download_todays_files(tmp_dir)
            except Exception as exc:
                print(f"\nERROR downloading files from Google Drive: {exc}")
                send_email(
                    subject=f"UPS Import Failed — Drive Error ({today_str})",
                    body=f"The UPS import could not download files from Google Drive:\n\n{exc}",
                )
                return

            if not all_files:
                print(f"\n  No UPS files found for {date.today().strftime('%Y%m%d')}. Nothing to do.")
                return

            print(f"  Files found: {len(all_files)}\n")

            # Split out suboutcorex files
            suboutcorex = [f for f in all_files if "suboutcorex" in os.path.basename(f).lower()]
            processable = [f for f in all_files if "suboutcorex" not in os.path.basename(f).lower()]

            if suboutcorex:
                names = [os.path.basename(f) for f in suboutcorex]
                print(f"  [NOTICE] Skipping {len(suboutcorex)} suboutcorex file(s): {', '.join(names)}")
                send_email(
                    subject=f"UPS Import — Manual Review Required ({today_str})",
                    body=(
                        f"The following UPS file(s) contain 'suboutcorex' in the filename "
                        f"and were NOT automatically imported. Please review them manually:\n\n"
                        + "\n".join(f"  • {n}" for n in names)
                    ),
                )

            if not processable:
                print("  No processable files remaining.")
                return

            all_results = []
            for filepath in processable:
                result = await process_file(filepath, syncore_client)
                all_results.append(result)

    # async with syncore_client and temp directory are both cleaned up here

    total_logs = sum(r["logs_added"] for r in all_results)
    all_manual = [e for r in all_results for e in r["manual_entries"]]
    all_errors = [err for r in all_results for err in r["errors"]]

    print(f"\n{'='*55}")
    print(f"  Job Logs added   : {total_logs}")
    print(f"  Manual entries   : {len(all_manual)}")
    print(f"  Errors           : {len(all_errors)}")
    print(f"{'='*55}\n")

    if all_manual:
        sep = "-" * 48
        blocks = []
        for entry in all_manual:
            blocks.append(
                f"Job #{entry['job_id']} — PO {entry['po_number']}\n"
                f"{sep}\n"
                f"{entry['log_text']}"
            )
        send_email(
            subject=f"UPS Import — Manual Entry Required ({today_str})",
            body=(
                f"The UPS tracking import ran on {today_str}.\n"
                f"The Syncore job log API is currently unavailable, so the "
                f"{len(all_manual)} entry/entries below could not be added automatically.\n\n"
                f"For each job, open it in Syncore and paste the entry into the Job Log tab.\n\n"
                f"{'=' * 48}\n"
                + f"\n\n{'=' * 48}\n".join(blocks)
                + f"\n{'=' * 48}"
            ),
        )

    if all_errors:
        send_email(
            subject=f"UPS Import Errors ({today_str})",
            body=(
                f"The UPS tracking import on {today_str} encountered unexpected errors:\n\n"
                + "\n".join(f"  • {err}" for err in all_errors)
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
