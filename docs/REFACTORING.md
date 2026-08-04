# v1.2.0 Refactoring Notes

This release is an internal-quality and commercial-polish refactor. It preserves existing workflows, database tables, pricing rules, documents, and public service methods.

## Structural changes

- Added a typed application service container for dependency construction.
- Centralized navigation metadata and route mapping.
- Added shared formatting functions for currency, dates, identifiers, and nullable database aggregates.
- Added reusable UI components for headers, cards, debouncing, tables, and model refreshes.
- Reorganized theme behavior around one cached `ThemeManager`.
- Reformatted the complete Python codebase using Black for consistent readability.

## Performance changes

- Feature pages are created lazily rather than all at application startup.
- Search fields use debounced refreshes.
- Table and model refreshes suspend sorting and repainting while rows are replaced.
- Settings writes are skipped when values have not changed.
- Stylesheet files are cached and unchanged themes are not reapplied.

## Responsive behavior

- The shell preserves access to navigation at compact widths.
- Shared page headers stack title text and actions when space is limited.
- Customer, fleet, invoice, and reporting workspaces change layout rather than removing controls.
- Window size is restored within the current screen's available geometry.

## Compatibility

- No database migration is required.
- Existing local settings are preserved and merged with defaults.
- Existing service method names and feature routes remain available.
- Existing PDF, CSV, and Excel exports remain supported.

## Verification

Automated tests cover database bootstrap, statuses, CRM, quote pricing, dispatch, fleet, invoicing, reporting, authentication, user management, settings persistence, and shared formatting. The Qt graphical runtime still requires final Windows verification because the Linux validation environment does not include PySide6.
