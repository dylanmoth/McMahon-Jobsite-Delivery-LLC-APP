from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from mcmahon_dispatch.database.models import (
    Customer,
    Driver,
    Expense,
    ExpenseCategory,
    FuelEntry,
    Job,
    JobAssignment,
)


@dataclass(frozen=True, slots=True)
class SummaryTotals:
    revenue_cents: int
    direct_cost_cents: int
    expenses_cents: int
    fuel_cents: int
    profit_cents: int
    miles: float
    jobs: int

    @property
    def profit_per_mile_cents(self) -> int:
        return round(self.profit_cents / self.miles) if self.miles > 0 else 0


@dataclass(frozen=True, slots=True)
class TrendRow:
    period: str
    revenue_cents: int
    profit_cents: int
    fuel_cents: int
    expenses_cents: int
    miles: float
    jobs: int


@dataclass(frozen=True, slots=True)
class RankedRow:
    key: str
    name: str
    revenue_cents: int
    cost_cents: int
    profit_cents: int
    miles: float
    jobs: int

    @property
    def profit_per_mile_cents(self) -> int:
        return round(self.profit_cents / self.miles) if self.miles > 0 else 0


@dataclass(frozen=True, slots=True)
class ExpenseRow:
    category: str
    amount_cents: int


class ReportingRepository:
    def __init__(self, session: Session, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    @staticmethod
    def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        return start, end

    def summary(self, date_from: date, date_to: date) -> SummaryTotals:
        start, end = self._bounds(date_from, date_to)
        job_row = self.session.execute(
            select(
                func.coalesce(func.sum(Job.actual_revenue_cents), 0),
                func.coalesce(func.sum(Job.actual_cost_cents), 0),
                func.coalesce(func.sum(Job.actual_profit_cents), 0),
                func.coalesce(func.sum(Job.actual_miles), 0),
                func.count(Job.id),
            ).where(
                Job.organization_id == self.organization_id,
                Job.deleted_at.is_(None),
                Job.created_at.between(start, end),
            )
        ).one()
        expense_total = self.session.scalar(
            select(func.coalesce(func.sum(Expense.amount_cents + Expense.tax_cents), 0)).where(
                Expense.organization_id == self.organization_id,
                Expense.deleted_at.is_(None),
                Expense.expense_date.between(date_from, date_to),
            )
        ) or 0
        fuel_total = self.session.scalar(
            select(func.coalesce(func.sum(FuelEntry.total_cost_cents), 0)).where(
                FuelEntry.organization_id == self.organization_id,
                FuelEntry.purchased_at.between(start, end),
            )
        ) or 0
        revenue, direct_cost, job_profit, miles, jobs = job_row
        # Job.actual_profit_cents already reflects job direct costs. General expenses and
        # unassigned fuel are then deducted to produce operating profit for the period.
        operating_profit = int(job_profit or 0) - int(expense_total) - int(fuel_total)
        return SummaryTotals(
            revenue_cents=int(revenue or 0),
            direct_cost_cents=int(direct_cost or 0),
            expenses_cents=int(expense_total),
            fuel_cents=int(fuel_total),
            profit_cents=operating_profit,
            miles=float(miles or 0),
            jobs=int(jobs or 0),
        )

    def monthly_trend(self, date_from: date, date_to: date) -> list[TrendRow]:
        start, end = self._bounds(date_from, date_to)
        period_expr = func.strftime('%Y-%m', Job.created_at)
        jobs = self.session.execute(
            select(
                period_expr.label('period'),
                func.coalesce(func.sum(Job.actual_revenue_cents), 0),
                func.coalesce(func.sum(Job.actual_profit_cents), 0),
                func.coalesce(func.sum(Job.actual_miles), 0),
                func.count(Job.id),
            ).where(
                Job.organization_id == self.organization_id,
                Job.deleted_at.is_(None),
                Job.created_at.between(start, end),
            ).group_by(period_expr)
        ).all()
        expense_period = func.strftime('%Y-%m', Expense.expense_date)
        expenses = dict(self.session.execute(
            select(expense_period, func.coalesce(func.sum(Expense.amount_cents + Expense.tax_cents), 0)).where(
                Expense.organization_id == self.organization_id,
                Expense.deleted_at.is_(None),
                Expense.expense_date.between(date_from, date_to),
            ).group_by(expense_period)
        ).all())
        fuel_period = func.strftime('%Y-%m', FuelEntry.purchased_at)
        fuel = dict(self.session.execute(
            select(fuel_period, func.coalesce(func.sum(FuelEntry.total_cost_cents), 0)).where(
                FuelEntry.organization_id == self.organization_id,
                FuelEntry.purchased_at.between(start, end),
            ).group_by(fuel_period)
        ).all())
        job_map = {str(p): (int(r or 0), int(pr or 0), float(m or 0), int(c or 0)) for p,r,pr,m,c in jobs}
        periods = sorted(set(job_map) | set(expenses) | set(fuel))
        return [TrendRow(
            period=p,
            revenue_cents=job_map.get(p, (0,0,0,0))[0],
            profit_cents=job_map.get(p, (0,0,0,0))[1] - int(expenses.get(p,0) or 0) - int(fuel.get(p,0) or 0),
            fuel_cents=int(fuel.get(p,0) or 0),
            expenses_cents=int(expenses.get(p,0) or 0),
            miles=job_map.get(p, (0,0,0,0))[2],
            jobs=job_map.get(p, (0,0,0,0))[3],
        ) for p in periods]

    def yearly_trend(self, date_from: date, date_to: date) -> list[TrendRow]:
        start, end = self._bounds(date_from, date_to)
        period_expr = func.strftime('%Y', Job.created_at)
        jobs = self.session.execute(
            select(period_expr, func.coalesce(func.sum(Job.actual_revenue_cents), 0), func.coalesce(func.sum(Job.actual_profit_cents), 0), func.coalesce(func.sum(Job.actual_miles), 0), func.count(Job.id)).where(
                Job.organization_id == self.organization_id, Job.deleted_at.is_(None), Job.created_at.between(start, end)
            ).group_by(period_expr)
        ).all()
        expense_period = func.strftime('%Y', Expense.expense_date)
        expenses = dict(self.session.execute(select(expense_period, func.coalesce(func.sum(Expense.amount_cents + Expense.tax_cents), 0)).where(Expense.organization_id == self.organization_id, Expense.deleted_at.is_(None), Expense.expense_date.between(date_from, date_to)).group_by(expense_period)).all())
        fuel_period = func.strftime('%Y', FuelEntry.purchased_at)
        fuel = dict(self.session.execute(select(fuel_period, func.coalesce(func.sum(FuelEntry.total_cost_cents), 0)).where(FuelEntry.organization_id == self.organization_id, FuelEntry.purchased_at.between(start, end)).group_by(fuel_period)).all())
        job_map = {str(p): (int(r or 0), int(pr or 0), float(m or 0), int(c or 0)) for p,r,pr,m,c in jobs}
        periods = sorted(set(job_map) | set(expenses) | set(fuel))
        return [TrendRow(p, job_map.get(p,(0,0,0,0))[0], job_map.get(p,(0,0,0,0))[1]-int(expenses.get(p,0) or 0)-int(fuel.get(p,0) or 0), int(fuel.get(p,0) or 0), int(expenses.get(p,0) or 0), job_map.get(p,(0,0,0,0))[2], job_map.get(p,(0,0,0,0))[3]) for p in periods]

    def by_customer(self, date_from: date, date_to: date) -> list[RankedRow]:
        start, end = self._bounds(date_from, date_to)
        rows = self.session.execute(
            select(
                Customer.id,
                Customer.company_name,
                func.coalesce(func.sum(Job.actual_revenue_cents), 0),
                func.coalesce(func.sum(Job.actual_cost_cents), 0),
                func.coalesce(func.sum(Job.actual_profit_cents), 0),
                func.coalesce(func.sum(Job.actual_miles), 0),
                func.count(Job.id),
            ).join(Job, Job.customer_id == Customer.id).where(
                Customer.organization_id == self.organization_id,
                Customer.deleted_at.is_(None),
                Job.deleted_at.is_(None),
                Job.created_at.between(start, end),
            ).group_by(Customer.id, Customer.company_name).order_by(func.sum(Job.actual_profit_cents).desc())
        ).all()
        return [RankedRow(str(i), n, int(r or 0), int(c or 0), int(p or 0), float(m or 0), int(j or 0)) for i,n,r,c,p,m,j in rows]

    def by_driver(self, date_from: date, date_to: date) -> list[RankedRow]:
        start, end = self._bounds(date_from, date_to)
        active = JobAssignment.unassigned_at.is_(None)
        rows = self.session.execute(
            select(
                Driver.id,
                (Driver.first_name + ' ' + Driver.last_name).label('name'),
                func.coalesce(func.sum(Job.actual_revenue_cents), 0),
                func.coalesce(func.sum(Job.actual_cost_cents), 0),
                func.coalesce(func.sum(Job.actual_profit_cents), 0),
                func.coalesce(func.sum(Job.actual_miles), 0),
                func.count(func.distinct(Job.id)),
            ).join(JobAssignment, JobAssignment.driver_id == Driver.id).join(Job, Job.id == JobAssignment.job_id).where(
                Driver.organization_id == self.organization_id,
                Driver.deleted_at.is_(None),
                Job.deleted_at.is_(None),
                active,
                Job.created_at.between(start, end),
            ).group_by(Driver.id, Driver.first_name, Driver.last_name).order_by(func.sum(Job.actual_profit_cents).desc())
        ).all()
        return [RankedRow(str(i), n, int(r or 0), int(c or 0), int(p or 0), float(m or 0), int(j or 0)) for i,n,r,c,p,m,j in rows]

    def expense_breakdown(self, date_from: date, date_to: date) -> list[ExpenseRow]:
        rows = self.session.execute(
            select(ExpenseCategory.name, func.coalesce(func.sum(Expense.amount_cents + Expense.tax_cents), 0)).join(
                Expense, Expense.category_id == ExpenseCategory.id
            ).where(
                Expense.organization_id == self.organization_id,
                Expense.deleted_at.is_(None),
                Expense.expense_date.between(date_from, date_to),
            ).group_by(ExpenseCategory.name).order_by(func.sum(Expense.amount_cents + Expense.tax_cents).desc())
        ).all()
        return [ExpenseRow(str(name), int(amount or 0)) for name, amount in rows]
