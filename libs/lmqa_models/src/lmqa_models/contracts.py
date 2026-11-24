"""Loaders for `contracts/`: the authorization matrix and the lifecycle state machines (blueprint 18, R-10).

`Machine.load(name)` is the service-side guard generated from contracts/state-machines.yaml; the database enforces
the same declaration through the transition table and triggers (db/migrations/0010_lifecycle_machines.sql).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import yaml

from lmqa_models.envfile import ROOT
from lmqa_models.errors import ServiceError

CONTRACTS = ROOT / "contracts"


@dataclass(frozen=True)
class Transition:
    action: str
    from_status: str
    to_status: str
    workspace_status: str | None = None
    actors: frozenset[str] = frozenset()
    guards: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()


class IllegalTransition(ServiceError):
    """A state change the declaration does not allow: 409 for an undeclared pair, 403 for an actor or a guard."""

    def __init__(
        self, machine: str, from_state: str, to_state: str, actor: str, reason: str
    ) -> None:
        super().__init__(
            f"Cannot change from {from_state} to {to_state}."
            if reason == "undeclared"
            else "You are not allowed to make this change."
        )
        self.status = 409 if reason == "undeclared" else 403
        self.machine, self.from_state, self.to_state = machine, from_state, to_state
        self.actor, self.reason = actor, reason


@dataclass(frozen=True)
class Machine:
    name: str
    states: frozenset[str]
    transitions: Mapping[str, Transition] = field(hash=False)

    @classmethod
    def load(cls, name: str) -> Machine:
        return _machine(name)

    def action(self, action: str) -> Transition | None:
        return self.transitions.get(action)

    def check(
        self,
        actor_role: str,
        from_state: str,
        to_state: str,
        guards: Mapping[str, bool] | None = None,
    ) -> Transition:
        """The first declared transition (by action name) from `from_state` to `to_state` that lists `actor_role`
        and whose guards are all true in `guards`; raises IllegalTransition otherwise."""
        pair = [
            t
            for _, t in sorted(self.transitions.items())
            if (t.from_status, t.to_status) == (from_state, to_state)
        ]
        if not pair:
            raise IllegalTransition(self.name, from_state, to_state, actor_role, "undeclared")
        allowed = [t for t in pair if actor_role in t.actors]
        if not allowed:
            raise IllegalTransition(self.name, from_state, to_state, actor_role, "actor")
        held = guards or {}
        for t in allowed:
            if all(held.get(g) is True for g in t.guards):
                return t
        raise IllegalTransition(self.name, from_state, to_state, actor_role, "guard")


@cache
def _machine(name: str) -> Machine:
    spec = _load("state-machines.yaml")["machines"][name]
    transitions = {
        action: Transition(
            action,
            t["from"],
            t["to"],
            t.get("workspace"),
            frozenset(t["actors"]),
            tuple(t.get("guards", ())),
            tuple(t.get("effects", ())),
        )
        for action, t in spec["transitions"].items()
    }
    return Machine(name, frozenset(spec["states"]), transitions)


@cache
def _load(name: str) -> dict[str, Any]:
    with (CONTRACTS / name).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"contracts/{name} must be a mapping")
    return data


def transition(machine: str, action: str) -> Transition | None:
    """Look up one transition of a state machine declared in contracts/state-machines.yaml."""
    return Machine.load(machine).action(action)


def authz_matrix() -> dict[tuple[str, str], frozenset[str]]:
    """(METHOD, path template) -> allowed roles, from contracts/authz-matrix.yaml."""
    out: dict[tuple[str, str], frozenset[str]] = {}
    for route in _load("authz-matrix.yaml")["routes"]:
        out[(route["method"].upper(), route["path"])] = frozenset(route["roles"])
    return out


@dataclass(frozen=True)
class RouteRule:
    roles: frozenset[str]
    step_up: bool = False
    feature: str | None = None


def route_rules() -> dict[tuple[str, str], RouteRule]:
    """(METHOD, path) -> roles, step-up requirement and the feature flag that gates the route (18, 19.6)."""
    out: dict[tuple[str, str], RouteRule] = {}
    for route in _load("authz-matrix.yaml")["routes"]:
        out[(route["method"].upper(), route["path"])] = RouteRule(
            frozenset(route["roles"]), bool(route.get("step_up", False)), route.get("feature")
        )
    return out


@cache
def features() -> dict[str, bool]:
    """contracts/features.toml: name -> enabled. `FEATURE_<NAME>=on` overrides locally (never in production: the
    gatekeeper refuses an enabled flag without attestations, and the production profile ignores overrides). A frozen
    flag (non-empty `pending`, DEV-21) honours the override only with APP_ENV=local, so it stays off in every
    deployed environment until its open questions are answered."""
    import tomllib

    from lmqa_models.envfile import merged_env

    data = tomllib.loads((CONTRACTS / "features.toml").read_text(encoding="utf-8")).get(
        "feature", {}
    )
    env = merged_env()
    app_env = env.get("APP_ENV", "local")
    out = {}
    for name, spec in data.items():
        value = bool(spec.get("enabled", False))
        override = env.get(f"FEATURE_{name.upper()}", "").strip().lower()
        allowed = app_env == "local" if spec.get("pending") else app_env != "production"
        if override and allowed:
            value = override in {"on", "true", "1", "yes"}
        out[name] = value
    return out


def feature_enabled(name: str | None) -> bool:
    return name is None or features().get(name, False)
