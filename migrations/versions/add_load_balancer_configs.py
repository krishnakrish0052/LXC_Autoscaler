"""add load_balancer_configs table

Revision ID: 123456789abc
Revises: d6e95a1b6436
Create Date: 2025-04-18 17:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '123456789abc'
down_revision = 'd6e95a1b6436'
branch_labels = None
depends_on = None


def upgrade():
    # Create load_balancer_configs table
    op.create_table(
        'load_balancer_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('container_image', sa.String(length=255), nullable=False, server_default='ubuntu:20.04'),
        sa.Column('static_ip', sa.String(length=255), nullable=True),
        sa.Column('network_bridge', sa.String(length=255), nullable=False, server_default='lxdbr0'),
        sa.Column('port', sa.Integer(), nullable=False, server_default='80'),
        sa.Column('algorithm', sa.String(length=50), nullable=False, server_default='round_robin'),
        sa.Column('configuration', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )


def downgrade():
    # Drop load_balancer_configs table
    op.drop_table('load_balancer_configs')