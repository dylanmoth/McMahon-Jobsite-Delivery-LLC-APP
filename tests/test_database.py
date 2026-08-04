from sqlalchemy import inspect


def test_foundation_tables_are_created(database) -> None:
    names = set(inspect(database.engine).get_table_names())
    assert {
        "organizations",
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "audit_events",
        "customers",
        "quotes",
        "jobs",
        "invoices",
        "sync_queue",
    } <= names
