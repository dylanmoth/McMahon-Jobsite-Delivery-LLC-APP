from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.core.config import AppConfig
from mcmahon_dispatch.services.auth_service import AuthenticatedUser, AuthenticationService
from mcmahon_dispatch.services.customer_service import CustomerService
from mcmahon_dispatch.services.dashboard_service import DashboardService
from mcmahon_dispatch.services.dispatch_service import DispatchService
from mcmahon_dispatch.services.fleet_service import FleetService
from mcmahon_dispatch.services.invoice_service import InvoiceService
from mcmahon_dispatch.services.quote_service import QuoteService
from mcmahon_dispatch.services.reporting_service import ReportingService
from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.services.supplier_service import SupplierService
from mcmahon_dispatch.services.document_service import DocumentService
from mcmahon_dispatch.services.user_management_service import UserManagementService


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    """Runtime services used by the authenticated desktop session."""

    settings: SettingsService
    auth: AuthenticationService
    dashboard: DashboardService
    customers: CustomerService
    quotes: QuoteService
    dispatch: DispatchService
    fleet: FleetService
    invoices: InvoiceService
    reporting: ReportingService
    user_management: UserManagementService
    suppliers: SupplierService
    documents: DocumentService


def build_services(
    factory: sessionmaker[Session],
    config: AppConfig,
    settings: SettingsService,
    auth: AuthenticationService,
    user: AuthenticatedUser,
) -> ServiceContainer:
    """Build one service graph for the signed-in user.

    Permission decisions are resolved once at session startup and passed into the
    corresponding services. This keeps permission checks consistent across screens.
    """

    logo_path = Path(__file__).parents[1] / "assets" / "images" / "mcmahon_dispatch_logo.png"

    return ServiceContainer(
        settings=settings,
        auth=auth,
        dashboard=DashboardService(factory),
        customers=CustomerService(factory, user.organization_id, user.id),
        quotes=QuoteService(
            factory,
            user.organization_id,
            user.id,
            config.paths.documents,
            logo_path,
            can_override_price=user.can("quotes.override_price"),
            can_write=user.can("quotes.write"),
        ),
        dispatch=DispatchService(
            factory,
            user.organization_id,
            user.id,
            can_manage=user.can("dispatch.manage"),
            can_view_financials=user.can("reports.financial"),
        ),
        fleet=FleetService(
            factory,
            user.organization_id,
            user.id,
            can_write=user.can("fleet.write"),
        ),
        invoices=InvoiceService(
            factory,
            user.organization_id,
            user.id,
            config.paths.documents,
            logo_path,
            can_write=user.can("billing.write"),
        ),
        reporting=ReportingService(factory, user.organization_id, config.paths.documents),
        suppliers=SupplierService(
            factory,
            user.organization_id,
            user.id,
            can_write=user.can("customers.write"),
        ),
        documents=DocumentService(
            factory,
            user.organization_id,
            user.id,
            config.paths.documents,
            can_write=user.can("customers.write"),
        ),
        user_management=UserManagementService(
            factory,
            user.organization_id,
            user.id,
            can_manage_users=user.can("users.manage"),
            can_read_audit=user.can("audit.read"),
            can_manage_settings=user.can("settings.manage"),
        ),
    )
