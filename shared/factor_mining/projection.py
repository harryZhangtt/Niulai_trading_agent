"""Bounded read-only projection of immutable factor RunManifest records."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from . import manifest


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "factor/runtime/registry"
RUN_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
OVERVIEW_LIMIT = 256 * 1024
DETAIL_LIMIT = 1024 * 1024


class ProjectionError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ProjectionError(code)


def scrub(value, maximum=1000):
    text = str(value)[:maximum]
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+",
                  r"\1=[redacted]", text)
    text = re.sub(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b",
                  "[redacted]", text)
    text = re.sub(r"(?<![:/\\\w])/(?!/)[^\s,;\"'<>]+", "/[redacted]", text)
    text = re.sub(r"\b[A-Za-z]:\\[^\s,;]+", "[redacted]", text)
    return text


def _artifact(artifact):
    return {key: artifact[key] for key in ("id", "kind", "sha256", "size_bytes")}


def _performance_state(value):
    provenance = value["provenance"]
    if provenance["origin"] == "synthetic_fixture":
        return "withheld_fixture"
    if value["schema_version"] == 1:
        return ("legacy_reported_unverified" if provenance["origin"] == "reported_external"
                else "legacy_reproduced_hash_bound")
    performance = value["performance"]
    if not performance:
        return "not_published"
    if any(item["availability"] == "available" for item in performance):
        return ("available_unverified" if provenance["origin"] == "reported_external"
                else "available_hash_bound")
    return "unavailable"


def _factors(value):
    synthetic = value["provenance"]["origin"] == "synthetic_fixture"
    return [{**factor, "metrics": {} if synthetic else dict(factor["metrics"])}
            for factor in value["factors"]]


def _run(value, manifest_sha256, *, detail=False):
    projected = {
        "id": value["run_id"], "revision": value["revision"],
        "manifest_sha256": manifest_sha256,
        "manifest_schema_version": value["schema_version"],
        "created_at": value["created_at"],
        "status": value["status"], "provenance": value["provenance"],
        "performance_state": _performance_state(value),
        "engine": value["engine"], "protocol_sha256": value["protocol_sha256"],
        "dataset_snapshot_sha256": value["dataset_snapshot_sha256"],
        "stages": value["stages"], "factors": _factors(value), "gates": value["gates"],
        "failures": value["failures"], "resources": value["resources"],
        "limitations": [scrub(item) for item in value["limitations"]],
        "artifact_count": len(value["artifacts"]),
    }
    if detail:
        projected["artifacts"] = [_artifact(item) for item in value["artifacts"]]
        if value["schema_version"] == 2:
            projected["performance"] = value["performance"]
    return projected


def _heads(registry):
    directory = registry / "heads"
    if not directory.exists():
        return []
    require(directory.is_dir() and not directory.is_symlink(), "FACTOR_PROJECTION_HEADS_INVALID")
    heads = [(path.lstat().st_mtime_ns, path.stem)
             for path in directory.iterdir()
             if path.is_file() and not path.is_symlink() and path.suffix == ".json"]
    require(len(heads) <= 1000 and all(RUN_ID.fullmatch(name) for _, name in heads),
            "FACTOR_PROJECTION_RUN_LIMIT")
    return [name for _, name in sorted(heads, reverse=True)]


def project(registry_root=DEFAULT_REGISTRY, *, run_id=None, manifest_sha256=None, limit=50):
    registry = Path(registry_root).absolute()
    require(registry.is_dir() and not registry.is_symlink() and registry.resolve() == registry,
            "FACTOR_PROJECTION_REGISTRY_UNAVAILABLE")
    require(run_id is None or isinstance(run_id, str) and RUN_ID.fullmatch(run_id),
            "FACTOR_PROJECTION_RUN_ID_INVALID")
    require(manifest_sha256 is None or isinstance(manifest_sha256, str) and
            SHA64.fullmatch(manifest_sha256), "FACTOR_PROJECTION_SHA_INVALID")
    require(manifest_sha256 is None or run_id is not None, "FACTOR_PROJECTION_RUN_REQUIRED")
    require(type(limit) is int and 1 <= limit <= 100, "FACTOR_PROJECTION_LIMIT_INVALID")
    warnings = []
    runs = []
    selected = [run_id] if run_id is not None else _heads(registry)[:limit]
    for selected_id in selected:
        try:
            if manifest_sha256 is None:
                loaded = manifest.load_head(registry, selected_id)
                value = loaded["manifest"]
                identity = loaded["head"]["manifest_sha256"]
            else:
                value = manifest.load_manifest(registry, selected_id, manifest_sha256)
                identity = manifest_sha256
            runs.append(_run(value, identity, detail=run_id is not None))
        except (manifest.ManifestError, OSError, ValueError):
            if run_id is not None:
                raise ProjectionError("FACTOR_PROJECTION_RUN_UNAVAILABLE") from None
            warnings.append({"run_id": selected_id, "code": "RUN_UNAVAILABLE"})
    result = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True, "scope": "factor_mining", "status":
            "partial" if warnings else "empty" if not runs else "ok",
        "projection_state": "fresh", "runs": runs, "warnings": warnings,
    }
    maximum = DETAIL_LIMIT if run_id is not None else OVERVIEW_LIMIT
    require(len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) <= maximum,
            "FACTOR_PROJECTION_SIZE_LIMIT")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--run-id")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    try:
        value = project(args.registry, run_id=args.run_id,
                        manifest_sha256=args.manifest_sha256, limit=args.limit)
    except Exception:
        print(json.dumps({"schema_version": 1, "status": "unavailable",
                          "error": {"code": "FACTOR_PROJECTION_UNAVAILABLE"}}))
        return 1
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
