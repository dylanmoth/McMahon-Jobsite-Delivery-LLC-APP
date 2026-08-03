from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from mcmahon_dispatch.core.exceptions import AuthenticationError
from mcmahon_dispatch.services.auth_service import AuthenticatedUser, AuthenticationService


class LoginDialog(QDialog):
    def __init__(self, auth: AuthenticationService) -> None:
        super().__init__()
        self.auth = auth
        self.authenticated_user: AuthenticatedUser | None = None
        self.setWindowTitle("Sign in to McMahon Dispatch")
        self.setMinimumWidth(440)
        title = QLabel("McMahon Dispatch")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Sign in with your individual employee account.")
        subtitle.setObjectName("muted")
        self.username = QLineEdit()
        self.username.setClearButtonEnabled(True)
        self.username.setText(auth.remembered_username())
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._login)
        self.remember = QCheckBox("Keep me signed in on this computer")
        self.remember.setToolTip(
            "Stores a protected device token in Windows Credential Manager. Your password is never saved."
        )
        self.remember.setEnabled(auth.remembered_login_available())
        if not self.remember.isEnabled():
            self.remember.setText("Keep me signed in (Windows credential storage unavailable)")
        form = QFormLayout()
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow("", self.remember)
        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        sign_in = QPushButton("Sign In")
        sign_in.setObjectName("primary")
        sign_in.clicked.connect(self._login)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(exit_button)
        buttons.addWidget(sign_in)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addLayout(buttons)
        (self.password if self.username.text() else self.username).setFocus()

    def _login(self) -> None:
        try:
            self.authenticated_user = self.auth.authenticate(
                self.username.text(),
                self.password.text(),
                remember_login=self.remember.isChecked(),
            )
        except AuthenticationError as exc:
            self.password.clear()
            QMessageBox.warning(self, "Sign-in failed", str(exc))
            return
        self.accept()
