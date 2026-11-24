"""Unit tests for auth-strength names and the audience organization rule (R-21.2, DEV-10, DEV-41), plus the
policy defaults used by step-up when the POLICY_* overrides are empty."""

from __future__ import annotations

import pytest

from lmqa_auth.strength import AUTH_STRENGTHS, PHISHING_RESISTANT, at_least, normalize
from lmqa_auth.verifier import MAIN, ONBOARDING, Unauthorized, check_organization
from lmqa_models.policy import load_policy

pytestmark = [pytest.mark.unit, pytest.mark.stage2]


def test_strength_names_are_the_design_names() -> None:
    assert AUTH_STRENGTHS == ("passkey", "webauthn_mfa", "otp_mfa", "password")
    assert {"passkey", "webauthn_mfa"} == PHISHING_RESISTANT


@pytest.mark.parametrize("old", ["otp", "mfa", "passkey_mfa", "", None, 3])
def test_unknown_or_old_names_normalize_to_the_weakest(old: object) -> None:
    assert normalize(old) == "password"


def test_step_up_needs_a_phishing_resistant_factor() -> None:
    assert at_least("passkey", "passkey")
    assert at_least("webauthn_mfa", "passkey")
    assert not at_least("otp_mfa", "passkey")
    assert not at_least("password", "otp_mfa")
    assert not at_least("unknown", "otp_mfa")


def test_main_requires_an_organization_when_organizations_are_on() -> None:
    check_organization(MAIN, "org_abc", required=True)
    check_organization(MAIN, None, required=False)
    with pytest.raises(Unauthorized):
        check_organization(MAIN, None, required=True)


def test_onboarding_denies_an_organization() -> None:
    check_organization(ONBOARDING, None, required=True)
    with pytest.raises(Unauthorized):
        check_organization(ONBOARDING, "org_abc", required=False)


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_policy_overrides_fall_back_to_design_defaults(value: str) -> None:
    policy = load_policy({"POLICY_STEP_UP_MAX_AGE": value, "POLICY_WALL_LIFT_WAIT": value})
    assert policy.step_up_max_age == 300
    assert policy.wall_lift_wait == 24 * 3600


def test_policy_override_still_applies() -> None:
    assert load_policy({"POLICY_STEP_UP_MAX_AGE": "60"}).step_up_max_age == 60
