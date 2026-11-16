import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/progress-and-recovery/scripts/validate_architecture_escalation.py"


def candidate_family():
    return [
        {"path": "investment/research/acquisition_acceptance.py", "sha256": "1" * 64,
         "owner": "acceptance", "module_boundary": "session-to-publication"},
        {"path": "investment/research/acquisition_live_session.py", "sha256": "2" * 64,
         "owner": "live-session", "module_boundary": "packet-to-runtime"},
        {"path": "shared/job_runtime/business.py", "sha256": "3" * 64,
         "owner": "gmail-effect", "module_boundary": "runtime-to-provider"},
    ]


def record():
    family = candidate_family()
    counters = {
        "critical_cross_module": 1,
        "clustered_high_same_root": 2,
        "confirmed_findings": 4,
        "module_count": 3,
        "owner_count": 3,
        "critical_reopens": 0,
        "high_boundary_reopens": 1,
        "lower_root_reopens": 0,
        "invalidated_reviews": 2,
        "post_green_high_findings": 3,
    }
    return {
        "version": "architecture-escalation-1",
        "candidate_sha256": hashlib.sha256(json.dumps(
            family, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_family": family,
        "owner": "integration-owner",
        "counters": counters,
        "triggered": True,
        "trigger_codes": [
            "critical_boundary", "clustered_high", "breadth", "reopen",
            "candidate_instability", "green_suite_contradiction",
        ],
        "external_semantics": True,
        "evidence": {
            "finding_ids": ["ARCH-CANDIDATE-001", "ARCH-SCHEMA-001", "ARCH-STATE-001", "ARCH-TRUST-001"],
            "candidate_hashes": ["candidate:sealed"],
            "module_boundaries": ["producer -> owner -> verifier"],
            "reproducer_refs": ["fixture:unknown-outcome"],
            "schema_refs": ["schema:producer", "schema:consumer"],
            "state_map_refs": ["state:effect-ledger"],
            "chronology_refs": ["progress:attempts"],
            "web_sources": [
                {"url": "https://example.com/primary", "role": "primary",
                 "route": "native_websearch_webfetch", "source_version_or_date": "2026-11-05",
                 "semantics": "caller token binds intent", "applicability_limits": "external API only",
                 "accessed_at": "2026-11-05"},
                {"url": "https://example.com/independent", "role": "independent",
                 "route": "native_websearch_webfetch", "source_version_or_date": "2026-11-05",
                 "semantics": "unknown effects require reconciliation", "applicability_limits": "no global exactly-once",
                 "accessed_at": "2026-11-05"},
            ],
        },
        "options": [
            {"id": "O0", "summary": "retain prior", "trust": "known prior boundary",
             "contract_fit": "capability remains blocked", "migration_failure_radius": "none",
             "maintenance_runtime_cost": "low", "fixture_realism": "existing evidence",
             "rollback": "keep disabled"},
            {"id": "O1", "summary": "narrow repair", "trust": "duplicated checks",
             "contract_fit": "partial", "migration_failure_radius": "small",
             "maintenance_runtime_cost": "low", "fixture_realism": "real-shaped fixture",
             "rollback": "restore prior"},
            {"id": "O2", "summary": "shared owner", "trust": "one authority",
             "contract_fit": "complete", "migration_failure_radius": "medium",
             "maintenance_runtime_cost": "medium", "fixture_realism": "vertical production boundaries",
             "rollback": "disable candidate"},
        ],
        "vertical_experiment": {
            "falsifiable_hypothesis": "one owner makes setup and runtime return identical custody verdicts",
            "falsifier": "any malformed fixture yields different setup/runtime verdicts or permits an effect",
            "nominal": "one provider-free nominal path",
            "failure": "one post-dispatch callback loss",
            "assertions": ["one legal transition", "unknown remains fenced"],
            "no_external_effects": True,
        },
        "decision": {
            "selected": "O2",
            "rationale": "shared custody dominates repeated adapters",
            "rollback_owner": "integration-owner",
            "allowed_claim": "provider-free structural evidence only",
            "unresolved": ["future live acceptance"],
        },
        "stop_rules": ["stop on candidate drift", "revert on duplicate effect"],
    }


class ArchitectureEscalationTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "runtime/test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="architecture-escalation-", dir=parent)
        self.addCleanup(self.temp.cleanup)

    def run_record(self, value, raw=None):
        path = Path(self.temp.name) / "record.json"
        path.write_text(raw if raw is not None else json.dumps(value))
        result = subprocess.run(["python3", str(SCRIPT), str(path)], text=True,
                                capture_output=True, timeout=10)
        return result, path

    def test_triggered_record_is_valid_and_read_only(self):
        result, path = self.run_record(record())
        before = path.read_bytes()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "ARCHITECTURE_ESCALATION_VALID")
        self.assertEqual(path.read_bytes(), before)

    def test_trigger_math_is_deterministic(self):
        cases = {"critical_cross_module": "critical_boundary",
                 "clustered_high_same_root": "clustered_high",
                 "invalidated_reviews": "candidate_instability",
                 "post_green_high_findings": "green_suite_contradiction"}
        for key, code in cases.items():
            with self.subTest(key=key):
                value = record()
                value["counters"] = {name: 0 for name in value["counters"]}
                value["evidence"]["finding_ids"] = ["ARCH-TEST-001"]
                value["counters"]["confirmed_findings"] = 1
                value["counters"]["module_count"] = len(value["candidate_family"])
                value["counters"]["owner_count"] = len({v["owner"] for v in value["candidate_family"]})
                value["counters"][key] = 2 if key != "critical_cross_module" else 1
                value["trigger_codes"] = [code]
                if key not in ("critical_cross_module", "clustered_high_same_root"):
                    value["counters"]["critical_cross_module"] = 0
                    value["counters"]["clustered_high_same_root"] = 0
                result, _ = self.run_record(value)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_candidate_family_hash_order_and_counts_are_bound(self):
        for kind in ("hash", "order", "module_count", "owner_count"):
            with self.subTest(kind=kind):
                value = record()
                if kind == "hash": value["candidate_sha256"] = "f" * 64
                elif kind == "order": value["candidate_family"].reverse()
                else: value["counters"][kind] += 1
                result, _ = self.run_record(value)
                self.assertEqual(result.returncode, 1)

    def test_finding_ids_are_unique_and_match_deduplicated_count(self):
        for kind in ("duplicate", "count"):
            value = record()
            if kind == "duplicate": value["evidence"]["finding_ids"][1] = value["evidence"]["finding_ids"][0]
            else: value["counters"]["confirmed_findings"] += 1
            result, _ = self.run_record(value)
            self.assertEqual(result.returncode, 1)

    def test_mismatched_trigger_and_missing_option_dimension_fail_closed(self):
        for kind in ("trigger", "option", "dimension"):
            with self.subTest(kind=kind):
                value = record()
                if kind == "trigger": value["trigger_codes"].pop()
                elif kind == "option": value["options"] = value["options"][:2]
                else: value["options"][0].pop("fixture_realism")
                result, _ = self.run_record(value)
                self.assertEqual(result.returncode, 1)

    def test_web_sources_require_exact_metadata_and_roles(self):
        for kind in ("role", "metadata", "route"):
            value = record()
            if kind == "role": value["evidence"]["web_sources"] = value["evidence"]["web_sources"][:1]
            elif kind == "metadata": value["evidence"]["web_sources"][0].pop("applicability_limits")
            else: value["evidence"]["web_sources"][0]["route"] = "unknown"
            result, _ = self.run_record(value)
            self.assertEqual(result.returncode, 1)

    def test_falsifier_is_required(self):
        value = record(); value["vertical_experiment"].pop("falsifier")
        result, _ = self.run_record(value)
        self.assertEqual(result.returncode, 1)

    def test_duplicate_keys_nonfinite_and_unsafe_input_are_malformed(self):
        for raw in ('{"version":"architecture-escalation-1","version":"x"}', '{"value":NaN}', '{'):
            result, _ = self.run_record({}, raw=raw)
            self.assertEqual(result.returncode, 2)
        target = Path(self.temp.name) / "target.json"; target.write_text(json.dumps(record()))
        link = Path(self.temp.name) / "link.json"; link.symlink_to(target)
        result = subprocess.run(["python3", str(SCRIPT), str(link)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    def test_boolean_counter_and_external_effect_experiment_fail(self):
        for kind in ("bool", "external"):
            value = record()
            if kind == "bool": value["counters"]["confirmed_findings"] = True
            else: value["vertical_experiment"]["no_external_effects"] = False
            result, _ = self.run_record(value)
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
