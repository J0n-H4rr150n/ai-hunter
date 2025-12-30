"""Add tool approvals and settings for HITL training

Revision ID: 003
Revises: 002
Create Date: 2025-12-30 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

# Custom type for pgvector
class Vector(UserDefinedType):
    cache_ok = True
    
    def __init__(self, dim):
        self.dim = dim
    
    def get_col_spec(self):
        return f"vector({self.dim})"

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Settings table for global and per-mission configuration
    op.create_table('settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),  # NULL = global settings
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mission_id', 'key', name='uq_settings_mission_key')
    )
    op.create_index('idx_settings_mission', 'settings', ['mission_id'])
    
    # Tool approvals table for HITL feedback with vector embeddings
    op.create_table('tool_approvals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('tool_name', sa.String(length=100), nullable=False),
        sa.Column('tool_inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),  # Mission state, current step, etc.
        sa.Column('screenshot_path', sa.Text(), nullable=True),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('edited_inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),  # If human edited the tool call
        sa.Column('feedback', sa.Text(), nullable=True),  # Human's reason for approval/rejection
        sa.Column('embedding', Vector(384), nullable=True),  # Vector embedding of context+feedback for RAG
        sa.Column('response_time_ms', sa.Integer(), nullable=True),  # How long human took to respond
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_approvals_mission', 'tool_approvals', ['mission_id'])
    op.create_index('idx_approvals_tool', 'tool_approvals', ['tool_name'])
    op.create_index('idx_approvals_approved', 'tool_approvals', ['approved'])
    # Create vector index for similarity search on feedback
    op.execute("CREATE INDEX idx_approvals_embedding ON tool_approvals USING ivfflat (embedding vector_cosine_ops)")
    
    # Insert default global settings
    op.execute("""
        INSERT INTO settings (mission_id, key, value) VALUES
        (NULL, 'hitl_enabled', '{"enabled": false, "approve_all_tools": false}'::jsonb),
        (NULL, 'auto_approve_tools', '["view_raw_source", "check_network", "view_dom"]'::jsonb),
        (NULL, 'ui_theme', '{"mode": "dark"}'::jsonb)
    """)


def downgrade() -> None:
    op.drop_table('tool_approvals')
    op.drop_table('settings')
