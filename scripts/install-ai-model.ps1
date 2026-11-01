# Trains the crack CNN from the dataset zip on this laptop and installs it (≈10–20 min, quick mode).
param([Parameter(Position = 0)][string]$Zip = "", [switch]$Full)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Setting up backend\.venv first ..." -ForegroundColor Yellow
  Push-Location $backend; python -m venv .venv; & $py -m pip install -q -r requirements.txt; Pop-Location
}
if (-not $Zip) {
  $places = @("$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop", "$env:USERPROFILE\OneDrive\Desktop", $root)
  $cand = foreach ($d in $places) { if (Test-Path $d) { Get-ChildItem $d -File -Include data.zip, *crack*.zip, 5y9wdsg2zt*.zip -Recurse -Depth 0 -ErrorAction SilentlyContinue } }
  $cand = $cand | Where-Object { $_.Length -gt 50MB } | Sort-Object LastWriteTime -Descending
  if ($cand) { $Zip = $cand[0].FullName }
}
if (-not $Zip) {
  Write-Host "Dataset zip not found. Download 'Concrete Crack Images for Classification' from" -ForegroundColor Red
  Write-Host "https://data.mendeley.com/datasets/5y9wdsg2zt/2 into Downloads, or run:  scripts\install-ai-model.bat C:\path\to\data.zip"
  exit 1
}
Write-Host "Dataset: $Zip" -ForegroundColor Cyan
$limit = if ($Full) { 20000 } else { 3000 }
$epochs = if ($Full) { 8 } else { 6 }
Push-Location $backend
& $py -u -m ml.setup_crack_model --data-dir "$Zip" --limit $limit --epochs $epochs
$code = $LASTEXITCODE
Pop-Location
if ($code -eq 0) { Write-Host "Done. Open Settings > AI model in the app to see it and its test scores." -ForegroundColor Green }
else { Write-Host "Failed - the message above says why." -ForegroundColor Red }
exit $code
