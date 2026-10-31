# Makes the Windows Mosquitto service accept the ESP32 (one broker, on the network, survives reboots).
# Run in PowerShell as Administrator:   powershell -ExecutionPolicy Bypass -File scripts\start-broker.ps1
# Anonymous access is enabled: use it only on your own private Wi-Fi.
$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Please run this in PowerShell opened with 'Run as administrator'." -ForegroundColor Red; exit 1 }

$dir = "C:\Program Files\mosquitto"
if (-not (Test-Path "$dir\mosquitto.exe")) { Write-Host "Mosquitto not found in $dir. Install it from https://mosquitto.org/download/ first." -ForegroundColor Red; exit 1 }
$conf = "$dir\mosquitto.conf"

# 1. stop any broker started by hand (they would hold port 1883)
Get-Process mosquitto -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Stop-Service mosquitto -ErrorAction SilentlyContinue

# 2. listen on all network interfaces (backup the original once)
if (-not (Test-Path "$conf.structurasense-backup")) { Copy-Item $conf "$conf.structurasense-backup" }
$text = Get-Content $conf -Raw
if ($text -notmatch "(?m)^\s*listener\s+1883\s+0\.0\.0\.0") {
  Add-Content $conf "`r`n# added by StructuraSense scripts\start-broker.ps1`r`nlistener 1883 0.0.0.0`r`nallow_anonymous true`r`n"
}

# 3. start the service automatically from now on
Set-Service mosquitto -StartupType Automatic
Start-Service mosquitto

# 4. allow the ESP32 through the firewall (private networks)
if (-not (Get-NetFirewallRule -DisplayName "Mosquitto MQTT 1883" -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName "Mosquitto MQTT 1883" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow -Profile Private | Out-Null
}
$net = (Get-NetConnectionProfile | Select-Object -First 1)
if ($net.NetworkCategory -eq "Public") {
  Write-Host "Your Wi-Fi '$($net.Name)' is set to Public, so the firewall rule does not apply. Set it to Private:" -ForegroundColor Yellow
  Write-Host "  Settings > Network & internet > Wi-Fi > $($net.Name) > Private network"
}

$ips = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }).IPAddress
Write-Host "Mosquitto is running on port 1883 for this computer and the network." -ForegroundColor Green
Write-Host "Put this address in the sketch (MQTT_HOST): $($ips -join ', ')"
Write-Host "Then restart the backend and open Settings > Overview > 'Check connection'."
