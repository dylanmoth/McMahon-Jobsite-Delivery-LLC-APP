from mcmahon_dispatch.database.models import Organization
from mcmahon_dispatch.repositories.dashboard_repository import DashboardRepository


def test_empty_dashboard_snapshot_is_safe_and_scoped(database) -> None:
    with database.session_factory() as session:
        organization = session.query(Organization).one()
        snapshot = DashboardRepository(session, organization.id).snapshot()

    assert snapshot.today_revenue_cents == 0
    assert snapshot.today_profit_cents == 0
    assert snapshot.jobs_scheduled == 0
    assert snapshot.pending_quotes == 0
    assert snapshot.outstanding_invoice_cents == 0
    assert len(snapshot.trend) == 7
    assert snapshot.notifications[0].severity == "success"
