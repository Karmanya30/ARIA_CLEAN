# Starts ARIA if it is not already running, then opens Edge:
#   - API: port 8000, or the next free port if another app (e.g. Bhauly) holds 8000; the port is passed to vite (ARIA_API_PORT)
#   - web: port 5173
#   - with aria://launch-gpu: also the MuseTalk lip-sync server on port 8010 (GPU; the first start takes a few minutes)
# Re-running is safe: whatever is already running (or still starting) is reused, never started twice.
# Called by Launch_ARIA.bat / the aria:// link (see register_launcher.ps1) or directly. The URL argument is ignored except for
# the strings aria://launch and aria://launch-gpu, so a link on any page can only ever start ARIA, nothing else.
# Everything is logged to logs\launch.log (+ api/web/musetalk .out/.err.log). A failure shows a message box.
# Test switches: ARIA_NO_BROWSER=1 (don't open Edge), ARIA_LAUNCH_NOGUI=1 (no message boxes).
param([string]$Url = "aria://launch")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$logFile = Join-Path $logDir "launch.log"
$gpu = $Url -like "aria://launch-gpu*"
$MT_PORT = 8010; $WEB_PORT = 5173
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUNBUFFERED = "1"

function Log($msg, $color = "Gray") {
    Add-Content -Path $logFile -Value ((Get-Date).ToString("yyyy-MM-dd HH:mm:ss", [Globalization.CultureInfo]::InvariantCulture) + " " + $msg) -Encoding UTF8
    Write-Host $msg -ForegroundColor $color
}
function Show-Box($text, $icon = "Error") {
    if ($env:ARIA_LAUNCH_NOGUI) { return }
    try { Add-Type -AssemblyName System.Windows.Forms; [void][System.Windows.Forms.MessageBox]::Show($text, "ARIA launcher", "OK", $icon) } catch { }
}
function Tail($file, $n = 12) { if (Test-Path $file) { (Get-Content $file -Tail $n -ErrorAction SilentlyContinue) -join "`n" } }
function Test-Port($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
function Test-Http($url, $secs = 3) { try { (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec $secs).StatusCode -eq 200 } catch { $false } }
function Get-Json($url, $secs = 3) { try { Invoke-RestMethod $url -UseBasicParsing -TimeoutSec $secs } catch { $null } }
function Test-AriaApi($port) { $j = Get-Json "http://127.0.0.1:$port/openapi.json"; [bool]($j -and $j.info.title -eq "ARIA API") }
function Find-Proc($exe, $rx) { @(Get-CimInstance Win32_Process -Filter "Name='$exe'" | Where-Object { $_.CommandLine -match $rx }) }
function Port-Owner($port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" }
}
function Start-Hidden($file, $argList, $dir, $name) {
    Start-Process -WindowStyle Hidden -FilePath $file -ArgumentList $argList -WorkingDirectory $dir -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "$name.out.log") -RedirectStandardError (Join-Path $logDir "$name.err.log")
}
# Waits until $test is true; stops early if $proc (the process we started) exits. Prints progress every few seconds.
function Wait-Ready($name, [scriptblock]$test, $secs, $proc) {
    $sw = [Diagnostics.Stopwatch]::StartNew(); $shown = -100
    while ($sw.Elapsed.TotalSeconds -lt $secs) {
        if (& $test) { Log ("{0} is ready ({1:N0}s)" -f $name, $sw.Elapsed.TotalSeconds) Green; return $true }
        if ($proc -and $proc.HasExited) { Log "$name exited early (code $($proc.ExitCode))" Red; return $false }
        if ($sw.Elapsed.TotalSeconds - $shown -ge 5) { $shown = $sw.Elapsed.TotalSeconds; Write-Host ("  waiting for {0}... {1:N0}s" -f $name, $shown) -ForegroundColor DarkGray }
        Start-Sleep -Milliseconds 700
    }
    Log "$name not ready after $secs s" Red
    $false
}

