"""Create roles and the database, then apply db/migrations, db/policies and db/roles/grants.sql."""

from __future__ import annotations

import sys

from lmqa_db.migrate import migrate
from lmqa_models.settings import load_settings


def main() -> int:
    settings = load_settings()
    applied = migrate(settings)
    print(f"database {settings.db_name}: {len(applied)} new migration(s) {applied or ''}; policies and grants applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
