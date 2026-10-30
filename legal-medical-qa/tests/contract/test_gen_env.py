"""tools/gen_env.py: strong, distinct local secrets; third-party values stay placeholders."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.stage0]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    out = tmp_path_factory.mktemp("env") / "generated.env"
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "tools" / "gen_env.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr
    pairs = (
        line.split("=", 1)
        for line in out.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    return {k.strip(): v.split("#", 1)[0].strip() for k, v in pairs}


def test_every_service_secret_is_a_distinct_64_hex_value(generated: dict[str, str]) -> None:
    secrets_ = [
        v
        for k, v in generated.items()
        if k.startswith("SVC_SECRET_")
        or k in {"CODE_PEPPER_V1", "GATEWAY_RESUME_KEY", "AUTH0_SESSION_SECRET"}
    ]
    assert len(secrets_) >= 10
    assert all(re.fullmatch(r"[0-9a-f]{64}", v) for v in secrets_)
    assert len(set(secrets_)) == len(secrets_), "no two secrets may be equal"


def test_each_database_password_is_generated_and_shared_between_a_dsn_and_its_worker_dsn(
    generated: dict[str, str],
) -> None:
    def password(name: str) -> str:
        return re.search(r"://[^:]+:([^@]+)@", generated[name]).group(1)  # type: ignore[union-attr]

    assert password("PG_DSN_INGESTION") == password("PG_DSN_WORKER")
    names = [
        "PG_DSN_GATEWAY",
        "PG_DSN_IDENTITY",
        "PG_DSN_INGESTION",
        "PG_DSN_RETRIEVAL",
        "PG_DSN_GENERATION",
        "PG_DSN_VALIDATOR",
        "PG_DSN_AUDIT",
        "PG_DSN_OPS",
        "PG_MIGRATION_DSN",
    ]
    passwords = [password(n) for n in names]
    assert len(set(passwords)) == len(passwords), "one distinct password per role"
    assert all(len(p) >= 24 and "<" not in p for p in passwords)


def test_third_party_credentials_remain_placeholders(generated: dict[str, str]) -> None:
    for name in (
        "AUTH0_CLIENT_SECRET_BFF",
        "AUTH0_M2M_CLIENT_SECRET",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "SMTP_PASSWORD",
        "HF_TOKEN",
    ):
        assert generated[name].startswith("<"), f"{name} must stay a placeholder"


def test_qdrant_and_object_store_values_are_consistent_where_they_repeat(
    generated: dict[str, str],
) -> None:
    assert generated["QDRANT_KEY_RW"] != generated["QDRANT_KEY_RO"]
    assert generated["POSTGRES_SUPERUSER_PASSWORD"] in generated["POSTGRES_SUPERUSER_DSN"]
    assert generated["OBJECT_STORE_CREDS_INGESTION_ACCESS_KEY"]
    assert not generated["OBJECT_STORE_CREDS_INGESTION_SECRET_KEY"].startswith("<")


def test_the_generator_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "x.env"
    target.write_text("keep me")
    done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [sys.executable, str(ROOT / "tools" / "gen_env.py"), "--out", str(target)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert done.returncode == 1
    assert target.read_text() == "keep me"
