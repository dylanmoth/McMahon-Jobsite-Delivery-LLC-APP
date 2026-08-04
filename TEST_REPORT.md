# McMahon Dispatch v1.2.0 Validation Report

## Completed in the build environment

- Python bytecode compilation completed for `src`, `tests`, and `migrations`.
- 90 non-Qt automated tests passed:
  - 68 database, schema, status, dashboard, customer, pricing, quote, and dispatch tests
  - 14 fleet, invoice, reporting, settings, and formatting tests
  - 8 authentication and user-management tests
- Black formatting completed across the full Python codebase.
- The update archive was checked for excluded local data and cache files.

## Environment limitation

The validation environment does not include PySide6, so Qt widget tests and a full graphical launch could not be performed here. Run the complete test suite and perform Windows interface testing after installing the patch.
