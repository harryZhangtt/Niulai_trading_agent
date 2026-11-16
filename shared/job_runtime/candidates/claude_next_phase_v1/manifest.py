"""Hash-closed manifest validation with no activation or I/O beyond source reads."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .contracts import CAPABILITIES, IntegrationContractError

ROOT = Path(__file__).resolve().parents[4]
MANIFEST_PATH = Path(__file__).with_name("manifest.json")


def load_manifest() -> Mapping[str, object]:
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    required = {"schema_version", "classification", "enabled", "capability_open", "live_authority",
                "intended_runtime", "cli_enabled", "cli_materialized", "promotion_blocked",
                "promotion_block_reason", "source_bindings", "prior_evidence", "independent_review"}
    if type(value) is not dict or set(value) != required:
        raise IntegrationContractError("MANIFEST_SHAPE_INVALID")
    for key in ("enabled", "capability_open", "live_authority", "intended_runtime",
                "cli_enabled", "cli_materialized"):
        if value[key] is not False:
            raise IntegrationContractError("MANIFEST_NOT_INERT")
    if value["promotion_blocked"] is not True:
        raise IntegrationContractError("MANIFEST_PROMOTION_OPEN")
    return MappingProxyType(value)


def verify_source_closure(root: Path = ROOT) -> Mapping[str, str]:
    manifest = load_manifest()
    observed = {}
    for group in manifest["source_bindings"].values():
        for relative, expected in group.items():
            path = root / relative
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise IntegrationContractError("SOURCE_BINDING_MISMATCH")
            observed[relative] = actual
    return MappingProxyType(observed)
