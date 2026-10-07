"""benchmark reference loading (POC-12)

- benchmark.samples.expected_outcome: 'estimate' or 'abstain' (abstaining is the correct
  answer for some difficult inputs, plan §11).
- fv_evaluator may INSERT into telemetry.images so the evaluator can register benchmark photos
  (metadata only: object key, hashes, consent, retention). Images are not labels; the
  inference role's access is unchanged and it still has nothing on schema benchmark.
  See docs/decisions/0002-evaluator-registers-benchmark-images.md.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "samples",
        sa.Column("expected_outcome", sa.Text(), server_default="estimate", nullable=False),
        schema="benchmark",
    )
    op.create_check_constraint(
        op.f("ck_samples_expected_outcome"),
        "samples",
        "expected_outcome IN ('estimate', 'abstain')",
        schema="benchmark",
    )
    op.execute("GRANT INSERT ON telemetry.images TO fv_evaluator")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON telemetry.images FROM fv_evaluator")
    op.drop_constraint(
        op.f("ck_samples_expected_outcome"), "samples", schema="benchmark", type_="check"
    )
    op.drop_column("samples", "expected_outcome", schema="benchmark")
