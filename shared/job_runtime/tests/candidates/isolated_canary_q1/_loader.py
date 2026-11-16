from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys


def package():
    name = "isolated_canary_q1"
    if name not in sys.modules:
        root = Path(__file__).resolve().parents[3] / "candidates" / name
        spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def submodule(name: str):
    package()
    return importlib.import_module(f"isolated_canary_q1.{name}")
