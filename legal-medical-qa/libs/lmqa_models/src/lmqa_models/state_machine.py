"""State machines declared as data (doc section 6.1).

``contracts/state-machines.yaml`` is the single source for three things:

1. database transition tables and triggers (``sql_for``),
2. service-side guards (``StateMachine.assert_transition``),
3. generated tests (``StateMachine.all_state_pairs``).
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

CONTRACTS_ENV: Final = "LMQA_CONTRACTS_DIR"
_IDENT_OK: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


class IllegalTransitionError(ValueError):
    """Raised when a transition is not declared or the actor is not allowed."""


class Transition(BaseModel):
    """One allowed edge of a state machine."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_state: str
    to_state: str
    event: str
    actors: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _rename_keys(cls, data: dict[str, object]) -> dict[str, object]:
        out = dict(data)
        if "from" in out:
            out["from_state"] = out.pop("from")
        if "to" in out:
            out["to_state"] = out.pop("to")
        return out


class StateMachine(BaseModel):
    """A lifecycle: states, initial state, and allowed transitions."""

    model_config = ConfigDict(frozen=True)

    name: str = ""
    table: str
    column: str
    initial: str
    terminal: tuple[str, ...]
    states: tuple[str, ...]
    transitions: tuple[Transition, ...]

    @model_validator(mode="after")
    def _check_consistency(self) -> StateMachine:
        known = set(self.states)
        if self.initial not in known:
            msg = f"{self.name}: initial state {self.initial!r} not in states"
            raise ValueError(msg)
        for t in self.transitions:
            if t.from_state not in known or t.to_state not in known:
                msg = f"{self.name}: transition {t.from_state}->{t.to_state} uses unknown state"
                raise ValueError(msg)
            if t.from_state in self.terminal:
                msg = f"{self.name}: transition leaves terminal state {t.from_state}"
                raise ValueError(msg)
        return self

    def allowed(self, from_state: str, to_state: str) -> tuple[Transition, ...]:
        """Return the declared transitions between two states."""
        return tuple(
            t for t in self.transitions if t.from_state == from_state and t.to_state == to_state
        )

    def can_transition(self, from_state: str, to_state: str, actor: str) -> bool:
        """Return True if ``actor`` may move the machine from one state to the other."""
        return any(actor in t.actors for t in self.allowed(from_state, to_state))

    def assert_transition(self, from_state: str, to_state: str, actor: str) -> None:
        """Raise ``IllegalTransitionError`` unless the transition is declared for ``actor``."""
        edges = self.allowed(from_state, to_state)
        if not edges:
            msg = f"{self.name}: {from_state} -> {to_state} is not a declared transition"
            raise IllegalTransitionError(msg)
        if not any(actor in t.actors for t in edges):
            msg = f"{self.name}: actor {actor!r} may not move {from_state} -> {to_state}"
            raise IllegalTransitionError(msg)

    def all_state_pairs(self) -> tuple[tuple[str, str], ...]:
        """Every ordered (from, to) pair, including self-pairs, for generated tests."""
        return tuple((a, b) for a in self.states for b in self.states)

    def illegal_pairs(self) -> tuple[tuple[str, str], ...]:
        """Every ordered state pair that has no declared transition."""
        legal = {(t.from_state, t.to_state) for t in self.transitions}
        return tuple(p for p in self.all_state_pairs() if p not in legal)


def contracts_dir() -> Path:
    """Locate the ``contracts`` directory (env override, then walk up from this file)."""
    override = os.environ.get(CONTRACTS_ENV)
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "contracts" / "state-machines.yaml"
        if candidate.is_file():
            return candidate.parent
    msg = f"contracts directory not found; set {CONTRACTS_ENV}"
    raise FileNotFoundError(msg)


@cache
def load_machines(path: str | None = None) -> dict[str, StateMachine]:
    """Load and validate every machine declared in the YAML contract."""
    file = Path(path) if path else contracts_dir() / "state-machines.yaml"
    raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    machines: dict[str, StateMachine] = {}
    for name, body in raw["machines"].items():
        machines[name] = StateMachine.model_validate({**body, "name": name})
    return machines


def _ident(value: str) -> str:
    """Return ``value`` if it is a safe SQL identifier fragment, else raise."""
    if not value or not set(value) <= _IDENT_OK:
        msg = f"unsafe SQL identifier: {value!r}"
        raise ValueError(msg)
    return value


def _lit(value: str) -> str:
    """Quote a value as a SQL string literal after validating it is simple."""
    return "'" + _ident(value) + "'"


def sql_for(machine: StateMachine) -> str:
    """Generate the transition table, seed rows and enforcing trigger for one machine.

    A change of the status column that is not listed in the transition table is rejected by
    the database, so an application bug cannot skip a state (doc 6.1).
    """
    name = _ident(machine.name)
    table = _ident(machine.table)
    column = _ident(machine.column)
    tt = f"sm_{name}_transitions"
    fn = f"sm_{name}_guard"
    rows = sorted({(t.from_state, t.to_state) for t in machine.transitions})
    values = ",\n  ".join(f"({_lit(a)}, {_lit(b)})" for a, b in rows)
    # Every interpolated value passed the _ident allowlist (a-z, 0-9, _) above, and
    # test_sql_generator_rejects_unsafe_identifiers proves unsafe names are refused.
    return f"""
CREATE TABLE IF NOT EXISTS {tt} (
  from_state text NOT NULL,
  to_state   text NOT NULL,
  PRIMARY KEY (from_state, to_state)
);
INSERT INTO {tt} (from_state, to_state) VALUES
  {values}
ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $fn$
BEGIN
  IF NEW.{column}::text IS DISTINCT FROM OLD.{column}::text THEN
    IF NOT EXISTS (
      SELECT 1 FROM {tt} t
       WHERE t.from_state = OLD.{column}::text AND t.to_state = NEW.{column}::text
    ) THEN
      RAISE EXCEPTION 'illegal {name} transition % -> %', OLD.{column}, NEW.{column}
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END
$fn$;
DROP TRIGGER IF EXISTS {fn} ON {table};
CREATE TRIGGER {fn} BEFORE UPDATE OF {column} ON {table}
  FOR EACH ROW EXECUTE FUNCTION {fn}();
""".strip()  # noqa: S608 - identifiers are allowlisted by _ident
