from __future__ import annotations

import json
from collections import defaultdict
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.core.exceptions import AuthenticationError, ValidationError
from mcmahon_dispatch.core.formatting import format_datetime, humanize_identifier
from mcmahon_dispatch.ui.common import DebouncedCall, PageHeader, configure_data_table
from mcmahon_dispatch.ui.common.tables import populate_table
from mcmahon_dispatch.services.auth_service import AuthenticationService
from mcmahon_dispatch.services.settings_service import SettingsService
from mcmahon_dispatch.ui.theme.theme_manager import ThemeManager
from mcmahon_dispatch.services.user_management_service import (
    PermissionChoice,
    RoleChoice,
    UserDetails,
    UserManagementService,
    UserRow,
)


class PasswordDialog(QDialog):
    def __init__(
        self, title: str, include_current: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        self.current = QLineEdit()
        self.current.setEchoMode(QLineEdit.EchoMode.Password)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.require_change = QCheckBox("Require password change at next sign-in")
        self.require_change.setChecked(True)
        form = QFormLayout()
        if include_current:
            form.addRow("Current password", self.current)
        form.addRow("New password", self.password)
        form.addRow("Confirm password", self.confirm)
        if not include_current:
            form.addRow("", self.require_change)
        hint = QLabel("At least 12 characters with uppercase, lowercase, and a number.")
        hint.setObjectName("muted")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "Password", "The new passwords do not match.")
            return
        self.accept()


class UserEditorDialog(QDialog):
    def __init__(
        self,
        roles: list[RoleChoice],
        details: UserDetails | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.details = details
        self.setWindowTitle("Edit User" if details else "New User")
        self.setMinimumSize(620, 620)
        self.username = QLineEdit(details.username if details else "")
        self.username.setEnabled(details is None)
        self.display_name = QLineEdit(details.display_name if details else "")
        self.first_name = QLineEdit(details.first_name if details else "")
        self.last_name = QLineEdit(details.last_name if details else "")
        self.email = QLineEdit(details.email if details else "")
        self.phone = QLineEdit(details.phone if details else "")
        self.status = QComboBox()
        self.status.addItem("Active", "active")
        self.status.addItem("Disabled", "disabled")
        self.status.addItem("Locked", "locked")
        if details:
            index = self.status.findData(details.status)
            self.status.setCurrentIndex(max(index, 0))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.must_change = QCheckBox("Require password change at next sign-in")
        self.must_change.setChecked(details.must_change_password if details else True)
        self.roles = QListWidget()
        self.roles.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        selected = details.role_ids if details else frozenset()
        for role in roles:
            item = QListWidgetItem(f"{role.name} — {role.description}")
            item.setData(Qt.ItemDataRole.UserRole, role.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if role.id in selected else Qt.CheckState.Unchecked
            )
            self.roles.addItem(item)
        form = QFormLayout()
        form.addRow("Username", self.username)
        form.addRow("Display name", self.display_name)
        form.addRow("First name", self.first_name)
        form.addRow("Last name", self.last_name)
        form.addRow("Email", self.email)
        form.addRow("Phone", self.phone)
        if details:
            form.addRow("Status", self.status)
        else:
            form.addRow("Temporary password", self.password)
            form.addRow("Confirm password", self.confirm)
        form.addRow("", self.must_change)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Roles"))
        layout.addWidget(self.roles, 1)
        layout.addWidget(buttons)

    def selected_role_ids(self) -> set[str]:
        return {
            str(self.roles.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.roles.count())
            if self.roles.item(i).checkState() == Qt.CheckState.Checked
        }

    def _accept(self) -> None:
        if not self.display_name.text().strip():
            QMessageBox.warning(self, "User", "Display name is required.")
            return
        if not self.selected_role_ids():
            QMessageBox.warning(self, "User", "Select at least one role.")
            return
        if self.details is None and self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "User", "The passwords do not match.")
            return
        self.accept()


