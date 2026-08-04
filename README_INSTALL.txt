McMahon Dispatch v1.3.0 Production Release Patch

INSTALL THE PATCH
1. Close McMahon Dispatch.
2. Back up the full project folder.
3. Extract this ZIP.
4. Open PowerShell in the extracted folder.
5. Run:
   powershell -ExecutionPolicy Bypass -File .\APPLY_PATCH.ps1

TEST THE APPLICATION
cd "C:\Users\thedy\OneDrive\Desktop\MJD BUSINESS\McMahonDispatch"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mcmahon_dispatch

BUILD THE INSTALLER
Install Inno Setup 6 and a trusted Authenticode certificate, then run:
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -RequireSigning

No database migration is included in this patch.
The release installer preserves all local databases, documents, settings, logs, and backups.
