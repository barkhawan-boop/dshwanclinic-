# Run from an Administrator PowerShell window on the server PC.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Settings = Get-Content -LiteralPath (Join-Path $Root 'settings.json') -Raw | ConvertFrom-Json
$DataDir = Join-Path $Root ([string]$Settings.data_dir)
$NewDb = Join-Path $DataDir 'clinic-replacement.db'
$Db = Join-Path $DataDir 'clinic.db'
$RetiredDb = Join-Path $DataDir 'clinic.db.legacy-retired'
$TaskName = [string]$Settings.startup_task
$Port = [int]$Settings.port

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Open PowerShell as Administrator and run this script again.' }
if (-not (Test-Path -LiteralPath $NewDb)) { throw "Prepared migrated database is missing: $NewDb" }
$python = [string]$Settings.python_executable
if (-not (Test-Path -LiteralPath $python)) { throw "Python executable is missing: $python" }
$check = & $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); t={r[0] for r in c.execute('select name from sqlite_master where type=?',('table',))}; assert {'patients','users','lab_orders','notifications'} <= t; cols={r[1] for r in c.execute('pragma table_info(patients)')}; assert {'code','name','dob','doctor_id'} <= cols; print(c.execute('select count(*) from patients').fetchone()[0])" $NewDb
if ($LASTEXITCODE -ne 0) { throw 'The replacement database does not match the new app schema.' }
Write-Output "Replacement database verified; migrated patient count: $check"

# Disable prior scheduled launchers that point into this app folder, while preserving unrelated tasks.
$rootNeedle = $Root.TrimEnd('\')
$legacyTasks = Get-ScheduledTask | Where-Object {
    $_.TaskName -ne $TaskName -and (($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -join ' ') -like "*$rootNeedle*"
}
foreach ($task in $legacyTasks) {
    Stop-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath | Out-Null
    Write-Output "Disabled legacy startup task: $($task.TaskPath)$($task.TaskName)"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Write-Output "Stopping previous listener PID $($listener.OwningProcess) on port $Port."
    & taskkill.exe /PID $listener.OwningProcess /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Windows would not stop the old server. Run this in the Administrator/SYSTEM context that owns its process.' }
    Start-Sleep -Seconds 2
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is still occupied. Cutover stopped before changing the database." }

if (Test-Path -LiteralPath $RetiredDb) { Remove-Item -LiteralPath $RetiredDb -Force }
if (Test-Path -LiteralPath $Db) { Move-Item -LiteralPath $Db -Destination $RetiredDb }
try {
    Move-Item -LiteralPath $NewDb -Destination $Db
    Remove-Item -LiteralPath "$Db-wal","$Db-shm" -Force -ErrorAction SilentlyContinue
    & (Join-Path $Root 'start-mmc-server.ps1')
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 8 -UseBasicParsing
    if ($response.StatusCode -ne 200 -or $response.Content -notmatch 'OFFLINE SYSTEM|OFFLINE CLINIC|MMC Offline') { throw 'New sign-in page did not pass the local HTTP check.' }
    Write-Output "New MMC Offline Clinic returned HTTP $($response.StatusCode) locally."
    & (Join-Path $Root 'install-server-startup.ps1') -ConfigureFirewall
    Remove-Item -LiteralPath $RetiredDb,(Join-Path $DataDir 'legacy-snapshot.sqlite'),(Join-Path $DataDir 'lan-client-check.log'),(Join-Path $DataDir 'stderr.log'),(Join-Path $DataDir 'stdout.log'),(Join-Path $DataDir 'watch-server-heartbeat.txt'),(Join-Path $DataDir 'server.log') -Force -ErrorAction SilentlyContinue
    Write-Output "Cutover complete. Verify from a separate LAN PC: http://DESKTOP-HD1KKOO:$Port/"
} catch {
    if (Test-Path -LiteralPath $Db) { Remove-Item -LiteralPath $Db -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $RetiredDb) { Move-Item -LiteralPath $RetiredDb -Destination $Db -Force -ErrorAction SilentlyContinue }
    throw "Cutover did not complete; the prior database file was restored where possible. $($_.Exception.Message)"
}
