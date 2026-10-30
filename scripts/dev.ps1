# Start the StructuraSense AI backend (:8000) and frontend (:5173) on Windows (PowerShell).
# First run installs dependencies. Close the two windows to stop.
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

if (-not (Test-Path (Join-Path $Backend ".venv\Scripts\python.exe"))) {
  Write-Host "> creating backend virtualenv"
  py -3 -m venv (Join-Path $Backend ".venv")
  & (Join-Path $Backend ".venv\Scripts\python.exe") -m pip install -q --upgrade pip
  & (Join-Path $Backend ".venv\Scripts\python.exe") -m pip install -q -r (Join-Path $Backend "requirements.txt")
}
if (-not (Test-Path (Join-Path $Backend ".env"))) { Copy-Item (Join-Path $Backend ".env.example") (Join-Path $Backend ".env") }
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Write-Host "> installing frontend packages"
  Push-Location $Frontend; npm install --no-audit --no-fund; Pop-Location
}

Write-Host "> backend  http://127.0.0.1:8000  (API docs: /docs)"
Start-Process powershell -WorkingDirectory $Backend -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Write-Host "> frontend http://127.0.0.1:5173"
Start-Process powershell -WorkingDirectory $Frontend -ArgumentList "-NoExit", "-Command", "npx vite --host 127.0.0.1 --port 5173"
