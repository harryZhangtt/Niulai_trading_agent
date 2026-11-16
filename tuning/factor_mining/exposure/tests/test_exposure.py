import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tuning.factor_mining.exposure import contract

ROOT = Path(__file__).resolve().parents[4]
SHA_A = "a" * 64
SHA_B = "b" * 64


def event(event_id="share-read", evidence=SHA_A, affected="2026-01-30",
          observed="2026-02-01T12:00:00Z", exposure_class="outcome_summary"):
    return {
        "event_id": event_id,
        "exposure_class": exposure_class,
        "semantic_subject_id": "spy",
        "evidence_sha256": evidence,
        "observed_at": observed,
        "latest_affected_session": affected,
        "provenance": {"source_type": "public_share", "source_ref_sha256": SHA_B,
                       "limitations": ["reported-unverified"]},
    }


def weekdays(start, end):
    current = date.fromisoformat(start); finish = date.fromisoformat(end); result = []
    while current <= finish:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


class ExposureContractTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / "tuning/factor_mining/runtime/exposure-tests"
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "ledger"
        self.ledger = contract.SyntheticExposureLedger.provision(self.root)

    def test_append_chain_and_t_seen_are_monotonic(self):
        first = self.ledger.append(event())
        older = event("older-late-discovery", "c" * 64, "2025-01-31", "2026-03-01T00:00:00Z")
        second = self.ledger.append(older)
        later = event("later", "d" * 64, "2026-03-31", "2026-04-01T00:00:00Z")
        third = self.ledger.append(later)
        self.assertEqual(first["t_seen"], "2026-01-30")
        self.assertEqual(second["t_seen"], "2026-01-30")
        self.assertEqual(third["t_seen"], "2026-03-31")
        status = self.ledger.status()
        self.assertFalse(status["authoritative"])
        self.assertEqual(status["status"], "development-only-blocked")
        self.assertEqual(status["events"], 3)

    def test_each_ledger_has_immutable_distinct_genesis_identity(self):
        other = contract.SyntheticExposureLedger.provision(Path(self.temp.name) / "other-ledger")
        first = self.ledger.status(); second = other.status()
        self.assertNotEqual(first["ledger_id"], second["ledger_id"])
        self.assertNotEqual(first["ledger_genesis_sha256"], second["ledger_genesis_sha256"])
        head = json.loads((self.root / "head.json").read_text())
        head["ledger_genesis_sha256"] = second["ledger_genesis_sha256"]
        (self.root / "head.json").write_text(json.dumps(head, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaisesRegex(contract.ExposureError, "HEAD_INVALID"):
            contract.SyntheticExposureLedger(self.root)

    def test_alias_and_duplicate_evidence_cannot_reset_history(self):
        self.ledger.append(event())
        alias = event("renamed", SHA_A)
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_EVIDENCE"):
            self.ledger.append(alias)
        changed_evidence_same_semantics = event("renamed-again", "e" * 64)
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_EVIDENCE"):
            self.ledger.append(changed_evidence_same_semantics)
        duplicate_id = event("share-read", "f" * 64, "2026-02-27", "2026-03-01T00:00:00Z")
        duplicate_id["provenance"]["source_ref_sha256"] = "1" * 64
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_EVIDENCE"):
            self.ledger.append(duplicate_id)
        repackaged = event("new-wrapper", "2" * 64)
        repackaged["provenance"] = {"source_type": "local_report",
                                    "source_ref_sha256": "3" * 64,
                                    "limitations": ["manual-review-required"]}
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_EVIDENCE"):
            self.ledger.append(repackaged)

    def test_distinct_semantic_subjects_can_coexist(self):
        self.ledger.append(event("spy", SHA_A))
        oneq = event("oneq", "4" * 64)
        oneq["semantic_subject_id"] = "oneq"
        oneq["provenance"]["source_ref_sha256"] = "6" * 64
        self.ledger.append(oneq)
        self.assertEqual(self.ledger.status()["events"], 2)
        unknown = event("unknown", "7" * 64); unknown["semantic_subject_id"] = "spy-renamed"
        with self.assertRaisesRegex(contract.ExposureError, "SUBJECT_INVALID"):
            self.ledger.append(unknown)

    def test_joint_subject_repackaging_is_duplicate(self):
        first = event("joint-first", SHA_A); first["semantic_subject_id"] = "joint-spy-oneq"
        self.ledger.append(first)
        second = event("joint-wrapper", "8" * 64); second["semantic_subject_id"] = "joint-spy-oneq"
        second["provenance"] = {"source_type": "reviewer_receipt",
                                "source_ref_sha256": "9" * 64,
                                "limitations": ["manual-review-required"]}
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_EVIDENCE"):
            self.ledger.append(second)

    def test_chain_mutation_and_missing_head_fail_closed(self):
        self.ledger.append(event())
        path = next((self.root / "events").iterdir())
        value = json.loads(path.read_text()); value["latest_affected_session"] = "2024-01-01"
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaisesRegex(contract.ExposureError, "CHAIN_INVALID"):
            contract.SyntheticExposureLedger(self.root)
        other = Path(self.temp.name) / "missing"
        contract.SyntheticExposureLedger.provision(other)
        (other / "head.json").unlink()
        with self.assertRaisesRegex(contract.ExposureError, "RECORD_UNAVAILABLE"):
            contract.SyntheticExposureLedger(other)

    def test_orphan_event_after_head_failure_is_recovered_without_replay(self):
        original = contract._atomic_write
        def fail_head(path, payload, replace=False):
            if Path(path).name == "head.json" and replace:
                raise contract.ExposureWriteFailed()
            return original(path, payload, replace=replace)
        with mock.patch.object(contract, "_atomic_write", side_effect=fail_head):
            with self.assertRaisesRegex(contract.ExposureError, "WRITE_FAILED"):
                self.ledger.append(event())
        self.assertEqual(len(list((self.root / "events").iterdir())), 1)
        reopened = contract.SyntheticExposureLedger(self.root)
        self.assertEqual(reopened.status()["sequence"], 1)
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_EVIDENCE"):
            reopened.append(event())
        reopened.append(event("later", "c" * 64, "2026-02-27", "2026-03-01T00:00:00Z"))
        self.assertEqual(reopened.status()["sequence"], 2)

    def test_backdating_timezones_and_invalid_dates_fail(self):
        cases = [
            event(observed="2025-01-01T00:00:00Z"),
            event(observed="2026-01-30T23:59:59Z"),
            event(observed="2026-02-01T12:00:00+00:00"),
            event(observed="2026-02-30T12:00:00Z"),
            event(affected="2026-02-30"),
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(contract.ExposureError):
                self.ledger.append(value)

    def test_missing_evidence_outcome_fields_and_sensitive_text_fail(self):
        missing = event(); missing.pop("evidence_sha256")
        metric = event(); metric["provenance"]["metric"] = 1
        secret = event(); secret["provenance"]["limitations"] = ["api_key=canary"]
        path = event(); path["provenance"]["limitations"] = ["/users/private/result"]
        sharpe = event(); sharpe["provenance"]["limitations"] = ["sharpe-1.2"]
        returns = event(); returns["provenance"]["limitations"] = ["return-positive"]
        result = event(); result["provenance"]["limitations"] = ["result-pass"]
        source_list = event(); source_list["provenance"]["source_type"] = []
        class_list = event(); class_list["exposure_class"] = []
        for value in (missing, metric, secret, path, sharpe, returns, result,
                      source_list, class_list):
            with self.subTest(value=value), self.assertRaises(contract.ExposureError):
                self.ledger.append(value)

    def test_atomic_effect_then_raise_is_unknown_and_retry_is_idempotent(self):
        base = Path(self.temp.name) / "atomic"; base.mkdir()
        payload = b"exposure-intent"
        target = base / "event.json"
        real_link = contract.os.link
        def link_then_raise(source, destination, **kwargs):
            real_link(source, destination, **kwargs)
            raise OSError("post-link-private")
        with mock.patch.object(contract.os, "link", side_effect=link_then_raise):
            with self.assertRaisesRegex(contract.ExposureWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN") as raised:
                contract._atomic_write(target, payload)
        self.assertEqual(raised.exception.destination, str(target))
        self.assertEqual(raised.exception.intended_bytes, payload)
        self.assertEqual(raised.exception.intended_sha256,
                         contract.hashlib.sha256(payload).hexdigest())
        contract._atomic_write(target, payload)

        head = base / "head.json"; head.write_bytes(b"old")
        real_replace = contract.os.replace
        def replace_then_raise(source, destination):
            real_replace(source, destination)
            raise OSError("post-replace-private")
        with mock.patch.object(contract.os, "replace", side_effect=replace_then_raise):
            with self.assertRaisesRegex(contract.ExposureWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN"):
                contract._atomic_write(head, payload, replace=True)
        contract._atomic_write(head, payload, replace=True)
        self.assertEqual(head.read_bytes(), payload)

        drifted = base / "drifted-head.json"; drifted.write_bytes(b"old")
        def replace_drift_then_raise(source, destination):
            real_replace(source, destination)
            Path(destination).write_bytes(b"intervening-state")
            raise OSError("post-replace-drift-private")
        with mock.patch.object(contract.os, "replace", side_effect=replace_drift_then_raise):
            with self.assertRaisesRegex(contract.ExposureWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN") as drift:
                contract._write_reconciled(drifted, payload, replace=True)
        self.assertEqual(drift.exception.readback_state, "different")
        self.assertEqual(drifted.read_bytes(), b"intervening-state")

    def test_filesystem_and_cleanup_failures_are_sanitized(self):
        with mock.patch.object(contract.os, "scandir", side_effect=OSError("private-events")):
            with self.assertRaisesRegex(contract.ExposureError, "EVENTS_INVALID"):
                self.ledger.status()
        readiness = Path(__file__).resolve().parents[1] / "exposure-readiness.json"
        real_close = contract.os.close
        def close_then_raise(descriptor):
            real_close(descriptor)
            raise OSError("private-close")
        with mock.patch.object(contract.os, "close", side_effect=close_then_raise):
            value = contract._read_json(readiness)
        self.assertEqual(value["status"], "draft_blocked")
        with mock.patch.object(contract.os, "fstat", side_effect=OSError("private-read")):
            with self.assertRaisesRegex(contract.ExposureError, "RECORD_INVALID"):
                contract._read_json(readiness)

    def test_subject_inventory_shape_failure_is_stable_and_sanitized(self):
        inventory, inventory_sha256 = contract._tracked_source_inventory()
        malformed = copy.deepcopy(inventory)
        market = next(item for item in malformed["entries"] if item["role"] == "spy_market")
        market.pop("provider_routes")
        with mock.patch.object(contract, "_tracked_source_inventory",
                               return_value=(malformed, inventory_sha256)):
            with self.assertRaisesRegex(contract.ExposureError,
                                        "EXPOSURE_SUBJECT_INVENTORY_MISMATCH") as raised:
                self.ledger.append(event())
        self.assertEqual(str(raised.exception), "EXPOSURE_SUBJECT_INVENTORY_MISMATCH")
        self.assertNotIsInstance(raised.exception, KeyError)

    def test_symlinked_provision_ancestor_fails(self):
        real_parent = Path(self.temp.name) / "real-parent"; real_parent.mkdir()
        linked_parent = Path(self.temp.name) / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(contract.ExposureError, "PROVISION_INVALID"):
            contract.SyntheticExposureLedger.provision(linked_parent / "ledger")

    def test_strict_json_and_event_schema(self):
        with self.assertRaisesRegex(contract.ExposureError, "DUPLICATE_KEY"):
            contract.loads_strict('{"a":1,"a":2}')
        with self.assertRaisesRegex(contract.ExposureError, "NONFINITE"):
            contract.loads_strict('{"a":NaN}')
        for name in ("exposure-event-v1.schema.json", "exposure-genesis-v1.schema.json",
                     "exposure-readiness-v1.schema.json", "fresh-split-readiness-v1.schema.json"):
            schema = json.loads((Path(__file__).resolve().parents[1] / name).read_text())
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
            if name == "exposure-event-v1.schema.json":
                allowed = schema["properties"]["provenance"]["properties"]["limitations"]["items"]["enum"]
                self.assertEqual(set(allowed), contract.LIMITATION_CODES)
        readiness_path = Path(__file__).resolve().parents[1] / "exposure-readiness.json"
        readiness = contract.load_readiness(readiness_path)
        self.assertEqual(readiness["status"], "draft_blocked")
        self.assertIsNone(readiness["t_seen"])
        self.assertFalse(readiness["authoritative"])


class FreshSplitPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sessions = weekdays("2008-01-02", "2026-12-31")

    def test_public_readiness_derives_t_seen_from_ledger_and_stays_blocked(self):
        runtime = ROOT / "tuning/factor_mining/runtime/exposure-tests"; runtime.mkdir(parents=True, exist_ok=True)
        readiness = contract.load_readiness(Path(__file__).resolve().parents[1] / "exposure-readiness.json")
        with tempfile.TemporaryDirectory(dir=runtime) as temporary:
            ledger = contract.SyntheticExposureLedger.provision(Path(temporary) / "ledger")
            ledger.append(event("known-exposure", SHA_A, "2015-12-31", "2016-01-02T00:00:00Z"))
            result = contract.plan_fresh_splits_from_ledger(
                ledger=ledger, readiness=readiness, sessions=self.sessions,
                as_of_session=self.sessions[-1],
                calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                universe_identity_sha256="4" * 64, label_roster_sha256="5" * 64)
            self.assertEqual(result["status"], "blocked_nonsealable")
            self.assertFalse(result["authoritative"]); self.assertFalse(result["sealable"])
            self.assertEqual(result["ledger_binding"]["t_seen"], "2015-12-31")
            self.assertEqual(result["candidate_plan"]["status"], "ready")
            self.assertFalse(result["candidate_plan"]["authoritative"])
            self.assertEqual(result["candidate_plan"]["parameters"]["horizon_sessions"], 126)
            self.assertEqual(result["candidate_plan_sha256"],
                             contract.digest(result["candidate_plan"]))
            self.assertTrue(all(result["identity_bindings"][key] is None
                                for key in contract.IDENTITY_BLOCKERS))
            self.assertEqual(result["blockers"], contract.READINESS_BLOCKERS +
                             list(contract.IDENTITY_BLOCKERS.values()))
            resolved = contract.plan_fresh_splits_from_ledger(
                ledger=ledger, readiness=readiness, sessions=self.sessions,
                as_of_session=self.sessions[-1],
                calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                universe_identity_sha256="4" * 64, label_roster_sha256="5" * 64,
                dataset_snapshot_sha256="7" * 64,
                observation_set_sha256="8" * 64, feature_snapshot_sha256="9" * 64,
                evaluation_population_sha256="a" * 64)
            self.assertEqual(resolved["blockers"], contract.READINESS_BLOCKERS)
            self.assertFalse(resolved["sealable"])
            self.assertRegex(result["identity_bindings"]["authority_deployment_profile_sha256"],
                             r"^[a-f0-9]{64}$")
            self.assertEqual(result["identity_bindings"]["admission_policy_sha256"],
                             contract.ADMISSION_POLICY_SHA256)
            inventory = contract.source_inventory_contract.load_inventory(
                contract.SOURCE_INVENTORY_PATH)
            self.assertEqual(result["identity_bindings"]["source_inventory_sha256"],
                             contract.source_inventory_contract.inventory_sha256(inventory))
            profile = contract.trusted_authority_contract.load_profile()
            invalid_profile = copy.deepcopy(profile); invalid_profile["status"] = "active"
            with mock.patch.object(contract.trusted_authority_contract, "load_profile",
                                   return_value=invalid_profile):
                with self.assertRaisesRegex(contract.ExposureError, "TRUST_PROFILE"):
                    contract.plan_fresh_splits_from_ledger(
                        ledger=ledger, readiness=readiness, sessions=self.sessions,
                        as_of_session=self.sessions[-1],
                        calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                        universe_identity_sha256="4" * 64,
                        label_roster_sha256="5" * 64)
            with mock.patch.object(contract.trusted_authority_contract, "digest",
                                   return_value="f" * 64):
                changed_profile = contract.plan_fresh_splits_from_ledger(
                    ledger=ledger, readiness=readiness, sessions=self.sessions,
                    as_of_session=self.sessions[-1],
                    calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                    universe_identity_sha256="4" * 64,
                    label_roster_sha256="5" * 64)
            self.assertEqual(changed_profile["identity_bindings"]
                             ["authority_deployment_profile_sha256"], "f" * 64)
            self.assertNotEqual(changed_profile["integration_identity_sha256"],
                                result["integration_identity_sha256"])
            self.assertRegex(result["integration_identity_sha256"], r"^[a-f0-9]{64}$")
            forged = copy.deepcopy(result); forged["integration_identity_sha256"] = "0" * 64
            with self.assertRaisesRegex(contract.ExposureError, "READINESS_IDENTITY"):
                contract.validate_fresh_split_readiness(forged, sessions=self.sessions)
            for role, index, replacement in (("validation", 0, "2016-01-04"),
                                              ("validation", 0, "2017-01-03"),
                                              ("protected", -1, "2026-12-31")):
                mutated = copy.deepcopy(result); plan = mutated["candidate_plan"]
                plan[role][index] = replacement
                policy = {**plan["parameters"], "calendar_sha256": plan["calendar_sha256"],
                          "t_seen": plan["t_seen"], "as_of_session": plan["as_of_session"]}
                plan["split_identities"] = {
                    "validation": contract.digest({"role": "validation", "policy": policy,
                                                   "ordered_origins": plan["validation"]}),
                    "protected": contract.digest({"role": "protected", "policy": policy,
                                                  "ordered_origins": plan["protected"]})}
                mutated["candidate_plan_sha256"] = contract.digest(plan)
                mutated["integration_identity_sha256"] = contract.digest({
                    "ledger_binding": mutated["ledger_binding"],
                    "identity_bindings": mutated["identity_bindings"],
                    "blockers": mutated["blockers"], "candidate_plan": plan,
                    "candidate_plan_sha256": mutated["candidate_plan_sha256"]})
                with self.subTest(role=role, replacement=replacement), self.assertRaises(contract.ExposureError):
                    contract.validate_fresh_split_readiness(mutated, sessions=self.sessions)
            other = contract.SyntheticExposureLedger.provision(Path(temporary) / "other-ledger")
            other.append(event("known-exposure", SHA_A, "2015-12-31", "2016-01-02T00:00:00Z"))
            other_result = contract.plan_fresh_splits_from_ledger(
                ledger=other, readiness=readiness, sessions=self.sessions,
                as_of_session=self.sessions[-1],
                calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                universe_identity_sha256="4" * 64, label_roster_sha256="5" * 64)
            self.assertNotEqual(result["ledger_binding"]["ledger_genesis_sha256"],
                                other_result["ledger_binding"]["ledger_genesis_sha256"])
            self.assertNotEqual(result["integration_identity_sha256"],
                                other_result["integration_identity_sha256"])

    def test_new_root_or_weakened_readiness_cannot_manufacture_ready(self):
        runtime = ROOT / "tuning/factor_mining/runtime/exposure-tests"; runtime.mkdir(parents=True, exist_ok=True)
        readiness = contract.load_readiness(Path(__file__).resolve().parents[1] / "exposure-readiness.json")
        with tempfile.TemporaryDirectory(dir=runtime) as temporary:
            ledger = contract.SyntheticExposureLedger.provision(Path(temporary) / "new-ledger")
            result = contract.plan_fresh_splits_from_ledger(
                ledger=ledger, readiness=readiness, sessions=self.sessions,
                as_of_session=self.sessions[-1],
                calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                universe_identity_sha256="4" * 64, label_roster_sha256="5" * 64)
            self.assertEqual(result["status"], "blocked_nonsealable")
            self.assertIsNone(result["candidate_plan"])
            weakened = copy.deepcopy(readiness); weakened["authoritative"] = True
            with self.assertRaisesRegex(contract.ExposureError, "READINESS_INVALID"):
                contract.plan_fresh_splits_from_ledger(
                    ledger=ledger, readiness=weakened, sessions=self.sessions,
                    as_of_session=self.sessions[-1],
                    calendar_identity_sha256=contract.digest({"sessions": self.sessions}),
                    universe_identity_sha256="4" * 64, label_roster_sha256="5" * 64)

    def test_ready_memberships_obey_purge_embargo_maturity(self):
        result = contract._plan_fresh_splits(
            sessions=self.sessions, t_seen="2015-12-31", as_of_session=self.sessions[-1])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["validation"]), 24)
        self.assertEqual(len(result["protected"]), 36)
        position = {item: index for index, item in enumerate(self.sessions)}
        seen = max(index for index, item in enumerate(self.sessions) if item <= "2015-12-31")
        self.assertGreaterEqual(position[result["validation"][0]], seen + 127)
        self.assertGreaterEqual(position[result["protected"][0]],
                                position[result["validation"][-1]] + 274)
        self.assertLessEqual(position[result["protected"][-1]] + 126,
                             position[self.sessions[-1]])
        self.assertRegex(result["split_identities"]["protected"], r"^[a-f0-9]{64}$")

    def test_recent_inspected_history_cannot_be_backfilled(self):
        result = contract._plan_fresh_splits(
            sessions=self.sessions, t_seen="2025-12-31", as_of_session=self.sessions[-1])
        self.assertEqual(result["status"], "inconclusive_awaiting_fresh_data")
        self.assertGreater(result["validation_deficit"] + result["protected_deficit"], 0)
        self.assertIsNone(result["split_identities"])

    def test_insufficient_protected_coverage_is_inconclusive(self):
        result = contract._plan_fresh_splits(
            sessions=self.sessions, t_seen="2019-12-31", as_of_session="2025-12-31")
        self.assertEqual(result["status"], "inconclusive_awaiting_fresh_data")
        self.assertEqual(result["validation_deficit"], 0)
        self.assertGreater(result["protected_deficit"], 0)

    def test_aliases_paths_and_repackaging_do_not_enter_identity(self):
        first = contract._plan_fresh_splits(
            sessions=list(self.sessions), t_seen="2015-12-31", as_of_session=self.sessions[-1])
        second = contract._plan_fresh_splits(
            sessions=json.loads(json.dumps(self.sessions)), t_seen="2015-12-31",
            as_of_session=self.sessions[-1])
        self.assertEqual(first["split_identities"], second["split_identities"])

    def test_calendar_identity_is_bound_even_when_selected_origins_match(self):
        first = contract._plan_fresh_splits(
            sessions=self.sessions, t_seen="2015-12-31", as_of_session=self.sessions[-1])
        changed = list(self.sessions); changed[0] = "2008-01-01"
        second = contract._plan_fresh_splits(
            sessions=changed, t_seen="2015-12-31", as_of_session=changed[-1])
        self.assertEqual(first["validation"], second["validation"])
        self.assertNotEqual(first["calendar_sha256"], second["calendar_sha256"])
        self.assertNotEqual(first["split_identities"], second["split_identities"])

    def test_calendar_order_duplicates_dates_and_policy_fail(self):
        cases = [
            {"sessions": list(reversed(self.sessions))},
            {"sessions": self.sessions + [self.sessions[-1]]},
            {"sessions": ["2026-02-30"]},
            {"sessions": self.sessions, "purge_sessions": 125},
            {"sessions": self.sessions, "embargo_sessions": -1},
            {"sessions": self.sessions, "t_seen": "2027-01-01"},
        ]
        for patch in cases:
            args = {"sessions": self.sessions, "t_seen": "2015-12-31",
                    "as_of_session": self.sessions[-1]}
            args.update(patch)
            with self.subTest(patch=patch), self.assertRaises(contract.ExposureError):
                contract._plan_fresh_splits(**args)

    def test_monthly_origins_are_derived_not_caller_selected(self):
        result = contract._plan_fresh_splits(
            sessions=self.sessions, t_seen="2015-12-31", as_of_session=self.sessions[-1])
        all_origins = result["validation"] + result["protected"]
        for origin in all_origins:
            later_same_month = [item for item in self.sessions if item > origin and
                                item[:7] == origin[:7]]
            self.assertEqual(later_same_month, [])


if __name__ == "__main__":
    unittest.main()
