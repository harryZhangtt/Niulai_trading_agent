"""Validate frozen screening artifacts and summarize quality/context separately."""

import hashlib
import json
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / "tuning/runtime/mentor-routing-v1"


def read(path):
    return json.loads(path.read_text())


def main():
    manifest = read(RUN / "manifest.json")
    for field, name in [("cases_sha256", "cases.json"),
                        ("protocol_sha256", "protocol.md"),
                        ("candidate_routing_sha256", "candidate-routing.md")]:
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == manifest[field], name
    anchors = {x["id"]: x for x in read(RUN / "calibration.json")["items"]}
    assert anchors["anchor-x"]["scores"] == [0, 0, 0, 0]
    assert len(anchors["anchor-x"]["critical_failures"]) == 3
    assert anchors["anchor-y"]["scores"] == [2, 2, 2, 2]
    assert not anchors["anchor-y"]["critical_failures"]
    items = read(RUN / "grades.json")["items"]
    assert len(items) == 12 and len({x["id"] for x in items}) == 12
    grades = {x["id"]: x for x in items}
    assert set(grades) == {j["id"] for j in manifest["jobs"]}
    enc = tiktoken.get_encoding("o200k_base")
    arms = {a: {"quality": 0, "maximum": 32, "instruction_tokens_proxy": 0,
                "output_tokens_proxy": 0, "cases": {}, "critical_failures": []}
            for a in ["baseline", "current", "candidate"]}
    for job in manifest["jobs"]:
        packet = (RUN / (job["id"] + ".txt")).read_bytes()
        assert hashlib.sha256(packet).hexdigest() == job["sha256"]
        response_text = (RUN / job["output"]).read_text()
        response = json.loads(response_text)
        assert set(response) == {"decision", "next_actions", "evidence_needed", "limits"}
        grade = grades[job["id"]]
        assert len(grade["scores"]) == 4 and all(type(x) is int and 0 <= x <= 2 for x in grade["scores"])
        assert len(grade["evidence"]) == 4
        assert isinstance(grade["critical_failures"], list)
        arm = arms[job["arm"]]
        score = sum(grade["scores"])
        arm["quality"] += score
        arm["instruction_tokens_proxy"] += job["instruction_tokens_proxy"]
        arm["output_tokens_proxy"] += len(enc.encode(response_text))
        arm["critical_failures"].extend(grade["critical_failures"])
        arm["cases"][job["case"]] = {"score": score, "scores": grade["scores"],
                                         "packet": job["id"], "evidence": grade["evidence"]}
    expected_routes = {x["id"]: x for x in read(SOURCE / "routing-cases.json")}
    route_items = read(RUN / "routing-response.json")["routes"]
    assert len(route_items) == len(expected_routes)
    assert len({x["id"] for x in route_items}) == len(expected_routes)
    route_checks = []
    for item in route_items:
        expected = expected_routes[item["id"]]
        selected = set(item["skills"])
        missing = set(expected["required"]) - selected
        extra = selected - set(expected["required"]) - set(expected["optional"])
        route_checks.append({"id": item["id"], "selected": item["skills"],
                             "missing": sorted(missing), "unnecessary": sorted(extra),
                             "passed": not missing and not extra})
    current, candidate = arms["current"], arms["candidate"]
    saving = 1 - candidate["instruction_tokens_proxy"] / current["instruction_tokens_proxy"]
    quality_gate = not candidate["critical_failures"] and all(
        c["score"] >= current["cases"][name]["score"] for name, c in candidate["cases"].items())
    router_gate = all(x["passed"] for x in route_checks)
    result = {"experiment": "mentor-routing-v1", "arms": arms,
              "context_proxy_reduction": saving,
              "routing": {"passed": sum(x["passed"] for x in route_checks), "total": len(route_checks), "cases": route_checks},
              "gates": {"quality_no_case_regression": quality_gate,
                        "context_reduction_at_least_30_percent": saving >= .30,
                        "blind_routing": router_gate},
              "routing_disposition": "provisional_adopt" if quality_gate and router_gate and saving >= .30 else "retain_current",
              "effectiveness_disposition": "inconclusive: four synthetic advice cases, one run per arm/case, same-family model grading",
              "measured_cost_scope": "o200k_base serialized instruction/output proxy; excludes billed usage, reasoning, caching and host/tool overhead"}
    (SOURCE / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"arms": {k: {f: v[f] for f in ["quality", "instruction_tokens_proxy", "output_tokens_proxy", "critical_failures"]} for k, v in arms.items()},
                      "context_proxy_reduction": saving, "routing": result["routing"]["passed"], "gates": result["gates"],
                      "disposition": result["routing_disposition"]}, indent=2))


if __name__ == "__main__":
    main()
