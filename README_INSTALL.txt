McMahon Dispatch v1.2.1
Invoice Fix + Suppliers + Documents

INSTALL
1. Close McMahon Dispatch.
2. Back up the McMahonDispatch project folder.
3. Extract this ZIP.
4. Right-click APPLY_PATCH.ps1 and choose "Run with PowerShell".
   If Windows blocks scripts, open PowerShell in the extracted folder and run:
   powershell -ExecutionPolicy Bypass -File .\APPLY_PATCH.ps1
5. Run tests and start the app:
   cd "C:\Users\thedy\OneDrive\Desktop\MJD BUSINESS\McMahonDispatch"
   .\.venv\Scripts\python.exe -m pytest
   .\.venv\Scripts\python.exe -m mcmahon_dispatch

WHAT IT CHANGES
- Fixes InvoicePage _search_debounce initialization order.
- Replaces the Suppliers placeholder with a database-backed supplier directory.
- Replaces the Documents placeholder with a managed document library.
- Uses the existing suppliers, supplier locations, contacts, addresses, documents,
  and document links database tables. No Alembic migration is required.
