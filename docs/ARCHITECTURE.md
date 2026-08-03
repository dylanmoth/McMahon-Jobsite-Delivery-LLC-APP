# Architecture Decision Baseline

The desktop application is modular, layered, and local-first:

1. PySide6 views render state and emit intent.
2. Application services implement use cases and transaction boundaries.
3. Repositories isolate SQLAlchemy persistence.
4. SQLite stores local source data under Windows Local AppData.
5. Provider adapters and cloud synchronization will remain outside business logic.

The UI does not execute SQL. Money uses integer cents. Mutable records use UUIDs, UTC timestamps, audit metadata, and optimistic versions. Business records are designed for soft deletion.

## Approved owner resolutions
- Quote lifecycle uses `Ready to Send`.
- Job lifecycle includes `Quoted`, `On Hold`, `Failed Pickup`, `Failed Delivery`, and `Return`.
