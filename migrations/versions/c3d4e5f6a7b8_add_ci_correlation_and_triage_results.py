"""add TestRun CI correlation fields and standalone triage_results

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('test_runs', sa.Column('ci_provider', sa.String(), nullable=True))
    op.add_column('test_runs', sa.Column('ci_repository', sa.String(), nullable=True))
    op.add_column('test_runs', sa.Column('ci_run_id', sa.String(), nullable=True))
    op.create_index(
        'ix_test_runs_ci_correlation',
        'test_runs',
        ['ci_provider', 'ci_repository', 'ci_run_id'],
        unique=False,
    )

    op.create_table(
        'triage_results',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('repository', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('triage_state', sa.String(), nullable=False),
        sa.Column('pipeline_name', sa.String(), nullable=True),
        sa.Column('pipeline_status', sa.String(), nullable=True),
        sa.Column('failed_job', sa.String(), nullable=True),
        sa.Column('failed_step', sa.String(), nullable=True),
        sa.Column('classification', sa.String(), nullable=True),
        sa.Column('subtype', sa.String(), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('probable_cause', sa.Text(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('recommended_action', sa.Text(), nullable=True),
        sa.Column('human_review_required', sa.Boolean(), nullable=True),
        sa.Column('analysis_mode', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('provider', 'repository', 'run_id', name='uq_triage_results_correlation'),
    )
    op.create_index(op.f('ix_triage_results_id'), 'triage_results', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_triage_results_id'), table_name='triage_results')
    op.drop_table('triage_results')
    op.drop_index('ix_test_runs_ci_correlation', table_name='test_runs')
    op.drop_column('test_runs', 'ci_run_id')
    op.drop_column('test_runs', 'ci_repository')
    op.drop_column('test_runs', 'ci_provider')
