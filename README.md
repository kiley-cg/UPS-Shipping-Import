# UPS Tracking Import

Reads today's UPS Excel files from a Google Shared Drive and adds Job Log
entries to the matching Syncore jobs. Runs automatically every weekday via
GitHub Actions — no local machine required.

---

## What it does

1. Downloads today's UPS Excel files from the **UPS Shipping Info** Google
   Shared Drive (files whose name starts with today's date, e.g. `20260225_…`)
2. Skips files with `suboutcorex` in the name and emails the CSR group
3. Parses each file — reads Tracking Number, Neg Total Charge, and PO#
4. Groups shipments by PO number (`NNNNN-N`, e.g. `31987-1`)
5. Adds a **Job Log entry** to the matching Syncore job with:
   - PO number
   - All tracking numbers for that PO
   - Total UPS shipping cost
6. Emails the CSR group if any jobs couldn't be found (manual entry needed)

---

## One-time setup

### Step 1 — Create a Google Cloud Service Account

This is how the script accesses the Google Shared Drive from the cloud.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. **UPS Tracking Import**), or select an existing one
3. In the left menu: **APIs & Services → Library**
   - Search for **Google Drive API** and click **Enable**
4. In the left menu: **APIs & Services → Credentials**
   - Click **Create Credentials → Service account**
   - Name: `ups-tracking-import` → click **Done**
5. Click the new service account email to open it
6. Go to the **Keys** tab → **Add Key → Create new key → JSON** → **Create**
   - A `.json` file downloads — keep it safe, you'll need it in Step 3

### Step 2 — Share the Google Shared Drive with the service account

1. Copy the service account email address (looks like
   `ups-tracking-import@your-project.iam.gserviceaccount.com`)
2. In Google Drive, open the **UPS Shipping Info** shared drive
3. Click the gear icon → **Manage members**
4. Add the service account email as a member with **Viewer** role
5. Click **Send** (no email will actually be sent — it's a bot account)

### Step 3 — Find the Google Drive Folder ID

1. Open the **UPS Shipping Info** shared drive in Google Drive
2. Look at the URL in your browser — it will look like:
   `https://drive.google.com/drive/folders/`**`1aBcDeFgHiJkLmNoPqRsTuV`**
3. Copy the bold part — that's your **Folder ID**

### Step 4 — Add GitHub Actions secrets

Go to your GitHub repo → **Settings → Secrets and variables → Actions →
New repository secret** and add each of these:

| Secret name | Value |
|---|---|
| `SYNCORE_API_KEY` | Your Syncore API key (Settings → API in Syncore) |
| `GMAIL_USER` | Gmail address the script sends FROM (e.g. `kiley@colorgraphicswa.com`) |
| `GMAIL_APP_PASSWORD` | Gmail App Password — generate at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| `CSR_EMAIL` | CSR group email for error/skip notifications |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The **entire contents** of the `.json` key file from Step 1 (copy-paste the whole thing) |
| `GOOGLE_DRIVE_FOLDER_ID` | The folder ID from Step 3 |

---

## Schedule

The workflow runs **weekdays at noon PST (8 PM UTC)**.

To change the time, edit `.github/workflows/ups_import.yml` and update the
`cron` value. [crontab.guru](https://crontab.guru) is a helpful tool for
writing cron expressions. Remember GitHub Actions runs in UTC.

---

## Manual run

Go to your GitHub repo → **Actions** tab → **UPS Tracking Import** →
**Run workflow** → **Run workflow**.

Use this to test after initial setup or to re-run if something failed.

---

## Syncore MCP Server — new tools

`syncore_job_log_tools.py` contains two new MCP tools to add to
`syncore_server.py`:

- `get_job_logs(job_id)` — read Job Log entries for a job
- `add_job_log(job_id, description)` — write a new Job Log entry

Copy those functions into the **JOB LOG** section of `syncore_server.py`.

---

## Local testing (optional)

If you want to test the script locally with Google Drive synced to your Mac,
you can skip the service account and use the local path fallback:

```bash
pip install -r requirements.txt
cp .env.example .env
# Leave GOOGLE_SERVICE_ACCOUNT_JSON blank — the script will use UPS_DRIVE_PATH
python ups_import.py
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `SYNCORE_API_KEY is not set` | Check your GitHub Actions secrets |
| `GOOGLE_DRIVE_FOLDER_ID is not set` | Add the secret in GitHub → Settings → Secrets |
| Files not found in Drive | Confirm the service account was added to the shared drive (Step 2) and the folder ID is correct |
| Job not found (404) | The job number from the PO# doesn't exist in Syncore — CSR will get an email |
| Email not sending | Verify `GMAIL_APP_PASSWORD` is an App Password, not your regular Gmail password |
| No files found today | Confirm UPS files are named starting with `YYYYMMDD` (e.g. `20260225_...`) |
