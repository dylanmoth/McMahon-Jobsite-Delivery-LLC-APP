$ErrorActionPreference = "Stop"
$Project = "C:\Users\thedy\OneDrive\Desktop\MJD BUSINESS\McMahonDispatch"
$Python = Join-Path $Project ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "The McMahon Dispatch virtual environment was not found at $Python"
}

& $Python (Join-Path $PSScriptRoot "apply_patch.py") --project $Project
Write-Host ""
Write-Host "Patch installed. Run McMahon Dispatch with:"
Write-Host "& `"$Python`" -m mcmahon_dispatch"
