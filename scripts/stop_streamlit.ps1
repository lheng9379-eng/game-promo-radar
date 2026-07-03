$ErrorActionPreference = "Stop"
$root = (Resolve-Path ".").Path
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match "streamlit" -and
    $_.CommandLine -match "app.py" -and
    $_.CommandLine -like ("*" + $root + "*")
}

if (-not $targets) {
    Write-Host "No Streamlit process for this project was found."
    exit 0
}

$targets | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host ("Stopped PID=" + $_.ProcessId)
}
