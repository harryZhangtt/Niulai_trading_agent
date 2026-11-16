"""Sealed provider-free fixture ports; no callbacks, subprocesses, or I/O effects."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, canonical_bytes, exact, require, validate_provider_result

_ROOT = Path(__file__).resolve().parent

class FixtureProfile(Enum):
    NOMINAL = "NOMINAL"
    UNKNOWN_FIRST = "UNKNOWN_FIRST"

@dataclass(frozen=True)
class _FixtureSource:
    relative_path: str
    size: int
    sha256: str

_CLAUDE_NOMINAL = _FixtureSource("fixtures/providers/claude-nominal-v1.json", 2269, "7232ed512d3bab5f758952d35e1d26bda605ed9b572415abc6d16d2a4eb40422")
_CLAUDE_UNKNOWN = _FixtureSource("fixtures/providers/claude-unknown-first-v1.json", 2275, "30c165ea1230f0e5c128837dbffd181185d6c5eafb6e4ee1b842a8ef026615b5")
_CODEX_NOMINAL = _FixtureSource("fixtures/providers/codex-nominal-v1.json", 2266, "6d4b1a67d3fbfbc434a04fa0c879377962c484893f6dbeaea1a0321968501750")


def _load(source: _FixtureSource, provider: str) -> Mapping[str, Any]:
    path = _ROOT / source.relative_path
    require(path.is_file() and not path.is_symlink(), "FIXTURE_SOURCE_NOT_REGULAR")
    raw = path.read_bytes()
    require(len(raw) == source.size and hashlib.sha256(raw).hexdigest() == source.sha256, "FIXTURE_SOURCE_DRIFT")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("FIXTURE_SOURCE_JSON") from exc
    require(canonical_bytes(value) == raw, "FIXTURE_SOURCE_NOT_CANONICAL")
    value = exact(value, ("version", "fixture_shape", "provider_port", "results"), "FIXTURE_FILE_SHAPE")
    require(value["version"] == 1 and value["fixture_shape"] == "REAL_SHAPED_SANITIZED_NO_EFFECT", "FIXTURE_FILE_VERSION")
    require(value["provider_port"] == provider and type(value["results"]) is list, "FIXTURE_FILE_PROVIDER")
    return value


class _SealedFixturePort:
    __slots__ = ("_provider", "_results", "_admitted", "_active", "_max_active")

    def __init__(self, provider: str, source: _FixtureSource) -> None:
        fixture = _load(source, provider)
        self._provider = provider
        self._results = {item["cell_id"]: copy.deepcopy(item) for item in fixture["results"]}
        require(len(self._results) == len(fixture["results"]), "FIXTURE_DUPLICATE_CELL")
        self._admitted: set[str] = set()
        self._active = 0
        self._max_active = 0

    @property
    def admission_count(self) -> int:
        return len(self._admitted)

    @property
    def max_active(self) -> int:
        return self._max_active

    def admit(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        require(type(plan) is dict, "PLAN_TYPE")
        exact(plan, ("cell_id", "order_index", "provider_port", "blind_addon_label", "checks_enabled", "destination_id"), "PLAN_SHAPE")
        require(plan["provider_port"] == self._provider, "PROVIDER_SWAP")
        cell_id = plan["cell_id"]
        require(cell_id not in self._admitted, "SECOND_ADMISSION_FORBIDDEN")
        require(cell_id in self._results, "FIXTURE_CELL_NOT_FOUND")
        require(self._active == 0, "CONCURRENCY_GREATER_THAN_ONE")
        self._active += 1
        self._max_active = max(self._max_active, self._active)
        try:
            result = copy.deepcopy(self._results[cell_id])
            validate_provider_result(result, plan)
            self._admitted.add(cell_id)
            return result
        finally:
            self._active -= 1


class ClaudeFixturePort(_SealedFixturePort):
    __slots__ = ()

    def __init__(self, profile: FixtureProfile = FixtureProfile.NOMINAL) -> None:
        require(type(profile) is FixtureProfile, "CLAUDE_PROFILE_TYPE")
        source = _CLAUDE_NOMINAL if profile is FixtureProfile.NOMINAL else _CLAUDE_UNKNOWN
        super().__init__("CLAUDE", source)


class CodexFixturePort(_SealedFixturePort):
    __slots__ = ()

    def __init__(self, profile: FixtureProfile = FixtureProfile.NOMINAL) -> None:
        require(profile is FixtureProfile.NOMINAL, "CODEX_PROFILE_UNSUPPORTED")
        super().__init__("CODEX", _CODEX_NOMINAL)


__all__ = ["ClaudeFixturePort", "CodexFixturePort", "FixtureProfile"]
