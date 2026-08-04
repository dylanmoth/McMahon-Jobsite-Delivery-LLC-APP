from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"Could not locate integration point: {label}")
    return text.replace(old, new, 1)


def patch_invoice(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    line = "        self._search_debounce = DebouncedCall(self.refresh, parent=self)\n"
    text = text.replace(line, "")
    marker = '        self.setObjectName("invoicePage")\n'
    text = replace_once(
        text,
        marker,
        marker + line,
        "InvoicePage debounce initialization",
    )
    path.write_text(text, encoding="utf-8")


def patch_services(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from mcmahon_dispatch.services.settings_service import SettingsService\n",
        "from mcmahon_dispatch.services.settings_service import SettingsService\n"
        "from mcmahon_dispatch.services.supplier_service import SupplierService\n"
        "from mcmahon_dispatch.services.document_service import DocumentService\n",
        "service imports",
    )
    text = replace_once(
        text,
        "    user_management: UserManagementService\n",
        "    user_management: UserManagementService\n"
        "    suppliers: SupplierService\n"
        "    documents: DocumentService\n",
        "ServiceContainer fields",
    )
    text = replace_once(
        text,
        "        reporting=ReportingService(factory, user.organization_id, config.paths.documents),\n",
        "        reporting=ReportingService(factory, user.organization_id, config.paths.documents),\n"
        "        suppliers=SupplierService(\n"
        "            factory,\n"
        "            user.organization_id,\n"
        "            user.id,\n"
        "            can_write=user.can(\"customers.write\"),\n"
        "        ),\n"
        "        documents=DocumentService(\n"
        "            factory,\n"
        "            user.organization_id,\n"
        "            user.id,\n"
        "            config.paths.documents,\n"
        "            can_write=user.can(\"customers.write\"),\n"
        "        ),\n",
        "service construction",
    )
    path.write_text(text, encoding="utf-8")


def patch_main_window(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from mcmahon_dispatch.ui.pages.reporting_page import ReportingPage\n",
        "from mcmahon_dispatch.ui.pages.reporting_page import ReportingPage\n"
        "from mcmahon_dispatch.ui.pages.supplier_page import SupplierPage\n"
        "from mcmahon_dispatch.ui.pages.document_page import DocumentPage\n",
        "page imports",
    )
    text = replace_once(
        text,
        '        if self.user.can("fleet.read"):\n'
        '            factories["fleet"] = lambda: FleetPage(self.services.fleet)\n',
        '        if self.user.can("fleet.read"):\n'
        '            factories["fleet"] = lambda: FleetPage(self.services.fleet)\n'
        '        if self.user.can("customers.read"):\n'
        '            factories["suppliers"] = lambda: SupplierPage(self.services.suppliers)\n'
        '            factories["documents"] = lambda: DocumentPage(self.services.documents)\n',
        "page factories",
    )
    text = replace_once(
        text,
        '            "settings",\n',
        '            "settings",\n'
        '            "suppliers",\n'
        '            "documents",\n',
        "implemented pages",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(r"C:\Users\thedy\OneDrive\Desktop\MJD BUSINESS\McMahonDispatch"),
    )
    args = parser.parse_args()
    project = args.project.resolve()
    payload = Path(__file__).resolve().parent / "payload"
    if not (project / "src/mcmahon_dispatch").exists():
        raise RuntimeError(f"McMahon Dispatch project not found at {project}")

    for source in payload.rglob("*"):
        if source.is_file():
            destination = project / source.relative_to(payload)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    patch_invoice(project / "src/mcmahon_dispatch/ui/pages/invoice_page.py")
    patch_services(project / "src/mcmahon_dispatch/application/services.py")
    patch_main_window(project / "src/mcmahon_dispatch/ui/main_window.py")
    print("McMahon Dispatch v1.2.1 patch applied successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
