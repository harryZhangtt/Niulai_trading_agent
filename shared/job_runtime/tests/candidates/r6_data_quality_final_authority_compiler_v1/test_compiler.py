from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from shared.job_runtime.candidates.r6_data_quality_final_authority_compiler_v1 import (
    DENY, STATUS, compile_deny_report,
)
from shared.job_runtime.candidates.r6_data_quality_final_authority_compiler_v1 import compiler, drafts


def _cell(cell_id: str):
    spec = drafts._CELLS[cell_id]
    return {
        "artifact_kind": "NON_AUTHORIZING_CELL_GRANT_DRAFT",
        "status": STATUS,
        "activation": False,
        "authority_effect": "NONE",
        "self_minted": False,
        "cell_id": cell_id,
        "order_index": spec["order"],
        "provider": {"port": spec["provider"], **spec["provider_identity"]},
        "addon": {"label": spec["addon"], "state": spec["addon_state"]},
        "model": {"id": spec["model"], "effort": spec["effort"]},
        "budget": {"currency": "USD", "hard_cap": "0.01"},
        "window": {**drafts._WINDOW, "admission_offset_seconds": spec["offset"]},
        "prompt": dict(drafts._COMMON_PROMPT),
        "tool_policy": dict(drafts._TOOL),
        "p0": {"version": "P0-v10", "clean_pin_required": True},
        "limits": dict(drafts._LIMITS),
        "countable": False,
    }


def _block():
    cells = [_cell(cell_id) for cell_id in drafts._ORDER]
    return {
        "artifact_kind": "NON_AUTHORIZING_BLOCK_GRANT_DRAFT",
        "status": STATUS,
        "activation": False,
        "authority_effect": "NONE",
        "self_minted": False,
        "block_id": "R6-DQ-FINAL-FOUR-CELL-BLOCK-V1",
        "cell_order": list(drafts._ORDER),
        "cells": cells,
        "limits": {"concurrency": 1, "requests_per_cell": 1, "total_requests": 4, "retries": 0, "replays": 0, "status_queries": 0},
        "countability": "ALL_FOUR_OR_NONE",
        "partial_block": False,
        "bytedcli_allowed": False,
    }


