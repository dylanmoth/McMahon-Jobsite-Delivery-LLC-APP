from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mcmahon_dispatch.core.enums import InvoiceStatus, JobStatus, QuoteStatus
from mcmahon_dispatch.database.models import (
    AuditEvent,
    Customer,
    Invoice,
    Job,
    JobStatusEvent,
    Quote,
    SyncQueueItem,
)


@dataclass(frozen=True, slots=True)
class TrendPoint:
    day: date
    revenue_cents: int
    profit_cents: int


@dataclass(frozen=True, slots=True)
class RecentCustomerItem:
    customer_id: str
    customer_number: str
    company_name: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationItem:
    severity: str
    title: str
    detail: str
    route: str


@dataclass(frozen=True, slots=True)
class ActivityItem:
    event_type: str
    entity_type: str | None
    occurred_at: datetime
    description: str


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    today_revenue_cents: int
    today_profit_cents: int
    jobs_scheduled: int
    pending_quotes: int
    outstanding_invoice_cents: int
    recent_customers: tuple[RecentCustomerItem, ...]
    trend: tuple[TrendPoint, ...]
    notifications: tuple[NotificationItem, ...]
    recent_activity: tuple[ActivityItem, ...]
    sync_queue_count: int
    generated_at: datetime


class DashboardRepository:
    """Read-only, organization-scoped dashboard queries.

    Dashboard calculations deliberately remain outside the UI so they can be reused by
    reports, the future cloud API, and automated tests.
    """

    _PENDING_QUOTE_STATUSES = {
        QuoteStatus.DRAFT.value,
        QuoteStatus.NEEDS_INFORMATION.value,
        QuoteStatus.RESEARCH_REQUIRED.value,
        QuoteStatus.READY_TO_SEND.value,
        QuoteStatus.SENT.value,
        QuoteStatus.VIEWED.value,
    }
    _UNPAID_INVOICE_STATUSES = {
        InvoiceStatus.ISSUED.value,
        InvoiceStatus.SENT.value,
        InvoiceStatus.VIEWED.value,
        InvoiceStatus.PARTIALLY_PAID.value,
        InvoiceStatus.OVERDUE.value,
    }

    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def snapshot(self, *, trend_days: int = 7) -> DashboardSnapshot:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        completed_job_ids = tuple(
            self.session.scalars(
                select(JobStatusEvent.job_id)
                .where(
                    JobStatusEvent.organization_id == self.organization_id,
                    JobStatusEvent.to_status == JobStatus.COMPLETED.value,
                    JobStatusEvent.occurred_at >= day_start,
                    JobStatusEvent.occurred_at < day_end,
                )
                .distinct()
            )
        )

        today_revenue_cents, today_profit_cents = self._job_financial_totals(completed_job_ids)

        scheduled_at = func.coalesce(Job.promised_pickup_at, Job.requested_window_start)
        jobs_scheduled = int(
            self.session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.organization_id == self.organization_id,
                    scheduled_at >= day_start,
                    scheduled_at < day_end,
                    Job.deleted_at.is_(None),
                    Job.status.not_in(
                        {
                            JobStatus.CANCELLED.value,
                            JobStatus.COMPLETED.value,
                            JobStatus.FAILED_PICKUP.value,
                            JobStatus.FAILED_DELIVERY.value,
                        }
                    ),
                )
            )
            or 0
        )
        pending_quotes = int(
            self.session.scalar(
                select(func.count())
                .select_from(Quote)
                .where(
                    Quote.organization_id == self.organization_id,
                    Quote.status.in_(self._PENDING_QUOTE_STATUSES),
                    Quote.deleted_at.is_(None),
                )
            )
            or 0
        )
        outstanding_invoice_cents = int(
            self.session.scalar(
                select(func.coalesce(func.sum(Invoice.balance_cents), 0)).where(
                    Invoice.organization_id == self.organization_id,
                    Invoice.status.in_(self._UNPAID_INVOICE_STATUSES),
                    Invoice.deleted_at.is_(None),
                )
            )
            or 0
        )
        sync_queue_count = int(
            self.session.scalar(
                select(func.count()).select_from(SyncQueueItem).where(
                    SyncQueueItem.organization_id == self.organization_id,
                    SyncQueueItem.completed_at.is_(None),
                )
            )
            or 0
        )

        return DashboardSnapshot(
            today_revenue_cents=today_revenue_cents,
            today_profit_cents=today_profit_cents,
            jobs_scheduled=jobs_scheduled,
            pending_quotes=pending_quotes,
            outstanding_invoice_cents=outstanding_invoice_cents,
            recent_customers=self._recent_customers(),
            trend=self._trend(now, trend_days),
            notifications=self._notifications(now, sync_queue_count),
            recent_activity=self._recent_activity(),
            sync_queue_count=sync_queue_count,
            generated_at=now,
        )

    def _job_financial_totals(self, job_ids: Iterable[str]) -> tuple[int, int]:
        ids = tuple(job_ids)
        if not ids:
            return 0, 0
        row = self.session.execute(
            select(
                func.coalesce(func.sum(Job.actual_revenue_cents), 0),
                func.coalesce(func.sum(Job.actual_profit_cents), 0),
            ).where(
                Job.organization_id == self.organization_id,
                Job.id.in_(ids),
                Job.deleted_at.is_(None),
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    def _trend(self, now: datetime, trend_days: int) -> tuple[TrendPoint, ...]:
        days = max(7, min(trend_days, 31))
        first_day = now.date() - timedelta(days=days - 1)
        start = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
        events = self.session.execute(
            select(
                JobStatusEvent.job_id,
                JobStatusEvent.occurred_at,
                Job.actual_revenue_cents,
                Job.actual_profit_cents,
            )
            .join(Job, Job.id == JobStatusEvent.job_id)
            .where(
                JobStatusEvent.organization_id == self.organization_id,
                Job.organization_id == self.organization_id,
                JobStatusEvent.to_status == JobStatus.COMPLETED.value,
                JobStatusEvent.occurred_at >= start,
                Job.deleted_at.is_(None),
            )
            .order_by(JobStatusEvent.occurred_at.asc())
        ).all()

        totals: dict[date, list[int]] = {
            first_day + timedelta(days=index): [0, 0] for index in range(days)
        }
        seen_jobs: set[str] = set()
        for job_id, occurred_at, revenue_cents, profit_cents in events:
            if job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)
            event_day = occurred_at.date()
            if event_day in totals:
                totals[event_day][0] += int(revenue_cents or 0)
                totals[event_day][1] += int(profit_cents or 0)

        return tuple(
            TrendPoint(day=day, revenue_cents=values[0], profit_cents=values[1])
            for day, values in sorted(totals.items())
        )

    def _recent_customers(self) -> tuple[RecentCustomerItem, ...]:
        rows = self.session.scalars(
            select(Customer)
            .where(
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
            )
            .order_by(Customer.created_at.desc())
            .limit(6)
        )
        return tuple(
            RecentCustomerItem(
                customer_id=row.id,
                customer_number=row.customer_number,
                company_name=row.company_name,
                status=row.status,
                created_at=row.created_at,
            )
            for row in rows
        )

    def _notifications(self, now: datetime, sync_queue_count: int) -> tuple[NotificationItem, ...]:
        notifications: list[NotificationItem] = []
        overdue_count = int(
            self.session.scalar(
                select(func.count()).select_from(Invoice).where(
                    Invoice.organization_id == self.organization_id,
                    Invoice.deleted_at.is_(None),
                    Invoice.balance_cents > 0,
                    Invoice.due_at.is_not(None),
                    Invoice.due_at < now,
                    Invoice.status.in_(self._UNPAID_INVOICE_STATUSES),
                )
            )
            or 0
        )
        waiting_count = int(
            self.session.scalar(
                select(func.count()).select_from(Job).where(
                    Job.organization_id == self.organization_id,
                    Job.deleted_at.is_(None),
                    Job.status == JobStatus.WAITING.value,
                )
            )
            or 0
        )
        research_count = int(
            self.session.scalar(
                select(func.count()).select_from(Quote).where(
                    Quote.organization_id == self.organization_id,
                    Quote.deleted_at.is_(None),
                    Quote.status == QuoteStatus.RESEARCH_REQUIRED.value,
                )
            )
            or 0
        )

        if waiting_count:
            notifications.append(
                NotificationItem(
                    "danger",
                    f"{waiting_count} job{'s' if waiting_count != 1 else ''} waiting",
                    "Review elapsed wait time and customer communication.",
                    "dispatch",
                )
            )
        if overdue_count:
            notifications.append(
                NotificationItem(
                    "warning",
                    f"{overdue_count} overdue invoice{'s' if overdue_count != 1 else ''}",
                    "Balances need collection review.",
                    "invoices",
                )
            )
        if research_count:
            notifications.append(
                NotificationItem(
                    "warning",
                    f"{research_count} quote{'s' if research_count != 1 else ''} need research",
                    "Manual review is required before sending.",
                    "quotes",
                )
            )
        if sync_queue_count:
            notifications.append(
                NotificationItem(
                    "info",
                    f"{sync_queue_count} change{'s' if sync_queue_count != 1 else ''} queued",
                    "Local work is safe and waiting for synchronization.",
                    "dashboard",
                )
            )
        if not notifications:
            notifications.append(
                NotificationItem(
                    "success",
                    "No critical alerts",
                    "Operations, billing, and synchronization have no active warnings.",
                    "dashboard",
                )
            )
        return tuple(notifications[:5])

    def _recent_activity(self) -> tuple[ActivityItem, ...]:
        rows = self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.organization_id == self.organization_id)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(8)
        )
        return tuple(
            ActivityItem(
                event_type=row.event_type,
                entity_type=row.entity_type,
                occurred_at=row.occurred_at,
                description=self._humanize_event(row.event_type, row.entity_type),
            )
            for row in rows
        )

    @staticmethod
    def _humanize_event(event_type: str, entity_type: str | None) -> str:
        label = event_type.replace(".", " ").replace("_", " ").strip().title()
        if entity_type and entity_type.lower() not in label.lower():
            return f"{label} · {entity_type.replace('_', ' ').title()}"
        return label
