# McMahon Dispatch

McMahon Dispatch is a local-first Windows desktop operations platform for McMahon Jobsite Delivery LLC. Development follows MJD-SRS-001 v1.0 and approved owner decisions.

## Current modules

- Authentication and role permissions
- Dashboard
- Customer CRM
- Quote Builder and quote PDFs
- Dispatch Center v0.6.0
  - Seven-lane Kanban board
  - Day, week, and month calendar views
  - Drag-and-drop status and schedule changes
  - Driver and vehicle assignment with conflict warnings
  - Job, driver, vehicle, wait, assignment, and timeline persistence
  - Responsive laptop and desktop layouts

## Requirements

- Windows 10 or 11
- Python 3.12, 64-bit

## Run without activating PowerShell scripts

```powershell
cd "C:\path\to\McMahonDispatch"
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
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```
