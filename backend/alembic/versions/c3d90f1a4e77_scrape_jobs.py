"""scrape jobs

Revision ID: c3d90f1a4e77
Revises: 8b21c4f0d7ae
Create Date: 2026-07-30 21:05:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d90f1a4e77'
down_revision: Union[str, None] = '8b21c4f0d7ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scrape_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.Enum('UPLOADED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', name='scrapejobstatus'), nullable=False),
        sa.Column('total_records', sa.Integer(), nullable=False),
        sa.Column('processed_records', sa.Integer(), nullable=False),
        sa.Column('fields_filled', sa.Integer(), nullable=False),
        sa.Column('records_with_findings', sa.Integer(), nullable=False),
        sa.Column('current_business', sa.String(length=255), nullable=True),
        sa.Column('source_report', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_by_email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scrape_jobs_project_id'), 'scrape_jobs', ['project_id'])
    op.create_index(op.f('ix_scrape_jobs_status'), 'scrape_jobs', ['status'])

    with op.batch_alter_table('validation_records') as batch:
        batch.add_column(sa.Column('job_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('scrape_state', sa.String(length=30), nullable=True))
        batch.add_column(sa.Column('scrape_findings', sa.JSON(), nullable=True))
        batch.drop_constraint('uq_validation_project_row', type_='unique')
        batch.create_unique_constraint('uq_validation_project_row', ['project_id', 'job_id', 'source_row'])
        batch.create_foreign_key('fk_validation_records_job', 'scrape_jobs', ['job_id'], ['id'])
    op.create_index(op.f('ix_validation_records_job_id'), 'validation_records', ['job_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_validation_records_job_id'), table_name='validation_records')
    with op.batch_alter_table('validation_records') as batch:
        batch.drop_constraint('fk_validation_records_job', type_='foreignkey')
        batch.drop_constraint('uq_validation_project_row', type_='unique')
        batch.create_unique_constraint('uq_validation_project_row', ['project_id', 'source_row'])
        batch.drop_column('scrape_findings')
        batch.drop_column('scrape_state')
        batch.drop_column('job_id')
    op.drop_index(op.f('ix_scrape_jobs_status'), table_name='scrape_jobs')
    op.drop_index(op.f('ix_scrape_jobs_project_id'), table_name='scrape_jobs')
    op.drop_table('scrape_jobs')
