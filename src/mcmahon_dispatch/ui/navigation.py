from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NavigationItem:
    key: str
    label: str
    permission: str
    compact_label: str


NAVIGATION: tuple[NavigationItem, ...] = (
    NavigationItem("dashboard", "Home", "dashboard.view", "H"),
    NavigationItem("quotes", "Quotes", "quotes.read", "Q"),
    NavigationItem("dispatch", "Dispatch", "dispatch.read", "D"),
    NavigationItem("calendar", "Calendar", "dispatch.read", "C"),
    NavigationItem("customers", "Customers", "customers.read", "C"),
    NavigationItem("suppliers", "Suppliers", "customers.read", "S"),
    NavigationItem("fleet", "Fleet Management", "fleet.read", "F"),
    NavigationItem("invoices", "Invoices", "billing.read", "I"),
    NavigationItem("reports", "Reports", "reports.financial", "R"),
    NavigationItem("users", "Users & Access", "users.manage", "U"),
    NavigationItem("profile", "My Profile", "dashboard.view", "P"),
    NavigationItem("documents", "Documents", "customers.read", "D"),
    NavigationItem("settings", "Settings", "settings.manage", "S"),
)

NAVIGATION_LABELS = {item.key: item.label for item in NAVIGATION}


def page_key_for_route(route: str) -> str:
    """Map alternate navigation views to the page that owns them."""

    if route == "calendar":
        return "dispatch"
    if route == "settings":
        return "users"
    return route
