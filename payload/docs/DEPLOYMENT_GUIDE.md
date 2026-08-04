# Deployment Guide

## 1. Release prerequisites

Use a clean 64-bit Windows 11 build workstation with:

- Python 3.12 or 3.13
- Inno Setup 6
- Windows SDK signing tools
- Git
- A trusted Authenticode certificate
- Access to the GitHub repository's Releases page

Do not build production releases from an employee workstation that contains live business data.

## 2. Prepare the source tree

```powershell
git status
git pull
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Confirm `git status` is clean and the application version is correct:

```powershell
.\.venv\Scripts\python.exe -c "from mcmahon_dispatch.core.version import __version__; print(__version__)"
```

## 3. Code signing

Set the SHA-1 thumbprint of the code-signing certificate available in the current Windows certificate store:

```powershell
$env:WINDOWS_CERTIFICATE_THUMBPRINT = "CERTIFICATE_THUMBPRINT_WITHOUT_SPACES"
```

The release script signs the main executable and final installer with SHA-256 and a trusted timestamp. Use `-RequireSigning` for every public release. Never publish an unsigned installer as a production release.

## 4. Build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -RequireSigning
```

The build runs tests, linting, formatting validation, PyInstaller, Authenticode signing, Inno Setup, hashing, and manifest generation.

## 5. Verify

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_release.ps1
Get-AuthenticodeSignature ".\release\McMahonDispatch-Setup-<VERSION>.exe"
```

The signature status must be `Valid`.

Perform a clean-machine test in Windows Sandbox or a Windows VM:

1. Install the previous production release.
2. Create non-sensitive test records.
3. Install the new release over it.
4. Confirm the existing database and documents remain.
5. Test login, Customers, Quotes, Dispatch, Fleet, Invoices, Reports, Suppliers, Documents, and Users.
6. Test desktop shortcut creation.
7. Test uninstall and confirm application data remains.
8. Reinstall and confirm the existing test account/data returns.

## 6. Publish to GitHub Releases

Create a tag matching the semantic version, such as `v1.3.0`. Create a non-draft, non-prerelease GitHub Release and upload:

- `McMahonDispatch-Setup-<VERSION>.exe`
- `McMahonDispatch-Setup-<VERSION>.exe.sha256`
- `McMahonDispatch-Portable-<VERSION>.zip`
- `SHA256SUMS.txt`
- `release-manifest.json`

The automatic updater requires the installer and its checksum asset to use those exact names.

## 7. Rollout

For a small internal deployment:

1. Back up the production data directory.
2. Install on one pilot computer.
3. Validate for one business day.
4. Install on remaining computers.
5. Retain the previous signed installer until the new release is accepted.

## 8. Data locations

The installer writes program binaries under:

```text
%LOCALAPPDATA%\Programs\McMahon Dispatch
```

Mutable application data remains under:

```text
%LOCALAPPDATA%\McMahon Jobsite Delivery LLC\McMahon Dispatch
```

Never place the SQLite database inside the installation directory.
