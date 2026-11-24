"""Render the per-organization CMK key policy from infra/keyguard/key-policy.json.tftpl (the same template OpenTofu
uses), so runtime-created keys and infrastructure-created keys carry one policy and one lint (G1.12)."""

from __future__ import annotations

import json
from collections.abc import Sequence

from lmqa_models.envfile import ROOT

TEMPLATE = ROOT / "infra" / "keyguard" / "key-policy.json.tftpl"


def render_org_key_policy(
    *, account_id: str, org_id: str, service_role_arns: Sequence[str], min_window_days: int = 30
) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    values = {
        "account_id": account_id,
        "org_id": org_id,
        "service_role_arns": json.dumps(list(service_role_arns)),
        "min_window_days": str(min_window_days),
    }
    for name, value in values.items():
        text = text.replace("${" + name + "}", value)
    json.loads(text)  # must be valid JSON after rendering
    return text
