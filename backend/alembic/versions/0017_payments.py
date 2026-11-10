"""Payments (F12): Razorpay Pro subscription, Week Pass and the (flagged) outcome plan; GST-ready invoices

Revision ID: d2a6f1c8e357
Revises: b8e3c5a17d40
Create Date: 2026-11-10 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd2a6f1c8e357'
down_revision: Union[str, Sequence[str], None] = 'b8e3c5a17d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('plan_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('razorpay_subscription_id', sa.String(length=40), nullable=True))
    op.add_column('users', sa.Column('outcome_plan', sa.Boolean(), server_default='false', nullable=False))
    op.execute("CREATE SEQUENCE IF NOT EXISTS invoice_seq")
    op.create_table(
        'payments',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('plan', sa.String(length=20), nullable=False),  # pro_monthly | week_pass | outcome
        sa.Column('amount_inr', sa.Integer(), nullable=False),
        sa.Column('razorpay_id', sa.String(length=60), nullable=True, unique=True),  # payment id once paid
        sa.Column('razorpay_ref', sa.String(length=60), nullable=True, index=True),  # payment link / subscription id
        sa.Column('status', sa.String(length=20), server_default='created', nullable=False),  # created | paid | failed | cancelled
        sa.Column('invoice_number', sa.String(length=30), nullable=True, unique=True),
        sa.Column('invoice', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'payment_events',
        sa.Column('id', sa.String(length=80), primary_key=True),  # Razorpay x-razorpay-event-id: each webhook once
        sa.Column('event', sa.String(length=60), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('payment_events')
    op.drop_table('payments')
    op.execute("DROP SEQUENCE IF EXISTS invoice_seq")
    op.drop_column('users', 'outcome_plan')
    op.drop_column('users', 'razorpay_subscription_id')
    op.drop_column('users', 'plan_expires_at')