$mutex = New-Object System.Threading.Mutex($false, "Local\ARIA_Launcher")
if (-not $mutex.WaitOne(0)) { Log "Another ARIA launcher is already running; it will open ARIA when ready." Yellow; Start-Sleep 3; exit 0 }
try {
    Log "=== launch ($Url) ===" Cyan
    $problems = @()

    # ---- API: reuse an ARIA API (running or still starting), else start one on the first free port from 8000
    $apiProc = $null; $apiPort = $null
    $starting = Find-Proc "python.exe" "uvicorn\s+api\.main:app" | Select-Object -First 1
    if ($starting) { $apiPort = if ($starting.CommandLine -match "--port\s+(\d+)") { [int]$Matches[1] } else { 8000 }; Log "API already running/starting on port $apiPort" }
    if (-not $apiPort) { $apiPort = (8000..8019 | Where-Object { (Test-Port $_) -and (Test-AriaApi $_) } | Select-Object -First 1) }
    if (-not $apiPort) {
        $apiPort = 8000..8019 | Where-Object { -not (Test-Port $_) } | Select-Object -First 1
        if (-not $apiPort) { throw "No free port between 8000 and 8019 for the ARIA API." }
        if ($apiPort -ne 8000) { Log "Port 8000 is used by another app; ARIA API goes on port $apiPort." Yellow }
        Log "Starting API on port $apiPort"
        $apiProc = Start-Hidden $py @("-m", "uvicorn", "api.main:app", "--port", "$apiPort") $root "api"
    }
    $env:ARIA_API_PORT = "$apiPort"   # read by web/vite.config.ts

    # ---- web: reuse ARIA's vite if it is on 5173; refuse if some other app holds 5173
    $webProc = $null
    $vite = @(Find-Proc "node.exe" ("(?i)" + [regex]::Escape($root) + ".*vite|vite.*" + [regex]::Escape($root)))
    if (Test-Port $WEB_PORT) {
        $owner = Port-Owner $WEB_PORT
        if (-not ($vite | Where-Object { $_.ProcessId -eq $owner.ProcessId })) {
            throw "Port $WEB_PORT is used by another app (PID $($owner.ProcessId): $($owner.CommandLine)). Close it and start ARIA again."
        }
        Log "Web already running on port $WEB_PORT"
    } elseif ($vite) { Log "Web is already starting" }
    else {
        Log "Starting web on port $WEB_PORT"
        $webProc = Start-Hidden "cmd.exe" @("/c", "npm run dev -- --port $WEB_PORT --strictPort") (Join-Path $root "web") "web"
    }

    # ---- MuseTalk (GPU lip-sync)
    $mtProc = $null; $mtWanted = $false
    if ($gpu) {
        $mtWanted = $true
        $mtDir = if ($env:MUSETALK_DIR) { $env:MUSETALK_DIR } else { "E:\musetalk\MuseTalk" }
        $health = Get-Json "http://127.0.0.1:$MT_PORT/health"
        if ($health -and $null -ne $health.ready) { Log "MuseTalk already running on port $MT_PORT (ready=$($health.ready))" }
        elseif (Find-Proc "python.exe" "musetalk_server\.py") { Log "MuseTalk is already starting" }
        elseif (Test-Port $MT_PORT) { $problems += "Port $MT_PORT is used by another app, so the lip-sync server cannot start."; $mtWanted = $false }
        else {
            $missing = @("$mtDir\..\env\python.exe", "$mtDir\models\musetalkV15\unet.pth", "$PSScriptRoot\musetalk_server.py", "$root\interface\avatar\face.png") |
                Where-Object { -not (Test-Path $_) }
            if ($missing) { $problems += "Lip-sync server files are missing: " + ($missing -join ", "); $mtWanted = $false }
            else {
                try {
                    $mem = (& nvidia-smi "--query-gpu=memory.used,memory.total" "--format=csv,noheader,nounits" 2>$null | Select-Object -First 1) -split ",\s*"
                    $free = [int]$mem[1] - [int]$mem[0]
                    Log "GPU memory free: $free MiB"
                    if ($free -lt 3000) { Log "Warning: only $free MiB of GPU memory is free (another program is using it); MuseTalk needs about 3 GB." Yellow }
                } catch { Log "Warning: nvidia-smi not available; is the NVIDIA driver installed?" Yellow }
                $os = Get-CimInstance Win32_OperatingSystem   # MuseTalk fails mid-sentence if Windows runs out of memory (commit)
                $freeGb = [math]::Round($os.FreeVirtualMemory / 1MB, 1)
                Log "Windows memory (RAM + page file) free: $freeGb GB"
                if ($freeGb -lt 6) { Log "Warning: Windows memory is nearly full ($freeGb GB free), lip-sync may stop mid-sentence. Close big programs (python jobs such as Bhauly) first." Yellow }
                Log "Starting MuseTalk on port $MT_PORT (first start takes a few minutes: loading models to the GPU)"
                $mtProc = Start-Hidden "cmd.exe" @("/c", "`"$PSScriptRoot\start_musetalk.bat`"") $root "musetalk"
            }
        }
    }

    # ---- wait for everything, then open the browser
    if (-not (Wait-Ready "ARIA API (port $apiPort)" { Test-Http "http://127.0.0.1:$apiPort/api/health" } 180 $apiProc)) {
        throw "The ARIA API did not start.`n`n$(Tail (Join-Path $logDir 'api.err.log'))"
    }
    if (-not (Wait-Ready "web (port $WEB_PORT)" { Test-Http "http://localhost:$WEB_PORT" } 90 $webProc)) {
        throw "The web app did not start.`n`n$(Tail (Join-Path $logDir 'web.err.log'))`n$(Tail (Join-Path $logDir 'web.out.log'))"
    }
    # the web app must proxy to the API port chosen above; an older web server may point at a different port
    if (-not (Test-Http "http://localhost:$WEB_PORT/api/health")) {
        $old = @($vite | Where-Object { $_ })
        if (-not $old) { throw "The web app on port $WEB_PORT cannot reach the API on port $apiPort." }
        Log "Web proxy does not reach the API on port $apiPort; restarting ARIA's web server." Yellow
        $old | ForEach-Object { & taskkill /PID $_.ProcessId /T /F | Out-Null }
        Start-Sleep 2
        $webProc = Start-Hidden "cmd.exe" @("/c", "npm run dev -- --port $WEB_PORT --strictPort") (Join-Path $root "web") "web"
        if (-not (Wait-Ready "web proxy" { Test-Http "http://localhost:$WEB_PORT/api/health" } 60 $webProc)) { throw "The web app cannot reach the API on port $apiPort." }
    }
    if ($mtWanted) {
        $ok = Wait-Ready "MuseTalk lip-sync (port $MT_PORT)" { $h = Get-Json "http://127.0.0.1:$MT_PORT/health" 2; [bool]($h -and $h.ready) } 480 $mtProc
        if (-not $ok) { $problems += "The lip-sync server did not start.`n`n$(Tail (Join-Path $logDir 'musetalk.err.log'))`n(logs\musetalk.err.log)" }
    }

    if (-not $env:ARIA_NO_BROWSER) {
        try { Start-Process "msedge.exe" "http://localhost:$WEB_PORT" } catch { Start-Process "http://localhost:$WEB_PORT" }
    }
    if ($problems) {
        $msg = "ARIA is running at http://localhost:$WEB_PORT, but:`n`n" + ($problems -join "`n`n") + "`n`nARIA uses the standard avatar instead."
        Log $msg Red; Show-Box $msg "Warning"
    } else {
        Log "ARIA is ready: http://localhost:$WEB_PORT (API port $apiPort$(if ($mtWanted) { ", lip-sync on $MT_PORT" }))" Green
        Start-Sleep 3
    }
} catch {
    $msg = "ARIA could not start.`n`n$($_.Exception.Message)`n`nDetails: $logFile"
    Log $msg Red; Show-Box $msg "Error"
    exit 1
} finally {
    $mutex.ReleaseMutex()
}
