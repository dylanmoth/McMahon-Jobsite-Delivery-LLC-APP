# McMahon Dispatch

McMahon Dispatch is a local-first Windows desktop platform for McMahon Jobsite Delivery LLC. It combines customers, quotes, dispatch, fleet operations, invoicing, payments, reporting, users, suppliers, documents, and branded PDFs in one application.

## Supported release

- Version: **1.3.0**
- Windows 10 version 1809 or later, and Windows 11
- 64-bit Windows
- Per-user installation; administrator access is not required
- Application data remains under `%LOCALAPPDATA%\McMahon Jobsite Delivery LLC\McMahon Dispatch`

## Install for employees

1. Download `McMahonDispatch-Setup-1.3.0.exe` from the approved GitHub release.
2. Confirm the publisher is **McMahon Jobsite Delivery LLC** when the installer is digitally signed.
3. Run the installer.
4. Leave **Create a desktop shortcut** selected.
5. Launch McMahon Dispatch and sign in.

Updating or uninstalling the program does not remove the database, customer documents, logs, settings, or backups.

## Developer setup

```powershell
cd "C:\path\to\McMahonDispatch"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mcmahon_dispatch
```

## Build a Windows release

Install:

- Python 3.12 or 3.13, 64-bit
- Inno Setup 6
- Windows SDK `signtool.exe`
- A trusted Authenticode code-signing certificate for public distribution

Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -RequireSigning
```

Artifacts are written to `release\`:

- Windows installer
- Portable ZIP
- SHA-256 checksum files
- Machine-readable release manifest

See:

- `docs/DEPLOYMENT_GUIDE.md`
- `docs/RELEASE_PROCESS.md`
- `docs/AUTOMATIC_UPDATES.md`
- `docs/USER_GUIDE.md`
- `docs/SUPPORT_AND_RECOVERY.md`

## Versioning

McMahon Dispatch follows semantic versioning:

- `MAJOR`: incompatible platform or data-contract changes
- `MINOR`: backward-compatible features
- `PATCH`: backward-compatible fixes

Update the single source version with:

```powershell
.\.venv\Scripts\python.exe scripts\bump_version.py 1.3.1
```

## Updates

Production builds check GitHub Releases at startup at most once every 24 hours. Downloads are accepted only over HTTPS and must match the published SHA-256 checksum before the installer can run. Installation always requires user approval.

## Source layout

```text
src/mcmahon_dispatch/
  application/   Dependency composition
  core/          Configuration, versioning, logging, exceptions
  database/      SQLAlchemy models and Alembic bootstrap
  documents/     PDF writers
  repositories/  Database queries
  services/      Business workflows and update service
  ui/            PySide6 shell, pages, themes, update controller
build/            PyInstaller spec, manifest, version resources
installer/        Inno Setup installer configuration
scripts/          Build, version, and release verification tools
docs/             Deployment, release, user, and support guides
```
