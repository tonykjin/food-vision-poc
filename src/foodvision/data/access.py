"""Runtime check that an inference connection really cannot reach hidden labels.

Schema separation alone is not access control; this asks Postgres what the connected
role can actually do and refuses to run inference with evaluator-level access.
"""

from sqlalchemy import Connection, text


class InferenceIsolationError(PermissionError):
    pass


def assert_inference_isolation(conn: Connection) -> None:
    role = conn.execute(text("SELECT current_user")).scalar_one()
    superuser = conn.execute(
        text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    ).scalar_one()
    if superuser:
        raise InferenceIsolationError(f"inference connects as superuser {role!r}")
    if conn.execute(text("SELECT has_schema_privilege('benchmark', 'USAGE')")).scalar_one():
        raise InferenceIsolationError(f"role {role!r} has USAGE on schema benchmark")
    # Look tables up by OID: naming them would itself need USAGE on the schema.
    readable = (
        conn.execute(
            text(
                "SELECT n.nspname || '.' || c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'benchmark' AND c.relkind = 'r' "
                "AND has_table_privilege(c.oid, 'SELECT')"
            )
        )
        .scalars()
        .all()
    )
    if readable:
        raise InferenceIsolationError(f"role {role!r} can SELECT {sorted(readable)}")
