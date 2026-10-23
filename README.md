# MMC Offline Clinic System

Portable local-network clinic workflow application for Mamostayan Medical Complex.

## What is included

- Python 3.11+ web server using only the Python standard library and SQLite.
- Department and staff accounts, PIN sign-in, patient registration, doctor queues, nursing intake, clinician notes and test orders.
- Lab queues, patient-name-checked PDF/Word uploads, results attached to the patient record, and optional copies under `F:\lab test`.
- Prescriptions, medicine stock by barcode/batch/expiry, supplier invoices, pharmacy sales, collection and cash handover reporting, HR records, IT user/department setup.
- English, Arabic and Kurdish navigation controls; blue and gold responsive UI.
- LAN video call signaling with local camera/microphone controls. Browsers generally require HTTPS for camera/microphone from another PC; provide a trusted certificate in settings to enable that.
- Windows launch script and optional at-boot scheduled task / Private-network firewall rule.

## Quick start (Windows server PC)

1. Install Python 3.11 or newer.
2. Put this folder somewhere stable on the server PC. Edit `settings.json` if the Python path, database path, LAN port or lab-share path differs.
3. Run `start-mmc-server.ps1` in PowerShell. It binds to `0.0.0.0:8000`.
4. Open `http://127.0.0.1:8000/` on the server or `http://DESKTOP-HD1KKOO:8000/` on clinic PCs. If the server hostname changes, use the new Windows hostname.
5. Default initial PIN is `1122`; IT PIN is `3344`. Change these in IT administration before live use.
6. For startup after reboot and client access through Windows Firewall, open Administrator PowerShell in this folder and run `./install-server-startup.ps1 -ConfigureFirewall`. Confirm Windows is using the Private network profile.

## Data and backups

SQLite database: `data/clinic.db`. Uploaded reports are stored under `data/uploads/<patient-id>/`. The optional archive copy goes to `F:\lab test\<test folder>`. Back up the database and uploads together while the service is stopped; keep the archive share backed up separately. The source zip intentionally excludes `data/` and all clinical records.

## First launch account list

The app seeds the staff and departments defined in `app.py` on first start. New accounts and departments can be added from the IT administration screen. All seeded non-IT accounts start with PIN `1122`, IT starts with `3344`.

## Settings

`settings.json` contains the server bind address and port, Python executable, database location, archive location, upload limit, session duration, initial PINs, startup task name and optional TLS certificate/key paths. Environment variables `MMC_HOST`, `MMC_PORT`, `MMC_DB_PATH`, `MMC_DATA_DIR`, `MMC_ARCHIVE_DIR`, `MMC_DEFAULT_PIN`, `MMC_ADMIN_PIN`, `MMC_TLS_CERT`, and `MMC_TLS_KEY` can override the matching runtime settings.

## Operational notes

- A server-side HTTP 200 check confirms the server PC response only; verify from a client PC for end-to-end LAN reachability.
- The app is an operational fallback/workflow system, not a validated electronic health record. Review access controls, backups, privacy, medical workflows and local regulatory requirements before using it for real clinical care.
- PINs are stored as PBKDF2 hashes. Session lifetime is configurable. Use a trusted HTTPS certificate for secure cross-PC camera access.
- The app does not synchronize with a cloud database or a second server. Keep one authoritative server/database unless a separately designed replication and conflict-recovery plan is implemented.
