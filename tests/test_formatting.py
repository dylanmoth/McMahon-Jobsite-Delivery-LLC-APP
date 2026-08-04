from datetime import UTC, date, datetime
from decimal import Decimal

from mcmahon_dispatch.core.formatting import (
    coalesce_int,
    format_currency,
    format_date,
    format_datetime,
    format_decimal_currency,
    humanize_identifier,
)


def test_currency_formatting_preserves_sign_and_cents() -> None:
    assert format_currency(123_456) == "$1,234.56"
    assert format_currency(-250) == "$-2.50"
    assert format_currency(0) == "$0.00"
    assert format_currency(None) == "—"


def test_decimal_currency_does_not_use_binary_float_formatting() -> None:
    assert format_decimal_currency(Decimal("19.995")) == "$20.00"
    assert format_decimal_currency(None) == "—"


def test_dates_and_identifiers_are_human_readable() -> None:
    assert format_date(date(2026, 8, 3)) == "Aug 03, 2026"
    assert format_datetime(datetime(2026, 8, 3, 16, 30, tzinfo=UTC)).startswith("Aug 03, 2026")
    assert humanize_identifier("users.password_reset") == "Users › Password Reset"
    assert humanize_identifier(None) == "—"


def test_database_aggregate_values_are_coalesced_safely() -> None:
    assert coalesce_int(None) == 0
    assert coalesce_int("") == 0
    assert coalesce_int("42") == 42
    assert coalesce_int(None, default=7) == 7
