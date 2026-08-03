"""customer operational profile fields

Revision ID: c5a81d2f901e
Revises: 7b91c2d7e4a0
Create Date: 2026-08-03 03:05:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c5a81d2f901e"
down_revision: Union[str, None] = "7b91c2d7e4a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.add_column(sa.Column("website", sa.String(length=254), nullable=True))
        batch.add_column(sa.Column("customer_type", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("primary_phone", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("primary_email", sa.String(length=254), nullable=True))
        batch.add_column(sa.Column("billing_email", sa.String(length=254), nullable=True))
        batch.add_column(sa.Column("purchase_order_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("requires_call_ahead", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("transactional_updates_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("photo_confirmation_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("appointment_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("forklift_available", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("liftgate_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("preferred_pickup_window", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("preferred_delivery_window", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("receiving_hours", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("typical_materials", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("default_access_instructions", sa.Text(), nullable=False, server_default=""))
        batch.create_index("ix_customers_org_primary_email", ["organization_id", "primary_email"], unique=False)
        batch.create_index("ix_customers_org_primary_phone", ["organization_id", "primary_phone"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.drop_index("ix_customers_org_primary_phone")
        batch.drop_index("ix_customers_org_primary_email")
        for column in (
            "default_access_instructions", "typical_materials", "receiving_hours",
            "preferred_delivery_window", "preferred_pickup_window", "liftgate_required",
            "forklift_available", "appointment_required", "photo_confirmation_required",
            "transactional_updates_enabled", "requires_call_ahead", "purchase_order_required",
            "billing_email", "primary_email", "primary_phone", "customer_type", "website",
        ):
            batch.drop_column(column)
