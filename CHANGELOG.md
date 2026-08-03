# Changelog

## 0.7.0 - 2026-08-03

- Added production Fleet Management for vehicles, odometer tracking, maintenance, repairs, oil changes, fuel purchases, MPG, insurance and registration expiration, cost per mile, and fleet reports.
- Added responsive vehicle, maintenance, fuel, and report screens.
- Added permission-aware fleet writes and audited fleet changes.
- Added automatic MPG and blended operating-cost calculations.

# McMahon Dispatch v0.6.1 — Navigation Accessibility

## Changed

- Renamed the visible Dispatch tab from **Kanban** to **Job Board**.
- Standardized the customer-facing module label as **Customers**.
- Restored an always-visible navigation toggle in the top-left application bar.
- Added `Ctrl+B` as a keyboard shortcut for showing or hiding navigation.
- Navigation collapse state remains saved between launches.

## Database

No migration is required.

---

# McMahon Dispatch v0.6.0 — Dispatch Center

## Added

- Production Dispatch Center integrated into the main application and sidebar routes.
- Seven-lane Kanban workflow: Scheduled, Picking Up, Waiting, In Transit, Delivered, Completed, and Cancelled.
- Drag-and-drop job status changes with transition validation and confirmation dialogs.
- Day-by-driver, week, and month calendar screens.
- Calendar drag-and-drop rescheduling that preserves time and duration.
- Unassigned and unscheduled job queue.
- Searchable all-jobs table, including Accepted and non-board operational statuses.
- New/edit job screen with schedule, route, order, financial plan, and internal dispatch fields.
- Driver and vehicle assignment screen with availability, overlap, duration, and promised-window conflict checks.
- Driver management and fleet management screens.
- Persistent job status timeline, wait events, assignment history, and audit events.
- Live dispatch metrics and automatic job warnings.
- Responsive header, metrics, detail panel, calendar queue, and horizontal Kanban layouts.

## Operational behavior

- Reassignments retain prior assignment history.
- Waiting starts and stops a persisted wait timer.
- Completed and cancelled jobs release active driver and vehicle resources while retaining the last assignment for history/display.
- Calendar moves detect conflicts and require explicit override approval.
- Status changes enforce the lifecycle rules in MJD-SRS-001 v1.0.

## Database

No new migration is required. The normalized schema already includes all Dispatch Center tables used by this release.

## 0.8.0 - 2026-08-03

- Added complete invoice management with live totals, partial payments, balances, overdue status, manual late fees, searchable invoices and payments, financial reports, professional PDF invoices, email-ready invoice packages, and customer statement PDFs.
