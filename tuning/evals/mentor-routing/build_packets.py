"""Freeze isolated solver packets; no model calls or automatic grading."""

import hashlib
import json
import random
import sys
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / "tuning/runtime/mentor-routing-v1"


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    target = RUN / "manifest.json"
    if target.exists():
        raise SystemExit("Refusing to overwrite frozen packets")
    encoder = tiktoken.get_encoding("o200k_base")
    cases = json.loads((SOURCE / "cases.json").read_text())
    common = (ROOT / "mentor/AGENTS.md").read_text().split("# Skill routing")[0]
    candidate = (SOURCE / "candidate-routing.md").read_text()
    contract = """You are advising the next tuning step from supplied evidence only.
Do not execute the proposed work or claim any new result. Answer in at most 220
words, as a JSON object with keys decision, next_actions (list), evidence_needed
(list), limits. Focus on the smallest useful next action and an honest status.
The following is the complete task-specific guidance for this controlled case.
Do not discover additional skills or read other project files.
"""
    jobs = []
    for case in cases:
        for arm in ["baseline", "current", "candidate"]:
            skills = [] if arm == "baseline" else case[arm + "_skills"]
            guidance = common + ("\n" + candidate if arm == "candidate" else "")
            for name in skills:
                base = ROOT / "mentor/skills" / name
                guidance += "\n" + (base / "SKILL.md").read_text()
                guidance += "\n" + (base / "references/investment-context.md").read_text()
            packet = contract + "\n<guidance>\n" + guidance + "\n</guidance>\n<case>\n" + case["request"] + "\n</case>\n"
            jobs.append({"case": case["id"], "arm": arm, "skills": skills,
                         "instruction_tokens_proxy": len(encoder.encode(contract + guidance)),
                         "packet_tokens_proxy": len(encoder.encode(packet)), "packet": packet})
    random.Random(73026).shuffle(jobs)
    for i, job in enumerate(jobs, 1):
        name = f"packet-{i:02d}"
        packet = job.pop("packet")
        (RUN / (name + ".txt")).write_text(packet)
        job.update(id=name, sha256=hashlib.sha256(packet.encode()).hexdigest(),
                   output=name + "-response.json")
    manifest = {"model_policy": "inherit parent gpt-6.1-sol; no overrides",
                "tokenizer": "tiktoken 0.12.0 o200k_base; proxy only",
                "isolation": "fresh fork_turns=none worker; permitted file instructions, not OS sandbox",
                "cases_sha256": hashlib.sha256((SOURCE / "cases.json").read_bytes()).hexdigest(),
                "protocol_sha256": hashlib.sha256((SOURCE / "protocol.md").read_bytes()).hexdigest(),
                "candidate_routing_sha256": hashlib.sha256((SOURCE / "candidate-routing.md").read_bytes()).hexdigest(),
                "jobs": jobs}
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps([{k: j[k] for k in ["id", "case", "arm", "instruction_tokens_proxy"]} for j in jobs], indent=2))


if __name__ == "__main__":
    main()
