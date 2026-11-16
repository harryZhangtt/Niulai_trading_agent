"""Explicit provider-free experiments with a hash-bound inert Engine loader."""
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
import hashlib, importlib.util, sqlite3, sys
from .contracts import BINDING_FIELDS, BindingV1, EvidenceV1, binding_from_mapping, digest
from .fake_provider import DenyEffectRecorder, FakeTransport

_ENGINE_FILES = {
    "engine_schema": "f3f22ce1ec6531ad4d0e9cfdb7aa63b78b5a21ddee69fa74b6b60d713ad87e9b",
    "provider_contract": "9de31552df5b1474bf3b29e36ce07278264e71a19f05b45cc1c09213d6873333",
    "retry_policy": "ca152ed42518ead0adfe4318e6b3b53a9a31fa6f062db578091429f44b254f56",
    "prompt_custody": "bf553a519f646378529a510a9f0a7811bfeb409a39dc097e0086b59dd16bbd02",
    "engine": "42721bf751ebe50cc0720138bfb66509cababd2b873e41192ee50d9cf8df10be",
}
_PACKAGE = "_pfl_canonical_engine_v1"

def _execute_verified(raw: bytes, path: Path, module: ModuleType) -> None:
    code = compile(raw, str(path), "exec", dont_inherit=True)
    exec(code, module.__dict__)

def _load_engine() -> tuple:
    root = Path(__file__).parents[2]
    names = [_PACKAGE] + [_PACKAGE + "." + name for name in _ENGINE_FILES]
    if any(name in sys.modules for name in names):
        raise RuntimeError("PFL_ENGINE_NAMESPACE_OCCUPIED")
    package = ModuleType(_PACKAGE); package.__path__ = [str(root)]; sys.modules[_PACKAGE] = package
    loaded = {}
    try:
        for name in ("engine_schema", "provider_contract", "retry_policy", "prompt_custody", "engine"):
            path = root / (name + ".py"); raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != _ENGINE_FILES[name]:
                raise RuntimeError("PFL_CANONICAL_ENGINE_DRIFT")
            full = _PACKAGE + "." + name
            spec = importlib.util.spec_from_file_location(full, path)
            if spec is None or spec.loader is None: raise RuntimeError("PFL_ENGINE_LOAD_INVALID")
            module = importlib.util.module_from_spec(spec); sys.modules[full] = module; _execute_verified(raw, path, module); loaded[name] = module
            if Path(module.__file__).absolute() != path.absolute(): raise RuntimeError("PFL_ENGINE_ORIGIN_INVALID")
    except BaseException:
        for name in reversed(names): sys.modules.pop(name, None)
        raise
    def cleanup() -> None:
        for name in reversed(names): sys.modules.pop(name, None)
    return loaded["engine"].Engine, loaded, cleanup

def _binding_sha(binding: BindingV1) -> str:
    return digest({key: getattr(binding, key) for key in BINDING_FIELDS})

def _job(binding: BindingV1, due: datetime, modules: dict) -> dict:
    binding_sha = _binding_sha(binding)
    prompt = modules["prompt_custody"].PromptArtifactDescriptorV1(
        1, "pa1:sha256:%s:80" % binding.prompt_sha256, binding.prompt_sha256, 80,
        binding.source_sha256, "pfl-%s" % binding_sha[:16], "native_v1")
    provider = modules["provider_contract"]
    policy = modules["retry_policy"].RetryPolicyV2(1, 1, 1, deadline_seconds=60)
    return {"id": "pfl.%s.%s" % (binding.scenario, binding_sha), "enabled": True,
            "replay_safe": False, "schedule": {"kind": "once", "at": due.isoformat(), "grace_seconds": 60},
            "_provider": "claude_host", "_replay_contract": provider.ReplayContractV1(
                provider.ReplayEffect.NONE, (provider.Phase.CONNECTING,), "pfl/%s" % binding_sha),
            "_retry_policy": policy, "_prompt_artifact": prompt}

