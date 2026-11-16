from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import uuid

from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    CredentialReadinessReceipt,
    CredentialReadinessStatus,
    NON_CRYPTO_LIMITATION,
    OperationalEvidenceSource,
    OperationalTrustPolicy,
)
from tuning.evals.information_fetch.live_e2e import materialize_host as materialize_module
from tuning.evals.information_fetch.live_e2e.materialize_host import (
    INPUT_VERSION,
    MaterializeHostError,
    describe,
    materialize,
)


ROOT = Path(__file__).resolve().parents[4]


class HostMaterializerTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".research-sources/test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (".job-runtime", ".research-sources", "runtime", "profiles"):
            path = self.root / name
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.chmod(0o700)
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        self.refs = {}
        for name in ("runtime/python", "profiles/codex.json", "profiles/claude.json"):
            path = self.root / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_text("fixture:" + name)
            path.chmod(0o600)
            self.refs[name] = {
                "path": name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        self.value = {
            "schema_version": INPUT_VERSION,
            "output_directory": ".job-runtime/materialized-hosts",
            "mcp": "not_used",
            "hosts": [self.host("codex"), self.host("claude")],
        }

    def host(self, host):
        codex = host == "codex"
        adapter = AdapterId.CODEX_NATIVE_WEB if codex else AdapterId.CLAUDE_CODE_WEB
        backend = "native_tools.web__run" if codex else "claude_code.web"
        owner = f"{host}-owner"
        profile = f"{host}.profile"
        fingerprint = ("a" if codex else "b") * 64
        session = f"{host}-session-1"
        receipt = CredentialReadinessReceipt(
            adapter_id=adapter,
            owner_ref=owner,
            profile_ref=profile,
            profile_fingerprint_sha256=fingerprint,
            host_session_id=session,
            capability_observed=backend,
            checked_at=self.now.isoformat(),
            status=CredentialReadinessStatus.READY,
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        ).to_public_dict()
        return {
            "host": host,
            "host_session_id": session,
            "runtime_identity": f"{host}.runtime",
            "interpreter_ref": self.refs["runtime/python"],
            "runtime_profile_ref": self.refs[f"profiles/{host}.json"],
            "credential": {
                "owner_ref": owner,
                "source": f"{host}_profile",
                "profile_ref": profile,
                "fingerprint_sha256": fingerprint,
            },
            "execution": {
                "execution_id": str(uuid.uuid4()),
                "trace_id": f"trace-{host}",
                "dispatch_namespace": f"dispatch-{host}",
                "artifact_root": f".research-sources/runs/{host}/artifacts",
                "cache_root": f".research-sources/runs/{host}/cache",
                "budget": {
                    "search_items": 1, "open_items": 2, "provider_items": 3,
                    "concurrency": 1, "call_timeout_seconds": 60,
                    "run_timeout_seconds": 300,
                },
            },
            "observation": receipt,
        }

    @staticmethod
    def remove_sealed_generation(generation):
        generation.chmod(0o700)
        for member in generation.iterdir():
            member.chmod(0o600)
            member.unlink()
        generation.rmdir()

    def test_describe_has_no_writes(self):
        before = set((self.root / ".job-runtime").iterdir())
        value = describe()
        self.assertEqual(value["side_effects"], [])
        self.assertFalse(value["credential_values_read"])
        self.assertEqual(set((self.root / ".job-runtime").iterdir()), before)

    def test_valid_pair_materializes_private_public_contracts_and_reuses_exactly(self):
        first = materialize(self.value, workspace_root=self.root, now=self.now)
        output = self.root / self.value["output_directory"]
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertEqual(len(list(output.iterdir())), 3)
        manifest = json.loads((output / "materialization-manifest.json").read_text())
        self.assertEqual(manifest["kind"], "host_profile_materialization_head")
        generation = output / manifest["generation"]
        self.assertTrue(generation.is_dir())
        self.assertEqual(stat.S_IMODE(generation.stat().st_mode), 0o500)
        self.assertEqual(stat.S_IMODE((output / ".materialize.lock").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((output / "materialization-manifest.json").stat().st_mode), 0o600)
        self.assertEqual(set(manifest["files"]), {
            f"{host}-{suffix}.json" for host in ("codex", "claude")
            for suffix in ("profile", "credential-readiness", "binding")})
        self.assertEqual(set(path.name for path in generation.iterdir()),
                         set(manifest["files"]))
        for path in generation.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
        self.assertTrue(first["hosts"]["codex"]["ready_for_live"])
        self.assertTrue(first["hosts"]["claude"]["ready_for_live"])
        public = json.dumps(first)
        self.assertNotIn('"credential_value":', public)
        self.assertIn('"manifest"', public)
        self.assertEqual(json.loads((generation / "codex-profile.json").read_text())["mcp"], None)
        self.assertEqual(first["generation"]["path"], str(generation.relative_to(self.root)))
        second = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertTrue(second["generation"]["reused"])
        for host in ("codex", "claude"):
            for key in ("profile", "credential_readiness", "binding"):
                self.assertTrue(second["hosts"][host][key]["reused"])

    def test_partial_exact_recovery_and_conflict_rejection(self):
        first = materialize(self.value, workspace_root=self.root, now=self.now)
        output = self.root / self.value["output_directory"]
        generation = self.root / first["generation"]["path"]
        (output / "materialization-manifest.json").unlink()
        recovered = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertTrue(recovered["generation"]["reused"])
        self.assertFalse(recovered["manifest"]["reused"])
        for host in ("codex", "claude"):
            for key in ("profile", "credential_readiness", "binding"):
                self.assertTrue(recovered["hosts"][host][key]["reused"])
        (output / "materialization-manifest.json").unlink()
        generation.chmod(0o700)
        (generation / "codex-profile.json").chmod(0o600)
        (generation / "codex-profile.json").write_text("conflict")
        with self.assertRaises(MaterializeHostError):
            materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertFalse((output / "materialization-manifest.json").exists())

    def test_traversal_symlink_nonempty_output_and_mutable_root_fail(self):
        for output in ("../escape", "/absolute", ".job-runtime/../escape"):
            changed = deepcopy(self.value); changed["output_directory"] = output
            with self.subTest(output=output), self.assertRaises(MaterializeHostError):
                materialize(changed, workspace_root=self.root, now=self.now)
        target = self.root / ".job-runtime/actual"
        target.mkdir(mode=0o700)
        (self.root / ".job-runtime/link").symlink_to(target, target_is_directory=True)
        changed = deepcopy(self.value); changed["output_directory"] = ".job-runtime/link/out"
        with self.assertRaises(MaterializeHostError):
            materialize(changed, workspace_root=self.root, now=self.now)
        output = self.root / self.value["output_directory"]
        output.mkdir(mode=0o700)
        (output / "extra").write_text("unexpected")
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_OUTPUT_NOT_EMPTY"):
            materialize(self.value, workspace_root=self.root, now=self.now)
        output.joinpath("extra").unlink()
        output.joinpath(".materialize.lock").unlink()
        output.rmdir()
        artifact = self.root / self.value["hosts"][0]["execution"]["artifact_root"]
        artifact.mkdir(mode=0o700, parents=True)
        (artifact / "occupied").write_text("x")
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_MUTABLE_ROOT_NOT_EMPTY"):
            materialize(self.value, workspace_root=self.root, now=self.now)

    def test_stale_future_capability_session_and_fingerprint_mismatch_fail(self):
        cases = []
        stale = deepcopy(self.value); stale["hosts"][0]["observation"]["checked_at"] = (
            self.now - timedelta(minutes=16)).isoformat(); cases.append(stale)
        future = deepcopy(self.value); future["hosts"][0]["observation"]["checked_at"] = (
            self.now + timedelta(seconds=6)).isoformat(); cases.append(future)
        capability = deepcopy(self.value); capability["hosts"][0]["observation"][
            "capability_observed"] = "other.backend"; cases.append(capability)
        session = deepcopy(self.value); session["hosts"][0]["observation"][
            "host_session_id"] = "other-session"; cases.append(session)
        fingerprint = deepcopy(self.value); fingerprint["hosts"][0]["observation"][
            "profile_fingerprint_sha256"] = "c" * 64; cases.append(fingerprint)
        for index, changed in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(MaterializeHostError):
                materialize(changed, workspace_root=self.root, now=self.now)

    def test_synthetic_observation_materializes_but_never_becomes_ready(self):
        changed = deepcopy(self.value)
        changed["hosts"][0]["observation"]["source"] = "synthetic_fixture"
        changed["hosts"][0]["observation"]["live_acceptance_eligible"] = False
        result = materialize(changed, workspace_root=self.root, now=self.now)
        self.assertFalse(result["hosts"]["codex"]["ready_for_live"])
        self.assertTrue(result["hosts"]["claude"]["ready_for_live"])

    def test_secret_shaped_keys_values_and_credential_values_are_rejected(self):
        cases = []
        keyed = deepcopy(self.value); keyed["access_token"] = "synthetic"; cases.append(keyed)
        bearer = deepcopy(self.value); bearer["hosts"][0]["credential"][
            "owner_ref"] = "Bearer abcdefghijklmnopqrstuvwxyz"; cases.append(bearer)
        present = deepcopy(self.value); present["hosts"][0]["observation"][
            "credential_values_present"] = True; cases.append(present)
        aws = deepcopy(self.value); aws["hosts"][0]["credential"][
            "owner_ref"] = "AKIAABCDEFGHIJKLMNOP"; cases.append(aws)
        private_url = deepcopy(self.value); private_url["hosts"][0][
            "runtime_identity"] = "https://127.0.0.1/private"; cases.append(private_url)
        uppercase_url = deepcopy(self.value); uppercase_url["hosts"][0][
            "runtime_identity"] = "HTTPS://127.0.0.1/private"; cases.append(uppercase_url)
        for sensitive in (
                "oauth/session.json", "oauth-backup/session.json",
                "oauth.backup/session.json", "backup-oauth/session.json",
                "backup.auth/session.json", "auth.json", "credentials/store.json",
                "credentials.backup", "my-secrets/private.json",
                "profile-store/private.json", "profile.backup", "x-profile/private.json",
                ".env.production"):
            changed = deepcopy(self.value)
            changed["hosts"][0]["interpreter_ref"] = {
                "path": f"runtime/{sensitive}", "sha256": "c" * 64}
            cases.append(changed)
        unsafe_limit = deepcopy(self.value); unsafe_limit["hosts"][0]["observation"][
            "limitations"].append("Bearer synthetic-secret"); cases.append(unsafe_limit)
        env_file = self.root / ".env"; env_file.write_text("synthetic")
        env_file.chmod(0o600)
        hidden = deepcopy(self.value); hidden["hosts"][0]["interpreter_ref"] = {
            "path": ".env", "sha256": hashlib.sha256(env_file.read_bytes()).hexdigest()}
        cases.append(hidden)
        for changed in cases:
            with self.assertRaises(MaterializeHostError):
                materialize(changed, workspace_root=self.root, now=self.now)

    def test_path_tokens_do_not_reject_non_path_identifiers(self):
        for identifier in ("backup-oauth", "backup.auth", "my-secrets", "x-profile",
                           "codex.profile"):
            materialize_module._reject_secrets(identifier)
        for value in ("runtime/backup-oauth/file.json", "runtime/backup.auth/file.json",
                      "runtime/my-secrets/file.json", "runtime/x-profile/file.json"):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_SECRET_REJECTED"):
                materialize_module._reject_path_field(value)

    def test_cross_host_identity_root_runtime_and_credential_sharing_fail(self):
        mutations = []
        for key in ("execution_id", "trace_id", "dispatch_namespace",
                    "artifact_root", "cache_root"):
            changed = deepcopy(self.value)
            changed["hosts"][1]["execution"][key] = changed["hosts"][0]["execution"][key]
            mutations.append(changed)
        runtime = deepcopy(self.value); runtime["hosts"][1]["runtime_profile_ref"] = (
            runtime["hosts"][0]["runtime_profile_ref"]); mutations.append(runtime)
        credential = deepcopy(self.value); credential["hosts"][1]["credential"].update({
            "owner_ref": credential["hosts"][0]["credential"]["owner_ref"],
            "source": "claude_profile",
            "profile_ref": credential["hosts"][0]["credential"]["profile_ref"],
            "fingerprint_sha256": credential["hosts"][0]["credential"]["fingerprint_sha256"],
        })
        credential["hosts"][1]["observation"].update({
            "owner_ref": credential["hosts"][0]["observation"]["owner_ref"],
            "profile_ref": credential["hosts"][0]["observation"]["profile_ref"],
            "profile_fingerprint_sha256": credential["hosts"][0]["observation"][
                "profile_fingerprint_sha256"],
        }); mutations.append(credential)
        session = deepcopy(self.value); session["hosts"][1]["host_session_id"] = (
            session["hosts"][0]["host_session_id"]); mutations.append(session)
        for index, changed in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(MaterializeHostError):
                materialize(changed, workspace_root=self.root, now=self.now)


    def test_owned_orphan_cleanup_and_manifest_last_partial_recovery(self):
        output = self.root / self.value["output_directory"]
        output.mkdir(mode=0o700)
        orphan = output / (".generation-" + "a" * 64 + ".123." + "b" * 16 + ".tmp")
        orphan.mkdir(mode=0o700)
        orphan_file = orphan / "codex-profile.json"
        orphan_file.write_text("orphan"); orphan_file.chmod(0o600)
        first = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertFalse(orphan.exists())
        self.assertTrue((output / "materialization-manifest.json").is_file())
        generation = self.root / first["generation"]["path"]
        self.assertTrue(generation.is_dir())
        (output / "materialization-manifest.json").unlink()
        second = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertTrue(second["generation"]["reused"])
        self.assertTrue(second["hosts"]["codex"]["credential_readiness"]["reused"])
        self.assertFalse(second["manifest"]["reused"])

    def test_crash_after_seal_orphan_is_verified_cleaned_and_rebuilt(self):
        first = materialize(self.value, workspace_root=self.root, now=self.now)
        output = self.root / self.value["output_directory"]
        generation = self.root / first["generation"]["path"]
        digest = generation.name.removeprefix("generation-")
        orphan = output / f".generation-{digest}.123.{'b' * 16}.tmp"
        (output / "materialization-manifest.json").unlink()
        generation.rename(orphan)
        self.assertEqual(stat.S_IMODE(orphan.stat().st_mode), 0o500)
        result = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertFalse(orphan.exists())
        self.assertFalse(result["generation"]["reused"])
        self.assertTrue((self.root / result["generation"]["path"]).is_dir())
        self.assertTrue((output / "materialization-manifest.json").is_file())

    def test_staging_cleanup_recovers_seal_and_delete_transition_crashes(self):
        for state in ("mixed-seal", "partial-delete"):
            changed = deepcopy(self.value)
            changed["output_directory"] = f".job-runtime/staging-transition-{state}"
            first = materialize(changed, workspace_root=self.root, now=self.now)
            output = self.root / changed["output_directory"]
            generation = self.root / first["generation"]["path"]
            digest = generation.name.removeprefix("generation-")
            orphan = output / f".generation-{digest}.789.{'d' * 16}.tmp"
            (output / "materialization-manifest.json").unlink()
            generation.rename(orphan)
            orphan.chmod(0o700)
            members = sorted(orphan.iterdir())
            if state == "mixed-seal":
                members[0].chmod(0o600)
            else:
                members[0].unlink()
                members[1].chmod(0o600)
            replay = materialize(changed, workspace_root=self.root, now=self.now)
            self.assertFalse(orphan.exists())
            self.assertFalse(replay["generation"]["reused"])
            self.assertTrue((self.root / replay["generation"]["path"]).is_dir())
            self.assertTrue((output / "materialization-manifest.json").is_file())

    def test_dangling_head_recovers_after_generation_removal_or_owned_rename(self):
        for action in ("remove", "rename"):
            changed = deepcopy(self.value)
            changed["output_directory"] = f".job-runtime/dangling-head-{action}"
            first = materialize(changed, workspace_root=self.root, now=self.now)
            output = self.root / changed["output_directory"]
            generation = self.root / first["generation"]["path"]
            if action == "remove":
                self.remove_sealed_generation(generation)
            else:
                generation.rename(output / "arbitrarily-renamed-generation")
            self.assertTrue((output / "materialization-manifest.json").is_file())
            replay = materialize(changed, workspace_root=self.root, now=self.now)
            self.assertEqual(replay["generation"]["reused"], action == "rename")
            self.assertEqual(replay["manifest"]["reused"], action == "rename")
            self.assertTrue((self.root / replay["generation"]["path"]).is_dir())
            self.assertTrue((output / "materialization-manifest.json").is_file())

    def test_generation_destination_collision_is_explicit(self):
        original = materialize_module._rename_generation_noclobber

        changed = deepcopy(self.value)
        changed["output_directory"] = ".job-runtime/generation-collision-exact"

        def exact_winner(directory_fd, source, destination):
            original(directory_fd, source, destination)
            raise FileExistsError

        with mock.patch.object(materialize_module, "_rename_generation_noclobber",
                               side_effect=exact_winner):
            result = materialize(changed, workspace_root=self.root, now=self.now)
        self.assertTrue(result["generation"]["reused"])
        self.assertTrue((self.root / result["generation"]["path"]).is_dir())

        conflicting = deepcopy(self.value)
        conflicting["output_directory"] = ".job-runtime/generation-collision-conflict"
        conflict_output = self.root / conflicting["output_directory"]

        def conflicting_winner(directory_fd, source, destination):
            os.mkdir(destination, 0o700, dir_fd=directory_fd)
            raise FileExistsError

        with mock.patch.object(materialize_module, "_rename_generation_noclobber",
                               side_effect=conflicting_winner):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_GENERATION_INVALID"):
                materialize(conflicting, workspace_root=self.root, now=self.now)
        self.assertFalse((conflict_output / "materialization-manifest.json").exists())

    def test_late_conflict_never_publishes_manifest_and_exact_partial_recovers(self):
        output = self.root / self.value["output_directory"]
        original = materialize_module._publish_at
        injected = {"done": False}

        def late_conflict(directory_fd, name, payload):
            if name == "claude-credential-readiness.json" and not injected["done"]:
                injected["done"] = True
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                     0o600, dir_fd=directory_fd)
                os.write(descriptor, b"conflict"); os.close(descriptor)
            return original(directory_fd, name, payload)

        with mock.patch.object(materialize_module, "_publish_at",
                               side_effect=late_conflict):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_OUTPUT_CONFLICT"):
                materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertFalse((output / "materialization-manifest.json").exists())
        result = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertTrue((output / "materialization-manifest.json").is_file())
        self.assertFalse(result["manifest"]["reused"])

    def test_manifest_is_withheld_when_published_member_is_removed_or_replaced(self):
        original = materialize_module._publish_at
        for action in ("remove", "replace"):
            changed = deepcopy(self.value)
            changed["output_directory"] = f".job-runtime/materialized-hosts-{action}"
            output = self.root / changed["output_directory"]
            injected = {"done": False}

            def race(directory_fd, name, payload, *, selected=action):
                reused = original(directory_fd, name, payload)
                if name == "codex-profile.json" and not injected["done"]:
                    injected["done"] = True
                    os.unlink("claude-binding.json", dir_fd=directory_fd)
                    if selected == "replace":
                        descriptor = os.open(
                            "claude-binding.json",
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=directory_fd)
                        os.write(descriptor, b"replacement")
                        os.fsync(descriptor)
                        os.close(descriptor)
                return reused

            with self.subTest(action=action), mock.patch.object(
                    materialize_module, "_publish_at", side_effect=race):
                with self.assertRaises(MaterializeHostError):
                    materialize(changed, workspace_root=self.root, now=self.now)
            self.assertFalse((output / "materialization-manifest.json").exists())

    def test_sealed_generation_blocks_late_member_removal_before_head(self):
        original = materialize_module._publish_at
        observed = {"blocked": False}

        def race(directory_fd, name, payload):
            if name == "materialization-manifest.json" and not observed["blocked"]:
                generation = next(
                    entry for entry in os.listdir(directory_fd)
                    if entry.startswith("generation-"))
                generation_fd = os.open(
                    generation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd)
                try:
                    with self.assertRaises(PermissionError):
                        os.unlink("claude-binding.json", dir_fd=generation_fd)
                    observed["blocked"] = True
                finally:
                    os.close(generation_fd)
            return original(directory_fd, name, payload)

        with mock.patch.object(materialize_module, "_publish_at", side_effect=race):
            result = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertTrue(observed["blocked"])
        output = self.root / self.value["output_directory"]
        generation = self.root / result["generation"]["path"]
        self.assertTrue((generation / "claude-binding.json").is_file())
        self.assertTrue((output / "materialization-manifest.json").is_file())

    def test_race_loser_revalidates_symlink_target_by_dirfd(self):
        output = self.root / self.value["output_directory"]
        outside = self.root / "outside.json"; outside.write_text("outside")
        outside.chmod(0o600)
        original = materialize_module.os.link
        injected = {"done": False}

        def race_link(src, dst, **kwargs):
            if dst == "claude-binding.json" and not injected["done"]:
                injected["done"] = True
                os.symlink(str(outside), dst, dir_fd=kwargs["dst_dir_fd"])
                raise FileExistsError
            return original(src, dst, **kwargs)

        with mock.patch.object(materialize_module.os, "link", side_effect=race_link):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_OUTPUT_CONFLICT"):
                materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertFalse((output / "materialization-manifest.json").exists())

    def test_generated_payload_is_revalidated_before_persistence(self):
        with mock.patch.object(materialize_module.HostAdapterProfile,
                               "to_public_dict",
                               return_value={"access_token": "synthetic"}):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_SECRET_REJECTED"):
                materialize(self.value, workspace_root=self.root, now=self.now)
        original_profile = materialize_module.HostAdapterProfile.to_public_dict

        def drifted_backend(profile):
            value = original_profile(profile)
            value["configured_backend"] = "wrong.backend"
            return value

        with mock.patch.object(materialize_module.HostAdapterProfile,
                               "to_public_dict", side_effect=drifted_backend,
                               autospec=True):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_PROFILE_OUTPUT"):
                materialize(self.value, workspace_root=self.root, now=self.now)

        def sensitive_profile_path(profile):
            value = original_profile(profile)
            value["runtime"]["profile_ref"] = {
                "path": "profiles/oauth/session.json", "sha256": "c" * 64}
            return value

        with mock.patch.object(materialize_module.HostAdapterProfile,
                               "to_public_dict", side_effect=sensitive_profile_path,
                               autospec=True):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_PROFILE_OUTPUT"):
                materialize(self.value, workspace_root=self.root, now=self.now)

        original_binding = materialize_module.HostExecutionBinding.to_public_dict

        def mutate_binding(mutator):
            def changed(binding):
                value = original_binding(binding)
                mutator(value)
                unsigned = {key: item for key, item in value.items()
                            if key != "binding_sha256"}
                value["binding_sha256"] = hashlib.sha256(
                    json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                return value
            return changed

        mutations = (
            lambda value: value["budget"].update({"concurrency": 0}),
            lambda value: value.update({"artifact_root": "HTTPS://example.test/private"}),
            lambda value: value.update({"execution_id": str(uuid.uuid4())}),
            lambda value: value.update({
                "cache_root": ".research-sources/runs/generated-root-drift"}),
        )
        for index, mutator in enumerate(mutations):
            with self.subTest(generated_binding=index), mock.patch.object(
                    materialize_module.HostExecutionBinding, "to_public_dict",
                    side_effect=mutate_binding(mutator), autospec=True):
                with self.assertRaises(MaterializeHostError):
                    materialize(self.value, workspace_root=self.root, now=self.now)

        with mock.patch.object(materialize_module, "validate_execution_pair",
                               wraps=materialize_module.validate_execution_pair) as pair:
            materialize(self.value, workspace_root=self.root, now=self.now)
            self.assertEqual(pair.call_count, 2)

    def test_metadata_mode_drift_during_read_fails_closed(self):
        output = self.root / self.value["output_directory"]
        output.mkdir(mode=0o700)
        target = output / "race.json"
        target.write_bytes(b"{}\n"); target.chmod(0o600)
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, directory_fd)
        original_read = materialize_module.os.read

        def chmod_after_read(descriptor, count):
            value = original_read(descriptor, count)
            os.fchmod(descriptor, 0o644)
            return value

        with mock.patch.object(materialize_module.os, "read",
                               side_effect=chmod_after_read):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_OUTPUT_CONFLICT"):
                materialize_module._read_existing_at(directory_fd, "race.json")

        input_path = self.root / ".job-runtime/input-race.json"
        input_path.write_text(json.dumps(self.value)); input_path.chmod(0o600)
        with mock.patch.object(materialize_module.os, "read",
                               side_effect=chmod_after_read):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_INPUT_FILE"):
                materialize_module._load_input(input_path, workspace_root=self.root)


    def test_cli_input_is_workspace_bounded_private_nofollow_and_unique(self):
        input_path = self.root / ".job-runtime/input.json"
        input_path.write_text(json.dumps(self.value)); input_path.chmod(0o600)
        loaded = materialize_module._load_input(
            Path(".job-runtime/input.json"), workspace_root=self.root)
        self.assertEqual(loaded, self.value)
        duplicate = self.root / ".job-runtime/duplicate.json"
        duplicate.write_text('{"schema_version":1,"schema_version":2}')
        duplicate.chmod(0o600)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_INPUT_FILE"):
            materialize_module._load_input(duplicate, workspace_root=self.root)
        link = self.root / ".job-runtime/input-link.json"
        link.symlink_to(input_path)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_INPUT_FILE"):
            materialize_module._load_input(link, workspace_root=self.root)
        input_path.chmod(0o644)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_INPUT_FILE"):
            materialize_module._load_input(input_path, workspace_root=self.root)
        outside = self.root.parent / f"{self.root.name}-outside.json"
        outside.write_text("{}"); outside.chmod(0o600)
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_INPUT_FILE"):
            materialize_module._load_input(outside, workspace_root=self.root)

    def test_cli_input_ancestor_swap_during_dirfd_walk_fails_closed(self):
        parent = self.root / ".job-runtime"
        original_dir = parent / "input-parent"
        original_dir.mkdir(mode=0o700)
        input_path = original_dir / "input.json"
        input_path.write_text(json.dumps(self.value)); input_path.chmod(0o600)
        moved_dir = parent / "input-parent-moved"
        original_open = materialize_module.os.open
        injected = {"done": False}

        def swap_ancestor(path, flags, mode=0o777, *, dir_fd=None):
            if dir_fd is None:
                descriptor = original_open(path, flags, mode)
            else:
                descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
            if path == "input-parent" and flags & os.O_DIRECTORY and not injected["done"]:
                injected["done"] = True
                original_dir.rename(moved_dir)
                original_dir.mkdir(mode=0o700)
                replacement = original_dir / "input.json"
                replacement.write_text("{}")
                replacement.chmod(0o600)
            return descriptor

        with mock.patch.object(materialize_module.os, "open", side_effect=swap_ancestor):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_INPUT_FILE"):
                materialize_module._load_input(
                    Path(".job-runtime/input-parent/input.json"),
                    workspace_root=self.root)

    def test_conflicting_head_blocks_generation_publication(self):
        output = self.root / self.value["output_directory"]
        output.mkdir(mode=0o700)
        head = output / "materialization-manifest.json"
        head.write_text("conflicting-head"); head.chmod(0o600)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_OUTPUT_CONFLICT"):
            materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertEqual(head.read_text(), "conflicting-head")
        self.assertFalse(any(path.name.startswith("generation-")
                             for path in output.iterdir()))

    def test_output_component_walk_rejects_ancestor_swap(self):
        changed = deepcopy(self.value)
        changed["output_directory"] = ".job-runtime/output-parent/materialized-hosts"
        parent = self.root / ".job-runtime"
        original_dir = parent / "output-parent"
        original_dir.mkdir(mode=0o700)
        moved_dir = parent / "output-parent-moved"
        original_open = materialize_module.os.open
        injected = {"done": False}

        def swap_ancestor(path, flags, mode=0o777, *, dir_fd=None):
            if dir_fd is None:
                descriptor = original_open(path, flags, mode)
            else:
                descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
            if path == "output-parent" and flags & os.O_DIRECTORY and not injected["done"]:
                injected["done"] = True
                original_dir.rename(moved_dir)
                original_dir.mkdir(mode=0o700)
            return descriptor

        with mock.patch.object(materialize_module.os, "open", side_effect=swap_ancestor):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_OUTPUT_PATH"):
                materialize(changed, workspace_root=self.root, now=self.now)

    def test_hard_link_inputs_refs_and_persisted_files_fail_closed(self):
        input_path = self.root / ".job-runtime/hardlink-input.json"
        input_path.write_text(json.dumps(self.value)); input_path.chmod(0o600)
        input_alias = self.root / ".job-runtime/hardlink-input-alias.json"
        os.link(input_path, input_alias)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_INPUT_FILE"):
            materialize_module._load_input(input_alias, workspace_root=self.root)

        runtime_path = self.root / "runtime/python"
        runtime_alias = self.root / "runtime/python-alias"
        os.link(runtime_path, runtime_alias)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_FILE_REF_LINKED"):
            materialize(self.value, workspace_root=self.root, now=self.now)
        runtime_alias.unlink()

        result = materialize(self.value, workspace_root=self.root, now=self.now)
        output = self.root / self.value["output_directory"]
        head_alias = self.root / ".job-runtime/head-alias.json"
        os.link(output / "materialization-manifest.json", head_alias)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_OUTPUT_CONFLICT"):
            materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertTrue(result["manifest"]["path"])

    def test_output_root_cannot_overlap_host_mutable_roots(self):
        mutations = []
        exact = deepcopy(self.value)
        exact["output_directory"] = exact["hosts"][0]["execution"]["artifact_root"]
        mutations.append(exact)
        parent = deepcopy(self.value)
        parent["output_directory"] = ".research-sources/runs/codex"
        mutations.append(parent)
        child = deepcopy(self.value)
        child["hosts"][0]["execution"]["artifact_root"] = (
            ".job-runtime/materialized-hosts/artifacts")
        child["hosts"][0]["execution"]["cache_root"] = (
            ".job-runtime/materialized-hosts/cache")
        mutations.append(child)
        for index, changed in enumerate(mutations):
            with self.subTest(index=index), self.assertRaisesRegex(
                    MaterializeHostError, "HOST_MATERIALIZE_OUTPUT_ROOT_OVERLAP"):
                materialize(changed, workspace_root=self.root, now=self.now)

    def test_lock_acquisition_is_bounded_and_typed_busy(self):
        output = self.root / self.value["output_directory"]
        output.mkdir(mode=0o700)
        lock = output / ".materialize.lock"
        first = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        second = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        self.addCleanup(os.close, second)
        self.addCleanup(os.close, first)
        materialize_module._acquire_lock(first, timeout_seconds=0)
        self.addCleanup(materialize_module.fcntl.flock,
                        first, materialize_module.fcntl.LOCK_UN)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_LOCK_BUSY"):
            materialize_module._acquire_lock(second, timeout_seconds=0)

    def test_post_head_fsync_failure_returns_unknown_write_fence(self):
        original_link = materialize_module.os.link
        original_fsync = materialize_module.os.fsync
        state = {"head_linked": False, "failed": False}

        def observed_link(source, destination, **kwargs):
            result = original_link(source, destination, **kwargs)
            if destination == "materialization-manifest.json":
                state["head_linked"] = True
            return result

        def fail_after_head(descriptor):
            if state["head_linked"] and not state["failed"]:
                state["failed"] = True
                raise OSError("synthetic post-publication fsync failure")
            return original_fsync(descriptor)

        with mock.patch.object(materialize_module.os, "link", side_effect=observed_link),                 mock.patch.object(materialize_module.os, "fsync", side_effect=fail_after_head):
            result = materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertEqual(result["status"], "unknown_write_outcome")
        self.assertEqual(result["code"], "HOST_MATERIALIZE_WRITE_OUTCOME_UNKNOWN")
        self.assertFalse(result["retry_permitted"])
        self.assertTrue(result["reconcile_before_retry"])
        self.assertEqual(set(result["unknown_outcome_fence"]), {
            "generation", "generation_sha256", "manifest", "manifest_sha256"})

    def test_invalid_host_scalar_fails_without_dict_key_exception(self):
        for invalid in ([], {}, 1, None):
            changed = deepcopy(self.value)
            changed["hosts"][0]["host"] = invalid
            with self.subTest(invalid=repr(invalid)), self.assertRaisesRegex(
                    MaterializeHostError, "HOST_MATERIALIZE_HOSTS_INVALID"):
                materialize(changed, workspace_root=self.root, now=self.now)

    def test_credential_profile_ref_rejects_auth_paths(self):
        for profile_ref in (
                "auth.json", "profiles/oauth/credentials.json",
                "backup-credential/store.json", "backup-auth.json",
                "backup-oauth.json", "my-credentials.json", "env", "auth",
                "authentication", "oauth", "oauth2", "credential",
                "credentials", "secret", "secrets"):
            changed = deepcopy(self.value)
            changed["hosts"][0]["credential"]["profile_ref"] = profile_ref
            changed["hosts"][0]["observation"]["profile_ref"] = profile_ref
            with self.subTest(profile_ref=profile_ref), self.assertRaisesRegex(
                    MaterializeHostError, "HOST_MATERIALIZE_SECRET_REJECTED"):
                materialize(changed, workspace_root=self.root, now=self.now)

    def test_ordinary_dotted_profile_ref_remains_identifier(self):
        changed = deepcopy(self.value)
        changed["hosts"][0]["credential"]["profile_ref"] = "backup.auth.profile"
        changed["hosts"][0]["observation"]["profile_ref"] = "backup.auth.profile"
        result = materialize(changed, workspace_root=self.root, now=self.now)
        self.assertTrue(result["hosts"]["codex"]["ready_for_live"])

    def test_json_decode_recursion_is_typed_input_failure(self):
        input_path = self.root / ".job-runtime/recursive-input.json"
        input_path.write_text(json.dumps(self.value)); input_path.chmod(0o600)
        with mock.patch.object(materialize_module.json, "loads",
                               side_effect=RecursionError):
            with self.assertRaisesRegex(MaterializeHostError,
                                        "HOST_MATERIALIZE_INPUT_FILE"):
                materialize_module._load_input(input_path, workspace_root=self.root)

    def test_changed_observation_requires_distinct_empty_output_and_runtime_roots(self):
        materialize(self.value, workspace_root=self.root, now=self.now)
        changed = deepcopy(self.value)
        changed["hosts"][0]["observation"]["source"] = "synthetic_fixture"
        changed["hosts"][0]["observation"]["live_acceptance_eligible"] = False
        for host_row in changed["hosts"]:
            host = host_row["host"]
            host_row["execution"]["artifact_root"] = (
                f".research-sources/runs/{host}/changed/artifacts")
            host_row["execution"]["cache_root"] = (
                f".research-sources/runs/{host}/changed/cache")
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_OUTPUT_CONFLICT"):
            materialize(changed, workspace_root=self.root, now=self.now)
        changed["output_directory"] = ".job-runtime/materialized-hosts-changed"
        result = materialize(changed, workspace_root=self.root, now=self.now)
        self.assertFalse(result["hosts"]["codex"]["ready_for_live"])

    def test_lock_symlink_fails_with_stable_error_before_publication(self):
        output = self.root / self.value["output_directory"]
        output.mkdir(mode=0o700)
        outside = self.root / "outside-lock"; outside.write_text("lock")
        outside.chmod(0o600)
        (output / ".materialize.lock").symlink_to(outside)
        with self.assertRaisesRegex(MaterializeHostError,
                                    "HOST_MATERIALIZE_LOCK_INVALID"):
            materialize(self.value, workspace_root=self.root, now=self.now)
        self.assertFalse((output / "materialization-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
