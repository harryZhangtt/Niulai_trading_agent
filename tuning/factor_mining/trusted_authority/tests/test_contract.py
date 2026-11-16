import copy
import json
from pathlib import Path
import unittest

from tuning.factor_mining.trusted_authority import contract

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
T0 = "2026-11-05T00:00:00Z"
T1 = "2026-11-05T01:00:00Z"
T2 = "2026-11-05T02:00:00Z"
T3 = "2026-11-05T03:00:00Z"


def fixture():
    backend = contract.MemoryCheckpointBackend()
    keys = contract.FixtureKeyring()
    first = contract.FixtureSigner("fixture-key-a", b"a" * 32)
    keys.add(first, activate=True)
    return backend, keys, first


class TrustedAuthorityContractTests(unittest.TestCase):
    def test_tracked_profile_is_exact_disabled_and_nonactivatable(self):
        profile = contract.load_profile()
        self.assertEqual(profile["status"], "candidate-disabled")
        self.assertEqual(profile["blockers"], contract.BLOCKERS)
        self.assertTrue(all(profile[key] is None for key in (
            "checkpoint_backend_id", "signer_policy_sha256", "key_custody_owner_id",
            "recovery_policy_sha256", "recovery_owner_id",
            "independent_checker_policy_sha256", "publication_service_id")))
        self.assertEqual(profile["allowed_purposes"], [])
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "PROFILE_BLOCKED"):
            contract.assert_active(profile)
        changed = copy.deepcopy(profile); changed["status"] = "active"
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "PROFILE_INVALID"):
            contract.validate_profile(changed)

    def test_checkpoint_chain_rejects_rollback_reset_copy_and_wrong_workspace(self):
        backend, keys, _ = fixture()
        first = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                          issued_at=T0)
        backend.publish(first)
        second = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_B,
                                           issued_at=T1)
        backend.publish(second)
        self.assertEqual(backend.latest()["sequence"], 2)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "ROLLBACK"):
            backend.publish(first)
        copied = copy.deepcopy(second); copied["workspace_id"] = "other-workspace"
        with self.assertRaises(contract.TrustedAuthorityError):
            contract.validate_checkpoint(copied)
        reset = copy.deepcopy(first); reset["ledger_head_sha256"] = SHA_C
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "ROLLBACK"):
            backend.publish(reset)

    def test_backend_returns_deep_copies_and_quarantine_stays_authoritative(self):
        backend, keys, _ = fixture()
        first = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                          issued_at=T0)
        returned = backend.publish(first)
        returned["status"] = "revoked"
        latest = backend.latest(); latest["status"] = "revoked"
        exported = backend.exported(); exported[0]["status"] = "revoked"
        self.assertEqual(backend.latest()["status"], "active")
        authorization = contract.issue_authorization(
            backend.latest(), keys, authorization_id="auth-copy-test",
            purpose="performance_publication", payload_sha256=SHA_B,
            issued_at=T0, expires_at=T3)
        quarantine = contract.issue_checkpoint(
            backend, keys, ledger_head_sha256=SHA_C, issued_at=T1,
            status="quarantined")
        published = backend.publish(quarantine)
        published["status"] = "active"
        self.assertEqual(backend.latest()["status"], "quarantined")
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "STALE"):
            contract.lookup_authorization(authorization, backend, keys,
                                           purpose="performance_publication",
                                           payload_sha256=SHA_B, now=T2)

    def test_unknown_write_outcome_is_reconciled_not_replayed(self):
        backend, keys, _ = fixture()
        checkpoint = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                               issued_at=T0)
        with self.assertRaisesRegex(contract.UnknownOutcome, "UNKNOWN_OUTCOME"):
            backend.publish(checkpoint, unknown_after_write=True)
        self.assertTrue(backend.reconcile(contract.digest(checkpoint)))
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "ROLLBACK"):
            backend.publish(checkpoint)

    def test_checkpoint_and_authorization_times_are_strict_and_expiry_is_exclusive(self):
        backend, keys, _ = fixture()
        first = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                          issued_at=T1)
        backend.publish(first)
        backdated = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_B,
                                              issued_at=T0)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "ROLLBACK"):
            backend.publish(backdated)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "AUTHORIZATION_TIME_INVALID"):
            contract.issue_authorization(
                first, keys, authorization_id="auth-before-checkpoint",
                purpose="performance_publication", payload_sha256=SHA_B,
                issued_at=T0, expires_at=T2)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "AUTHORIZATION_TIME_INVALID"):
            contract.issue_authorization(
                first, keys, authorization_id="auth-zero-window",
                purpose="performance_publication", payload_sha256=SHA_B,
                issued_at=T1, expires_at=T1)
        authorization = contract.issue_authorization(
            first, keys, authorization_id="auth-exclusive-expiry",
            purpose="performance_publication", payload_sha256=SHA_B,
            issued_at=T1, expires_at=T2)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "AUTHORIZATION_DENIED"):
            contract.lookup_authorization(
                authorization, backend, keys, purpose="performance_publication",
                payload_sha256=SHA_B, now=T2)

    def test_key_rotation_revocation_and_historical_checkpoint_verification(self):
        backend, keys, first_signer = fixture()
        first = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                          issued_at=T0)
        backend.publish(first)
        second_signer = contract.FixtureSigner("fixture-key-b", b"b" * 32)
        keys.rotate(second_signer)
        second = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_B,
                                           issued_at=T1, epoch=2)
        backend.publish(second)
        self.assertEqual(second["key_id"], "fixture-key-b")
        first_signer.revoke()
        self.assertEqual(contract.verify_checkpoint(first, keys), first)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "KEY_REVOKED"):
            first_signer.sign({"x": 1})

    def test_authorization_is_purpose_payload_expiry_and_checkpoint_bound(self):
        backend, keys, signer = fixture()
        checkpoint = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                               issued_at=T0)
        backend.publish(checkpoint)
        authorization = contract.issue_authorization(
            checkpoint, keys, authorization_id="auth-performance-1",
            purpose="performance_publication", payload_sha256=SHA_B,
            issued_at=T0, expires_at=T2)
        self.assertEqual(contract.lookup_authorization(
            authorization, backend, keys, purpose="performance_publication",
            payload_sha256=SHA_B, now=T1), authorization)
        for purpose, payload, now in (("ev_publication", SHA_B, T1),
                                      ("performance_publication", SHA_C, T1),
                                      ("performance_publication", SHA_B, T3)):
            with self.subTest(purpose=purpose, payload=payload, now=now), self.assertRaises(
                    contract.TrustedAuthorityError):
                contract.lookup_authorization(authorization, backend, keys,
                                               purpose=purpose, payload_sha256=payload,
                                               now=now)
        signer.revoke()
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "SIGNATURE_INVALID"):
            contract.lookup_authorization(authorization, backend, keys,
                                           purpose="performance_publication",
                                           payload_sha256=SHA_B, now=T1)

    def test_quarantine_or_new_checkpoint_revokes_current_authorization(self):
        backend, keys, _ = fixture()
        first = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                          issued_at=T0)
        backend.publish(first)
        authorization = contract.issue_authorization(
            first, keys, authorization_id="auth-combination-1",
            purpose="combination_selection", payload_sha256=SHA_B,
            issued_at=T0, expires_at=T3)
        quarantine = contract.issue_checkpoint(
            backend, keys, ledger_head_sha256=SHA_C, issued_at=T1,
            status="quarantined")
        backend.publish(quarantine)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "STALE"):
            contract.lookup_authorization(authorization, backend, keys,
                                           purpose="combination_selection",
                                           payload_sha256=SHA_B, now=T2)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "NOT_ACTIVE"):
            contract.issue_authorization(quarantine, keys,
                                         authorization_id="auth-forbidden",
                                         purpose="performance_publication",
                                         payload_sha256=SHA_C,
                                         issued_at=T1, expires_at=T3)

    def test_recovery_import_requires_complete_nonrollback_chain_and_valid_signatures(self):
        backend, keys, _ = fixture()
        first = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_A,
                                          issued_at=T0); backend.publish(first)
        second = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_B,
                                           issued_at=T1); backend.publish(second)
        bundle = contract.export_recovery_bundle(backend)
        recovered = contract.MemoryCheckpointBackend()
        contract.import_recovery_bundle(recovered, keys, bundle)
        self.assertEqual(contract.digest(recovered.latest()), contract.digest(second))
        third = contract.issue_checkpoint(backend, keys, ledger_head_sha256=SHA_C,
                                          issued_at=T2); backend.publish(third)
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "RECOVERY_ROLLBACK"):
            contract.import_recovery_bundle(backend, keys, bundle)
        forged = copy.deepcopy(contract.export_recovery_bundle(backend))
        forged["checkpoints"][-1]["signature"] = "f" * 64
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "SIGNATURE_INVALID"):
            contract.import_recovery_bundle(contract.MemoryCheckpointBackend(), keys, forged)

    def test_strict_json_schemas_and_sensitive_values_are_absent(self):
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "DUPLICATE_KEY"):
            contract.loads_strict('{"a":1,"a":2}')
        with self.assertRaisesRegex(contract.TrustedAuthorityError, "NONFINITE"):
            contract.loads_strict('{"a":NaN}')
        schemas = sorted(Path(contract.PACKAGE).glob("*schema.json"))
        self.assertEqual(len(schemas), 4)
        for path in schemas:
            value = json.loads(path.read_text())
            self.assertEqual(set(value["required"]), set(value["properties"]))
        tracked = Path(contract.PROFILE_PATH).read_text().lower()
        for marker in ("api_key", "password", "bearer ", "secret="):
            self.assertNotIn(marker, tracked)


if __name__ == "__main__":
    unittest.main()
