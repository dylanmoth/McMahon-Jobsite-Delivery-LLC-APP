# Changelog

## 0.4.2 - 2026-08-03

- Added reversible customer archiving and restoration.
- Added protected customer deletion with linked-record assessment.
- Added customer duplication including profile, contacts, addresses, and preferred suppliers.
- Added customer merge preview and transactional merge of quotes, jobs, invoices, payments, documents, notes, contacts, addresses, and preferred suppliers.
- Added customer-list action toolbar, right-click actions, active/archived/all views, richer search, sortable columns, and archived-row styling.
- Added automated CRM tests for archive, restore, delete, duplicate, and merge workflows.

## 0.2.0 - 2026-08-03

- Replaced the foundation-only schema with the complete normalized operational schema.
- Added Alembic-managed automatic migrations and legacy foundation database preservation.
- Added customers, contacts, addresses, suppliers, drivers, shifts, vehicles, availability,
  quotes, revisions, stops, loads, charges, jobs, dispatch assignments, status events, waiting,
  invoices, invoice lines, payments, allocations, expenses, maintenance, fuel, documents,
  signatures, routing, communications, audit, settings, numbering, sync queue, and conflicts.
- Added production indexes, uniqueness constraints, check constraints, soft deletion, audit
  metadata, optimistic versions, organization isolation, and fixed-precision financial storage.
- Seeded the SRS v1.0 pricing baseline, default roles and permissions, number sequences, expense
  categories, and the unverified 2025 Volkswagen Tiguan profile.
