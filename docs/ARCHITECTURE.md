# McMahon Dispatch Architecture

McMahon Dispatch is a local-first PySide6 desktop application organized around clear layers and one-way dependencies.

## Runtime layers

1. **UI (`ui/`)** renders state, validates immediate input, and emits user intent.
2. **Application composition (`application/`)** creates the service container and wires permissions once.
3. **Services (`services/`)** implement use cases, validation, and transaction boundaries.
4. **Repositories (`repositories/`)** isolate SQLAlchemy queries and persistence.
5. **Database (`database/`)** defines normalized models, bootstrap behavior, and local SQLite storage.
6. **Documents (`documents/`)** generate customer-facing PDFs and exports without UI dependencies.
7. **Core (`core/`)** contains configuration, enums, exceptions, and reusable formatting.

The UI never executes SQL. Business logic does not depend on PySide6 widgets. Money is stored as integer cents. Mutable records use UUIDs, UTC timestamps, audit metadata, and optimistic versions.

## Desktop composition

`bootstrap.py` owns process startup, authentication, exception handling, and creation of the main window. `application/services.py` builds a typed `ServiceContainer`, eliminating repeated service construction and keeping permission wiring in one place.

`MainWindow` lazily creates pages when they are first opened. This reduces startup work and avoids loading large tables or reports that the user may not visit during a session.

## Shared UI foundation

Reusable desktop behavior lives in `ui/common/`:

- `PageHeader` and `SectionCard` provide consistent surfaces.
- `DebouncedCall` prevents repeated database searches while a user is typing.
- Table helpers standardize selection, sizing, and bulk updates.
- Model helpers suspend repainting and sorting during large refreshes.

Navigation definitions are centralized in `ui/navigation.py`. Theme logic is centralized in `ui/theme/theme_manager.py`; feature pages do not load stylesheets themselves.

## Responsiveness

Pages use splitters and layout-direction changes instead of hiding essential controls. The application shell keeps navigation recoverable at every supported window size. Customer, invoice, fleet, reporting, and other high-density pages adapt their orientation or card layout at compact widths.

## Approved owner resolutions

- Quote lifecycle uses `Ready to Send`.
- Job lifecycle includes `Quoted`, `On Hold`, `Failed Pickup`, `Failed Delivery`, and `Return`.
- Visible terminology uses **Customers** and **Job Board**.
