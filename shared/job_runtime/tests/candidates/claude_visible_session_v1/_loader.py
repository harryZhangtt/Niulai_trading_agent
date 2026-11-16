from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys


def package():
    name = "claude_visible_session_v1"
    if name not in sys.modules:
        root = Path(__file__).resolve().parents[3] / "candidates" / name
        spec = importlib.util.spec_from_file_location(
            name, root / "__init__.py", submodule_search_locations=[str(root)]
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("candidate package could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]
