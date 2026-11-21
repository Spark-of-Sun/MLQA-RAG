"""Loaders for `contracts/`: the authorization matrix and the lifecycle state machines (blueprint 18)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

import yaml

from lmqa_models.envfile import ROOT

CONTRACTS = ROOT / "contracts"


@dataclass(frozen=True)
class Transition:
    action: str
    from_status: str
    to_status: str
    workspace_status: str | None = None


@cache
def _load(name: str) -> dict[str, Any]:
    with (CONTRACTS / name).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"contracts/{name} must be a mapping")
    return data


def transition(machine: str, action: str) -> Transition | None:
    """Look up one transition of a state machine declared in contracts/state-machines.yaml."""
    spec = _load("state-machines.yaml")["machines"][machine]["transitions"].get(action)
    if spec is None:
        return None
    return Transition(action, spec["from"], spec["to"], spec.get("workspace"))


def authz_matrix() -> dict[tuple[str, str], frozenset[str]]:
    """(METHOD, path template) -> allowed roles, from contracts/authz-matrix.yaml."""
    out: dict[tuple[str, str], frozenset[str]] = {}
    for route in _load("authz-matrix.yaml")["routes"]:
        out[(route["method"].upper(), route["path"])] = frozenset(route["roles"])
    return out
