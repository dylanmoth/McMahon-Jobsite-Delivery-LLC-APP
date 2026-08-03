from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.repositories.dashboard_repository import DashboardRepository, DashboardSnapshot


class DashboardService:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def snapshot(self, organization_id: str) -> DashboardSnapshot:
        with self.factory() as session:
            return DashboardRepository(session, organization_id).snapshot()
