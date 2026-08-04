$ErrorActionPreference = "Stop"
$Project = "C:\Users\thedy\OneDrive\Desktop\MJD BUSINESS\McMahonDispatch"
$Python = Join-Path $Project ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "The McMahon Dispatch virtual environment was not found at $Python"
}

& $Python (Join-Path $PSScriptRoot "apply_patch.py") --project $Project
if ($LASTEXITCODE -ne 0) { throw "Patch installation failed." }

Set-Location $Project
& $Python -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Dependency refresh failed." }

Write-Host ""
Write-Host "Production release tooling installed." -ForegroundColor Green
Write-Host "Run tests with:"
Write-Host "& `"$Python`" -m pytest"
Write-Host "Build a signed installer with:"
Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -RequireSigning"
