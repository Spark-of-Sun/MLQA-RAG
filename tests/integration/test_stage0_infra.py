"""G0.4 infrastructure smoke and the local parts of G0.9, against the running stack (`make up`)."""

from __future__ import annotations

import base64
import json
import secrets
import shutil
import subprocess
import uuid

import httpx
import pytest
import valkey

from lmqa_db import connect_role as connect
from lmqa_models.infra import VALKEY_USERS, load_infra_settings
from lmqa_models.settings import load_settings
from lmqa_testing import infra as probes
from lmqa_testing.tools import load_tool

pytestmark = [pytest.mark.stage0, pytest.mark.integration]

DEFAULT_SERVICES = ("postgres", "pgbouncer", "valkey", "qdrant", "seaweedfs", "openbao")


def _container_health(name: str) -> str:
    docker = shutil.which("docker")
    assert docker, "docker is required for the infrastructure gate"
    out = subprocess.run(  # noqa: S603 - fixed docker argv
        [docker, "ps", "--filter", f"name=^lmqa-{name}$", "--format", "{{.Status}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.mark.parametrize("service", DEFAULT_SERVICES)
def test_every_container_is_healthy(service: str) -> None:
    status = _container_health(service)
    assert "(healthy)" in status, f"lmqa-{service}: {status or 'not running'} (run make up)"


def test_server_versions_match_the_ledger() -> None:
    gen_versions = load_tool("gen_versions")
    ledger = gen_versions.read_ledger()["Servers"]
    running = probes.server_versions()
    assert running == ledger, (
        "a running server differs from docs/versions.md (run make versions after review)"
    )
    assert running["postgresql"].startswith("18."), "PostgreSQL 18 (D22)"
    assert running["valkey"].startswith("9."), "Valkey 9 (D20)"


# --- PgBouncer: transaction pooling must not carry context between transactions (4.8, G1.7 preview) ----------


def test_pgbouncer_transaction_pooling_keeps_context_transaction_local() -> None:
    settings = load_settings()
    principal = str(uuid.uuid4())
    with connect(settings, "lmqa_app", via_pooler=True, connect_timeout=5) as conn:
        with conn.transaction():
            conn.execute("select set_config('app.user_id', %s, true)", [principal])
            inside = conn.execute("select current_setting('app.user_id', true)").fetchone()
        after = conn.execute("select nullif(current_setting('app.user_id', true), '')").fetchone()
        conn.commit()
    assert inside == (principal,)
    assert after == (None,), "a transaction-local setting survived into the next pooled transaction"


def test_pgbouncer_supports_prepared_statements() -> None:
    settings = load_settings()
    with connect(settings, "lmqa_app", via_pooler=True, connect_timeout=5) as conn:
        values = [
            conn.execute("select %s::int + 1", [i], prepare=True).fetchone() for i in range(10)
        ]
        conn.commit()
    assert values == [(i + 1,) for i in range(10)]


def test_pgbouncer_refuses_unknown_and_owner_roles() -> None:
    settings = load_settings()
    infra = load_infra_settings()
    owner = settings.dsn("lmqa_owner", host=infra.pgbouncer_host, port=infra.pgbouncer_port)
    import psycopg

    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(owner, connect_timeout=5).close()  # noqa: TID251 - proves a direct owner connection is refused


# --- Valkey: per-service ACL users, default user disabled, dangerous commands refused (4.2, D20) ---------------


def test_valkey_default_user_is_disabled() -> None:
    infra = load_infra_settings()
    client = valkey.Valkey.from_url(infra.valkey_url, socket_timeout=5)
    with pytest.raises((valkey.exceptions.AuthenticationError, valkey.exceptions.ResponseError)):
        client.set("lmqa-test:anonymous", "1")


@pytest.mark.parametrize("user", [u for u in VALKEY_USERS if u != "doctor"])
def test_valkey_users_cannot_run_dangerous_commands(user: str) -> None:
    with probes.valkey_client(user) as client:
        assert client.acl_whoami() == user
        with pytest.raises(valkey.exceptions.NoPermissionError):
            client.flushall()
        with pytest.raises(valkey.exceptions.NoPermissionError):
            client.config_get("*")


def test_valkey_key_patterns_confine_each_service() -> None:
    key = f"lmqa-test:{secrets.token_hex(4)}"
    with probes.valkey_client("test") as client:
        client.set(key, "v", ex=30)
        assert client.get(key) == b"v"
        client.delete(key)
    with (
        probes.valkey_client("generation") as client,
        pytest.raises(valkey.exceptions.NoPermissionError),
    ):
        client.get("sess:someone-elses-session")
    with (
        probes.valkey_client("frontend") as client,
        pytest.raises(valkey.exceptions.NoPermissionError),
    ):
        client.get("cache:answer")
    with (
        probes.valkey_client("doctor") as client,
        pytest.raises(valkey.exceptions.NoPermissionError),
    ):
        client.get(key)


def test_valkey_pubsub_channels_are_scoped() -> None:
    with probes.valkey_client("identity") as client:
        assert client.publish("revocation:principal", "probe") >= 0
    with (
        probes.valkey_client("retrieval") as client,
        pytest.raises(valkey.exceptions.NoPermissionError),
    ):
        client.publish("revocation:principal", "forged")


# --- Qdrant: read-only versus read-write keys (4.8, G5.1 preview) ----------------------------------------------


def test_qdrant_keys_are_enforced() -> None:
    infra = load_infra_settings()
    name = f"lmqa_probe_{secrets.token_hex(4)}"
    body = {"vectors": {"size": 4, "distance": "Cosine"}}
    url = f"{infra.qdrant_url}/collections/{name}"
    anonymous = httpx.get(f"{infra.qdrant_url}/collections", timeout=5)
    assert anonymous.status_code == 401
    ro = httpx.put(url, json=body, headers={"api-key": infra.require("QDRANT_KEY_RO")}, timeout=5)
    assert ro.status_code == 403, "the read-only key created a collection"
    rw_headers = {"api-key": infra.require("QDRANT_KEY_RW")}
    try:
        assert httpx.put(url, json=body, headers=rw_headers, timeout=10).status_code == 200
        listed = httpx.get(
            f"{infra.qdrant_url}/collections", headers={"api-key": infra.require("QDRANT_KEY_RO")}
        )
        assert name in {c["name"] for c in listed.json()["result"]["collections"]}
    finally:
        httpx.delete(url, headers=rw_headers, timeout=10)


# --- Object store capability probe (G0.4, D19) ------------------------------------------------------------------


def test_object_store_passes_the_capability_probe() -> None:
    caps = probes.object_store_capabilities()
    assert caps.all_ok, f"SeaweedFS capability probe failed: {caps}"


# --- OpenBao Transit (local key provider, G0.9 round trip) ------------------------------------------------------


def test_openbao_transit_round_trip_and_destruction() -> None:
    probes.ensure_transit()
    key = f"lmqa-probe-{secrets.token_hex(4)}"
    # Real bytes from this repository's ledger, never generated text (R1).
    plaintext = load_tool("gen_versions").LEDGER.read_bytes()[:512]
    context = base64.b64encode(json.dumps({"org_id": key}).encode()).decode()
    assert probes.openbao_request(
        "POST", f"transit/keys/{key}", json={"derived": True}
    ).status_code in {200, 204}
    enc = probes.openbao_request(
        "POST",
        f"transit/encrypt/{key}",
        json={"plaintext": base64.b64encode(plaintext).decode(), "context": context},
    )
    assert enc.status_code == 200
    ciphertext = enc.json()["data"]["ciphertext"]
    dec = probes.openbao_request(
        "POST", f"transit/decrypt/{key}", json={"ciphertext": ciphertext, "context": context}
    )
    assert base64.b64decode(dec.json()["data"]["plaintext"]) == plaintext
    wrong = base64.b64encode(json.dumps({"org_id": "other"}).encode()).decode()
    assert (
        probes.openbao_request(
            "POST", f"transit/decrypt/{key}", json={"ciphertext": ciphertext, "context": wrong}
        ).status_code
        == 400
    ), "decryption under the wrong encryption context must fail"
    probes.openbao_request(
        "POST", f"transit/keys/{key}/config", json={"deletion_allowed": True}
    ).raise_for_status()
    probes.openbao_request("DELETE", f"transit/keys/{key}").raise_for_status()
    gone = probes.openbao_request(
        "POST", f"transit/decrypt/{key}", json={"ciphertext": ciphertext, "context": context}
    )
    assert gone.status_code >= 400, "a destroyed key still decrypts"
