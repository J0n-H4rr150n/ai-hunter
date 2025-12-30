"""Add LLM tracing table

Revision ID: 002
Revises: 001
Create Date: 2025-12-30 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LLM traces for complete observability
    op.create_table('llm_traces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trace_id', sa.String(length=100), nullable=False),
        sa.Column('parent_trace_id', sa.String(length=100), nullable=True),
        sa.Column('session_id', sa.String(length=100), nullable=True),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        
        # Model configuration
        sa.Column('llm_model', sa.String(length=100), nullable=False),
        sa.Column('llm_provider', sa.String(length=50), nullable=True),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('top_p', sa.Float(), nullable=True),
        sa.Column('max_tokens', sa.Integer(), nullable=True),
        
        # Input
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('user_prompt', sa.Text(), nullable=True),
        sa.Column('conversation_history', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('input_characters', sa.Integer(), nullable=True),
        
        # Output
        sa.Column('llm_response', sa.Text(), nullable=True),
        sa.Column('llm_reasoning', sa.Text(), nullable=True),
        sa.Column('llm_decision', sa.Text(), nullable=True),
        sa.Column('llm_confidence', sa.Float(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('output_characters', sa.Integer(), nullable=True),
        
        # Performance
        sa.Column('timestamp_start', sa.TIMESTAMP(), nullable=False),
        sa.Column('timestamp_end', sa.TIMESTAMP(), nullable=True),
        sa.Column('elapsed_time_ms', sa.Integer(), nullable=True),
        sa.Column('tokens_per_second', sa.Float(), nullable=True),
        
        # Quality & Safety
        sa.Column('safety_scores', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('safety_blocked', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('finish_reason', sa.String(length=50), nullable=True),
        
        # Cost & Usage
        sa.Column('estimated_cost_usd', sa.Float(), nullable=True),
        sa.Column('request_id', sa.String(length=200), nullable=True),
        
        # Error Handling
        sa.Column('status', sa.String(length=50), nullable=False, server_default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('fallback_used', sa.Boolean(), nullable=True, server_default='false'),
        
        # Agent Context
        sa.Column('agent_name', sa.String(length=100), nullable=True),
        sa.Column('agent_state_before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('agent_state_after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tools_available', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('tools_called', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('memory_retrieved', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        
        # Debugging
        sa.Column('raw_request', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('environment', sa.String(length=20), nullable=True, server_default='development'),
        
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes for performance
    op.create_index('idx_llm_traces_trace_id', 'llm_traces', ['trace_id'])
    op.create_index('idx_llm_traces_mission', 'llm_traces', ['mission_id'])
    op.create_index('idx_llm_traces_agent', 'llm_traces', ['agent_name'])
    op.create_index('idx_llm_traces_model', 'llm_traces', ['llm_model'])
    op.create_index('idx_llm_traces_status', 'llm_traces', ['status'])
    op.create_index('idx_llm_traces_timestamp', 'llm_traces', [sa.text('timestamp_start DESC')])
    op.create_index('idx_llm_traces_confidence', 'llm_traces', ['llm_confidence'])


def downgrade() -> None:
    op.drop_table('llm_traces')
