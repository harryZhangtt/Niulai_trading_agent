#!/usr/bin/env python3
"""Generate compatibility references using the pinned upstream generator."""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "references/upstream"
OUTPUT = ROOT / "references/codex"
spec = importlib.util.spec_from_file_location(
    "upstream_sync", UPSTREAM / "scripts/sync-codex-skills.py")
upstream_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream_sync)


def main():
    check = sys.argv[1:] == ["--check"]
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("Usage: sync_workflows.py [--check]")
    if not check:
        OUTPUT.mkdir(parents=True, exist_ok=True)
    count = 0
    stale = []
    for source in sorted((UPSTREAM / "skills").glob("*.md")):
        name = source.stem
        text = source.read_text(encoding="utf-8")
        generated = upstream_sync.metadata_for(name, source.name, text)
        generated += upstream_sync.codex_body(name, source.name, text)
        target = OUTPUT / source.name
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != generated:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_text(generated, encoding="utf-8")
        count += 1
    if stale:
        raise SystemExit("Stale compatibility references: " + ", ".join(stale))
    print(f"{'Checked' if check else 'Generated'} {count} compatibility references")


if __name__ == "__main__":
    main()
