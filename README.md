# McMahon Dispatch

McMahon Dispatch is a commercial Windows desktop application for McMahon Jobsite Delivery LLC. This repository is a clean implementation based on MJD-SRS-001 v1.0 and approved owner decisions.

## Requirements
- Windows 10/11
- Python 3.12 (64-bit)

## Run without activating PowerShell scripts
```powershell
cd C:\path	o\McMahonDispatch
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m mcmahon_dispatch
```

On first launch, the application creates its SQLite database and asks for the first administrator account. Mutable files are stored under `%LOCALAPPDATA%\McMahon Jobsite Delivery LLC\McMahon Dispatch`.

## Quality gates
```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

## Build
```powershell
powershell -ExecutionPolicy Bypass -File .\scriptsuild_windows.ps1
```
