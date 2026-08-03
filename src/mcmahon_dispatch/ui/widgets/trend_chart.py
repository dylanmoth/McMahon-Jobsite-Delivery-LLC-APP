from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class ChartPoint:
    label: str
    value: float


class TrendChart(QWidget):
    """Lightweight responsive line chart with no external chart dependency."""

    def __init__(self, *, prefix: str = "$", empty_message: str = "No completed jobs yet") -> None:
        super().__init__()
        self._points: tuple[ChartPoint, ...] = ()
        self._prefix = prefix
        self._empty_message = empty_message
        self.setMinimumHeight(210)
        self.setAccessibleName("Trend chart")

    def set_points(self, points: Sequence[ChartPoint]) -> None:
        self._points = tuple(points)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        palette = self.palette()
        text_color = palette.color(QPalette.ColorRole.Text)
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        orange = QColor("#F97316")
        grid = QColor(muted)
        grid.setAlpha(45)

        bounds = QRectF(self.rect()).adjusted(18, 14, -18, -18)
        if not self._points or max((p.value for p in self._points), default=0) <= 0:
            painter.setPen(muted)
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, self._empty_message)
            return

        chart = bounds.adjusted(50, 8, -8, -28)
        maximum = max(point.value for point in self._points)
        padded_max = max(maximum * 1.15, 1.0)

        painter.setPen(QPen(grid, 1))
        for index in range(4):
            y = chart.top() + chart.height() * index / 3
            painter.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
            value = padded_max * (1 - index / 3)
            painter.setPen(muted)
            painter.drawText(
                QRectF(bounds.left(), y - 9, 44, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._compact_currency(value),
            )
            painter.setPen(QPen(grid, 1))

        spacing = chart.width() / max(len(self._points) - 1, 1)
        coordinates: list[QPointF] = []
        for index, point in enumerate(self._points):
            x = chart.left() + index * spacing
            y = chart.bottom() - (point.value / padded_max) * chart.height()
            coordinates.append(QPointF(x, y))

        fill_path = QPainterPath(coordinates[0])
        for point in coordinates[1:]:
            fill_path.lineTo(point)
        fill_path.lineTo(coordinates[-1].x(), chart.bottom())
        fill_path.lineTo(coordinates[0].x(), chart.bottom())
        fill_path.closeSubpath()
        fill = QColor(orange)
        fill.setAlpha(40)
        painter.fillPath(fill_path, fill)

        line_path = QPainterPath(coordinates[0])
        for point in coordinates[1:]:
            line_path.lineTo(point)
        painter.setPen(QPen(orange, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(line_path)

        painter.setBrush(orange)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Base), 2))
        for point in coordinates:
            painter.drawEllipse(point, 4, 4)

        painter.setPen(text_color)
        metrics = QFontMetrics(painter.font())
        for index, point in enumerate(self._points):
            if len(self._points) > 8 and index % 2:
                continue
            x = coordinates[index].x()
            label_width = metrics.horizontalAdvance(point.label) + 8
            painter.drawText(
                QRectF(x - label_width / 2, chart.bottom() + 8, label_width, 18),
                Qt.AlignmentFlag.AlignCenter,
                point.label,
            )

    def _compact_currency(self, value: float) -> str:
        if value >= 1_000_000:
            return f"{self._prefix}{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{self._prefix}{value / 1_000:.1f}K"
        return f"{self._prefix}{value:,.0f}"
