"""Add iterations table for iterative mission planning

Revision ID: 004_add_iterations
Revises: 003_add_tool_approvals
Create Date: 2025-12-30 15:47:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_add_iterations'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    # Create iterations table
    op.create_table(
        'iterations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mission_id', sa.Integer(), nullable=False),
        sa.Column('iteration_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('plan', postgresql.JSONB(), nullable=False),
        sa.Column('findings_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mission_id', 'iteration_number', name='uq_mission_iteration')
    )
    
    # Create index for fast lookups
    op.create_index('idx_iterations_mission', 'iterations', ['mission_id', 'iteration_number'])
    
    # Add iteration tracking columns to missions table
    op.add_column('missions', sa.Column('current_iteration_id', sa.Integer(), nullable=True))
    op.add_column('missions', sa.Column('total_iterations', sa.Integer(), nullable=False, server_default='0'))
    
    # Add foreign key constraint for current_iteration_id
    op.create_foreign_key(
        'fk_missions_current_iteration',
        'missions', 'iterations',
        ['current_iteration_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    # Remove foreign key constraint
    op.drop_constraint('fk_missions_current_iteration', 'missions', type_='foreignkey')
    
    # Remove columns from missions
    op.drop_column('missions', 'total_iterations')
    op.drop_column('missions', 'current_iteration_id')
    
    # Drop index
    op.drop_index('idx_iterations_mission', table_name='iterations')
    
    # Drop iterations table
    op.drop_table('iterations')
