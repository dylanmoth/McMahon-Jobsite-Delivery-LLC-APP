# Support and Recovery

## Log location

```text
%LOCALAPPDATA%\McMahon Jobsite Delivery LLC\McMahon Dispatch\Logs
```

When reporting a problem, include:

- application version;
- Windows version;
- steps that caused the issue;
- full traceback or relevant log excerpt;
- whether the issue affects one or all users.

Remove customer-sensitive information before sharing logs externally.

## Application will not start

1. Restart Windows.
2. Launch from the Start menu.
3. Review the newest log file.
4. Confirm the application-data directory is writable.
5. Reinstall the same signed release over the existing installation.

Do not delete the data directory as a troubleshooting step.

## Database recovery

Close the application before copying or restoring SQLite files. Preserve the database file and its `-wal` and `-shm` companions together when present.

Before restoring:

1. Copy the entire current data directory to a dated recovery folder.
2. Restore a verified backup.
3. Start the application and allow migrations to finish.
4. Validate users, customers, invoices, and recent jobs.

## Lost document file

The Documents module retains metadata and the managed storage path. Check the managed documents directory and backups. Do not manually rename managed files while the application is running.

## Update failure

A failed update download does not alter the installed application. Run **Check for Updates** again, or install the signed release manually. If checksum verification fails, do not bypass it; download a fresh release from the approved repository.
