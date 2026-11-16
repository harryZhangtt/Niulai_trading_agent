"""Offline durable one-time market-pilot authorization tests."""
import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import unittest
import uuid
from unittest.mock import patch

from shared.tiger import authorization as a
from shared.tiger import bridge
from shared.tiger import queries
from shared.tiger.queries import validate_query
from shared.tiger.tests.test_market import arguments


def receipt(auth_id="mpa_" + "1" * 32, cohort_sha256=queries.CALIBRATION_COHORT_SHA256):
    return {"schema_version": 1, "authorization_id": auth_id,
            "calibration_contract_sha256": "a" * 64, "cohort_sha256": cohort_sha256,
            "created_at": "2020-12-30T00:00:00Z"}


def claim_args(public, attempt=None):
    return {"authorization_id": public["authorization_id"],
            "authorization_sha256_value": public["authorization_sha256"],
            "calibration_contract_sha256": "a" * 64, "cohort_sha256": queries.CALIBRATION_COHORT_SHA256,
            "attempt_id": attempt or str(uuid.uuid4()), "query_sha256_value": "b" * 64,
            "symbols_sha256_value": "c" * 64, "claimed_at": "2020-12-30T01:00:00Z"}


def policy():
    return {"project_id": "synthetic-project", "origin": "https://synthetic.chatgpt.site", "owner_email": "owner@example.test"}


def site():
    return {"id": "synthetic-project", "current_user_role": "owner", "status": "active",
            "current_live_url": "https://synthetic.chatgpt.site", "access_mode": "custom",
            "siwc_bypass_bearer_token": "synthetic-only",
            "access_policy": {"project_id": "synthetic-project", "access_mode": "custom",
              "allowed_users": [{"account_user_id": "owner", "email": "owner@example.test", "role": "owner"}],
              "allowed_account_user_ids": ["owner"], "allowed_groups": [], "allowed_workspace_group_ids": [],
              "allowed_tenant_group_ids": [], "external_visitor_count": 0}}


