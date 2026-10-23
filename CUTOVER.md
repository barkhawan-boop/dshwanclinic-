# Server cutover

The new source and migrated database are ready. The old server still owns port 8000 under a Windows context that this Codex session (`desktop-hd1kkoo\codexsandboxoffline`) cannot control. The prior stop attempt returned Access is denied. No live database or startup task was changed.

## Complete the cutover on the server PC

Open **Administrator PowerShell** on the server PC in this folder and run:

```powershell
.\cutover-server.ps1
```

The script checks the prepared SQLite schema, disables older scheduled tasks that launch from this app folder, stops the port 8000 listener, installs the migrated database, starts the new app, checks its sign-in page locally, configures the new at-boot task and Private-network firewall rule, then removes the retired database snapshot and legacy logs after the local check passes.

If Windows still denies stopping the old listener, run the script from the administrator/SYSTEM context that owns the old server task. The script exits before replacing the database when it cannot free port 8000. Once it finishes, verify `http://127.0.0.1:8000/` and test `http://DESKTOP-HD1KKOO:8000/` from a separate LAN PC. A server-PC check alone cannot prove every client can connect.

The source ZIP intentionally excludes the live database and uploaded patient documents. The local `data/clinic-replacement.db` contains the migrated record and accounts for this cutover.
