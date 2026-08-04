from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

EMPTY_VALUE = "—"


def format_currency(cents: int | None, *, empty: str = EMPTY_VALUE) -> str:
    """Format integer cents without losing the sign or introducing float rounding."""

    if cents is None:
        return empty
    sign = "-" if cents < 0 else ""
    absolute = abs(int(cents))
    dollars, remainder = divmod(absolute, 100)
    return f"${sign}{dollars:,}.{remainder:02d}"


def format_decimal_currency(
    value: Decimal | int | float | None, *, empty: str = EMPTY_VALUE
) -> str:
    if value is None:
        return empty
    decimal_value = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"${decimal_value:,.2f}"


def format_date(value: date | datetime | None, *, empty: str = EMPTY_VALUE) -> str:
    if value is None:
        return empty
    return value.strftime("%b %d, %Y")


def format_datetime(value: datetime | None, *, empty: str = EMPTY_VALUE) -> str:
    if value is None:
        return empty
    local_value = value.astimezone() if value.tzinfo is not None else value
    return local_value.strftime("%b %d, %Y %I:%M %p")


def humanize_identifier(value: str | None, *, empty: str = EMPTY_VALUE) -> str:
    if not value:
        return empty
    return value.replace("_", " ").replace(".", " › ").strip().title()


def coalesce_int(value: Any, default: int = 0) -> int:
    """Convert database aggregate values safely; SQL SUM returns NULL for empty sets."""

    if value is None or value == "":
        return default
    return int(value)
