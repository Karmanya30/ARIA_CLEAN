# Starts ARIA (API on 8000, web on 5173) if they are not already running, then opens Edge.
# Called by the aria:// link (see register_launcher.ps1) or directly. The URL argument is ignored except for the exact
# strings aria://launch and aria://launch-gpu, so a link on any page can only ever start ARIA, nothing else.
param([string]$Url = "aria://launch")

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONIOENCODING = "utf-8"

function Test-Port($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

if (-not (Test-Port 8000)) {
    Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList "-m", "uvicorn", "api.main:app", "--port", "8000" `
        -WorkingDirectory $root -RedirectStandardOutput (Join-Path $root "api.out.log") -RedirectStandardError (Join-Path $root "api.err.log")
}
if (-not (Test-Port 5173)) {
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev -- --port 5173" -WorkingDirectory (Join-Path $root "web")
}
if ($Url -like "aria://launch-gpu*" -and -not (Test-Port 8010)) {
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", (Join-Path $PSScriptRoot "start_musetalk.bat") -WorkingDirectory $root
}

# wait (up to ~90 s) for the API and the web app, then open the browser
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 -and
            (Invoke-WebRequest "http://localhost:5173" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { break }
    } catch { }
    Start-Sleep -Seconds 2
}
Start-Process "msedge.exe" "http://localhost:5173"
