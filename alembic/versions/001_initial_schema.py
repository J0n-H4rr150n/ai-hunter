"""Initial schema with full observability

Revision ID: 001
Revises: 
Create Date: 2025-12-30 09:00:00.000000

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
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Missions table
    op.create_table('missions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('target_url', sa.Text(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, server_default='pending'),
        sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_missions_status', 'missions', ['status'])
    
    # Agent thoughts
    op.create_table('agent_thoughts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('thought_text', sa.Text(), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_thoughts_mission', 'agent_thoughts', ['mission_id'])
    
    # Agent actions
    op.create_table('agent_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(length=100), nullable=False),
        sa.Column('action_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('screenshot_path', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_actions_mission', 'agent_actions', ['mission_id'])
    op.create_index('idx_actions_created', 'agent_actions', [sa.text('created_at DESC')])
    
    # Tool executions
    op.create_table('tool_executions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('tool_name', sa.String(length=100), nullable=False),
        sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('outputs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('raw_output_path', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, server_default='running'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tools_mission', 'tool_executions', ['mission_id'])
    
    # Network traffic
    op.create_table('network_traffic',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('request_headers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response_headers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('request_body', sa.Text(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_network_mission', 'network_traffic', ['mission_id'])
    
    # Findings with vector embeddings
    op.create_table('findings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('finding_type', sa.String(length=100), nullable=True),
        sa.Column('source', sa.String(length=100), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('embedding', Vector(512), nullable=True),  # TensorFlow USE
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_findings_mission', 'findings', ['mission_id'])
    # Create vector index for similarity search
    op.execute("CREATE INDEX idx_findings_embedding ON findings USING ivfflat (embedding vector_cosine_ops)")
    
    # Human interactions
    op.create_table('human_interactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('interaction_type', sa.String(length=50), nullable=True),
        sa.Column('question', sa.Text(), nullable=True),
        sa.Column('response', sa.Text(), nullable=True),
        sa.Column('context_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('context_image', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Artifacts
    op.create_table('artifacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('artifact_type', sa.String(length=50), nullable=True),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Agent memory for RAG
    op.create_table('agent_memory',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=True),
        sa.Column('memory_type', sa.String(length=50), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(512), nullable=True),  # TensorFlow USE
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('relevance_score', sa.Float(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Create vector index for memory search
    op.execute("CREATE INDEX idx_memory_embedding ON agent_memory USING ivfflat (embedding vector_cosine_ops)")
    
    # Create updated_at trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    # Apply trigger to missions table
    op.execute("""
        CREATE TRIGGER update_missions_updated_at BEFORE UPDATE ON missions
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('agent_memory')
    op.drop_table('artifacts')
    op.drop_table('human_interactions')
    op.drop_table('findings')
    op.drop_table('network_traffic')
    op.drop_table('tool_executions')
    op.drop_table('agent_actions')
    op.drop_table('agent_thoughts')
    op.drop_table('missions')
    
    # Drop trigger and function
    op.execute('DROP TRIGGER IF EXISTS update_missions_updated_at ON missions')
    op.execute('DROP FUNCTION IF EXISTS update_updated_at_column()')
    
    # Drop extension
    op.execute('DROP EXTENSION IF EXISTS vector')
