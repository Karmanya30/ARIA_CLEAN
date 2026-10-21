param([string]$Vae = "half")
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'avatar_engine\.server' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
$env:AVATAR_VAE = $Vae
$p = Start-Process -FilePath "cmd.exe" -ArgumentList '/c','E:\ARIA\scripts\start_avatar_engine.bat' -WindowStyle Hidden -PassThru -RedirectStandardOutput E:\ARIA\logs\avatar_engine.out.log -RedirectStandardError E:\ARIA\logs\avatar_engine.err.log
$p.Id
