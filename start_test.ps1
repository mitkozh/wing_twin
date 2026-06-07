param(
    [switch]$NoMonitor,
    [switch]$NoSubscriber,
    [switch]$Help
)

$ProjectRoot = Split-Path -Parent $PSCommandPath
$MosquittoExe = "C:\Program Files\mosquitto\mosquitto.exe"
$MosquittoConfig = Join-Path $ProjectRoot "mosquitto_project.conf"
$MosquittoLog = Join-Path $ProjectRoot "mosquitto.log"
$BrokerHost = "192.168.4.2"
$BrokerPort = 1884

function Write-Title {
    param([string]$Text)
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host " $Text" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Write-Status {
    param([string]$Text, [string]$Status)
    $color = @{OK="Green"; FAIL="Red"; WARN="Yellow"; SKIP="Gray"}[$Status]
    Write-Host "[$Status] $Text" -ForegroundColor $color
}

if ($Help) {
    Write-Title "Wing Digital Twin - Test Launcher"
    Write-Host "Usage: .\start_test.ps1 [options]"
    Write-Host ""
    Write-Host "Prerequisites:"
    Write-Host "  Connect PC to ESP32 AP 'WingTwin-Demo' (password: wingtwin123)"
    Write-Host "  ESP32 AP: 192.168.4.1, PC gets: 192.168.4.2"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -NoMonitor      Skip ESP32 serial monitor"
    Write-Host "  -NoSubscriber   Skip MQTT subscriber window"
    Write-Host "  -Help           Show this help"
    Write-Host ""
    Write-Host "What it does:"
    Write-Host "  1. Kills stale Mosquitto on port $BrokerPort"
    Write-Host "  2. Starts Mosquitto broker with mosquitto_project.conf"
    Write-Host "  3. Opens MQTT subscriber (wing/#) in new window"
    Write-Host "  4. Opens ESP32 serial monitor (COM3, 115200)"
    Write-Host ""
    Write-Host "Press Q in this window to shut everything down."
    exit
}

Write-Host "=====================================================" -ForegroundColor Yellow
Write-Host " IMPORTANT: Connect PC to WiFi WingTwin-Demo" -ForegroundColor Yellow
Write-Host " (password: wingtwin123) BEFORE running this script" -ForegroundColor Yellow
Write-Host " ESP32 AP IP: 192.168.4.1 -> Mosquitto on 192.168.4.2" -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Yellow

Write-Title "Wing Digital Twin - Starting Test Environment"

# =============================================
# Step 1: Kill stale Mosquitto (port 1884 only)
# =============================================
Write-Title "Step 1/4: Clean up old Mosquitto (port $BrokerPort)"

$existingPid = (netstat -ano | Select-String "0.0.0.0:$BrokerPort" | ForEach-Object { $_ -split '\s+' | Select-Object -Last 1 } | Select-Object -First 1)
if ($existingPid) {
    $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -eq "mosquitto") {
        Write-Status "Killing old Mosquitto (PID $existingPid) on port $BrokerPort" "WARN"
        Stop-Process -Id $existingPid -Force
        Start-Sleep -Seconds 1
        Write-Status "Killed" "OK"
    }
} else {
    Write-Status "No stale Mosquitto on port $BrokerPort" "OK"
}

# =============================================
# Step 2: Start Mosquitto broker
# =============================================
Write-Title "Step 2/4: Starting Mosquitto broker"

if (-not (Test-Path $MosquittoExe)) {
    Write-Status "Mosquitto not found at $MosquittoExe" "FAIL"
    exit 1
}

Write-Host "  Config: $MosquittoConfig" -ForegroundColor Gray
Write-Host "  Listen: $BrokerHost`:$BrokerPort" -ForegroundColor Gray

Start-Process -FilePath $MosquittoExe -ArgumentList "-c `"$MosquittoConfig`" -v" -WindowStyle Hidden
Start-Sleep -Seconds 2

$newPid = (netstat -ano | Select-String "0.0.0.0:$BrokerPort" | ForEach-Object { $_ -split '\s+' | Select-Object -Last 1 } | Select-Object -First 1)
if ($newPid) {
    Write-Status "Mosquitto running (PID $newPid)" "OK"
} else {
    Write-Status "Mosquitto failed to start - check $MosquittoLog" "FAIL"
    exit 1
}

# =============================================
# Step 3: Start MQTT subscriber
# =============================================
if (-not $NoSubscriber) {
    Write-Title "Step 3/4: Opening MQTT subscriber (wing/#)"
    Start-Process -FilePath $MosquittoExe -ArgumentList "sub -h $BrokerHost -p $BrokerPort -t `"wing/#`" -v"
    Write-Status "Subscriber window opened" "OK"
} else {
    Write-Status "MQTT subscriber skipped (-NoSubscriber)" "SKIP"
}

# =============================================
# Step 4: Start ESP32 serial monitor
# =============================================
if (-not $NoMonitor) {
    Write-Title "Step 4/4: Opening ESP32 serial monitor (COM3 115200)"
    $EspDir = Join-Path $ProjectRoot "esp32"
    $PioExe = "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe"
    Start-Process -WindowStyle Normal -FilePath $PioExe -ArgumentList "device monitor --project-dir `"$EspDir`" --port COM3 --baud 115200"
    Write-Status "Serial monitor opened" "OK"
} else {
    Write-Status "Serial monitor skipped (-NoMonitor)" "SKIP"
}

# =============================================
# Done - wait for user
# =============================================
Write-Title "All systems running"
Write-Host "  Mosquitto : $BrokerHost`:$BrokerPort (PID $newPid)"
Write-Host "  Subscribe : wing/# (separate window)"
Write-Host "  Serial    : COM3 @ 115200 baud"
Write-Host ""
Write-Host "  Press Q then Enter to kill Mosquitto and exit."
Write-Host "" -ForegroundColor Green

do {
    $key = Read-Host
} while ($key -ne "q" -and $key -ne "Q")

Write-Title "Shutting down"
Stop-Process -Id $newPid -Force -ErrorAction SilentlyContinue
Write-Status "Mosquitto stopped" "OK"
Write-Status "Goodbye!" "OK"
