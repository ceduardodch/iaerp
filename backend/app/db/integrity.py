from collections.abc import Iterator

from sqlalchemy.exc import IntegrityError

UNIQUE_VIOLATION_SQLSTATE = "23505"
SQLITE_UNIQUE_ERROR_CODES = {1555, 2067}


def _error_chain(exc: IntegrityError) -> Iterator[BaseException]:
    current: BaseException | None = exc.orig
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_unique_violation(exc: IntegrityError) -> bool:
    return any(
        (getattr(error, "sqlstate", None) or getattr(error, "pgcode", None))
        == UNIQUE_VIOLATION_SQLSTATE
        or getattr(error, "sqlite_errorcode", None) in SQLITE_UNIQUE_ERROR_CODES
        for error in _error_chain(exc)
    )


def integrity_sqlstate(exc: IntegrityError) -> str | None:
    for error in _error_chain(exc):
        sqlstate = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
        if isinstance(sqlstate, str):
            return sqlstate
    return None


def unique_constraint_name(exc: IntegrityError) -> str | None:
    """Return the violated unique constraint across psycopg/asyncpg adapters."""
    for current in _error_chain(exc):
        sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        constraint = getattr(current, "constraint_name", None)
        if constraint is None:
            constraint = getattr(getattr(current, "diag", None), "constraint_name", None)
        if sqlstate == UNIQUE_VIOLATION_SQLSTATE and isinstance(constraint, str):
            return constraint
    return None
