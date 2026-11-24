"""Auth0 configuration as code against the implementation (task 5.1; R-19, R-21, R-25; DEV-10, DEV-41).

* the post-login Action computes the design strength names, the same names as `lmqa_auth.strength`;
* the Action denies `main` without an organization and `onboarding` with one, with both audiences wired from Terraform;
* the identity M2M grant in `infra/auth0/main.tf` equals `identity.auth0_mgmt.SCOPES`, and only the identity service
  reads the Management API credentials.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from identity.auth0_mgmt import SCOPES
from lmqa_auth.strength import AUTH_STRENGTHS
from lmqa_models.envfile import ROOT

pytestmark = [pytest.mark.contract, pytest.mark.stage2]

INFRA = ROOT / "infra" / "auth0"
MAIN_TF = (INFRA / "main.tf").read_text(encoding="utf-8")
ACTION = INFRA / "actions" / "post-login.js"
FIXTURE = json.loads(
    (ROOT / "contracts" / "claims" / "auth-methods.json").read_text(encoding="utf-8")
)


def _strength(methods: list[dict[str, str]]) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = f"process.stdout.write(require({json.dumps(str(ACTION))}).strengthOf({json.dumps(methods)}))"
    return subprocess.run(  # noqa: S603 - fixed node binary and a repository file
        [node, "-e", script], check=True, capture_output=True, text=True, timeout=30
    ).stdout


def test_fixture_and_library_agree_on_strength_names() -> None:
    assert tuple(FIXTURE["strengths"]) == AUTH_STRENGTHS
    for old in ("passkey_mfa", '"mfa" :', '"otp" :'):
        assert old not in ACTION.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("methods", "expected"),
    [
        ([{"name": "passkey"}], "passkey"),
        ([{"name": "pwd"}, {"name": "mfa", "type": "webauthn-roaming"}], "webauthn_mfa"),
        ([{"name": "pwd"}, {"name": "webauthn-platform"}], "webauthn_mfa"),
        ([{"name": "pwd"}, {"name": "mfa", "type": "otp"}], "otp_mfa"),
        ([{"name": "pwd"}], "password"),
        ([], "password"),
    ],
)
def test_action_computes_design_strength_names(
    methods: list[dict[str, str]], expected: str
) -> None:
    assert _strength(methods) == expected


def test_action_enforces_organization_per_audience() -> None:
    code = ACTION.read_text(encoding="utf-8")
    assert re.search(r"MAIN_AUDIENCE && !event\.organization\)\s*\{\s*api\.access\.deny", code)
    # the `main` rule follows the same AUTH0_ORGANIZATIONS flag as lmqa_auth.verifier
    assert 'orgsRequired = event.secrets.ORGANIZATIONS_REQUIRED === "on"' in code
    assert "if (orgsRequired && audience && audience === event.secrets.MAIN_AUDIENCE" in code
    assert re.search(r'name\s*=\s*"ORGANIZATIONS_REQUIRED"\s*value\s*=\s*var\.organizations_required', MAIN_TF)
    assert re.search(r"ONBOARDING_AUDIENCE && event\.organization\)\s*\{\s*api\.access\.deny", code)
    assert re.search(
        r'name\s*=\s*"MAIN_AUDIENCE"\s*value\s*=\s*auth0_resource_server\.main\.identifier', MAIN_TF
    )
    assert re.search(
        r'name\s*=\s*"ONBOARDING_AUDIENCE"\s*value\s*=\s*auth0_resource_server\.onboarding\.identifier',
        MAIN_TF,
    )


def test_identity_m2m_grant_equals_the_identity_service_scopes() -> None:
    block = re.search(
        r'resource "auth0_client_grant" "identity_m2m" \{(.*?)\n\}', MAIN_TF, re.DOTALL
    )
    assert block is not None
    scopes = set(re.findall(r'"([a-z_]+:[a-z_]+)"', block.group(1)))
    assert scopes == set(SCOPES)
    # the only Management API grant in the configuration
    assert MAIN_TF.count('resource "auth0_client_grant"') == 1


def test_only_the_identity_service_reads_management_api_credentials() -> None:
    readers = sorted(
        str(p.relative_to(ROOT))
        for top in ("services", "libs")
        for p in (ROOT / top).rglob("*.py")
        if "AUTH0_M2M_" in p.read_text(encoding="utf-8")
    )
    assert readers, "expected the identity service to read AUTH0_M2M_*"
    assert all(Path(r).parts[:2] == ("services", "identity") for r in readers), readers
