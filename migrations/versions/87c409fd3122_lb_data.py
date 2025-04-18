"""Add load balancer and target tables

Revision ID: 87c409fd3122
Revises: f5aa0ae43659
Create Date: 2025-04-16 08:15:24.342189

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '87c409fd3122'
down_revision = 'f5aa0ae43659'
branch_labels = None
depends_on = None

def upgrade():
    # Create load_balancers table
    op.create_table(
        'load_balancers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('algorithm', sa.String(length=50), nullable=True),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create load_balancer_targets table
    op.create_table(
        'load_balancer_targets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('load_balancer_id', sa.Integer(), nullable=False),
        sa.Column('container_name', sa.String(length=255), nullable=False),
        sa.Column('ip_address', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('health_status', sa.String(length=50), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['load_balancer_id'], ['load_balancers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_table('load_balancer_targets')
    op.drop_table('load_balancers')