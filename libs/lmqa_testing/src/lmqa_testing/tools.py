"""Import a script from tools/ as a module, so tests exercise the same functions the Makefile runs."""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from types import ModuleType

from lmqa_models.envfile import ROOT

TOOLS = ROOT / "tools"


@cache
def load_tool(name: str) -> ModuleType:
    path = TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"lmqa_tool_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"tools/{name}.py not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
