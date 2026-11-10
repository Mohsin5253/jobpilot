"""Clear subscription ids recorded at checkout for subscriptions that were never activated or paid

Until now starting a Pro checkout marked the account as subscribed straight away, which hid the buy buttons even if
the student never completed the payment. Accounts are now marked only when Razorpay confirms the subscription.

Revision ID: 2b8d4f0a6c35
Revises: 1a7c3e9f5b24
Create Date: 2026-11-11 05:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = '2b8d4f0a6c35'
down_revision: Union[str, Sequence[str], None] = '1a7c3e9f5b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET razorpay_subscription_id = NULL WHERE razorpay_subscription_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM payments p WHERE p.user_id = users.id AND p.plan = 'pro_monthly' AND p.status = 'paid')"
    )


def downgrade() -> None:
    pass
