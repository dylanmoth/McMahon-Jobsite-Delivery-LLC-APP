from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mcmahon_dispatch.repositories.dashboard_repository import (
    ActivityItem,
    DashboardSnapshot,
    NotificationItem,
    RecentCustomerItem,
)
from mcmahon_dispatch.services.auth_service import AuthenticatedUser
from mcmahon_dispatch.services.dashboard_service import DashboardService
from mcmahon_dispatch.ui.widgets.dashboard_panel import ClickableFrame, DashboardPanel
from mcmahon_dispatch.ui.widgets.metric_card import MetricCard
from mcmahon_dispatch.ui.widgets.trend_chart import ChartPoint, TrendChart


class DashboardPage(QWidget):
    drilldown_requested = Signal(str)
    quick_action_requested = Signal(str)

    def __init__(self, service: DashboardService, user: AuthenticatedUser, refresh_seconds: int) -> None:
        super().__init__()
        self.service = service
        self.user = user
        self._metric_columns = 5
        self._lower_columns = 2

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content = QWidget()
        self.content.setObjectName("dashboardContent")
        self.scroll.setWidget(self.content)

        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Live operational and financial overview")
        subtitle.setObjectName("muted")
        self.updated_label = QLabel("Not refreshed")
        self.updated_label.setObjectName("dashboardUpdated")
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryCompact")
        refresh.clicked.connect(self.refresh)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header = QHBoxLayout()
        header.addLayout(header_text)
        header.addStretch()
        header.addWidget(self.updated_label)
        header.addWidget(refresh)

        self.cards = {
            "today_revenue": MetricCard(
                "invoices", "Today's Revenue", accent="green", helper="Completed jobs today"
            ),
            "today_profit": MetricCard(
                "reports", "Today's Profit", accent="orange", helper="Revenue less direct costs"
            ),
            "jobs_scheduled": MetricCard(
                "calendar", "Jobs Scheduled", accent="blue", helper="Today's active schedule"
            ),
            "pending_quotes": MetricCard(
                "quotes", "Pending Quotes", accent="amber", helper="Draft through viewed"
            ),
            "outstanding": MetricCard(
                "invoices", "Outstanding Invoices", accent="red", helper="Unpaid customer balance"
            ),
        }
        for card in self.cards.values():
            card.activated.connect(self.drilldown_requested)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.setMinimumHeight(118)

        self.metric_grid = QGridLayout()
        self.metric_grid.setHorizontalSpacing(14)
        self.metric_grid.setVerticalSpacing(14)

        self.revenue_chart = TrendChart(empty_message="Revenue appears after completed jobs")
        self.profit_chart = TrendChart(empty_message="Profit appears after completed jobs")
        self.revenue_panel = DashboardPanel("Revenue", "Completed-job revenue over the last 7 days")
        self.revenue_panel.body.setContentsMargins(10, 0, 10, 10)
        self.revenue_panel.body.addWidget(self.revenue_chart)
        self.profit_panel = DashboardPanel("Profit", "Actual job profit over the last 7 days")
        self.profit_panel.body.setContentsMargins(10, 0, 10, 10)
        self.profit_panel.body.addWidget(self.profit_chart)

        self.chart_grid = QGridLayout()
        self.chart_grid.setHorizontalSpacing(14)
        self.chart_grid.setVerticalSpacing(14)

        self.quick_actions_panel = DashboardPanel("Quick Actions", "Start the most common workflows")
        quick_actions = (
            ("New Quote", "new_quote", "primaryAction"),
            ("New Job", "new_job", "quickAction"),
            ("Add Customer", "new_customer", "quickAction"),
            ("Record Payment", "record_payment", "quickAction"),
        )
        action_grid = QGridLayout()
        action_grid.setContentsMargins(18, 0, 18, 18)
        action_grid.setSpacing(10)
        for index, (label, key, object_name) in enumerate(quick_actions):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda _checked=False, action=key: self.quick_action_requested.emit(action))
            action_grid.addWidget(button, index // 2, index % 2)
        self.quick_actions_panel.body.addLayout(action_grid)

        self.notifications_panel = DashboardPanel("Notifications", "Items that need attention")
        self.notifications_layout = QVBoxLayout()
        self.notifications_layout.setContentsMargins(12, 0, 12, 12)
        self.notifications_layout.setSpacing(8)
        self.notifications_panel.body.addLayout(self.notifications_layout)

        self.customers_panel = DashboardPanel("Recent Customers", "Newest customer records")
        self.customers_layout = QVBoxLayout()
        self.customers_layout.setContentsMargins(12, 0, 12, 12)
        self.customers_layout.setSpacing(0)
        self.customers_panel.body.addLayout(self.customers_layout)

        self.activity_panel = DashboardPanel("Recent Activity", "Latest audited actions")
        self.activity_layout = QVBoxLayout()
        self.activity_layout.setContentsMargins(12, 0, 12, 12)
        self.activity_layout.setSpacing(0)
        self.activity_panel.body.addLayout(self.activity_layout)

        self.lower_grid = QGridLayout()
        self.lower_grid.setHorizontalSpacing(14)
        self.lower_grid.setVerticalSpacing(14)

        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(24, 20, 24, 28)
        content_layout.setSpacing(16)
        content_layout.addLayout(header)
        content_layout.addLayout(self.metric_grid)
        content_layout.addLayout(self.chart_grid)
        content_layout.addLayout(self.lower_grid)
        content_layout.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(max(15, refresh_seconds) * 1000)
        self._reflow()
        self.refresh()

    def refresh(self) -> None:
        snapshot = self.service.snapshot(self.user.organization_id)
        self._apply(snapshot)

    def _apply(self, snapshot: DashboardSnapshot) -> None:
        can_view_financials = self.user.can("dashboard.financial")
        self.cards["today_revenue"].set_value(
            self._money(snapshot.today_revenue_cents) if can_view_financials else "Restricted"
        )
        self.cards["today_profit"].set_value(
            self._money(snapshot.today_profit_cents) if can_view_financials else "Restricted"
        )
        self.cards["jobs_scheduled"].set_value(str(snapshot.jobs_scheduled))
        self.cards["pending_quotes"].set_value(str(snapshot.pending_quotes))
        self.cards["outstanding"].set_value(
            self._money(snapshot.outstanding_invoice_cents) if can_view_financials else "Restricted"
        )

        if can_view_financials:
            self.revenue_chart.set_points(
                [
                    ChartPoint(point.day.strftime("%a"), point.revenue_cents / 100)
                    for point in snapshot.trend
                ]
            )
            self.profit_chart.set_points(
                [
                    ChartPoint(point.day.strftime("%a"), point.profit_cents / 100)
                    for point in snapshot.trend
                ]
            )
        else:
            self.revenue_chart.set_points(())
            self.profit_chart.set_points(())

        self._replace_rows(
            self.notifications_layout,
            [self._notification_row(item) for item in snapshot.notifications],
        )
        customer_rows = [self._customer_row(item) for item in snapshot.recent_customers]
        if not customer_rows:
            customer_rows = [self._empty_row("No customers have been added yet.")]
        self._replace_rows(self.customers_layout, customer_rows)

        activity_rows = [self._activity_row(item) for item in snapshot.recent_activity]
        if not activity_rows:
            activity_rows = [self._empty_row("No audited activity is available yet.")]
        self._replace_rows(self.activity_layout, activity_rows)

        local_time = snapshot.generated_at.astimezone()
        sync_suffix = f" · {snapshot.sync_queue_count} queued" if snapshot.sync_queue_count else ""
        self.updated_label.setText(f"Updated {local_time:%I:%M %p}{sync_suffix}")

    def _notification_row(self, item: NotificationItem) -> QWidget:
        row = ClickableFrame()
        row.setObjectName("notificationRow")
        row.setProperty("severity", item.severity)
        row.activated.connect(lambda route=item.route: self.drilldown_requested.emit(route))
        marker = QLabel("●")
        marker.setObjectName("notificationMarker")
        marker.setProperty("severity", item.severity)
        title = QLabel(item.title)
        title.setObjectName("rowTitle")
        detail = QLabel(item.detail)
        detail.setObjectName("rowSubtitle")
        detail.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(title)
        text.addWidget(detail)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)
        return row

    def _customer_row(self, item: RecentCustomerItem) -> QWidget:
        row = QPushButton()
        row.setObjectName("listRowButton")
        row.clicked.connect(lambda _checked=False: self.drilldown_requested.emit("customers"))
        company = QLabel(item.company_name)
        company.setObjectName("rowTitle")
        meta = QLabel(f"{item.customer_number} · {item.status.replace('_', ' ').title()}")
        meta.setObjectName("rowSubtitle")
        date_label = QLabel(self._friendly_date(item.created_at))
        date_label.setObjectName("rowMeta")
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(company)
        text.addWidget(meta)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(text, 1)
        layout.addWidget(date_label)
        return row

    def _activity_row(self, item: ActivityItem) -> QWidget:
        row = QFrame()
        row.setObjectName("activityRow")
        marker = QLabel("•")
        marker.setObjectName("activityMarker")
        title = QLabel(item.description)
        title.setObjectName("rowTitle")
        timestamp = QLabel(self._friendly_time(item.occurred_at))
        timestamp.setObjectName("rowMeta")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.addWidget(marker)
        layout.addWidget(title, 1)
        layout.addWidget(timestamp)
        return row

    @staticmethod
    def _empty_row(text: str) -> QWidget:
        label = QLabel(text)
        label.setObjectName("emptyState")
        label.setWordWrap(True)
        label.setContentsMargins(12, 18, 12, 18)
        return label

    @staticmethod
    def _replace_rows(layout: QVBoxLayout, rows: list[QWidget]) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for row in rows:
            layout.addWidget(row)
        layout.addStretch()

    @staticmethod
    def _money(cents: int) -> str:
        return f"${cents / 100:,.2f}"

    @staticmethod
    def _friendly_date(value: datetime) -> str:
        return value.astimezone().strftime("%b %d").replace(" 0", " ")

    @staticmethod
    def _friendly_time(value: datetime) -> str:
        return value.astimezone().strftime("%b %d, %I:%M %p")

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        width = self.width()
        metric_columns = 5 if width >= 1500 else 3 if width >= 1050 else 2 if width >= 700 else 1
        lower_columns = 2 if width >= 1050 else 1
        if metric_columns != self._metric_columns or lower_columns != self._lower_columns:
            self._metric_columns = metric_columns
            self._lower_columns = lower_columns
            self._reflow()

    def _reflow(self) -> None:
        self._clear_layout(self.metric_grid)
        for index, card in enumerate(self.cards.values()):
            self.metric_grid.addWidget(card, index // self._metric_columns, index % self._metric_columns)

        self._clear_layout(self.chart_grid)
        chart_columns = 2 if self.width() >= 1050 else 1
        self.chart_grid.addWidget(self.revenue_panel, 0, 0)
        self.chart_grid.addWidget(self.profit_panel, 0 if chart_columns == 2 else 1, 1 if chart_columns == 2 else 0)
        self.chart_grid.setColumnStretch(0, 1)
        if chart_columns == 2:
            self.chart_grid.setColumnStretch(1, 1)

        self._clear_layout(self.lower_grid)
        panels = (
            self.quick_actions_panel,
            self.notifications_panel,
            self.customers_panel,
            self.activity_panel,
        )
        for index, panel in enumerate(panels):
            self.lower_grid.addWidget(panel, index // self._lower_columns, index % self._lower_columns)
        for column in range(self._lower_columns):
            self.lower_grid.setColumnStretch(column, 1)

    @staticmethod
    def _clear_layout(layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                layout.removeWidget(widget)
