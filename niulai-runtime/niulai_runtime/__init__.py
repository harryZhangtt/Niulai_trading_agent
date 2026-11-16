"""Controlled runtime adapters for the preserved Niulai migration snapshot."""

from pathlib import Path as _Path
from shared.exact_source import load_exact as _load_exact

_load_exact(__name__ + ".delivery", _Path(__file__).with_name("delivery.py"))
del _Path, _load_exact
