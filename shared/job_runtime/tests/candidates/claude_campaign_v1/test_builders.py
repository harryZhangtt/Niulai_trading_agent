import copy
import json
import unittest
from pathlib import Path
from collections.abc import Mapping

from _schema import validate as schema_errors

from shared.job_runtime.candidates.claude_campaign_v1 import (
    CampaignContractError, build_campaign_manifest, build_job,
    build_replay_contract, build_schema2_config, canonical_sha256,
    validate_campaign_manifest, validate_schema2_profile,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "claude_campaign_v1"
HASHES = ("1" * 64, "2" * 64, "3" * 64)
PROFILE = {
    "provider": "claude_host", "model": "fixture-model", "effort": "low",
    "timeout_seconds": 60, "auth_home": ".job-runtime/config/auth/campaign",
}


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


class BuilderTests(unittest.TestCase):
    def test_exact_attempt_counts_and_single_worker(self):
        for campaign, attempts in (("R6", 1), ("R7", 2), ("R8", 1)):
            config = build_schema2_config(campaign, PROFILE, ".job-runtime/config/campaign.json")
            self.assertEqual(set(config), {"schema_version", "tick_seconds", "heartbeat_seconds",
                "stale_seconds", "max_workers", "retry", "model_profiles", "allocation_files", "source_paths"})
            self.assertEqual(config["schema_version"], 2)
            self.assertEqual(config["max_workers"], 1)
            self.assertEqual(config["retry"]["max_attempts"], attempts)
            self.assertEqual(config["retry"]["base_delay_seconds"], 30.0)
            self.assertEqual(config["retry"]["max_delay_seconds"], 30.0)

    def test_native_prompt_custody_and_disabled_jobs(self):
        for campaign in ("R6", "R7", "R8"):
            job = build_job(campaign, "slot-1", ".job-runtime/config/prompts/campaign.txt")
            self.assertEqual(set(job), {"id", "enabled", "schedule", "model_profile", "prompt_file", "replay_contract"})
            self.assertFalse(job["enabled"])
            self.assertTrue(job["prompt_file"].startswith(".job-runtime/config/"))
            manifest = build_campaign_manifest(campaign, *HASHES)
            self.assertEqual(manifest["prompt_custody"], {"schema_version": 2, "mode": "native_v1", "raw_prompt_forbidden": True})
            self.assertEqual(manifest["live"], {"provider": False, "network": False, "process": False})
            serialized = json.dumps(plain(manifest), sort_keys=True)
            self.assertNotIn("prompt_text", serialized)
            self.assertNotIn("prompt_raw", serialized)

    def test_replay_contracts_and_named_reconciliation(self):
        for campaign in ("R6", "R7", "R8"):
            replay = build_replay_contract(campaign)
            self.assertEqual(replay["effect"], "reconcile_before_replay")
            self.assertEqual(replay["reconciliation_adapter"], "claude_campaign_v1.named_unknown_reconciliation")
            self.assertEqual(replay["automatic_phases"], ("connecting",) if campaign == "R7" else ())
        self.assertNotEqual(build_replay_contract("R6")["slot_operation_scope"],
                            build_replay_contract("R8")["slot_operation_scope"])

    def test_builders_are_deeply_immutable_and_hash_deterministic(self):
        manifest = build_campaign_manifest("R7", *HASHES)
        with self.assertRaises(TypeError): manifest["execution"]["max_attempts"] = 99
        self.assertEqual(canonical_sha256(manifest), canonical_sha256(build_campaign_manifest("R7", *HASHES)))

    def test_invalid_paths_campaigns_and_hashes_fail_closed(self):
        with self.assertRaises(CampaignContractError): build_replay_contract("R9")
        bad_prompts = (
            "public/prompt.txt", "/.job-runtime/config/prompt.txt",
            ".job-runtime/config/../prompt.txt", ".job-runtime/config/./prompt.txt",
            ".job-runtime/config/a//prompt.txt", r".job-runtime\config\prompt.txt",
            ".job-runtime/configuration/prompt.txt", ".job-runtime/config/prompts/../../prompt.txt",
        )
        for value in bad_prompts:
            with self.subTest(prompt=value), self.assertRaises(CampaignContractError):
                build_job("R6", "slot-1", value)
        bad_allocations = (
            "../allocation.json", "/.job-runtime/config/a.json",
            ".job-runtime/config/../a.json", ".job-runtime/config/./a.json",
            ".job-runtime/config/a//b.json", r".job-runtime\config\a.json",
            ".job-runtime/configuration/a.json",
        )
        for value in bad_allocations:
            with self.subTest(allocation=value), self.assertRaises(CampaignContractError):
                build_schema2_config("R6", PROFILE, value)
        with self.assertRaises(CampaignContractError): build_campaign_manifest("R6", "x", HASHES[1], HASHES[2])

    def test_manifest_schema_and_runtime_discriminants(self):
        schema = json.loads((FIXTURES / "manifest-v1.schema.json").read_text())
        for campaign in ("r6", "r7", "r8"):
            value = json.loads((FIXTURES / (campaign + "-manifest.json")).read_text())
            self.assertEqual(schema_errors(value, schema), [])
            validate_campaign_manifest(value)
        mutations = [
            lambda value: value.update(campaign_id="R6"),
            lambda value: value.update(scenario="nominal"),
            lambda value: value["execution"].update(max_attempts=1),
            lambda value: value["replay_contract"].update(automatic_phases=[]),
            lambda value: value["replay_contract"].update(slot_operation_scope="claude-campaign-v1/r6/slot-operation"),
            lambda value: value["execution"].update(max_workers=True),
            lambda value: value["execution"].update(max_attempts=1.0),
            lambda value: value.update(enabled=0),
            lambda value: value["scope"].update(canonical_integration=0),
            lambda value: value.update(extra=False),
        ]
        base = json.loads((FIXTURES / "r7-manifest.json").read_text())
        for mutate in mutations:
            candidate = copy.deepcopy(base); mutate(candidate)
            self.assertTrue(schema_errors(candidate, schema))
            with self.assertRaises(CampaignContractError):
                validate_campaign_manifest(candidate)

    def test_schema_number_semantics_and_qualified_runtime_lexical_limit(self):
        schema = json.loads((FIXTURES / "manifest-v1.schema.json").read_text())
        candidate = json.loads((FIXTURES / "r6-manifest.json").read_text())
        candidate["execution"]["max_attempts"] = 1.0
        # Draft 2020-12 regards 1 and 1.0 as equal JSON numbers and 1.0 as integer.
        self.assertEqual(schema_errors(candidate, schema), [])
        # The pure runtime contract is deliberately lexically stricter.
        with self.assertRaises(CampaignContractError):
            validate_campaign_manifest(candidate)
        candidate["execution"]["max_attempts"] = True
        self.assertTrue(schema_errors(candidate, schema))

    def test_profile_validator_exact_keys_types_bounds_and_provider_fields(self):
        claude = dict(PROFILE)
        codex = {"provider": "codex_cli", "codex_bin": "/bin/codex",
                 "model": "fixture-model", "effort": "xhigh", "timeout_seconds": 60,
                 "auth_home": ".job-runtime/config/auth/codex",
                 "max_output_bytes": 4096, "strict_process_tree_containment": True,
                 "circuit": {"failure_threshold": 2, "open_seconds": 30, "probe_seconds": 5}}
        validate_schema2_profile(claude); validate_schema2_profile(codex)
        cases = [
            {**claude, "bogus": 1},
            {key: value for key, value in claude.items() if key != "model"},
            {**claude, "timeout_seconds": True},
            {**claude, "timeout_seconds": 3601},
            {**claude, "max_budget_usd": 0},
            {**claude, "codex_bin": "/bin/codex"},
            {**claude, "circuit": {"failure_threshold": True, "open_seconds": 30, "probe_seconds": 5}},
            {**claude, "circuit": {"failure_threshold": 1, "open_seconds": 0, "probe_seconds": 5}},
            {**codex, "codex_bin": "relative/codex"},
            {**codex, "effort": "invalid"},
            {**codex, "max_output_bytes": 1023},
            {**codex, "max_output_bytes": True},
            {**codex, "strict_process_tree_containment": 1},
            {**codex, "max_budget_usd": 1},
        ]
        for index, profile in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(CampaignContractError):
                validate_schema2_profile(profile)

    def test_manifest_validator_is_total_for_arbitrary_malformed_mappings(self):
        valid = json.loads((FIXTURES / "r6-manifest.json").read_text())
        malformed = [None, [], "x", {"campaign_id": []},
                     {**valid, "campaign_id": []},
                     {**valid, "bindings": []},
                     {**valid, "bindings": {"prompt_sha256": [], "source_sha256": "2" * 64,
                                              "config_sha256": "3" * 64}},
                     {**valid, "execution": []},
                     {**valid, "replay_contract": {"automatic_phases": [[]]}},
                     {**valid, "scope": []}]
        for index, value in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(CampaignContractError):
                validate_campaign_manifest(value)


if __name__ == "__main__":
    unittest.main()
