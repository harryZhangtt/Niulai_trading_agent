from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    CredentialReadinessReceipt,
    CredentialReadinessStatus,
    NON_CRYPTO_LIMITATION,
    OperationalEvidenceSource,
    OperationalTrustPolicy,
)
from tuning.evals.information_fetch.live_e2e.materialize_host import (
    INPUT_VERSION,
    materialize,
)


class HostBudgetMaterializerTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[3] / ".research-sources/test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (".job-runtime", ".research-sources", "runtime", "profiles"):
            (self.root / name).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.refs = {}
        for name in ("runtime/python", "profiles/codex.json", "profiles/claude.json"):
            path = self.root / name
            path.write_text("fixture:" + name)
            path.chmod(0o600)
            self.refs[name] = {
                "path": name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)

    def host(self, host):
        codex = host == "codex"
        adapter = AdapterId.CODEX_NATIVE_WEB if codex else AdapterId.CLAUDE_CODE_WEB
        backend = "native_tools.web__run" if codex else "claude_code.web"
        owner = f"{host}-owner"
        profile = f"{host}.profile"
        fingerprint = ("a" if codex else "b") * 64
        session = f"{host}-smoke-session"
        observation = CredentialReadinessReceipt(
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
            "runtime_identity": f"{host}.runtime.smoke",
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
                "trace_id": f"trace-{host}-smoke",
                "dispatch_namespace": f"dispatch-{host}-smoke",
                "artifact_root": f".research-sources/smoke/{host}/artifacts",
                "cache_root": f".research-sources/smoke/{host}/cache",
                "budget": {
                    "search_items": 1,
                    "open_items": 0,
                    "provider_items": 1,
                    "concurrency": 1,
                    "call_timeout_seconds": 60,
                    "run_timeout_seconds": 300,
                },
            },
            "observation": observation,
        }

    def test_public_materializer_round_trips_zero_open_smoke_budget(self):
        result = materialize({
            "schema_version": INPUT_VERSION,
            "output_directory": ".job-runtime/materialized-smoke",
            "mcp": "not_used",
            "hosts": [self.host("codex"), self.host("claude")],
        }, workspace_root=self.root, now=self.now)
        for host in ("codex", "claude"):
            ref = result["hosts"][host]["binding"]
            binding = json.loads((self.root / ref["path"]).read_text())
            self.assertEqual(binding["budget"], {
                "search_items": 1,
                "open_items": 0,
                "provider_items": 1,
                "concurrency": 1,
                "call_timeout_seconds": 60,
                "run_timeout_seconds": 300,
            })
            self.assertTrue(result["hosts"][host]["ready_for_live"])


if __name__ == "__main__":
    unittest.main()
