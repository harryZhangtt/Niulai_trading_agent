"""Validate the independent route screen and count its bounded text context."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / "tuning/runtime/ui-routing-screen-v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def main():
    import tiktoken
    manifest = read(RUN / "manifest.json")
    for relative, expected in manifest["frozen_hashes"].items():
        require(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, "frozen artifact changed: " + relative)
    cases = read(SOURCE / "cases.json")
    response = read(RUN / "worker/routes.json")
    routes = response["routes"]
    ids = [r["id"] for r in routes]
    require(len(ids) == len(set(ids)) and set(ids) == {c["id"] for c in cases}, "missing/duplicate/extra routes")
    routes = {r["id"]: r for r in routes}
    ui = ROOT / "ui"
    entries = {p.parent.name: str(p.relative_to(ui)) for p in (ui / "skills").glob("*/SKILL.md")}
    require(len(entries) == 7, "expected six imported UI skills and one local state skill")
    packet = read(RUN / "worker/packet.json")
    encoder = tiktoken.get_encoding("o200k_base")
    base = len(encoder.encode(packet["instructions"] + packet["policy"] + packet["router"]))
    router_tokens = len(encoder.encode(packet["router"]))
    files = {}

    def resource(relative):
        path = ui / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(ui.resolve()) and path.is_file(), "invalid resource: " + relative)
        if relative not in files:
            files[relative] = {"tokens_proxy": len(encoder.encode(path.read_text())),
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return files[relative]["tokens_proxy"]

    all_entries = set(entries.values())
    always_on = base + sum(resource(p) for p in all_entries)
    checks, loaded, total, matched_total = [], set(), 0, 0
    for case in cases:
        route = routes[case["id"]]
        require(set(route) == {"id", "skills", "references", "reason"}, "route schema")
        selected, refs = route["skills"], route["references"]
        require(isinstance(selected, list) and len(selected) == len(set(selected)) and set(selected) <= set(entries), "invalid skill names")
        require(isinstance(refs, list) and len(refs) == len(set(refs)) and all(isinstance(p, str) for p in refs), "invalid references")
        require(isinstance(route["reason"], str) and route["reason"].strip(), "empty route explanation")
        require(all(p.startswith("skills/") and "/AGENTS.md" not in p for p in refs), "unnecessary full compiled guide or non-skill reference")
        resources = {entries[s] for s in selected} | set(refs)
        cost = base + sum(resource(p) for p in resources)
        loaded.update(resources)
        total += cost
        matched_total += base + sum(resource(p) for p in all_entries | set(refs))
        missing = sorted(set(case["required"]) - set(selected))
        extra = sorted(set(selected) - set(case["required"]) - set(case["optional"]))
        missing_refs = sorted(set(case["refs"]) - set(refs))
        checks.append({"id": case["id"], "selected": selected, "references": refs,
                       "missing": missing, "unnecessary": extra, "missing_playbooks": missing_refs,
                       "passed": not missing and not extra and not missing_refs,
                       "instruction_tokens_proxy": cost})
    result = {"experiment": manifest["experiment"], "routing_passed": sum(c["passed"] for c in checks),
              "total": len(cases), "cases": checks, "router_tokens_proxy": router_tokens,
              "supplied_router_packet_tokens_proxy": len(encoder.encode((RUN / "worker/packet.json").read_text())),
              "routing_response_tokens_proxy": len(encoder.encode((RUN / "worker/routes.json").read_text())),
              "selected_snapshot_instruction_tokens_proxy": total,
              "all_seven_entrypoints_snapshot_tokens_proxy": always_on * len(cases),
              "selected_session_union_instruction_tokens_proxy": base + sum(files[p]["tokens_proxy"] for p in loaded),
              "all_seven_entrypoints_session_tokens_proxy": always_on,
              "all_seven_with_same_references_snapshot_tokens_proxy": matched_total,
              "all_seven_with_same_references_session_tokens_proxy": base + sum(resource(p) for p in all_entries | loaded),
              "resources": files, "provider_usage": None,
              "quality_scope": "Semantic routing only; no generated-UI quality comparison. Separate Playwright fixture tests runtime invariants.",
              "cost_scope": "o200k_base proxy, not billing/latency; entrypoints-only floor excludes conditional references; additional matched counterfactual includes same selected references in both paths"}
    (SOURCE / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("cases", "resources")}, indent=2))
    return 0 if result["routing_passed"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