class UsersTab(QWidget):
    def __init__(self, service: UserManagementService) -> None:
        super().__init__()
        self.service = service
        self.rows: list[UserRow] = []
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, username, email, or phone")
        self.search.setClearButtonEnabled(True)
        self.status = QComboBox()
        self.status.addItem("All statuses", None)
        self.status.addItem("Active", "active")
        self.status.addItem("Disabled", "disabled")
        self.status.addItem("Locked", "locked")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        new_user = QPushButton("New User")
        new_user.setObjectName("primary")
        new_user.clicked.connect(self._new)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit)
        reset = QPushButton("Reset Password")
        reset.clicked.connect(self._reset_password)
        sessions = QPushButton("Sign Out Devices")
        sessions.clicked.connect(self._revoke_sessions)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.status)
        toolbar.addWidget(refresh)
        toolbar.addWidget(new_user)
        toolbar.addWidget(edit)
        toolbar.addWidget(reset)
        toolbar.addWidget(sessions)
        self.table = QTableWidget()
        configure_data_table(
            self.table,
            (
                "Name",
                "Username",
                "Roles",
                "Status",
                "Email",
                "Last Sign-In",
                "Devices",
                "Password Change",
            ),
            stretch_column=0,
        )
        self.table.doubleClicked.connect(self._edit)
        self._search_debounce = DebouncedCall(self.refresh, parent=self)
        self.search.textChanged.connect(self._search_debounce.schedule)
        self.status.currentIndexChanged.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.table, 1)
        self.refresh()

    def selected(self) -> UserRow | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row]

    def refresh(self) -> None:
        try:
            self.rows = self.service.users(self.search.text(), self.status.currentData())
        except ValidationError as exc:
            QMessageBox.warning(self, "Users", str(exc))
            return
        populate_table(
            self.table,
            (
                (
                    row.display_name,
                    row.username,
                    ", ".join(row.roles),
                    humanize_identifier(row.status),
                    row.email,
                    format_datetime(row.last_login_at, empty="Never"),
                    str(row.active_devices),
                    "Required" if row.must_change_password else "No",
                )
                for row in self.rows
            ),
        )

    def _new(self) -> None:
        dialog = UserEditorDialog(self.service.roles(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.create_user(
                username=dialog.username.text(),
                display_name=dialog.display_name.text(),
                first_name=dialog.first_name.text(),
                last_name=dialog.last_name.text(),
                email=dialog.email.text(),
                phone=dialog.phone.text(),
                password=dialog.password.text(),
                role_ids=dialog.selected_role_ids(),
                must_change_password=dialog.must_change.isChecked(),
            )
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "New User", str(exc))

    def _edit(self) -> None:
        row = self.selected()
        if row is None:
            return
        try:
            details = self.service.user(row.id)
            dialog = UserEditorDialog(self.service.roles(), details, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.service.update_user(
                row.id,
                display_name=dialog.display_name.text(),
                first_name=dialog.first_name.text(),
                last_name=dialog.last_name.text(),
                email=dialog.email.text(),
                phone=dialog.phone.text(),
                status=str(dialog.status.currentData()),
                role_ids=dialog.selected_role_ids(),
                must_change_password=dialog.must_change.isChecked(),
            )
            self.refresh()
        except ValidationError as exc:
            QMessageBox.warning(self, "Edit User", str(exc))

    def _reset_password(self) -> None:
        row = self.selected()
        if row is None:
            return
        dialog = PasswordDialog(f"Reset Password — {row.display_name}", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.reset_password(
                row.id, dialog.password.text(), dialog.require_change.isChecked()
            )
            self.refresh()
            QMessageBox.information(
                self, "Password", "Password reset. Remembered sessions were revoked."
            )
        except ValidationError as exc:
            QMessageBox.warning(self, "Password", str(exc))

    def _revoke_sessions(self) -> None:
        row = self.selected()
        if row is None:
            return
        if (
            QMessageBox.question(
                self,
                "Sign Out Devices",
                f"Sign {row.display_name} out on all remembered devices?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            count = self.service.revoke_sessions(row.id)
            self.refresh()
            QMessageBox.information(self, "Devices", f"Revoked {count} active device session(s).")
        except ValidationError as exc:
            QMessageBox.warning(self, "Devices", str(exc))


class RolesTab(QWidget):
    def __init__(self, service: UserManagementService) -> None:
        super().__init__()
        self.service = service
        self.roles: list[RoleChoice] = []
        self.permissions: list[PermissionChoice] = []
        self.role_list = QListWidget()
        self.role_list.currentRowChanged.connect(self._show_role)
        self.permission_list = QListWidget()
        self.permission_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("muted")
        save = QPushButton("Save Permissions")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.description)
        right_layout.addWidget(self.permission_list, 1)
        right_layout.addWidget(save)
        splitter = QSplitter()
        splitter.addWidget(self.role_list)
        splitter.addWidget(right)
        splitter.setSizes([250, 700])
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Assign permissions to each role. Built-in Admin, Dispatcher, and Driver roles are ready to use."
            )
        )
        layout.addWidget(splitter, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.roles = self.service.roles()
            self.permissions = self.service.permissions()
        except ValidationError as exc:
            QMessageBox.warning(self, "Roles", str(exc))
            return
        self.role_list.clear()
        priority = {"admin": 0, "dispatcher": 1, "driver": 2}
        self.roles.sort(key=lambda r: (priority.get(r.code, 10), r.name.lower()))
        for role in self.roles:
            self.role_list.addItem(f"{role.name}  ({role.user_count})")
        if self.roles:
            self.role_list.setCurrentRow(0)

    def _show_role(self, row: int) -> None:
        self.permission_list.clear()
        if row < 0 or row >= len(self.roles):
            return
        role = self.roles[row]
        self.description.setText(role.description)
        by_category: dict[str, list[PermissionChoice]] = defaultdict(list)
        for permission in self.permissions:
            by_category[permission.category].append(permission)
        for category in sorted(by_category):
            header = QListWidgetItem(category.replace("_", " ").title())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.permission_list.addItem(header)
            for permission in by_category[category]:
                item = QListWidgetItem(f"    {permission.name} — {permission.description}")
                item.setData(Qt.ItemDataRole.UserRole, permission.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if permission.id in role.permission_ids
                    else Qt.CheckState.Unchecked
                )
                self.permission_list.addItem(item)

    def _save(self) -> None:
        row = self.role_list.currentRow()
        if row < 0 or row >= len(self.roles):
            return
        selected = {
            str(self.permission_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.permission_list.count())
            if self.permission_list.item(i).data(Qt.ItemDataRole.UserRole)
            and self.permission_list.item(i).checkState() == Qt.CheckState.Checked
        }
        try:
            self.service.set_role_permissions(self.roles[row].id, selected)
            self.refresh()
            QMessageBox.information(self, "Roles", "Role permissions saved.")
        except ValidationError as exc:
            QMessageBox.warning(self, "Roles", str(exc))


class AuditTab(QWidget):
    def __init__(self, service: UserManagementService) -> None:
        super().__init__()
        self.service = service
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search user, action, entity, or reason")
        self.search.setClearButtonEnabled(True)
        self.event_type = QComboBox()
        self.event_type.addItem("All actions", None)
        for event_type in service.audit_event_types():
            self.event_type.addItem(
                event_type.replace("_", " ").replace(".", " › ").title(), event_type
            )
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.event_type)
        bar.addWidget(refresh)
        self.table = QTableWidget()
        configure_data_table(
            self.table,
            ("Time", "User", "Action", "Record Type", "Reason", "Details"),
            stretch_column=5,
        )
        self._search_debounce = DebouncedCall(self.refresh, parent=self)
        self.search.textChanged.connect(self._search_debounce.schedule)
        self.event_type.currentIndexChanged.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.service.audit_events(self.search.text(), self.event_type.currentData())
        except ValidationError as exc:
            QMessageBox.warning(self, "Audit Log", str(exc))
            return
        populate_table(
            self.table,
            (
                (
                    format_datetime(row.occurred_at),
                    row.user_name,
                    humanize_identifier(row.event_type),
                    humanize_identifier(row.entity_type, empty=""),
                    row.reason,
                    json.dumps(row.details, sort_keys=True) if row.details else "",
                )
                for row in rows
            ),
        )


class ProfilePage(QWidget):
    def __init__(
        self,
        service: UserManagementService,
        auth: AuthenticationService,
    ) -> None:
        super().__init__()
        self.service = service
        self.auth = auth
        header = PageHeader(
            "My Profile",
            "Update your contact information and account security.",
        )
        self.username = QLabel()
        self.display_name = QLineEdit()
        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        self.email = QLineEdit()
        self.phone = QLineEdit()
        form = QFormLayout()
        form.addRow("Username", self.username)
        form.addRow("Display name", self.display_name)
        form.addRow("First name", self.first_name)
        form.addRow("Last name", self.last_name)
        form.addRow("Email", self.email)
        form.addRow("Phone", self.phone)
        save = QPushButton("Save Profile")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        password = QPushButton("Change Password")
        password.clicked.connect(self._change_password)
        forget = QPushButton("Forget Remembered Login")
        forget.clicked.connect(self._forget)
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(password)
        buttons.addWidget(forget)
        buttons.addStretch()
        box = QGroupBox("Profile Information")
        box_layout = QVBoxLayout(box)
        box_layout.addLayout(form)
        box_layout.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(header)
        layout.addWidget(box)
        layout.addStretch()
        self.on_activated()

    def on_activated(self) -> None:
        try:
            profile = self.service.profile()
        except ValidationError as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return
        self.username.setText(profile.username)
        self.display_name.setText(profile.display_name)
        self.first_name.setText(profile.first_name)
        self.last_name.setText(profile.last_name)
        self.email.setText(profile.email)
        self.phone.setText(profile.phone)

    def _save(self) -> None:
        try:
            self.service.update_profile(
                display_name=self.display_name.text(),
                first_name=self.first_name.text(),
                last_name=self.last_name.text(),
                email=self.email.text(),
                phone=self.phone.text(),
            )
            QMessageBox.information(self, "Profile", "Profile saved.")
        except ValidationError as exc:
            QMessageBox.warning(self, "Profile", str(exc))

    def _change_password(self) -> None:
        dialog = PasswordDialog("Change Password", include_current=True, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.change_password(dialog.current.text(), dialog.password.text())
            self.auth.forget_remembered_login()
            QMessageBox.information(
                self,
                "Password",
                "Password changed. Remembered logins were cleared for security.",
            )
        except (ValidationError, AuthenticationError) as exc:
            QMessageBox.warning(self, "Password", str(exc))

    def _forget(self) -> None:
        self.auth.forget_remembered_login()
        QMessageBox.information(
            self, "Remembered Login", "This computer will require a password next time."
        )


class SettingsTab(QWidget):
    def __init__(self, settings: SettingsService, theme_manager: ThemeManager) -> None:
        super().__init__()
        self.settings = settings
        self.theme_manager = theme_manager

        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.addItem("Follow Windows", "system")
        self._select_data(self.theme, settings.get("appearance.theme", "dark"))

        self.accent = QComboBox()
        for palette in theme_manager.accent_options:
            self.accent.addItem(palette.label, palette.code)
        self._select_data(self.accent, settings.get("appearance.accent", "classic"))

        self.density = QComboBox()
        self.density.addItem("Compact", "compact")
        self.density.addItem("Comfortable", "comfortable")
        self.density.addItem("Spacious", "spacious")
        self._select_data(self.density, settings.get("appearance.density", "comfortable"))

        self.font_scale = QComboBox()
        for percentage in (90, 100, 110, 125, 150):
            self.font_scale.addItem(f"{percentage}%", percentage)
        self._select_data(self.font_scale, int(settings.get("appearance.font_scale", 100)))

        self.inactivity = QSpinBox()
        self.inactivity.setRange(1, 240)
        self.inactivity.setSuffix(" minutes")
        self.inactivity.setValue(int(settings.get("security.inactivity_lock_minutes", 15)))

        self.dashboard_refresh = QSpinBox()
        self.dashboard_refresh.setRange(15, 3600)
        self.dashboard_refresh.setSuffix(" seconds")
        self.dashboard_refresh.setValue(int(settings.get("dashboard.refresh_seconds", 60)))

        self.start_page = QComboBox()
        for label, key in [
            ("Home", "dashboard"),
            ("Quotes", "quotes"),
            ("Dispatch", "dispatch"),
            ("Customers", "customers"),
            ("Invoices", "invoices"),
            ("Reports", "reports"),
        ]:
            self.start_page.addItem(label, key)
        self._select_data(
            self.start_page,
            settings.get("appearance.start_page", "dashboard"),
        )

        appearance = QGroupBox("Appearance")
        appearance_form = QFormLayout(appearance)
        appearance_form.addRow("Theme", self.theme)
        appearance_form.addRow("McMahon orange style", self.accent)
        appearance_form.addRow("Spacing", self.density)
        appearance_form.addRow("Text size", self.font_scale)

        behavior = QGroupBox("Application Behavior")
        behavior_form = QFormLayout(behavior)
        behavior_form.addRow("Lock after inactivity", self.inactivity)
        behavior_form.addRow("Dashboard refresh", self.dashboard_refresh)
        behavior_form.addRow("Start page", self.start_page)

        save = QPushButton("Save Settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save)

        note = QLabel("Appearance changes preview immediately. Select Save Settings to keep them.")
        note.setObjectName("muted")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(appearance)
        layout.addWidget(behavior)
        layout.addWidget(note)
        layout.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

        self.theme.currentIndexChanged.connect(self._preview)
        self.accent.currentIndexChanged.connect(self._preview)
        self.density.currentIndexChanged.connect(self._preview)
        self.font_scale.currentIndexChanged.connect(self._preview)

    @staticmethod
    def _select_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(index, 0))

    def _preview(self) -> None:
        self.theme_manager.preview(
            str(self.theme.currentData()),
            str(self.accent.currentData()),
            str(self.density.currentData()),
            int(self.font_scale.currentData()),
        )

    def _save(self) -> None:
        self.theme_manager.apply(
            str(self.theme.currentData()),
            str(self.accent.currentData()),
            str(self.density.currentData()),
            int(self.font_scale.currentData()),
            persist=True,
        )
        self.settings.set_many(
            {
                "security.inactivity_lock_minutes": self.inactivity.value(),
                "dashboard.refresh_seconds": self.dashboard_refresh.value(),
                "appearance.start_page": self.start_page.currentData(),
            }
        )
        QMessageBox.information(self, "Settings", "Appearance and settings saved.")


class UserManagementPage(QWidget):
    def __init__(
        self,
        service: UserManagementService,
        settings: SettingsService,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__()
        header = PageHeader(
            "Users & Access",
            "Manage employee accounts, roles, permissions, settings, and security history.",
        )
        self.tabs = QTabWidget()
        tabs = self.tabs
        tabs.addTab(UsersTab(service), "Users")
        tabs.addTab(RolesTab(service), "Roles & Permissions")
        if service.can_read_audit:
            tabs.addTab(AuditTab(service), "Audit Log")
        if service.can_manage_settings:
            tabs.addTab(SettingsTab(settings, theme_manager), "Settings")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(header)
        layout.addWidget(tabs, 1)

    def set_view(self, key: str) -> None:
        if key == "settings":
            for index in range(self.tabs.count()):
                if self.tabs.tabText(index) == "Settings":
                    self.tabs.setCurrentIndex(index)
                    return
        elif key == "users":
            self.tabs.setCurrentIndex(0)

    def on_activated(self) -> None:
        return
