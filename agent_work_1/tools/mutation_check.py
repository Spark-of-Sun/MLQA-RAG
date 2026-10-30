"""Mutation controls for the G1.4 differential test (agent tooling, not part of the project).

Re-introduces known bugs into app_can_access in a scratch database and checks that the
differential comparison reports mismatches. A test that cannot fail proves nothing.
"""

import importlib.util
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path("/home/user/workspace/legal-medical-qa")
sys.path.insert(0, str(ROOT / "libs" / "lmqa_db" / "src"))
spec = importlib.util.spec_from_file_location(
    "diff", ROOT / "libs" / "lmqa_db" / "tests" / "test_policy_equals_oracle.py"
)
assert spec and spec.loader
diff = importlib.util.module_from_spec(spec)
sys.modules["diff"] = diff
spec.loader.exec_module(diff)

from lmqa_db.bootstrap import with_database  # noqa: E402
from lmqa_models import AccessContext, Document, Role, Visibility, decide  # noqa: E402
from lmqa_testing.pg import fresh_database, role_dsn, superuser_dsn  # noqa: E402

SQL = (ROOT / "db/policies/030_context.sql").read_text()
START = SQL.index("CREATE FUNCTION app_can_access(")
FUNCTION = SQL[START:]

MUTATIONS = {
    "DEF-02: rule 5 ignores visibility (tenant reads others' private docs in a granted matter)": (
        "IF v_role = 'tenant' AND p_visibility = 'matter' AND p_matter IS NOT NULL AND EXISTS (\n    SELECT 1 FROM matter_grants g",
        "IF v_role = 'tenant' AND p_matter IS NOT NULL AND EXISTS (\n    SELECT 1 FROM matter_grants g",
    ),
    "wall check removed (rule 2)": (
        "IF p_matter IS NOT NULL AND EXISTS (\n    SELECT 1 FROM matter_walls w",
        "IF false AND p_matter IS NOT NULL AND EXISTS (\n    SELECT 1 FROM matter_walls w",
    ),
    "tier ceiling ignored (rule 5)": (
        "AND g.max_tier >= p_tier AND (g.expires_at",
        "AND (g.expires_at",
    ),
    "grant expiry ignored (rule 5)": (
        "AND (g.expires_at IS NULL OR g.expires_at > now())\n  ) THEN\n    RETURN true;",
        "\n  ) THEN\n    RETURN true;",
    ),
    "emergency tier cap removed (rule 6)": ("AND p_tier <= 3 AND EXISTS", "AND EXISTS"),
    "break-glass needs only the flag (rule 7)": (
        "  ) AND EXISTS (\n    SELECT 1 FROM access_sessions s\n     WHERE s.workspace_id = v_ws AND s.user_id = v_user AND s.kind = 'break_glass'\n       AND s.state = 'active' AND s.expires_at > now()\n  ) THEN",
        "  ) THEN",
    ),
    "inactive membership still allowed (rule 1)": (
        "IF NOT app_actor_active() THEN\n    RETURN false;\n  END IF;\n  -- Rule 2",
        "-- Rule 2",
    ),
}


def mismatches_for(dbname: str, worlds: int) -> int:
    ingestion = psycopg.connect(role_dsn("svc_ingestion", dbname))
    bad = 0
    try:
        with psycopg.connect(with_database(superuser_dsn(), dbname), autocommit=True) as admin:
            for index in range(worlds):
                now = datetime.now(UTC)
                w = diff.build_world(admin, random.Random(index), now)
                for user, role in w.users():
                    ctx: AccessContext = diff.oracle_context(w, user, role, now)
                    want = {
                        d.id
                        for d in w.docs
                        if decide(
                            ctx, Document(d.owner, Visibility(d.visibility), d.tier, d.matter)
                        ).allow
                    }
                    got = diff.visible_ids(ingestion, w, user, role.value, "documents", "id")
                    bad += got != want
    finally:
        ingestion.close()
    return bad


def main() -> None:
    name = "lmqa_mutation"
    fresh_database(name)
    print(f"baseline (unmutated): {mismatches_for(name, 40)} mismatching (user, world) pairs")  # noqa: T201
    for label, (old, new) in MUTATIONS.items():
        assert old in FUNCTION, f"mutation target not found: {label}"
        fresh_database(name)
        with psycopg.connect(with_database(superuser_dsn(), name), autocommit=True) as admin:
            admin.execute(
                FUNCTION.replace(old, new, 1).replace(
                    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
                )
            )
        print(f"mutation [{label}]: {mismatches_for(name, 40)} mismatching pairs")  # noqa: T201


if __name__ == "__main__":
    main()
