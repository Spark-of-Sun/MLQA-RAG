"""The authorization matrix as the Gateway's allow-list (doc 15.1, G3.6).

``contracts/authz-matrix.yaml`` is the single source: this module, the generated client and the
authorization tests all read it, so they cannot drift apart. A route a role may not call is
``None`` here and the caller answers 404 (existence is not revealed). A route whose feature flag
is off in ``contracts/features.toml`` is 404 for everyone, as if it did not exist.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import yaml

if TYPE_CHECKING:
    from pathlib import Path

ROLE_CODES: Final = {"super_admin": "SA", "admin": "AD", "tenant": "TE"}


@dataclass(frozen=True, slots=True)
class Route:
    """One allowed route."""

    method: str
    path: str
    service: str
    audience: str
    roles: frozenset[str]
    step_up: bool
    state_changing: bool
    stream: bool
    feature: str | None
    pattern: re.Pattern[str]


class Matrix:
    """Matches ``(method, path)`` to a route and decides who may call it."""

    def __init__(self, routes: list[Route], enabled: set[str]) -> None:
        """``enabled`` is the set of feature flags that are on."""
        self._routes, self._enabled = routes, enabled

    @classmethod
    def load(cls, matrix_path: Path, features_path: Path) -> Matrix:
        """Read the YAML matrix and the TOML feature flags."""
        raw = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))["routes"]
        flags = tomllib.loads(features_path.read_text(encoding="utf-8")).get("features", {})
        routes = [
            Route(
                r["method"],
                r["path"],
                r["service"],
                r["audience"],
                frozenset(r["roles"]),
                bool(r["step_up"]),
                bool(r["state_changing"]),
                bool(r["stream"]),
                r.get("feature"),
                re.compile(
                    "^"
                    + re.sub(
                        r"\{[^/]+\}",
                        "[^/]+",
                        re.escape(r["path"]).replace(r"\{", "{").replace(r"\}", "}"),
                    )
                    + "$"
                ),
            )
            for r in raw
        ]
        return cls(routes, {name for name, f in flags.items() if f.get("enabled")})

    def match(self, method: str, path: str) -> Route | None:
        """The route for a request, or None (unknown route, or its feature is disabled)."""
        for route in self._routes:
            if route.method == method and route.pattern.match(path):
                if route.feature and route.feature not in self._enabled:
                    return None
                return route
        return None

    def allows(self, route: Route, role_code: str) -> bool:
        """True if ``role_code`` (SA, AD, TE, ON, PENDING, ANON) may call ``route``."""
        return role_code in route.roles

    def routes(self) -> list[Route]:
        """Every declared route (used by the generated authorization tests)."""
        return list(self._routes)
