param([switch]$ConfigureFirewall)
$ErrorActionPreference = 'Stop'
$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Settings = Get-Content -LiteralPath (Join-Path $AppRoot 'settings.json') -Raw | ConvertFrom-Json
$TaskName = [string]$Settings.startup_task
$StartScript = Join-Path $AppRoot 'start-mmc-server.ps1'
$DataDir = Join-Path $AppRoot ([string]$Settings.data_dir)

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this installer from an Administrator PowerShell window. It installs an automatic startup task and can add the LAN firewall rule.'
}
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
# SYSTEM owns the at-boot task; grant it code/runtime read access and data write access.
& icacls.exe $AppRoot /grant '*S-1-5-18:(OI)(CI)RX' /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not grant the startup account read access to the app files.' }
& icacls.exe $DataDir /grant '*S-1-5-18:(OI)(CI)M' /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not grant the server startup account access to the data folder.' }
$PythonHome = Split-Path -Parent ([string]$Settings.python_executable)
if (Test-Path -LiteralPath $PythonHome) {
    & icacls.exe $PythonHome /grant '*S-1-5-18:(OI)(CI)RX' /T | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant the startup account access to the configured Python runtime.' }
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`"" -WorkingDirectory $AppRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $taskSettings -Description 'Starts the MMC Offline Clinic Desk after Windows starts.' -Force | Out-Null
if ($ConfigureFirewall) {
    $ruleName = 'MMC Offline Clinic TCP 8000'
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort ([int]$Settings.port) -Profile Private -Description 'Allow clinic LAN clients to connect to MMC Offline Clinic.' | Out-Null
}
Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed startup task '$TaskName'."
if ($ConfigureFirewall) { Write-Output "Allowed TCP $($Settings.port) on Private network profile." }
