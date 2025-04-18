"""merge multiple heads

Revision ID: d6e95a1b6436
Revises: 18a831a42368, 87c409fd3122
Create Date: 2025-04-16 12:06:52.911922

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd6e95a1b6436'
down_revision = ('18a831a42368', '87c409fd3122')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
