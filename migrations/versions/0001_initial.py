"""Create the initial EventFlow schema from the canonical SQL migration."""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    source = Path(__file__).resolve().parents[2] / "db" / "001_initial.sql"
    # Alembic owns the transaction. The SQL file remains runnable through psql.
    sql = source.read_text(encoding="utf-8").strip()
    if not sql.startswith("BEGIN;") or not sql.endswith("COMMIT;"):
        raise RuntimeError("Unexpected transaction boundaries in initial SQL")
    op.get_bind().exec_driver_sql(sql[len("BEGIN;") : -len("COMMIT;")])


def downgrade():
    for table in ("registrations", "activities", "rooms", "events", "users"):
        op.drop_table(table)
    # btree_gist may be shared with other schemas; leave the extension installed.
