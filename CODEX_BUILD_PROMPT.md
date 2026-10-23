# Codex build prompt — MMC Offline Clinic System

Build a portable, LAN-first clinic workflow web application for **Mamostayan Medical Complex (MMC)**. The app is a local fallback used when the main clinic system is unavailable. Optimize for fast page loads on modest office PCs, reliability during clinic hours, understandable workflows, patient privacy and easy migration to another Windows PC.

## Project rules

- Use the existing source design as a visual reference: clean abstract blue backgrounds, dark readable text, restrained gold highlights, responsive rectangular staff tiles and accessible form controls.
- Default language is English. Provide English, Arabic (RTL) and Kurdish language selection.
- Prefer a simple, well-documented architecture with one authoritative SQLite database, parameterized SQL, transactions, foreign keys, audit history, sensible indexes, validation and file size limits. Do not add cloud dependencies or services without explicit approval.
- Store uploaded documents under the patient's record and make a backup copy under the matching test folder on `F:\lab test` when available. Show a clear warning if the archive copy fails while retaining the app copy.
- Before attaching a lab document, verify that its file name includes the patient's full name or permanent patient ID. On mismatch, show exactly: `تکایە دڵنیابەوە لەناوی نەخۆش، ئنجا ئەپلۆدی بکە`.
- Each patient has a permanent unique ID, one profile, patient-only test results and attachment links, chronological visits, nurse preparation, resident-doctor intake, clinician diagnoses/notes, medication prescriptions, and ordered/completed test history.
- Keep permissions role-based: secretariat registers patient to a doctor; secretaries manage their doctor's queue; nurses record pre-visit observations and questions; resident doctors complete a multi-section intake and send it to the doctor; doctors view full clinical notes, diagnose, order tests and prescribe medicines; each lab sees only its department queue and uploads its own result; pharmacy sees prescriptions and manages stock/invoices/sales; accounting sees collections and reconciles end-of-day handovers; HR manages staff notes; IT administrators manage users, roles and departments.
- Seed two Echo labs, two blood-test labs, two TMT labs, radiology, sonar, pharmacy and the initial MMC team. Make adding departments, doctors, secretaries and lab accounts possible without code changes. Assign each doctor a secretary.
- Test orders route only to the correct lab department and include the doctor's test specification. A completed test clears its actionable lab notification. Expose notifications only to the assigned user/department.
- The pharmacy supports barcode-reader input, vendor records, invoice receipts, medicine name, expiry, batch, quantity, buy/sell prices and sales history. A doctor's prescription appears to pharmacy with medicine, quantity and instructions.
- Add staff presence and one-to-one audio/video calls with ringing, accept/reject/end, mute, and camera on/off controls for both callers. Explain that browser camera use from other PCs requires secure HTTPS and a trusted certificate.
- Add reports for patient counts, test counts, collections, pharmacy sales, supplier purchases and cash handovers.
- The home screen clearly says “Mamostayan Medical Complex Offline System” and shows the app's offline/local system status.

## Security and deployment

- PINs must be securely hashed, use CSRF protection for forms, secure cookies where HTTPS is used, escape rendered content, validate roles on the server, enforce upload size/type limits, and log sensitive actions without storing PINs.
- Default initial PINs are 1122 for ordinary seeded users and 3344 for IT, and must be changeable before production use.
- Bind to `0.0.0.0` on port 8000 for the LAN. Preserve the familiar URL `http://DESKTOP-HD1KKOO:8000/` unless the user asks to change it.
- Provide a Windows PowerShell launcher, optional at-boot task installer, Private profile firewall setup, settings file, README, requirements and a clean source archive. Do not package clinical database files, uploaded reports, logs, credentials or patient data in the source archive.
- Back up the SQLite database and uploads together. Do not claim automatic cloud/second-server synchronization unless it is designed, tested and deployed with explicit conflict handling.

## Delivery and validation

Deliver complete source code, configuration, installation/backup instructions and this prompt. Before cutover, inventory and preserve any patient records and attachments that exist in the old system. Start the new app on the configured port only after stopping the old server cleanly. Confirm the sign-in page and stylesheet return HTTP 200 locally and from at least one LAN client when available. State clearly which validations could not be run or which permissions/settings remain blocked. Never claim every LAN client can connect based only on a server-side check.
