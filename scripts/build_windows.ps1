$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Create .venv with Python 3.12 and install .[dev] before building." }
& $Python -m pytest
& $Python -m ruff check .
& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name "McMahon Dispatch" `
  --icon "src\mcmahon_dispatch\assets\icons\mcmahon_dispatch.ico" `
  --add-data "src\mcmahon_dispatch\ui\theme;mcmahon_dispatch\ui\theme" `
  --add-data "src\mcmahon_dispatch\assets;mcmahon_dispatch\assets" `
  --add-data "migrations;migrations" `
  --add-data "alembic.ini;." `
  "src\mcmahon_dispatch\__main__.py"
Write-Host "Build complete: dist\McMahon Dispatch\McMahon Dispatch.exe"
