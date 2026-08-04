"""Reusable desktop UI components and behavior helpers."""

from mcmahon_dispatch.ui.common.debounce import DebouncedCall
from mcmahon_dispatch.ui.common.models import (
    configure_table_view,
    model_record_id,
    replace_model_rows,
)
from mcmahon_dispatch.ui.common.tables import (
    configure_data_table,
    populate_table,
    selected_record_id,
)
from mcmahon_dispatch.ui.common.widgets import PageHeader, SectionCard

__all__ = [
    "DebouncedCall",
    "PageHeader",
    "SectionCard",
    "configure_data_table",
    "configure_table_view",
    "model_record_id",
    "populate_table",
    "replace_model_rows",
    "selected_record_id",
]
