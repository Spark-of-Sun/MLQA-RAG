"""Lifecycle State Machine Engine and Validator.

Parses contracts/state-machines.yaml, validates state graphs,
and enforces legal transition rules per Master System Design §6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Indentation level constants
INDENT_ROOT = 0
INDENT_MACHINE_PROP = 2
INDENT_STATE_DEF = 4
INDENT_STATE_PROP = 6
INDENT_TRANSITION = 8


@dataclass(frozen=True)
class Transition:
    """A directed state transition."""

    from_state: str
    event: str
    to_state: str


@dataclass
class StateMachine:
    """A declared lifecycle state machine."""

    name: str
    initial: str
    states: set[str] = field(default_factory=set)
    final_states: set[str] = field(default_factory=set)
    transitions: list[Transition] = field(default_factory=list)

    def is_final(self, state: str) -> bool:
        """Check if state is a terminal/final state."""
        return state in self.final_states

    def can_transition(self, from_state: str, to_state: str, event: str | None = None) -> bool:
        """Check if transition from from_state to to_state is allowed."""
        for t in self.transitions:
            if (
                t.from_state == from_state
                and t.to_state == to_state
                and (event is None or t.event == event)
            ):
                return True
        return False

    def get_valid_transitions(self) -> list[Transition]:
        """Return all declared valid transitions."""
        return list(self.transitions)

    def get_invalid_pairs(self) -> list[tuple[str, str]]:
        """Return all illegal (from_state, to_state) pairs."""
        valid_pairs = {(t.from_state, t.to_state) for t in self.transitions}
        return [
            (s1, s2)
            for s1 in sorted(self.states)
            for s2 in sorted(self.states)
            if (s1, s2) not in valid_pairs
        ]

    def validate_graph(self) -> list[str]:
        """Validate state machine graph consistency."""
        errors: list[str] = []
        if self.initial not in self.states:
            errors.append(
                f"[{self.name}] Initial state '{self.initial}' is not in declared states."
            )

        for t in self.transitions:
            if t.from_state not in self.states:
                errors.append(f"[{self.name}] Transition from undeclared state '{t.from_state}'")
            if t.to_state not in self.states:
                errors.append(f"[{self.name}] Transition to undeclared state '{t.to_state}'")
            if t.from_state in self.final_states:
                msg = (
                    f"[{self.name}] Final state '{t.from_state}' has "
                    f"outgoing transition to '{t.to_state}'"
                )
                errors.append(msg)

        return errors


class StateMachineRegistry:
    """Registry of all declared state machines in the system."""

    def __init__(self, machines: dict[str, StateMachine] | None = None) -> None:
        """Initialize registry with machines map."""
        self.machines: dict[str, StateMachine] = machines or {}

    def get(self, name: str) -> StateMachine:
        """Get state machine by name."""
        if name not in self.machines:
            msg = f"State machine '{name}' not found. Available: {list(self.machines.keys())}"
            raise KeyError(msg)
        return self.machines[name]

    def validate_all(self) -> dict[str, list[str]]:
        """Validate all registered state machines."""
        results: dict[str, list[str]] = {}
        for name, machine in self.machines.items():
            errs = machine.validate_graph()
            if errs:
                results[name] = errs
        return results


class _YamlStateMachineParser:
    """Helper parser for the YAML state machine schema."""

    def __init__(self) -> None:
        self.machines: dict[str, StateMachine] = {}
        self.current_machine: StateMachine | None = None
        self.current_state: str | None = None
        self.in_states_block = False
        self.in_on_block = False

    def parse(self, content: str) -> StateMachineRegistry:
        for raw_line in content.splitlines():
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            stripped = line.strip()
            self._process_line(indent, stripped)
        return StateMachineRegistry(self.machines)

    def _process_line(self, indent: int, stripped: str) -> None:
        if indent == INDENT_ROOT and stripped.endswith(":"):
            self._handle_root(stripped[:-1].strip())
        elif indent == INDENT_MACHINE_PROP and self.current_machine:
            self._handle_machine_prop(stripped)
        elif indent == INDENT_STATE_DEF and self.current_machine and self.in_states_block:
            self._handle_state_def(stripped)
        elif indent == INDENT_STATE_PROP and self.current_machine and self.current_state:
            self._handle_state_prop(stripped)
        elif indent == INDENT_TRANSITION and self.in_on_block:
            self._handle_transition(stripped)

    def _handle_root(self, machine_name: str) -> None:
        self.current_machine = StateMachine(name=machine_name, initial="")
        self.machines[machine_name] = self.current_machine
        self.current_state = None
        self.in_states_block = False
        self.in_on_block = False

    def _handle_machine_prop(self, stripped: str) -> None:
        self.in_on_block = False
        if stripped.startswith("initial:"):
            if self.current_machine:
                self.current_machine.initial = stripped.split(":", 1)[1].strip()
        elif stripped == "states:":
            self.in_states_block = True
        self.current_state = None

    def _handle_state_def(self, stripped: str) -> None:
        self.in_on_block = False
        if stripped.endswith(":") and self.current_machine:
            self.current_state = stripped[:-1].strip()
            self.current_machine.states.add(self.current_state)

    def _handle_state_prop(self, stripped: str) -> None:
        if stripped == "on:":
            self.in_on_block = True
        elif stripped.startswith("final:") and self.current_machine and self.current_state:
            val = stripped.split(":", 1)[1].strip().lower()
            if val == "true":
                self.current_machine.final_states.add(self.current_state)

    def _handle_transition(self, stripped: str) -> None:
        if ":" in stripped and self.current_machine and self.current_state:
            event, to_state = stripped.split(":", 1)
            self.current_machine.transitions.append(
                Transition(
                    from_state=self.current_state,
                    event=event.strip(),
                    to_state=to_state.strip(),
                )
            )


def parse_state_machines_yaml(content: str) -> StateMachineRegistry:
    """Parse YAML content into StateMachineRegistry without external dependencies."""
    return _YamlStateMachineParser().parse(content)


def load_state_machines(path: Path | str | None = None) -> StateMachineRegistry:
    """Load state machines from file path or default contracts/state-machines.yaml."""
    file_path = Path(path) if path else Path("contracts/state-machines.yaml")
    if not file_path.exists():
        msg = f"State machines file not found at: {file_path}"
        raise FileNotFoundError(msg)
    content = file_path.read_text(encoding="utf-8")
    return parse_state_machines_yaml(content)
