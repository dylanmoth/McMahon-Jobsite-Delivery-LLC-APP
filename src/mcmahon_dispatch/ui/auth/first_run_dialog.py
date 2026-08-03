from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

from mcmahon_dispatch.core.exceptions import McMahonDispatchError
from mcmahon_dispatch.services.auth_service import AuthenticationService


class FirstRunAdminDialog(QDialog):
    def __init__(self, auth: AuthenticationService) -> None:
        super().__init__()
        self.auth = auth
        self.setWindowTitle("Create McMahon Dispatch Administrator")
        self.setMinimumWidth(520)
        title = QLabel("Secure first-run setup")
        title.setObjectName("pageTitle")
        explanation = QLabel("Create the individual administrator account that will own users, pricing, backups, and audit settings. Shared production accounts are prohibited.")
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        self.username = QLineEdit(); self.username.setPlaceholderText("dmcmahon")
        self.display_name = QLineEdit(); self.display_name.setPlaceholderText("Dylan McMahon")
        self.email = QLineEdit(); self.email.setPlaceholderText("name@company.com")
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit(); self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout()
        form.addRow("Username", self.username); form.addRow("Display name", self.display_name); form.addRow("Email", self.email); form.addRow("Password", self.password); form.addRow("Confirm password", self.confirm)
        cancel = QPushButton("Exit"); cancel.clicked.connect(self.reject)
        create = QPushButton("Create Administrator"); create.setObjectName("primary"); create.clicked.connect(self._create)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(cancel); buttons.addWidget(create)
        layout = QVBoxLayout(self); layout.addWidget(title); layout.addWidget(explanation); layout.addSpacing(12); layout.addLayout(form); layout.addLayout(buttons)

    def _create(self) -> None:
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "Passwords do not match", "Enter the same password in both password fields.")
            return
        try:
            self.auth.create_initial_admin(self.username.text(), self.display_name.text(), self.email.text(), self.password.text())
        except McMahonDispatchError as exc:
            QMessageBox.warning(self, "Administrator not created", str(exc))
            return
        self.accept()
