# Database Architecture

McMahon Dispatch uses SQLAlchemy 2.x declarative models and Alembic migrations. SQLite is the
local source of truth and the schema avoids SQLite-only features so it can be migrated to
PostgreSQL for the cloud service.

## Invariants

- UUID string primary keys and separate human-readable numbers.
- Integer cents for money; fixed-precision numeric values for dimensions, weight, mileage, fuel,
  and hours.
- UTC timestamps.
- Organization scoping on tenant-owned records.
- Created/updated metadata and optimistic integer versions on mutable records.
- Soft deletion for business records where historical preservation is required.
- Historical quote revisions retain pricing and configuration snapshots.
- Foreign keys are enabled on every SQLite connection.
- Alembic upgrades run automatically before seed data and before the UI opens.
- An unversioned v0.1 foundation database is archived before migration and account identity is
  restored into the normalized schema.