class DenyOnlyTests(unittest.TestCase):
    def test_public_api_is_deny_only_and_argument_free(self):
        self.assertEqual(list(inspect.signature(compile_deny_report).parameters), [])
        with self.assertRaises(TypeError):
            compile_deny_report(Path("/caller/root"))
        with self.assertRaises(TypeError):
            compile_deny_report(clock="caller-clock", policy="caller-policy")
        package = __import__("shared.job_runtime.candidates.r6_data_quality_final_authority_compiler_v1", fromlist=["*"])
        self.assertEqual(package.__all__, ["DENY", "STATUS", "compile_deny_report"])
        for token in ("issue", "write", "activate", "adopt", "sign", "install"):
            self.assertFalse(any(name.lower().startswith(token) for name in package.__all__))

    def test_current_result_is_deny_with_machine_readable_missing_pins(self):
        result = compile_deny_report()
        self.assertEqual(result["decision"], DENY)
        self.assertEqual(result["status"], STATUS)
        self.assertFalse(result["activation"])
        self.assertFalse(result["authority_issued"])
        self.assertFalse(result["countable"])
        self.assertGreater(result["missing_pin_count"], 0)
        self.assertEqual(result["missing_pin_count"], len(result["missing_pins"]))
        self.assertIn("codex_v6_clean_pending_p0_v10", result["verified_pin_names"])
        self.assertIn("claude_v9_evidence_reseal_clean_pending_p0_v10", result["verified_pin_names"])
        missing = {item["name"]: item for item in result["missing_pins"]}
        self.assertIn("codex_v6_p0_v10_clean", missing)
        self.assertIn("authority_last_adoption", missing)
        self.assertEqual(missing["runner_v8_open_review"]["reason"], "VERIFIED_OPEN_BLOCKER_NOT_AUTHORITY")
        self.assertEqual(missing["runner_v8_open_review"]["required_bytes"], 6255)
        self.assertEqual(missing["runner_v8_open_review"]["required_sha256"], "145265647df2a9231d7b64f3b7c70c7266403b38cb15ad98e38deef3a6d588f5")
        self.assertEqual(missing["blind_map_v5_open_review"]["reason"], "VERIFIED_OPEN_BLOCKER_NOT_AUTHORITY")
        self.assertEqual(missing["blind_map_v5_open_review"]["required_bytes"], 23467)
        self.assertEqual(missing["blind_map_v5_open_review"]["required_sha256"], "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8")
        self.assertIn("blind_map_v6_clean", missing)
        self.assertNotIn("blind_map_v5_clean_review", result["verified_pin_names"])
        self.assertEqual(missing["claude_v8_open_review"]["reason"], "VERIFIED_OPEN_BLOCKER_NOT_AUTHORITY")
        self.assertEqual(missing["claude_v8_open_review"]["required_bytes"], 10896)
        self.assertEqual(missing["claude_v8_open_review"]["required_sha256"], "65e425cab9b0fd7ed9381e0f8019360fad0e5c0f2da432c3b5c4e4c27c16df0d")
        self.assertNotIn("claude_v9_clean", missing)
        self.assertNotIn("claude_v8_p0_v10_clean", missing)
        self.assertIn("p0_v10_clean", missing)
        self.assertIn("final_block_grant", missing)
        self.assertIn("final_block_grant_clean_review", missing)
        for cell in ("r6dq_7f2c91a4", "r6dq_1b8e43d7", "r6dq_c4a7095e", "r6dq_92d6f0b3"):
            self.assertIn("final_cell_grant_" + cell, missing)
            self.assertIn("final_cell_grant_" + cell + "_clean_review", missing)
        self.assertEqual(missing["runner_v2_open_review"]["reason"], "VERIFIED_OPEN_BLOCKER_NOT_AUTHORITY")
        self.assertEqual(missing["runner_v2_open_review"]["required_bytes"], 13206)
        self.assertEqual(missing["runner_v2_open_review"]["required_sha256"], "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1")
        self.assertNotIn("runner_v3_clean", missing)
        self.assertIn("runner_v3_open_review", missing)
        self.assertIsNone(missing["runner_v3_open_review"]["required_bytes"])
        self.assertIsNone(missing["runner_v3_open_review"]["required_sha256"])
        self.assertIn("runner_v4_clean", missing)
        self.assertNotIn("runner_v2_rebased_p0_v10_clean", missing)
        self.assertIn("p0_v10_clean", missing)
        self.assertNotIn("grant", result)
        self.assertNotIn("block_grant", result)
        self.assertNotIn("cell_grants", result)
        self.assertTrue(all(value == 0 for value in result["effects"].values()))

    def test_human_g1_g2_missing_and_g3_is_fixed_condition(self):
        result = compile_deny_report()
        missing = {item["name"] for item in result["missing_pins"]}
        self.assertTrue({"human_registry_authentic", "g1_authentic", "g2_authentic"} <= missing)
        self.assertNotIn("g3_authentic", missing)
        with mock.patch.object(compiler, "_g3_required", return_value=True):
            conditional = compile_deny_report()
        conditional_missing = {item["name"] for item in conditional["missing_pins"]}
        self.assertTrue({"g3_authentic", "g3_authentic_review"} <= conditional_missing)


class DraftAdversaryTests(unittest.TestCase):
    def test_exact_non_authorizing_block_draft_validates(self):
        self.assertIs(drafts.validate_block_draft(_block())["activation"], False)

    def test_coherent_self_minted_chain_is_rejected(self):
        value = _block()
        value["self_minted"] = True
        for cell in value["cells"]:
            cell["self_minted"] = True
        with self.assertRaisesRegex(compiler.ContractError, "MUST_NOT_AUTHORIZE"):
            drafts.validate_block_draft(value)

    def test_swapped_cells_providers_and_addon_are_rejected(self):
        swapped = _block()
        swapped["cells"][0], swapped["cells"][1] = swapped["cells"][1], swapped["cells"][0]
        with self.assertRaises(compiler.ContractError):
            drafts.validate_block_draft(swapped)
        provider = _block()
        provider["cells"][0]["provider"] = copy.deepcopy(provider["cells"][1]["provider"])
        with self.assertRaisesRegex(compiler.ContractError, "PROVIDER_DRIFT"):
            drafts.validate_block_draft(provider)
        addon = _block()
        addon["cells"][2]["addon"] = {"label": "CONDITION-X", "state": "OFF"}
        with self.assertRaisesRegex(compiler.ContractError, "ADDON_DRIFT"):
            drafts.validate_block_draft(addon)

    def test_partial_block_is_never_countable(self):
        value = _block()
        value["cells"].pop()
        value["cell_order"].pop()
        with self.assertRaises(compiler.ContractError):
            drafts.validate_block_draft(value)

    def test_bytedcli_budget_order_and_request_drift_are_rejected(self):
        mutations = []
        a = _block(); a["bytedcli_allowed"] = True; mutations.append(a)
        b = _block(); b["cells"][0]["budget"]["hard_cap"] = "0.02"; mutations.append(b)
        c = _block(); c["cells"][0]["order_index"] = 3; mutations.append(c)
        d = _block(); d["cells"][0]["limits"]["requests"] = 2; mutations.append(d)
        e = _block(); e["limits"]["status_queries"] = 1; mutations.append(e)
        for value in mutations:
            with self.assertRaises(compiler.ContractError):
                drafts.validate_block_draft(value)


