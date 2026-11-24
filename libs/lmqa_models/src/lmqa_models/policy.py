"""Governance and session policy values (blueprint 6.7, 8.4, Appendix C) and the production-profile lint (R7, G2.10,
G11.1). Waiting periods are configuration: tests use short values, and `lint_production` fails the build if the
production profile is below a policy minimum or above a maximum.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from lmqa_models.envfile import merged_env

HOUR = 3600
DAY = 24 * HOUR


@dataclass(frozen=True)
class Policy:
    # governance waits (seconds)
    successor_transfer_wait: int = 72 * HOUR
    wall_lift_wait: int = 24 * HOUR
    private_read_enable_wait: int = 24 * HOUR
    workspace_unseal_wait: int = 72 * HOUR
    workspace_destroy_wait: int = 30 * DAY
    org_delete_grace: int = 30 * DAY
    owner_recovery_wait: int = 72 * HOUR
    co_owner_set_wait: int = 72 * HOUR
    approval_expiry: int = 72 * HOUR
    kms_deletion_window_days: int = 30
    # authentication and sessions
    step_up_max_age: int = 300
    access_token_lifetime: int = 600
    context_token_lifetime: int = 60
    signer_certificate_lifetime: int = 3600
    privileged_idle_timeout: int = 15 * 60
    privileged_absolute_session: int = 8 * HOUR
    # access sessions
    emergency_duration: int = 60 * 60
    emergency_daily_limit: int = 5
    break_glass_duration: int = 60 * 60
    operator_infrastructure_max: int = 24 * HOUR
    operator_control_max: int = 8 * HOUR
    operator_content_max: int = 4 * HOUR
    backup_retention_days: int = 35
    workspace_seal_after: int = 30 * DAY
    review_due: int = 72 * HOUR

    def wait_for(self, kind: str) -> int:
        return {
            "successor_transfer": self.successor_transfer_wait,
            "wall_lift": self.wall_lift_wait,
            "private_read_enable": self.private_read_enable_wait,
            "workspace_unseal": self.workspace_unseal_wait,
            "workspace_destroy": self.workspace_destroy_wait,
            "org_delete": self.org_delete_grace,
            "owner_recovery": self.owner_recovery_wait,
            "co_owner_set": self.co_owner_set_wait,
        }[kind]


# (field, comparison, bound): ">=" means the production value must be at least the bound.
MINIMUMS: tuple[tuple[str, str, int], ...] = (
    ("successor_transfer_wait", ">=", 72 * HOUR),
    ("wall_lift_wait", ">=", 24 * HOUR),
    ("private_read_enable_wait", ">=", 24 * HOUR),
    ("workspace_unseal_wait", ">=", 72 * HOUR),
    ("workspace_destroy_wait", ">=", 30 * DAY),
    ("org_delete_grace", ">=", 30 * DAY),
    ("owner_recovery_wait", ">=", 72 * HOUR),
    ("approval_expiry", "<=", 72 * HOUR),
    ("kms_deletion_window_days", "==", 30),
    ("step_up_max_age", "<=", 300),
    ("access_token_lifetime", "<=", 600),
    ("context_token_lifetime", "<=", 60),
    ("signer_certificate_lifetime", "<=", 3600),
    ("privileged_idle_timeout", "<=", 15 * 60),
    ("privileged_absolute_session", "<=", 8 * HOUR),
    ("emergency_duration", "<=", 60 * 60),
    ("emergency_daily_limit", "<=", 5),
    ("break_glass_duration", "<=", 60 * 60),
    ("operator_infrastructure_max", "<=", 24 * HOUR),
    ("operator_control_max", "<=", 8 * HOUR),
    ("operator_content_max", "<=", 4 * HOUR),
    ("backup_retention_days", "<=", 35),
)


def load_policy(env: dict[str, str] | None = None) -> Policy:
    """`POLICY_<FIELD>` overrides a value (seconds or count), e.g. POLICY_WALL_LIFT_WAIT=5 in tests.

    An empty, blank or non-integer value falls back to the design default in `Policy` (for example
    `POLICY_STEP_UP_MAX_AGE=` gives 300 s and `POLICY_WALL_LIFT_WAIT=` gives 24 h)."""
    env = merged_env() if env is None else env
    values = {}
    for name, default in asdict(Policy()).items():
        raw = (env.get(f"POLICY_{name.upper()}") or "").strip()
        values[name] = int(raw) if raw.lstrip("-").isdigit() else default
    return Policy(**values)


def lint_production(policy: Policy) -> list[str]:
    problems = []
    for name, op, bound in MINIMUMS:
        value = getattr(policy, name)
        ok = {">=": value >= bound, "<=": value <= bound, "==": value == bound}[op]
        if not ok:
            problems.append(f"{name} = {value}, must be {op} {bound}")
    return problems
