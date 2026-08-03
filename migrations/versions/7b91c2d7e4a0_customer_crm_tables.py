"""customer CRM notes and preferred suppliers

Revision ID: 7b91c2d7e4a0
Revises: 3d601fca4465
Create Date: 2026-08-03 03:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7b91c2d7e4a0"
down_revision: Union[str, None] = "3d601fca4465"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_notes",
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("author_user_id", sa.String(length=36), nullable=True),
        sa.Column("note_type", sa.String(length=40), nullable=False, server_default="general"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_notes_organization_id", "customer_notes", ["organization_id"])
    op.create_index("ix_customer_notes_customer_created", "customer_notes", ["customer_id", "created_at"])
    op.create_index("ix_customer_notes_customer_pinned", "customer_notes", ["customer_id", "pinned"])

    op.create_table(
        "customer_preferred_suppliers",
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint("rank >= 1", name="ck_customer_preferred_supplier_rank"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "supplier_id", name="uq_customer_preferred_supplier"),
        sa.UniqueConstraint("customer_id", "rank", name="uq_customer_preferred_supplier_rank"),
    )
    op.create_index("ix_customer_preferred_suppliers_organization_id", "customer_preferred_suppliers", ["organization_id"])
    op.create_index("ix_customer_preferred_supplier_supplier", "customer_preferred_suppliers", ["supplier_id"])


def downgrade() -> None:
    op.drop_table("customer_preferred_suppliers")
    op.drop_table("customer_notes")
