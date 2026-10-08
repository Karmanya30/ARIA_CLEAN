# One-time setup: makes the aria://launch link work on this PC (current user only, no admin needed).
# Undo with:  Remove-Item -Recurse HKCU:\Software\Classes\aria
$launcher = Join-Path $PSScriptRoot "aria_launcher.ps1"
$key = "HKCU:\Software\Classes\aria"
New-Item -Path "$key\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path $key -Name "(default)" -Value "URL:ARIA Launcher"
New-ItemProperty -Path $key -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null
Set-ItemProperty -Path "$key\shell\open\command" -Name "(default)" `
    -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`" `"%1`""
Write-Host "Registered aria:// -> $launcher"
Write-Host "Test it:  Start-Process 'aria://launch'"
