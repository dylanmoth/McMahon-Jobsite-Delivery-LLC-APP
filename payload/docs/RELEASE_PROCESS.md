# Release Process

## Branch and version

1. Merge approved work into `main`.
2. Run all quality gates.
3. Choose a semantic version.
4. Update it with `scripts\bump_version.py`.
5. Commit with `Release vX.Y.Z`.
6. Create an annotated Git tag after validation.

## Required gates

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests migrations
.\.venv\Scripts\python.exe -m black --check src tests migrations
```

Database migrations must be tested against:

- a new database;
- a copy of the previous release database;
- interrupted-upgrade recovery where applicable.

## Release notes

Document:

- customer-visible features;
- bug fixes;
- database or configuration changes;
- known limitations;
- rollback instructions;
- validation performed.

Do not include credentials, customer names, addresses, or production data in release notes or build artifacts.

## Rollback

The application data is backward compatible only when explicitly verified. For a safe rollback:

1. Close McMahon Dispatch.
2. Back up the current application-data directory.
3. Restore the pre-upgrade database backup if the release introduced a migration that is not backward compatible.
4. Install the prior signed installer.
5. Validate login and key records.

## Retention

Retain:

- signed installers and checksums for supported releases;
- release notes and test evidence;
- database migration history;
- source tag and commit SHA;
- certificate/timestamp verification evidence.
