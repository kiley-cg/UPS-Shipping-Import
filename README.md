# UPS Tracking Import

Automatically reads today's UPS Excel files from Google Drive and adds
Job Log entries to the matching Syncore jobs.

---

## What it does

1. Looks for today's UPS files in the shared Google Drive folder
   (`Shared drives/UPS Shipping Info`)
2. Skips any file with `suboutcorex` in the name and emails the CSR group
3. Parses each file — reads Tracking Number, Neg Total Charge, and PO#
4. Groups shipments by PO number (format: `NNNNN-N`, e.g. `31987-1`)
5. For each PO, adds a **Job Log entry** to the matching Syncore job with:
   - The PO number
   - All tracking numbers for that PO
   - The total UPS shipping cost (Neg Total Charge)
6. Emails the CSR group if any jobs couldn't be found (manual entry required)

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Description |
|---|---|
| `SYNCORE_API_KEY` | Your Syncore API key (Settings → API in Syncore) |
| `GMAIL_USER` | Gmail address the script sends FROM |
| `GMAIL_APP_PASSWORD` | Gmail App Password — generate at myaccount.google.com/apppasswords |
| `CSR_EMAIL` | CSR group email for error/skip notifications |
| `UPS_DRIVE_PATH` | (optional) Override the default Google Drive path |

### 3. Run manually

```bash
python ups_import.py
```

### 4. Schedule daily (macOS)

Add to crontab (`crontab -e`) to run at 8 AM every day:

```
0 8 * * * cd /path/to/project && python ups_import.py >> ~/ups_import.log 2>&1
```

---

## File naming convention

The script looks for files whose name **starts with today's date** in
`YYYYMMDD` format (e.g. `20260225_UPS_Daily.xlsx`).

---

## Syncore MCP Server — new tools

`syncore_job_log_tools.py` contains two new tools to add to `syncore_server.py`:

- `get_job_logs(job_id)` — read Job Log entries for a job
- `add_job_log(job_id, description)` — write a new Job Log entry

Copy the functions from that file into the JOB LOG section of `syncore_server.py`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `openpyxl` not found | `pip install openpyxl` |
| `SYNCORE_API_KEY is not set` | Check your `.env` file |
| Job not found (404) | The job number from the PO# doesn't exist in Syncore — check the PO# in the UPS file |
| Email not sending | Verify `GMAIL_APP_PASSWORD` is an App Password, not your regular Gmail password |
| No files found | Confirm the file name starts with today's date in `YYYYMMDD` format |
