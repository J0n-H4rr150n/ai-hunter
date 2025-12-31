"""Add attack patterns tables for RAG system

Revision ID: 007_add_attack_patterns
Revises: 006_add_activity_logs
Create Date: 2025-12-31 10:41:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007_add_attack_patterns'
down_revision = '006_add_activity_logs'
branch_labels = None
depends_on = None




def upgrade():
    # Ensure pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    # Create attack_patterns table with vector embeddings
    op.execute("""
        CREATE TABLE attack_patterns (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            description TEXT,
            difficulty VARCHAR(50),
            tags TEXT[],
            embedding vector(512),
            success_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    
    # Create index for vector similarity search
    op.execute(
        "CREATE INDEX idx_patterns_embedding ON attack_patterns USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    
    # Create index for tags
    op.create_index('idx_patterns_tags', 'attack_patterns', ['tags'], postgresql_using='gin')
    
    # Create pattern_steps table
    op.create_table(
        'pattern_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern_id', sa.Integer(), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('tool', sa.String(100), nullable=True),
        sa.Column('expected_result', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['pattern_id'], ['attack_patterns.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pattern_id', 'step_number', name='uq_pattern_step')
    )
    
    # Create index for pattern lookups
    op.create_index('idx_pattern_steps_pattern', 'pattern_steps', ['pattern_id'])
    
    # Create pattern_indicators table
    op.create_table(
        'pattern_indicators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern_id', sa.Integer(), nullable=False),
        sa.Column('indicator', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['pattern_id'], ['attack_patterns.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create index for pattern lookups
    op.create_index('idx_pattern_indicators_pattern', 'pattern_indicators', ['pattern_id'])
    
    # Create pattern_usage tracking table
    op.create_table(
        'pattern_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern_id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=False),
        sa.Column('iteration_id', sa.Integer(), nullable=True),
        sa.Column('was_successful', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['pattern_id'], ['attack_patterns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['iteration_id'], ['iterations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for usage tracking
    op.create_index('idx_pattern_usage_pattern', 'pattern_usage', ['pattern_id'])
    op.create_index('idx_pattern_usage_mission', 'pattern_usage', ['mission_id'])


def downgrade():
    # Drop tables in reverse order
    op.drop_index('idx_pattern_usage_mission', table_name='pattern_usage')
    op.drop_index('idx_pattern_usage_pattern', table_name='pattern_usage')
    op.drop_table('pattern_usage')
    
    op.drop_index('idx_pattern_indicators_pattern', table_name='pattern_indicators')
    op.drop_table('pattern_indicators')
    
    op.drop_index('idx_pattern_steps_pattern', table_name='pattern_steps')
    op.drop_table('pattern_steps')
    
    op.drop_index('idx_patterns_tags', table_name='attack_patterns')
    op.drop_index('idx_patterns_embedding', table_name='attack_patterns')
    op.drop_table('attack_patterns')
