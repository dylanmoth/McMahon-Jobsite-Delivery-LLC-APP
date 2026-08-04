from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ModulePage(QWidget):
    DESCRIPTIONS = {
        "quotes": "Quote intake, revisions, acceptance, and versioned pricing.",
        "dispatch": "Jobs, assignments, statuses, exceptions, and proof of delivery.",
        "calendar": "Driver and vehicle scheduling with conflict visibility.",
        "customers": "Customer records, contacts, addresses, history, and balances.",
        "suppliers": "Supplier locations, pickup instructions, and readiness history.",
        "fleet": "Drivers, vehicles, capacity, fuel, maintenance, and compliance.",
        "invoices": "Invoices, payments, statements, aging, and balances.",
        "reports": "Permission-aware operational and financial analysis.",
        "documents": "Searchable business files, photos, signatures, and proof.",
        "settings": "Organization, pricing, users, integrations, backup, and appearance controls.",
    }

    def __init__(self, key: str) -> None:
        super().__init__()
        title = QLabel(key.replace("_", " ").title())
        title.setObjectName("pageTitle")
        description = QLabel(self.DESCRIPTIONS[key])
        description.setObjectName("muted")
        description.setWordWrap(True)
        state = QLabel(
            "Foundation boundary established. This module has no production records yet."
        )
        state.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(24)
        layout.addWidget(state)
        layout.addStretch()
