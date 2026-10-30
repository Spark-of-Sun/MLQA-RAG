"""Scoped database access, boot self-test and bootstrap helpers."""

from lmqa_db.bootstrap import LOGIN_ROLES, bootstrap_database, set_role_passwords
from lmqa_db.context import ContextRole, DbContext, MissingContextError
from lmqa_db.selftest import SelfTestError, boot_self_test
from lmqa_db.session import Database, to_async_url

__all__ = [
    "LOGIN_ROLES",
    "ContextRole",
    "Database",
    "DbContext",
    "MissingContextError",
    "SelfTestError",
    "boot_self_test",
    "bootstrap_database",
    "set_role_passwords",
    "to_async_url",
]