def run_provider_free_experiment(*, binding: BindingV1, workspace_root: Path, state_root: Path,
                                 now: datetime) -> EvidenceV1:
    if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
        raise ValueError("PFL_WORKSPACE_ROOT_INVALID")
    workspace = workspace_root.resolve(strict=True)
    expected_state = workspace / ".job-runtime" / "engine"
    if not isinstance(state_root, Path) or state_root.resolve(strict=False) != expected_state or state_root.exists():
        raise ValueError("PFL_STATE_ROOT_INVALID")
    if type(binding) is not BindingV1:
        raise ValueError("PFL_BINDING_TYPE_INVALID")
    binding = binding_from_mapping({key: getattr(binding, key) for key in BINDING_FIELDS})
    Engine, modules, cleanup_loader = _load_engine()
    try:
        due = now - timedelta(seconds=1)
        recorder = DenyEffectRecorder()
        transport = FakeTransport(binding.scenario, recorder)
        job = _job(binding, due, modules)
        provider = modules["provider_contract"]
        def dispatch(_job_value: dict, context: dict) -> Any:
            transport.mark_dispatch()
            if binding.scenario == "nominal":
                return provider.ProviderResultV1(provider.Provider.CLAUDE_HOST, context["operation_id"], provider.Phase.TERMINAL,
                    provider.Submission.DEFINITELY_SUBMITTED, provider.TerminalProof.VERIFIED, provider.ResultStatus.SUCCEEDED,
                    "PFL_FAKE_COMPLETED", receipt={"schema_version":1,"transport":"injected_fake","effect":"none"})
            return provider.ProviderResultV1(provider.Provider.CLAUDE_HOST, context["operation_id"], provider.Phase.STREAMING,
                provider.Submission.POSSIBLY_SUBMITTED, provider.TerminalProof.ABSENT, provider.ResultStatus.UNKNOWN,
                "PFL_FAKE_POST_ADMISSION_UNKNOWN", failure_kind=provider.FailureKind.PARTIAL_RESPONSE,
                receipt={"schema_version":1,"transport":"injected_fake","effect":"none"})
        retry = {"max_attempts":1,"backoff_seconds":1,"max_backoff_seconds":1}
        engine = Engine(state_root,[job],retry,dispatch,workspace_root=workspace,max_workers=1)
        engine.tick(now)
        dispatch_before_reconstruction = transport.dispatch_count
        reconstructed = Engine(state_root,[job],retry,dispatch,workspace_root=workspace,max_workers=1)
        reconstructed.tick(now+timedelta(seconds=5))
        with sqlite3.connect(state_root/"schedule.sqlite") as database:
            slot_count=database.execute("select count(*) from slots").fetchone()[0]
            attempt_count=database.execute("select count(*) from attempts").fetchone()[0]
            row=database.execute("select job_id,status,operation_id,binding_sha256 from slots").fetchone()
            attempt_status=database.execute("select status from attempts").fetchone()[0]
            provider_row=database.execute("select operation_id,prompt_binding_sha256 from provider_results").fetchone()
        binding_sha=_binding_sha(binding)
        expected="succeeded" if binding.scenario=="nominal" else "unknown"
        if row[0]!="pfl.%s.%s"%(binding.scenario,binding_sha) or row[1]!=expected or attempt_status!=expected or provider_row is None or row[2]!=provider_row[0] or row[3]!=provider_row[1]:
            raise ValueError("PFL_ENGINE_BINDING_INVALID")
        counts=recorder.snapshot()
        body={"schema_version":"provider-free-lifecycle-v1","scenario":binding.scenario,"binding_sha256":binding_sha,
              "engine_binding_sha256":binding_sha,"operation_binding_sha256":hashlib.sha256(row[2].encode()).hexdigest(),
              "prompt_binding_sha256":provider_row[1],"effect_evidence_kind":"deny_by_default_recorder",
              "dispatch_count":transport.dispatch_count,"dispatch_before_reconstruction":dispatch_before_reconstruction,
              "slot_count":slot_count,"attempt_count":attempt_count,"slot_status":row[1],"attempt_status":attempt_status,
              "reconstructed_dispatch_count":transport.dispatch_count,"replay_authorized":False,
              "provider_calls":counts["provider"],"network_calls":counts["network"],"process_calls":counts["process"],
              "host_calls":counts["host"],"email_calls":counts["email"],"business_effects":counts["business"],
              "enabled":False,"capability_open":False}
        return EvidenceV1(**body,evidence_sha256=digest(body))
    finally:
        cleanup_loader()
