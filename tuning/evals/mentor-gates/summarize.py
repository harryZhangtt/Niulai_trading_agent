"""Check atomic verdicts without substituting model judgment for the answer key."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / "tuning/runtime/mentor-gates-v1"


def read(path):
    return json.loads(path.read_text())


def response(path):
    data = read(path)
    assert set(data) == {"verdict", "decisive_evidence", "allowed_claim", "next_action"}
    assert data["verdict"] in {"accept", "reject", "inconclusive"}
    assert all(isinstance(x, str) and x.strip() for x in data.values())
    assert sum(len(x.split()) for x in data.values()) <= 100
    return data


def main():
    manifest = read(RUN / "manifest.json")
    for field, name in [("protocol_sha256", "protocol.md"), ("cases_sha256", "cases.json")]:
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == manifest[field]
    cases = {x["id"]: x for x in read(SOURCE / "cases.json")}
    original = []
    for job in manifest["jobs"]:
        assert hashlib.sha256((RUN / (job["packet"] + ".txt")).read_bytes()).hexdigest() == job["sha256"]
        case = cases[job["case"]]
        actual = response(RUN / job["output"])
        original.append({"case": case["id"], "pair": case["pair"], "expected": case["expected"],
                         "actual": actual["verdict"], "passed": actual["verdict"] == case["expected"],
                         "response": actual})
    refined_manifest = read(RUN / "refinement-manifest.json")
    for field, name in [("protocol_sha256", "refinement-protocol.md"),
                        ("cases_sha256", "refinement-cases.json")]:
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == refined_manifest[field]
    refined = []
    for i, case in enumerate(read(SOURCE / "refinement-cases.json"), 1):
        name = f"refine-{i:02}"
        assert hashlib.sha256((RUN / (name + ".txt")).read_bytes()).hexdigest() == refined_manifest["packet_sha256"][name]
        actual = response(RUN / (name + "-response.json"))
        refined.append({"case": case["id"], "expected": case["expected"], "actual": actual["verdict"],
                        "passed": actual["verdict"] == case["expected"], "response": actual})
    results = {"original_passed": sum(x["passed"] for x in original), "original_total": len(original),
               "original": original, "fresh_refinement_passed": sum(x["passed"] for x in refined),
               "fresh_refinement_total": len(refined), "fresh_refinement": refined,
               "rationale_review": "Root reviewed each response: evidence and allowed claims match the supplied situation. Original missing-case response recognized incomplete evidence but used reject rather than inconclusive.",
               "limitation": "Single-run synthetic atomic behavior checks; no baseline ablation or broad efficacy inference."}
    (SOURCE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Original: {results['original_passed']}/{len(original)} verdicts; fresh refinement: {results['fresh_refinement_passed']}/{len(refined)}.")


if __name__ == "__main__":
    main()
