# McMahon Dispatch

McMahon Dispatch is a local-first Windows desktop operations platform for McMahon Jobsite Delivery LLC. It combines customer management, quoting, dispatch, fleet operations, invoicing, reporting, user access, and branded documents in one application.

## Current modules

- Authentication, remembered login, users, roles, permissions, profiles, and audit history
- Dashboard and operational alerts
- Customers, contacts, addresses, notes, suppliers, and account history
- Quote Builder with live pricing, warnings, profitability, call sheets, and quote PDFs
- Dispatch with Job Board, calendars, drag-and-drop status changes, assignments, waiting, and job history
- Fleet with vehicles, mileage, fuel, maintenance, repairs, documents, and cost per mile
- Invoices, partial payments, balances, late fees, statements, and invoice PDFs
- Financial reporting with charts and CSV, Excel, and PDF exports
- Live light/dark appearance and McMahon orange brand variations

## Requirements

- Windows 10 or 11
- Python 3.12 or 3.13, 64-bit

## Install and run

```powershell
cd "C:\path\to\McMahonDispatch"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m mcmahon_dispatch
```

On first launch, the application creates its SQLite database and asks for the first administrator account. Mutable files are stored under `%LOCALAPPDATA%\McMahon Jobsite Delivery LLC\McMahon Dispatch`.

## Project layout

```text
src/mcmahon_dispatch/
  application/   Dependency composition
  core/          Configuration, enums, exceptions, formatting
  database/      SQLAlchemy models and database bootstrap
  documents/     PDF and export writers
  repositories/  Persistence queries
  services/      Business use cases and transactions
  ui/            PySide6 shell, pages, shared widgets, and themes
```

See `docs/ARCHITECTURE.md` and `docs/REFACTORING.md` for design details.

## Quality gates

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m black --check src tests migrations
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```
