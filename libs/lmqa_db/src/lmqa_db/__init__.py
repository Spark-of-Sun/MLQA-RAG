"""Database access. `Database.scoped()` is the only way to read content (blueprint 10.3)."""

from lmqa_db.database import Database, Row, Scope

__all__ = ["Database", "Row", "Scope"]
