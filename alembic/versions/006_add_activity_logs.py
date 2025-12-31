"""
Add activity_logs table for persistent activity feed

Revision ID: 006_add_activity_logs
Revises: 005_add_state_snapshots
Create Date: 2025-12-31 08:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006_add_activity_logs'
down_revision = '005_add_state_snapshots'
branch_labels = None
depends_on = None

def upgrade():
    """Add activity_logs table for mission activity feed persistence"""
    
    # Create activity_logs table
    op.create_table(
        'activity_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mission_id', sa.Integer(), nullable=False, index=True,
                  comment='Reference to missions table'),
        sa.Column('message', sa.Text(), nullable=False,
                  comment='Activity message displayed in feed'),
        sa.Column('message_type', sa.String(50), nullable=False, server_default='log',
                  comment='Type: log, error, success, warning, info'),
        sa.Column('screenshot_path', sa.Text(), nullable=True,
                  comment='Path to screenshot if attached'),
        sa.Column('metadata', postgresql.JSONB, nullable=True,
                  comment='Additional context: step_id, runbook_name, etc.'),
        sa.Column('timestamp', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()'), index=True),
    )
    
    # Add foreign key to missions table
    op.create_foreign_key(
        'fk_activity_logs_mission',
        'activity_logs', 'missions',
        ['mission_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # Create composite index for efficient mission + timestamp queries
    op.create_index(
        'idx_activity_logs_mission_timestamp',
        'activity_logs',
        ['mission_id', 'timestamp'],
        unique=False
    )
    
    print("✅ Created activity_logs table with indices and foreign key")

def downgrade():
    """Remove activity_logs table"""
    op.drop_index('idx_activity_logs_mission_timestamp', table_name='activity_logs')
    op.drop_constraint('fk_activity_logs_mission', 'activity_logs', type_='foreignkey')
    op.drop_table('activity_logs')
    print("✅ Dropped activity_logs table")
