"""quote builder intake and quick call notes

Revision ID: e3a9b7c4d210
Revises: c5a81d2f901e
Create Date: 2026-08-03 04:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e3a9b7c4d210"
down_revision: Union[str, None] = "c5a81d2f901e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "quick_call_notes",
        *_audit_columns(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_id", sa.String(length=36), nullable=True),
        sa.Column("customer_id", sa.String(length=36), nullable=True),
        sa.Column("quote_id", sa.String(length=36), nullable=True),
        sa.Column("company_contact", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=254), nullable=False, server_default=""),
        sa.Column("supplier_address", sa.Text(), nullable=False, server_default=""),
        sa.Column("jobsite_address", sa.Text(), nullable=False, server_default=""),
        sa.Column("materials", sa.Text(), nullable=False, server_default=""),
        sa.Column("dimensions_text", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("weight_text", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("overweight", sa.Boolean(), nullable=True),
        sa.Column("pickup_stops", sa.Integer(), nullable=True),
        sa.Column("order_ready", sa.Boolean(), nullable=True),
        sa.Column("same_day", sa.Boolean(), nullable=True),
        sa.Column("store_outside_psl", sa.Boolean(), nullable=True),
        sa.Column("jobsite_outside_psl", sa.Boolean(), nullable=True),
        sa.Column("miles_text", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("wait_text", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("trash_text", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("vehicle_text", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("other_client_scheduled", sa.Boolean(), nullable=True),
        sa.Column("general_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.CheckConstraint("pickup_stops IS NULL OR pickup_stops >= 1", name="ck_quick_call_stops"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quick_call_notes_org_created", "quick_call_notes", ["organization_id", "created_at"]
    )
    op.create_index("ix_quick_call_notes_quote", "quick_call_notes", ["quote_id"])

    op.create_table(
        "quote_intakes",
        *_audit_columns(),
        sa.Column("quote_id", sa.String(length=36), nullable=False),
        sa.Column(
            "customer_contact_name", sa.String(length=240), nullable=False, server_default=""
        ),
        sa.Column(
            "customer_contact_phone", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column(
            "customer_contact_email", sa.String(length=254), nullable=False, server_default=""
        ),
        sa.Column("supplier_name", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("supplier_address", sa.Text(), nullable=False, server_default=""),
        sa.Column("supplier_contact", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("order_number", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("order_paid", sa.Boolean(), nullable=True),
        sa.Column("order_ready", sa.Boolean(), nullable=True),
        sa.Column("pickup_authorization", sa.Text(), nullable=False, server_default=""),
        sa.Column("pickup_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("jobsite_address", sa.Text(), nullable=False, server_default=""),
        sa.Column("site_contact", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("access_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("delivery_window", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("materials", sa.Text(), nullable=False, server_default=""),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False, server_default="1"),
        sa.Column("length_inches", sa.Numeric(10, 2), nullable=True),
        sa.Column("width_inches", sa.Numeric(10, 2), nullable=True),
        sa.Column("height_inches", sa.Numeric(10, 2), nullable=True),
        sa.Column("weight_pounds", sa.Numeric(12, 2), nullable=True),
        sa.Column("overweight", sa.Boolean(), nullable=True),
        sa.Column("hazardous", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("prohibited_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("estimated_hours", sa.Numeric(8, 2), nullable=True),
        sa.Column("store_inside_psl", sa.Boolean(), nullable=True),
        sa.Column("jobsite_inside_psl", sa.Boolean(), nullable=True),
        sa.Column("boundary_to_store_miles", sa.Numeric(10, 2), nullable=True),
        sa.Column("store_to_jobsite_miles", sa.Numeric(10, 2), nullable=True),
        sa.Column("pickup_stops", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("same_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("other_client_affected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("wait_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delay_sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("loading_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trash_bag_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "trash_contents_identified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "cancelled_after_dispatch", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tolls_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tolls_pass_through", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parking_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parking_pass_through", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rental_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rental_pass_through", sa.Boolean(), nullable=True),
        sa.Column("rental_markup_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fuel_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("helper_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("securement_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processing_fee_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("other_direct_cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_adjustment_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_adjustment_reason", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint("quantity > 0", name="ck_quote_intake_quantity"),
        sa.CheckConstraint("pickup_stops >= 1", name="ck_quote_intake_stops"),
        sa.CheckConstraint("wait_minutes >= 0", name="ck_quote_intake_wait"),
        sa.CheckConstraint("delay_sequence >= 1", name="ck_quote_intake_delay_sequence"),
        sa.CheckConstraint("loading_minutes >= 0", name="ck_quote_intake_loading"),
        sa.CheckConstraint("trash_bag_count >= 0", name="ck_quote_intake_trash"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quote_id"),
    )
    op.create_index("ix_quote_intakes_org_quote", "quote_intakes", ["organization_id", "quote_id"])


def downgrade() -> None:
    op.drop_index("ix_quote_intakes_org_quote", table_name="quote_intakes")
    op.drop_table("quote_intakes")
    op.drop_index("ix_quick_call_notes_quote", table_name="quick_call_notes")
    op.drop_index("ix_quick_call_notes_org_created", table_name="quick_call_notes")
    op.drop_table("quick_call_notes")
