"""Fail closed on incomplete artifacts; report quality and context separately."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / "tuning/runtime/development-discipline-v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_json(text):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key: " + key)
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("nonstandard JSON constant: " + value)

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def indexed(items, expected, label):
    require(isinstance(items, list), label + " must be a list")
    ids = [x["id"] for x in items]
    require(len(ids) == len(set(ids)) and set(ids) == set(expected), label + " missing/duplicate/extra IDs")
    return {x["id"]: x for x in items}


def evaluate(cases, manifest, responses, routes, grades, encoder):
    require(len(manifest["jobs"]) == 2 and len({j["id"] for j in manifest["jobs"]}) == 2,
            "expected two unique worker jobs")
    case_map = {c["id"]: c for c in cases}
    engineering = [c["id"] for c in cases if "criteria" in c]
    expected_grades = {j["id"] + "/" + c for j in manifest["jobs"] for c in engineering}
    grade_map = indexed(grades, expected_grades, "grades")
    arms = {}
    for job in manifest["jobs"]:
        arm = job["arm"]
        answers = indexed(responses[job["id"]], case_map, "responses")
        chosen = indexed(routes[job["id"]], case_map, "routes")
        result = {"cases": {}, "quality": 0, "maximum": 8 * len(engineering),
                  "critical_failures": [], "routing": [], "instruction_tokens_proxy": 0,
                  "response_tokens_proxy": 0, "loaded_skills": set()}
        costs = {}
        for path, info in job["skill_files"].items():
            name = Path(path).parts[1]
            costs[name] = costs.get(name, 0) + info["tokens_proxy"]
        for cid, answer in answers.items():
            require(set(answer) == {"id", "skills", "decision", "next_actions", "evidence_ids", "allowed_claim"}, "response schema")
            selected = answer["skills"]
            require(isinstance(selected, list) and len(selected) == len(set(selected)) and all(x in costs for x in selected), "invalid skills")
            require(selected == chosen[cid]["skills"], "route changed after reading skill bodies")
            require(all(isinstance(answer[k], str) and answer[k].strip() for k in ("decision", "allowed_claim")), "empty decision/claim")
            require(isinstance(answer["next_actions"], list) and all(isinstance(x, str) for x in answer["next_actions"]), "invalid actions")
            evidence_ids = answer["evidence_ids"]
            require(isinstance(evidence_ids, list) and len(evidence_ids) == len(set(evidence_ids)), "invalid evidence IDs")
            require(set(evidence_ids) <= {x["id"] for x in case_map[cid]["public"]["artifacts"]}, "invented evidence ID")
            prose = " ".join([answer["decision"], *answer["next_actions"], answer["allowed_claim"]])
            require(len(re.findall(r"\S+", prose)) <= 220, "response over word budget")
            expected = case_map[cid]["expected"][arm]
            missing = sorted(set(expected["required"]) - set(selected))
            extra = sorted(set(selected) - set(expected["required"]) - set(expected["optional"]))
            result["routing"].append({"id": cid, "selected": selected, "missing": missing,
                                      "unnecessary": extra, "passed": not missing and not extra})
            result["loaded_skills"].update(selected)
            result["instruction_tokens_proxy"] += job["base_instruction_tokens_proxy"] + sum(costs[s] for s in selected)
            result["response_tokens_proxy"] += len(encoder.encode(json.dumps(answer)))
            if cid in engineering:
                grade = grade_map[job["id"] + "/" + cid]
                require(set(grade) == {"id", "scores", "evidence", "critical_failures"}, "grade schema")
                scores = grade["scores"]
                require(len(scores) == 4 and all(type(s) is int and 0 <= s <= 2 for s in scores), "invalid rubric scores")
                require(len(grade["evidence"]) == 4 and all(isinstance(e, str) and e and e in prose for e in grade["evidence"]), "grade evidence must quote response")
                require(isinstance(grade["critical_failures"], list) and all(isinstance(x, str) and x for x in grade["critical_failures"]), "invalid critical failures")
                result["quality"] += sum(scores)
                result["critical_failures"].extend(grade["critical_failures"])
                result["cases"][cid] = {"score": sum(scores), "scores": scores, "evidence": grade["evidence"], "critical_failures": grade["critical_failures"]}
        result["loaded_skills"] = sorted(result["loaded_skills"])
        result["session_instruction_tokens_proxy"] = job["base_instruction_tokens_proxy"] + sum(costs[s] for s in result["loaded_skills"])
        result["always_on_instruction_tokens_proxy"] = len(cases) * (job["base_instruction_tokens_proxy"] + sum(costs.values()))
        result["always_on_session_instruction_tokens_proxy"] = job["base_instruction_tokens_proxy"] + sum(costs.values())
        arms[arm] = result
    require(set(arms) == {"baseline", "candidate"}, "missing arm")
    baseline, candidate = arms["baseline"], arms["candidate"]
    gates = {
        "no_critical_failure": not candidate["critical_failures"],
        "no_case_quality_regression": all(candidate["cases"][c]["score"] >= baseline["cases"][c]["score"] for c in engineering),
        "correct_selective_routing": all(x["passed"] for x in candidate["routing"]),
        "cheaper_than_always_loading_all_six": candidate["instruction_tokens_proxy"] < candidate["always_on_instruction_tokens_proxy"],
    }
    return {"experiment": manifest["experiment"], "arms": arms, "gates": gates,
            "disposition": "provisional_procedural_adopt" if all(gates.values()) else "do_not_adopt_under_this_rule",
            "provider_usage": manifest.get("provider_usage"),
            "effectiveness": "inconclusive: synthetic decision screen, one worker per arm, same-family grading",
            "cost_scope": "o200k_base proxy; excludes host/reasoning/tool framing/billing/caching; session union retains loaded text"}


def main():
    import tiktoken
    manifest = parse_json((RUN / "manifest.json").read_text())
    for relative, expected in manifest["source_hashes"].items():
        require(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, "frozen source changed: " + relative)
    responses, routes = {}, {}
    for job in manifest["jobs"]:
        directory = RUN / job["id"]
        require(hashlib.sha256((directory / "packet.txt").read_bytes()).hexdigest() == job["packet_sha256"], "packet changed")
        for relative, info in job["skill_files"].items():
            require(hashlib.sha256((directory / relative).read_bytes()).hexdigest() == info["sha256"], "skill snapshot changed")
        responses[job["id"]] = parse_json((directory / "responses.json").read_text())["items"]
        routes[job["id"]] = parse_json((directory / "routes.json").read_text())["routes"]
    calibration = indexed(parse_json((RUN / "calibration.json").read_text())["items"], {"good", "bad"}, "calibration")
    require(calibration["good"]["scores"] == [2, 2, 2, 2] and not calibration["good"]["critical_failures"], "good anchor failed")
    require(calibration["bad"]["scores"] == [0, 0, 0, 0] and calibration["bad"]["critical_failures"], "bad anchor failed")
    result = evaluate(parse_json((SOURCE / "cases.json").read_text()), manifest, responses, routes,
                      parse_json((RUN / "grades.json").read_text())["items"], tiktoken.get_encoding("o200k_base"))
    (SOURCE / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"gates": result["gates"], "disposition": result["disposition"],
                      "arms": {a: {k: r[k] for k in ("quality", "instruction_tokens_proxy", "session_instruction_tokens_proxy", "always_on_instruction_tokens_proxy", "always_on_session_instruction_tokens_proxy")} for a, r in result["arms"].items()}}, indent=2))
    return 0 if all(result["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
