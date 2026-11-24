"""Database access. `scoped(connect(service), claims)`, `Database.scoped()` and `ServiceDatabase.scoped()` are the
only ways to run statements at runtime (10.3). `connect_role` is the direct connection for tools and migrations."""

from lmqa_db.database import Database, Row, Scope
from lmqa_db.direct import connect_role, dsn
from lmqa_db.pool import SERVICE_ROLES, Claims, MissingContextError, connect, scoped
from lmqa_db.service import (
    BootSelfTestError,
    OrgRouter,
    ScopeContext,
    ServiceDatabase,
    StalePrincipalError,
)

__all__ = [
    "SERVICE_ROLES",
    "BootSelfTestError",
    "Claims",
    "Database",
    "MissingContextError",
    "OrgRouter",
    "Row",
    "Scope",
    "ScopeContext",
    "ServiceDatabase",
    "StalePrincipalError",
    "connect",
    "connect_role",
    "dsn",
    "scoped",
]
