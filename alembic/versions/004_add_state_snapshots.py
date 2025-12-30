"""
Add state_snapshots table for state management system

Revision ID: 004
Revises: 003
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

def upgrade():
    """Add state_snapshots table for multi-scope state management"""
    
    # Create state_snapshots table
    op.create_table(
        'state_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('scope', sa.String(50), nullable=False, index=True,
                  comment='State scope: global, mission, agent, checkpoint'),
        sa.Column('scope_id', sa.String(255), nullable=False, index=True,
                  comment='ID for the scope: mission_id, agent_id, or "global"'),
        sa.Column('key', sa.String(255), nullable=False, index=True,
                  comment='State key identifier'),
        sa.Column('value', postgresql.JSONB, nullable=False,
                  comment='State value as JSONB'),
        sa.Column('version', sa.Integer(), nullable=False, default=1,
                  comment='Version number for this state key'),
        sa.Column('metadata', postgresql.JSONB, nullable=True,
                  comment='Optional metadata (timestamp, source, etc.)'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()'), index=True),
    )
    
    # Create composite index for fast lookups
    op.create_index(
        'idx_state_lookup',
        'state_snapshots',
        ['scope', 'scope_id', 'key', 'version'],
        unique=False
    )
    
    # Create index for checkpoint queries
    op.create_index(
        'idx_state_checkpoints',
        'state_snapshots',
        ['scope', 'scope_id', 'created_at'],
        unique=False,
        postgresql_where=sa.text("scope = 'checkpoint'")
    )
    
    print("✅ Created state_snapshots table with indices")

def downgrade():
    """Remove state_snapshots table"""
    op.drop_index('idx_state_checkpoints', table_name='state_snapshots')
    op.drop_index('idx_state_lookup', table_name='state_snapshots')
    op.drop_table('state_snapshots')
    print("✅ Dropped state_snapshots table")
