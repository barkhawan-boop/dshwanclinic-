param([switch]$Foreground)
$ErrorActionPreference = 'Stop'
$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $AppRoot
$Settings = Get-Content -LiteralPath (Join-Path $AppRoot 'settings.json') -Raw | ConvertFrom-Json
$DataDir = Join-Path $AppRoot ([string]$Settings.data_dir)
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$pythonPath = [string]$Settings.python_executable
if (-not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath)) {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command py.exe -ErrorAction SilentlyContinue }
    if (-not $python) { throw 'Python 3.11+ was not found. Set python_executable in settings.json or install Python.' }
    $pythonPath = $python.Source
}
$pythonArgs = if ([IO.Path]::GetFileName($pythonPath) -eq 'py.exe') { @('-3', 'app.py') } else { @('app.py') }
$listener = Get-NetTCPConnection -LocalPort ([int]$Settings.port) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($Settings.port)/" -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200 -and $response.Content -match 'MMC Offline|OFFLINE SYSTEM|OFFLINE CLINIC') {
            Write-Output "MMC Offline Clinic is already responding at http://127.0.0.1:$($Settings.port)/."
            exit 0
        }
    } catch { }
    throw "Port $($Settings.port) is occupied by a different service (PID $($listener.OwningProcess)). Stop it before launching this app."
}
if ($Foreground) { & $pythonPath @pythonArgs; exit $LASTEXITCODE }
$outLog = Join-Path $DataDir 'server_stdout.log'
$errLog = Join-Path $DataDir 'server_stderr.log'
$proc = Start-Process -FilePath $pythonPath -ArgumentList $pythonArgs -WorkingDirectory $AppRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Start-Sleep -Seconds 3
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$($Settings.port)/" -TimeoutSec 8 -UseBasicParsing
    if ($response.StatusCode -ne 200 -or $response.Content -notmatch 'OFFLINE SYSTEM|OFFLINE CLINIC|MMC Offline') { throw 'The server did not return the replacement clinic sign-in page.' }
    Write-Output 'MMC Offline Clinic is running.'
    Write-Output 'This PC: http://127.0.0.1:8000/'
    Write-Output 'Clinic LAN: http://DESKTOP-HD1KKOO:8000/'
    Write-Output "Server PID: $($proc.Id)"
} catch {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Get-Content -LiteralPath $errLog -Tail 30 -ErrorAction SilentlyContinue
    throw "MMC Offline Clinic did not start: $($_.Exception.Message)"
}
