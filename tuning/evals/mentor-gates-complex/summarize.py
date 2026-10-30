"""Verify immutable complex-gate artifacts and report paired outcomes."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / "tuning/runtime/mentor-gates-complex-v1"


def read(path):
    return json.loads(path.read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    manifest = read(RUN / "manifest.json")
    assert sha((SOURCE / "cases.json").read_bytes()) == manifest["cases_sha256"]
    assert sha((SOURCE / "protocol.md").read_bytes()) == manifest["protocol_sha256"]
    base = ROOT / "mentor/skills/evaluation-design"
    assert sha((base / "SKILL.md").read_bytes()) == manifest["skill_sha256"]
    assert sha((base / "references/promotion-gate.md").read_bytes()) == manifest["gate_sha256"]
    anchors = {a["id"]: a for a in read(RUN / "calibration.json")["items"]}
    assert anchors["cal-17"]["scores"] == [2, 2, 2] and not anchors["cal-17"]["critical_errors"]
    assert anchors["cal-42"]["scores"] == [0, 0, 0] and anchors["cal-42"]["critical_errors"]
    items = read(RUN / "grades.json")["items"]
    assert len(items) == len({x["id"] for x in items}) == 16
    grades = {x["id"]: x for x in items}
    assert set(grades) == {j["id"] for j in manifest["jobs"]}
    cases = {c["id"]: c for c in read(SOURCE / "cases.json")}
    enc = tiktoken.get_encoding("o200k_base")
    arms = {a: {"correct": 0, "total": 8, "false_acceptance": [],
                "valid_accept_rejected": [], "inconclusive_labeled_reject": [],
                "secondary_score": 0, "secondary_max": 48, "critical_errors": [],
                "instruction_tokens_proxy": 0, "output_tokens_proxy": 0, "cases": {}}
            for a in ["control", "gate"]}
    rows = []
    for job in manifest["jobs"]:
        assert sha((RUN / (job["id"] + ".txt")).read_bytes()) == job["sha256"]
        text = (RUN / job["output"]).read_text()
        answer = json.loads(text)
        assert set(answer) == {"verdict", "decisive_evidence_ids", "reason", "allowed_claim", "next_action"}
        assert answer["verdict"] in {"accept", "reject", "inconclusive"}
        assert isinstance(answer["decisive_evidence_ids"], list)
        case = cases[job["case"]]
        evidence_ids = {a["id"] for a in case["public"]["artifacts"]}
        invalid_ids = sorted(set(answer["decisive_evidence_ids"]) - evidence_ids)
        grade = grades[job["id"]]
        assert len(grade["scores"]) == len(grade["evidence"]) == 3
        assert all(type(x) is int and 0 <= x <= 2 for x in grade["scores"])
        assert isinstance(grade["critical_errors"], list)
        expected = case["gold"]["verdict"]
        actual = answer["verdict"]
        arm = arms[job["arm"]]
        arm["correct"] += actual == expected
        if actual == "accept" and expected != "accept":
            arm["false_acceptance"].append(case["id"])
        if actual == "reject" and expected == "accept":
            arm["valid_accept_rejected"].append(case["id"])
        if actual == "reject" and expected == "inconclusive":
            arm["inconclusive_labeled_reject"].append(case["id"])
        arm["secondary_score"] += sum(grade["scores"])
        arm["critical_errors"].extend(grade["critical_errors"])
        arm["instruction_tokens_proxy"] += job["instruction_tokens_proxy"]
        arm["output_tokens_proxy"] += len(enc.encode(text))
        words = sum(len(str(answer[k]).split()) for k in ["reason", "allowed_claim", "next_action"]) + len(answer["decisive_evidence_ids"]) + 1
        row = {"case": case["id"], "pair_id": case["pair_id"], "arm": job["arm"],
               "response_id": job["id"], "expected": expected, "actual": actual,
               "correct": actual == expected, "invalid_evidence_ids": invalid_ids,
               "words": words, "within_word_cap": words <= 180,
               "scores": grade["scores"], "grading_evidence": grade["evidence"],
               "critical_errors": grade["critical_errors"], "response": answer}
        rows.append(row)
        arm["cases"][case["id"]] = {k: row[k] for k in ["expected", "actual", "correct", "scores", "response_id"]}
    pairs = defaultdict(list)
    for c in cases.values():
        pairs[c["pair_id"]].append(c["id"])
    for arm in arms.values():
        arm["paired_relations_correct"] = sum(all(arm["cases"][cid]["correct"] for cid in ids) for ids in pairs.values())
        arm["clean_screen"] = arm["correct"] == 8 and not arm["critical_errors"] and not arm["false_acceptance"]
    result = {"experiment": "mentor-gates-complex-v1", "arms": arms, "cases": rows,
              "guidance_unchanged_during_screen": True,
              "invalid_evidence_id_count": sum(bool(x["invalid_evidence_ids"]) for x in rows),
              "word_cap_violations": [x["response_id"] for x in rows if not x["within_word_cap"]],
              "marginal_effect_limit": "Single observation per case/arm; same-family grading; not a statistical superiority or live-session claim.",
              "cost_scope": "serialized o200k_base instruction/output proxy; excludes reasoning, host/tool overhead, caching and billed usage"}
    (SOURCE / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"arms": {a: {k: v[k] for k in ["correct", "total", "paired_relations_correct", "secondary_score", "secondary_max", "false_acceptance", "inconclusive_labeled_reject", "critical_errors", "instruction_tokens_proxy"]} for a, v in arms.items()},
                      "invalid_evidence_ids": result["invalid_evidence_id_count"],
                      "word_cap_violations": result["word_cap_violations"]}, indent=2))


if __name__ == "__main__":
    main()