class SecurePinTests(unittest.TestCase):
    def _pin_for(self, root: Path, value, *, expected=None, mode=0o600):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
        path = root / "fixed.json"
        path.write_bytes(raw)
        os.chmod(path, mode)
        expectations = () if expected is None else ((('status',), expected),)
        return compiler._Pin("test", "fixed.json", len(raw), hashlib.sha256(raw).hexdigest(), mode, expectations)

    def test_stale_bytes_sha_mode_and_forged_clean_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pin = self._pin_for(root, {"status": "CLEAN"}, expected="CLEAN")
            with mock.patch.object(compiler, "_WORKSPACE_ROOT", root):
                self.assertEqual(compiler._secure_read(root, pin)["status"], "CLEAN")
                stale = compiler._Pin("test", "fixed.json", pin.bytes, "0" * 64, 0o600, pin.expectations)
                with self.assertRaisesRegex(compiler.ContractError, "SHA256_DRIFT"):
                    compiler._secure_read(root, stale)
                forged = self._pin_for(root, {"status": "FORGED_CLEAN"}, expected="CLEAN")
                with self.assertRaisesRegex(compiler.ContractError, "STATUS_NOT_CLEAN"):
                    compiler._secure_read(root, forged)
                os.chmod(root / "fixed.json", 0o644)
                with self.assertRaisesRegex(compiler.ContractError, "MODE_DRIFT"):
                    compiler._secure_read(root, forged)

    def test_nofollow_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.json"
            target.write_text('{"status":"CLEAN"}')
            os.chmod(target, 0o600)
            (root / "fixed.json").symlink_to(target)
            raw = target.read_bytes()
            pin = compiler._Pin("test", "fixed.json", len(raw), hashlib.sha256(raw).hexdigest(), 0o600)
            with mock.patch.object(compiler, "_WORKSPACE_ROOT", root):
                with self.assertRaisesRegex(compiler.ContractError, "NOFOLLOW"):
                    compiler._secure_read(root, pin)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = b'{"status":"CLEAN","status":"CLEAN"}'
            path = root / "fixed.json"; path.write_bytes(raw); os.chmod(path, 0o600)
            pin = compiler._Pin("test", "fixed.json", len(raw), hashlib.sha256(raw).hexdigest(), 0o600)
            with mock.patch.object(compiler, "_WORKSPACE_ROOT", root):
                with self.assertRaisesRegex(compiler.ContractError, "DUPLICATE_JSON_KEY"):
                    compiler._secure_read(root, pin)


class SchemaTests(unittest.TestCase):
    def test_all_schemas_are_strict_draft_2020_12(self):
        schema_root = Path(compiler.__file__).parent / "schemas"
        schemas = {path.name: json.loads(path.read_text()) for path in schema_root.glob("*.schema.json")}
        self.assertEqual(set(schemas), {"block-grant-draft-v1.schema.json", "cell-grant-draft-v1.schema.json", "deny-report-v1.schema.json", "missing-pin-list-v1.schema.json"})
        for value in schemas.values():
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schemas["block-grant-draft-v1.schema.json"]["const"]["activation"], False)
        self.assertEqual(len(schemas["cell-grant-draft-v1.schema.json"]["oneOf"]), 4)
        self.assertFalse(schemas["deny-report-v1.schema.json"]["additionalProperties"])
        self.assertFalse(schemas["missing-pin-list-v1.schema.json"]["items"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