def _concurrent_claim(workspace, kwargs, queue):
    try:
        result = a.claim_authorization(workspace, **kwargs)
        queue.put(("ok", result["authorization_status"]))
    except Exception as exc:
        queue.put(("error", str(exc)))


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def auth_root(self):
        return self.root.joinpath(*a.ROOT_PARTS)

    def ledger_path(self, auth_id="mpa_" + "1" * 32):
        return self.auth_root() / (auth_id + ".json")

    def test_create_schema_permissions_atomic_readback_and_public_projection(self):
        public = a.create_authorization(self.root, receipt())
        self.assertEqual(set(public), {"authorization_id", "authorization_sha256", "authorization_status"})
        self.assertEqual(public["authorization_status"], "unused")
        ledger = a.read_authorization(self.root, public["authorization_id"])
        self.assertEqual(ledger["authorization_sha256"], public["authorization_sha256"])
        self.assertEqual(ledger["receipt"], receipt())
        for parent in [self.auth_root(), *self.auth_root().parents]:
            if parent == self.root:
                break
            self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.ledger_path().stat().st_mode), 0o600)
        self.assertEqual(self.ledger_path().stat().st_nlink, 1)
        self.assertNotIn(str(self.auth_root()), json.dumps(public))
        self.assertFalse(list(self.auth_root().glob(".write-*")))

    def test_unused_claim_binds_attempt_and_hashes_then_all_terminals_cannot_reuse(self):
        for index, terminal in enumerate(("success", "failure", "unresolved"), 1):
            auth_id = "mpa_" + format(index, "032x")
            public = a.create_authorization(self.root, receipt(auth_id))
            kwargs = claim_args(public)
            claimed = a.claim_authorization(self.root, **kwargs)
            self.assertEqual(claimed["authorization_status"], "consumed")
            ledger = a.read_authorization(self.root, auth_id)
            self.assertEqual(ledger["claim"]["attempt_id"], kwargs["attempt_id"])
            self.assertEqual(ledger["claim"]["query_sha256"], "b" * 64)
            self.assertEqual(ledger["claim"]["symbols_sha256"], "c" * 64)
            a.finalize_authorization(self.root, authorization_id=auth_id,
                authorization_sha256_value=public["authorization_sha256"], attempt_id=kwargs["attempt_id"],
                terminal_status=terminal, terminal_at="2020-12-30T02:00:00Z")
            self.assertEqual(a.read_authorization(self.root, auth_id)["claim"]["terminal_status"], terminal)
            with self.assertRaisesRegex(a.AuthorizationError, "ALREADY_CONSUMED"):
                a.claim_authorization(self.root, **kwargs)
            with self.assertRaisesRegex(a.AuthorizationError, "TERMINAL_ALREADY_SET"):
                a.finalize_authorization(self.root, authorization_id=auth_id,
                    authorization_sha256_value=public["authorization_sha256"], attempt_id=kwargs["attempt_id"],
                    terminal_status=terminal)

    def test_interrupted_claim_and_unknown_attempt_preserve_reconciliation_evidence(self):
        public = a.create_authorization(self.root, receipt())
        kwargs = claim_args(public)
        a.claim_authorization(self.root, **kwargs)
        with self.assertRaisesRegex(a.AuthorizationError, "ATTEMPT_MISMATCH"):
            a.finalize_authorization(self.root, authorization_id=public["authorization_id"],
                authorization_sha256_value=public["authorization_sha256"], attempt_id=str(uuid.uuid4()),
                terminal_status="unresolved")
        ledger = a.read_authorization(self.root, public["authorization_id"])
        self.assertEqual(ledger["status"], "consumed")
        self.assertEqual(ledger["claim"]["terminal_status"], "claimed")
        with self.assertRaisesRegex(a.AuthorizationError, "ALREADY_CONSUMED"):
            a.claim_authorization(self.root, **claim_args(public))

    def test_concurrent_claim_has_exactly_one_winner(self):
        public = a.create_authorization(self.root, receipt())
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [context.Process(target=_concurrent_claim,
                     args=(str(self.root), claim_args(public, str(uuid.uuid4())), queue)) for _ in range(2)]
        for process in processes: process.start()
        for process in processes: process.join(5)
        results = [queue.get(timeout=2) for _ in processes]
        self.assertEqual(sum(kind == "ok" for kind, _ in results), 1)
        self.assertEqual(sum(value == "AUTHORIZATION_ALREADY_CONSUMED" for kind, value in results if kind == "error"), 1)

    def test_path_symlink_hardlink_mode_owner_rejected(self):
        with self.assertRaisesRegex(a.AuthorizationError, "ID_INVALID"):
            a.create_authorization(self.root, receipt("../../escape"))
        cases = ("symlink", "hardlink", "mode", "owner")
        for index, case in enumerate(cases, 10):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); auth_id = "mpa_" + format(index, "032x")
                public = a.create_authorization(root, receipt(auth_id)); path = root.joinpath(*a.ROOT_PARTS, auth_id + ".json")
                if case == "symlink":
                    target = path.with_name("target.json"); path.rename(target); path.symlink_to(target)
                elif case == "hardlink":
                    os.link(path, path.with_name("other-link.json"))
                elif case == "mode":
                    path.chmod(0o644)
                with self.assertRaises(a.AuthorizationError):
                    if case == "owner":
                        with patch.object(a.os, "getuid", return_value=os.getuid() + 1):
                            a.claim_authorization(root, **claim_args(public))
                    else:
                        a.claim_authorization(root, **claim_args(public))

    def test_hash_drift_malformed_and_oversize_rejected(self):
        for index, case in enumerate(("drift", "malformed", "oversize"), 20):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); auth_id = "mpa_" + format(index, "032x")
                public = a.create_authorization(root, receipt(auth_id)); path = root.joinpath(*a.ROOT_PARTS, auth_id + ".json")
                if case == "drift":
                    value = json.loads(path.read_text()); value["receipt"]["cohort_sha256"] = "f" * 64
                    path.write_text(json.dumps(value, separators=(",", ":")))
                elif case == "malformed":
                    path.write_text("not-json-secret")
                else:
                    path.write_bytes(b"x" * (a.MAX_LEDGER_BYTES + 1))
                path.chmod(0o600)
                with self.assertRaises(a.AuthorizationError):
                    a.claim_authorization(root, **claim_args(public))

    def test_contract_cohort_and_authorization_hash_drift_rejected_without_consuming(self):
        public = a.create_authorization(self.root, receipt())
        for key, value, code in (("authorization_sha256_value", "f" * 64, "HASH_MISMATCH"),
                                 ("calibration_contract_sha256", "f" * 64, "CONTRACT_DRIFT"),
                                 ("cohort_sha256", "f" * 64, "COHORT_DRIFT")):
            kwargs = claim_args(public); kwargs[key] = value
            with self.assertRaisesRegex(a.AuthorizationError, code):
                a.claim_authorization(self.root, **kwargs)
            self.assertEqual(a.read_authorization(self.root, public["authorization_id"])["status"], "unused")

    def test_selection_attacks_reject_before_claim_and_leave_authorization_unused(self):
        base = arguments()
        attacks = []
        bad = copy.deepcopy(base); bad["symbols"] = copy.deepcopy(bad["sample_selection"]["cohorts"]["reserved_promotion"]["query_symbol_records"]); attacks.append(("reserved", bad))
        bad = copy.deepcopy(base); bad["symbols"].reverse(); attacks.append(("reorder", bad))
        bad = copy.deepcopy(base); bad["sample_selection"]["builder"]["path"] = "modified"; attacks.append(("modified_document", bad))
        bad = copy.deepcopy(base); bad["contract"]["sample_selection_sha256"] = "0" * 64; attacks.append(("document_hash_drift", bad))
        bad = copy.deepcopy(base); bad["sample_selection"]["cohorts"]["calibration"]["cohort_sha256"] = "0" * 64; attacks.append(("cohort_hash_drift", bad))
        bad = copy.deepcopy(base); bad["sample_selection"]["cohorts"]["calibration"]["ordered_query_symbols_sha256"] = "0" * 64; attacks.append(("ordered_hash_drift", bad))
        bad = copy.deepcopy(base); promotion = copy.deepcopy(bad["sample_selection"]["cohorts"]["reserved_promotion"]); promotion["cohort_id"] = "calibration"; bad["sample_selection"]["cohorts"]["calibration"] = promotion
        canonical = json.dumps(bad["sample_selection"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(); bad["contract"]["sample_selection_sha256"] = hashlib.sha256(canonical).hexdigest(); bad["symbols"] = promotion["query_symbol_records"]; attacks.append(("self_consistent_noncohort", bad))
        bad = copy.deepcopy(base); bad["symbols"][0]["roster_row_sha256"] = "0" * 64; attacks.append(("wrong_row_hash", bad))
        bad = copy.deepcopy(base); bad["sample_selection"]["extra"] = True; attacks.append(("extra", bad))
        bad = copy.deepcopy(base); bad["sample_selection"] = "malformed"; attacks.append(("malformed", bad))
        bad = copy.deepcopy(base); bad["sample_selection"]["builder"]["path"] = "x" * (queries.MAX_SAMPLE_SELECTION_BYTES + 1); attacks.append(("oversize", bad))
        for index, (name, bad) in enumerate(attacks, 100):
            with self.subTest(name=name):
                auth_id = "mpa_" + format(index, "032x")
                public = a.create_authorization(self.root, receipt(auth_id, queries.CALIBRATION_COHORT_SHA256))
                bad["authorization_id"] = auth_id; bad["authorization_sha256"] = public["authorization_sha256"]
                with patch.object(bridge, "claim_authorization") as claim, patch.object(bridge, "StoreClient") as store:
                    with self.assertRaises(bridge.TigerBridgeError):
                        bridge.run_bridge(self.root, policy(), site(), self.root / f".niulai-state/reject-{index}",
                                          "query", query={"tool": "market_snapshot", "arguments": bad})
                    claim.assert_not_called(); store.assert_not_called()
                self.assertEqual(a.read_authorization(self.root, auth_id)["status"], "unused")

    def test_receipt_cohort_drift_rejects_without_consumption_or_credential_io(self):
        auth_id = "mpa_" + format(999, "032x")
        public = a.create_authorization(self.root, receipt(auth_id, "f" * 64))
        args = arguments(); args["authorization_id"] = auth_id; args["authorization_sha256"] = public["authorization_sha256"]
        with patch.object(bridge, "StoreClient") as store:
            with self.assertRaisesRegex(a.AuthorizationError, "COHORT_DRIFT"):
                bridge.run_bridge(self.root, policy(), site(), self.root / ".niulai-state/receipt-drift",
                                  "query", query={"tool": "market_snapshot", "arguments": args})
            store.assert_not_called()
        self.assertEqual(a.read_authorization(self.root, auth_id)["status"], "unused")

    def test_bridge_claims_before_provider_and_replay_never_reaches_credential_io(self):
        public = a.create_authorization(self.root, receipt())
        args = arguments(); args["authorization_id"] = public["authorization_id"]
        args["authorization_sha256"] = public["authorization_sha256"]
        query = validate_query({"tool": "market_snapshot", "arguments": args}, bridge.require)
        out = self.root / ".niulai-state/out"
        observed = {}
        def fake_run(workspace, state, out_path, mode, policy_value, session, blocker, **kwargs):
            ledger = a.read_authorization(self.root, public["authorization_id"])
            observed["status_before_provider"] = ledger["status"]
            return {"status": "queried", "tool": "market_snapshot", "source_read_status": "complete",
                    "files": ["market_raw.json", "market_manifest.json", "market_query.json"],
                    "committed": True, "release_requested": True}
        with patch.object(bridge, "_run_locked", side_effect=fake_run), patch.object(bridge, "StoreClient") as store:
            result = bridge.run_bridge(self.root, policy(), site(), out, "query", query=query)
        self.assertEqual(observed["status_before_provider"], "consumed")
        self.assertEqual(result["authorization_status"], "consumed")
        self.assertEqual(a.read_authorization(self.root, public["authorization_id"])["claim"]["terminal_status"], "success")
        store.assert_not_called()
        with patch.object(bridge, "StoreClient") as store:
            with self.assertRaisesRegex(a.AuthorizationError, "ALREADY_CONSUMED"):
                bridge.run_bridge(self.root, policy(), site(), self.root / ".niulai-state/out2", "query", query=query)
            store.assert_not_called()
