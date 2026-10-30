"""KeyGuard policy lint (G1.12 half): the shipped IaC passes, and the lint really detects the bad cases."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.control, pytest.mark.stage1]
ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("keyguard_lint", ROOT / "infra/keyguard/lint.py")
assert _spec
assert _spec.loader
lint = importlib.util.module_from_spec(_spec)
sys.modules["keyguard_lint"] = lint
_spec.loader.exec_module(lint)


def test_the_shipped_aws_infrastructure_is_clean() -> None:
    problems = []
    for path in sorted((ROOT / "infra/aws").rglob("*.tf")):
        text = path.read_text()
        problems += lint.lint_text(text, path.name) + lint.lint_grants(text, path.name)
    assert problems == []


BAD_WINDOW = 'resource "aws_kms_key" "k" {\n  deletion_window_in_days = 7\n  policy = "{}"\n}\n'
NO_POLICY = 'resource "aws_kms_key" "k" {\n  deletion_window_in_days = 30\n}\n'
DRILL = 'resource "aws_kms_key" "d" {\n  deletion_window_in_days = 7\n  policy = "{}"\n  tags = { drill = "true" }\n}\n'
GRANT = 'data "aws_iam_policy_document" "bad" {\n  statement {\n    actions = ["kms:ScheduleKeyDeletion"]\n  }\n}\n'


def test_a_production_key_with_a_short_window_is_rejected() -> None:
    assert any("7 day" in p for p in lint.lint_text(BAD_WINDOW))


def test_a_key_without_an_explicit_policy_is_rejected() -> None:
    assert any("no explicit key policy" in p for p in lint.lint_text(NO_POLICY))


def test_only_a_drill_tagged_key_may_use_the_provider_minimum() -> None:
    assert lint.lint_text(DRILL) == []


def test_a_service_policy_granting_key_deletion_is_rejected() -> None:
    assert any("kms:ScheduleKeyDeletion" in p for p in lint.lint_grants(GRANT))


def test_the_organization_scp_names_only_the_keyguard_roles_for_destruction() -> None:
    scp = json.loads((ROOT / "infra/keyguard/scp.json").read_text())
    by_sid = {s["Sid"]: s for s in scp["Statement"]}
    destroy = by_sid["KeyGuardNoServiceMayDestroyOrDisable"]
    allowed = destroy["Condition"]["ArnNotLike"]["aws:PrincipalArn"]
    assert set(destroy["Action"]) >= {"kms:ScheduleKeyDeletion", "kms:DisableKey"}
    assert all(("keyguard-destroyer" in a or "key-admin" in a) for a in allowed), (
        "no service role is exempt from destruction"
    )
    policy = by_sid["KeyGuardPolicyChangesOnlyAtCreationOrByKeyAdmin"]
    assert any("identity" in a for a in policy["Condition"]["ArnNotLike"]["aws:PrincipalArn"])
