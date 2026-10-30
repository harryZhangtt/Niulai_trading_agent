#!/usr/bin/env python3
"""Offline provenance and local-resource checks for the vendored mentor skills."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def verify(root):
    errors = []
    manifest = json.loads((root / "upstream/sources.lock.json").read_text())
    seen = set()
    for name, repo in manifest["repositories"].items():
        if not re.fullmatch(r"[0-9a-f]{40}", repo["commit"]):
            errors.append(f"{name}: not pinned to a full commit")
        if repo["license"] != "MIT":
            errors.append(f"{name}: license needs review")
    for item in manifest["files"]:
        relative = item["local_path"]
        path = root / relative
        if relative in seen:
            errors.append(f"duplicate provenance entry: {relative}")
        seen.add(relative)
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            errors.append(f"unsafe source path: {relative}")
            continue
        if not path.is_file():
            errors.append(f"missing imported file: {relative}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["local_sha256"]:
            errors.append(f"unreviewed change: {relative}")
        if item["modified"] != (digest != item["upstream_sha256"]):
            errors.append(f"incorrect modification declaration: {relative}")
        if item["repository"] not in manifest["repositories"]:
            errors.append(f"unknown repository: {relative}")
    skills = sorted((root / "skills").glob("*/SKILL.md"))
    local_skills = {"development-discipline"}
    imported = [s for s in skills if s.parent.name not in local_skills]
    if len(imported) != 5 or len(skills) != 6:
        errors.append(f"expected five imported and one authored skill, found {len(skills)} total")
    for skill in skills:
        if skill.parent.name in local_skills:
            # Workspace-authored guidance must not pretend to be an upstream copy.
            if str(skill.relative_to(root)) in seen:
                errors.append(f"authored skill incorrectly declares upstream provenance: {skill}")
            continue
        if str(skill.relative_to(root)) not in seen:
            errors.append(f"skill lacks upstream provenance: {skill}")
        for required in ["UPSTREAM.md", "references/investment-context.md"]:
            if not (skill.parent / required).is_file():
                errors.append(f"missing {required} for {skill.parent.name}")
    for page in (root / "skills").rglob("*.md"):
        text = page.read_text()
        # Fenced examples can contain illustrative URLs/paths, not resource links.
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in re.finditer(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
            target = match.group(1).strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            resolved = page.parent / unquote(parsed.path)
            if not resolved.exists():
                errors.append(f"broken local link: {page.relative_to(root)} -> {target}")
    return errors, len(manifest["files"]), len(skills)


if __name__ == "__main__":
    errors, files, skills = verify(Path(__file__).resolve().parents[1])
    for error in errors:
        print(error)
    if not errors:
        print(f"Verified {skills} skills, {files} imported-file hashes, commit pins and local Markdown links.")
    raise SystemExit(bool(errors))
