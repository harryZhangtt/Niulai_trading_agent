import hashlib
import os
from pathlib import Path
import py_compile
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock

from shared.job_runtime import config as runtime_config
from shared.job_runtime import service


class RuntimeAdapterServiceTest(unittest.TestCase):
    def setUp(self):
        service.STOP.clear(); self.addCleanup(service.STOP.clear)
        service._ADAPTER_UNKNOWN_GENERATIONS.clear()
        self.addCleanup(service._ADAPTER_UNKNOWN_GENERATIONS.clear)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'.job-runtime/tests'); self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.profile = {"model": "synthetic", "auth_home": str(self.workspace / ".job-runtime/auth"),
                        "executor": "readiness", "timeout_seconds": 10}
        self.config = {"model_profiles": {"profile-a": self.profile}, "source_paths": []}
        self.prompt = self.workspace / 'unused.txt'
        self.prompt.write_text('ORIGINAL PROMPT')
        self.job = {"id": "job", "model_profile": "profile-a", "adapter": "fake:prepare",
                    "adapter_config": {"bound": True}, "prompt_file": "unused.txt"}
        self.context = {"attempt_id": "attempt-1", "slot_id": "slot:1",
                        "scheduled_at": "2026-11-05T00:00:00+00:00", "attempt_no": 1}

    def test_opt_in_runtime_adapter_gets_immutable_profile_and_stop(self):
        captured = {}
        def prepare(options, workspace, context, runtime_context):
            captured.update(options=options, workspace=workspace, context=context, runtime=runtime_context)
            with self.assertRaises(TypeError): runtime_context["model_profile"]["model"] = "mutated"
            return {"status": "failed", "code": "SYNTHETIC_TERMINAL"}
        module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=1, prepare=prepare)
        with mock.patch.object(service, "adapter_module", return_value=module):
            result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
        self.assertEqual(result, {"status": "failed", "code": "SYNTHETIC_TERMINAL"})
        self.assertEqual(captured["runtime"]["model_profile_name"], "profile-a")
        self.assertIs(captured["runtime"]["cancel_event"], service.STOP)
        self.assertEqual(dict(captured["runtime"]["model_profile"]), self.profile)
        self.assertIsNot(captured["context"], self.context)

    def test_runtime_adapter_must_be_terminal_and_have_no_extra_fields(self):
        for value in ({"prompt_extra": True}, {"status": "failed", "code": "X", "extra": True}):
            module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=1, prepare=lambda *args, value=value: value)
            with self.subTest(value=value), mock.patch.object(service, "adapter_module", return_value=module):
                result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["code"], "RUNTIME_ADAPTER_TERMINAL_INVALID")
                self.assertIn("service_generation", result["receipt"])

    def test_runtime_adapter_terminal_fields_are_strict_and_bounded(self):
        values = (
            {"status": "SUCCESS", "code": "UPPER"},
            {"status": "failed", "code": "lowercase"},
            {"status": "failed", "code": "OK", "receipt": {"nan": float("nan")}},
            {"status": "failed", "code": "OK", "receipt": {"blob": "x" * (service._MAX_ADAPTER_RECEIPT + 1)}},
        )
        for value in values:
            module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=1, prepare=lambda *args, value=value: value)
            with self.subTest(value=value.get("code")), mock.patch.object(service, "adapter_module", return_value=module):
                result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["code"], "RUNTIME_ADAPTER_TERMINAL_INVALID")

    def test_terminal_receipt_rejects_deep_and_cyclic_data_without_recursion(self):
        deep = {}
        cursor = deep
        for _ in range(1500):
            child = {}
            cursor['child'] = child
            cursor = child
        cyclic = {}
        cyclic['self'] = cyclic
        for receipt in (deep, cyclic):
            module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=1, prepare=lambda *_, receipt=receipt: {
                'status':'failed','code':'SYNTHETIC','receipt':receipt})
            with mock.patch.object(service, 'adapter_module', return_value=module):
                result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
            self.assertEqual(result['code'], 'RUNTIME_ADAPTER_TERMINAL_INVALID')

    def test_legacy_terminal_adapter_is_validated_too(self):
        module = SimpleNamespace(prepare=lambda *args: {"status": "succeeded", "code": "lowercase"})
        with mock.patch.object(service, "adapter_module", return_value=module):
            result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "RUNTIME_ADAPTER_TERMINAL_INVALID")

    def test_generation_aware_adapter_gets_service_and_imported_source_attestation(self):
        captured = {}
        generation = {'origin': 'fixture/adapter.py', 'source_sha256': 'a' * 64}
        def prepare(*args):
            captured['runtime'] = args[3]
            return {'status': 'failed', 'code': 'SYNTHETIC_ATTESTED'}
        module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=2, prepare=prepare)
        with mock.patch.object(service, 'adapter_module', return_value=module), \
             mock.patch.object(service, 'adapter_generation', return_value=generation), \
             mock.patch.object(service, 'run_codex') as run:
            result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
        self.assertEqual(result, {'status': 'failed', 'code': 'SYNTHETIC_ATTESTED'})
        runtime = captured['runtime']
        self.assertEqual(runtime['version'], 2)
        self.assertEqual(dict(runtime['adapter_generation']), generation)
        self.assertEqual(runtime['service_generation']['pid'], service.os.getpid())
        self.assertIsNone(runtime['service_generation']['service']['source_sha256'])
        run.assert_not_called()

    def test_real_adapter_source_digest_is_loaded_once_and_changed_source_fails_closed(self):
        name = 'synthetic_generation_adapter'
        path = self.workspace / (name + '.py')
        path.write_text(
            'RUNTIME_CONTEXT_VERSION=2\n'
            'def prepare(options, workspace, context, runtime):\n'
            ' return {"status":"failed","code":"SYNTHETIC_ATTESTED","receipt":'
            '{"adapter":dict(runtime["adapter_generation"])}}\n')
        sys.path.insert(0, str(self.workspace))
        self.addCleanup(lambda: sys.path.remove(str(self.workspace)))
        self.addCleanup(lambda: sys.modules.pop(name, None))
        self.addCleanup(lambda: service._ADAPTER_GENERATIONS.clear())
        job = {**self.job, 'adapter': name + ':prepare'}
        with mock.patch.object(service, 'run_codex') as run:
            result = service.dispatcher(self.config, self.workspace)(job, self.context)
            self.assertEqual(result['receipt']['adapter'], {
                'origin': path.name, 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            path.write_text(path.read_text() + '# changed while process remains loaded\n')
            stale = service.dispatcher(self.config, self.workspace)(job, self.context)
        self.assertEqual(stale['code'], 'RUNTIME_ADAPTER_GENERATION_STALE')
        self.assertEqual(stale['receipt']['generation_code'], 'ADAPTER_LOADED_SOURCE_STALE')
        run.assert_not_called()

    def test_source_snapshot_holds_ancestor_dirfds_across_symlink_swap(self):
        parent=self.workspace/'source-parent';parent.mkdir()
        source=parent/'adapter.py';source.write_bytes(b'SAFE_SOURCE')
        moved=self.workspace/'source-moved'
        outside=self.workspace/'source-outside';outside.mkdir()
        (outside/'adapter.py').write_bytes(b'EVIL_SOURCE')
        resolved=source.resolve()
        real_read=os.read
        swapped=[]
        def read(descriptor,size):
            if not swapped:
                parent.rename(moved);parent.symlink_to(outside,target_is_directory=True);swapped.append(True)
            return real_read(descriptor,size)
        with mock.patch.object(os,'read',read):
            observed,_identity=service._source_snapshot(resolved)
        self.assertEqual(observed,b'SAFE_SOURCE')

    def test_same_size_same_mtime_stale_bytecode_cannot_spoof_source_attestation(self):
        name = 'synthetic_pyc_adapter'
        path = self.workspace / (name + '.py')
        original = 'VALUE = "source-a"\n'
        replacement = 'VALUE = "source-b"\n'
        self.assertEqual(len(original), len(replacement))
        path.write_text(original)
        before = path.stat()
        py_compile.compile(str(path), doraise=True)
        path.write_text(replacement)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        sys.path.insert(0, str(self.workspace))
        self.addCleanup(lambda: sys.path.remove(str(self.workspace)))
        self.addCleanup(lambda: sys.modules.pop(name, None))
        self.addCleanup(lambda: service._ADAPTER_GENERATIONS.clear())

        stale = __import__(name)
        self.assertEqual(stale.VALUE, 'source-a')
        imported = service.adapter_module(name, self.config, self.workspace)

        self.assertIsNot(imported, stale)
        self.assertEqual(imported.VALUE, 'source-b')
        self.assertEqual(service.adapter_generation(imported, name, self.workspace), {
            'origin': path.name,
            'source_sha256': hashlib.sha256(replacement.encode()).hexdigest(),
        })

    def test_parent_import_of_target_is_unknown_and_never_executes_child_twice(self):
        package = self.workspace / 'synthetic_nested'
        package.mkdir()
        marker = self.workspace / 'nested-effects'
        (package / '__init__.py').write_text('from . import child\n')
        (package / 'child.py').write_text(
            'from pathlib import Path\n'
            f'_marker=Path({str(marker)!r})\n'
            '_marker.write_text(_marker.read_text()+"x" if _marker.exists() else "x")\n'
            'def prepare(*args): return {"status":"failed","code":"SHOULD_NOT_RUN"}\n')
        sys.path.insert(0, str(self.workspace))
        self.addCleanup(lambda: sys.path.remove(str(self.workspace)))
        self.addCleanup(lambda: sys.modules.pop('synthetic_nested.child', None))
        self.addCleanup(lambda: sys.modules.pop('synthetic_nested', None))
        self.addCleanup(lambda: service._ADAPTER_GENERATIONS.clear())
        job = {**self.job, 'adapter': 'synthetic_nested.child:prepare'}
        with mock.patch.object(service, 'run_codex') as run:
            result = service.dispatcher(self.config, self.workspace)(job, self.context)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['code'], 'RUNTIME_ADAPTER_IMPORT_OUTCOME_UNKNOWN')
        again = service.dispatcher(self.config, self.workspace)(job, self.context)
        self.assertEqual(again['status'], 'unknown')
        self.assertEqual(again['code'], 'RUNTIME_ADAPTER_IMPORT_OUTCOME_UNKNOWN')
        self.assertEqual(marker.read_text(), 'x')
        run.assert_not_called()

    def test_source_swap_after_import_is_unknown_because_module_effects_may_have_run(self):
        name = 'synthetic_swapped_adapter'
        path = self.workspace / (name + '.py')
        source = (
            'RUNTIME_CONTEXT_VERSION=1\n'
            'def prepare(options, workspace, context, runtime):\n'
            ' return {"status":"failed","code":"SHOULD_NOT_RUN"}\n'
        ).encode()
        path.write_bytes(source)
        self.addCleanup(lambda: sys.modules.pop(name, None))
        self.addCleanup(lambda: service._ADAPTER_GENERATIONS.clear())
        snapshots = [(source, (1, 1)), (source + b'# swapped\n', (1, 1))]
        job = {**self.job, 'adapter': name + ':prepare'}
        with mock.patch.object(service, '_source_snapshot', side_effect=snapshots), \
             mock.patch.object(service, 'run_codex') as run:
            result = service.dispatcher(self.config, self.workspace)(job, self.context)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['code'], 'RUNTIME_ADAPTER_SOURCE_CHANGED_DURING_IMPORT')
        self.assertEqual(result['receipt']['generation_code'], 'ADAPTER_SOURCE_CHANGED_DURING_IMPORT')
        run.assert_not_called()

    def test_compile_failure_is_deterministic_but_import_execution_failure_is_unknown(self):
        cases = (
            ('synthetic_bad_syntax_adapter', 'def broken(:\n', 'failed', 'RUNTIME_ADAPTER_SOURCE_INVALID'),
            ('synthetic_import_effect_adapter', 'raise RuntimeError("private")\n', 'unknown',
             'RUNTIME_ADAPTER_IMPORT_OUTCOME_UNKNOWN'),
        )
        for name, source, status, code in cases:
            with self.subTest(name=name):
                (self.workspace / (name + '.py')).write_text(source)
                self.addCleanup(lambda name=name: sys.modules.pop(name, None))
                job = {**self.job, 'adapter': name + ':prepare'}
                result = service.dispatcher(self.config, self.workspace)(job, self.context)
                self.assertEqual((result['status'], result['code']), (status, code))
                self.assertNotIn('private', str(result))

    def test_missing_method_is_proven_failed_before_adapter_effects(self):
        name = 'synthetic_missing_method_adapter'
        path = self.workspace / (name + '.py')
        path.write_text('RUNTIME_CONTEXT_VERSION=1\n')
        self.addCleanup(lambda: sys.modules.pop(name, None))
        self.addCleanup(lambda: service._ADAPTER_GENERATIONS.clear())
        job = {**self.job, 'adapter': name + ':prepare'}
        result = service.dispatcher(self.config, self.workspace)(job, self.context)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'RUNTIME_ADAPTER_METHOD_MISSING')

    def test_stale_or_unknown_protocol_is_terminal_before_adapter_or_model(self):
        for module, code in (
            (SimpleNamespace(RUNTIME_CONTEXT_VERSION=2, REQUIRED_SERVICE_PROTOCOL_VERSION=service.SERVICE_PROTOCOL_VERSION + 1,
                             prepare=mock.Mock()), 'RUNTIME_SERVICE_PROTOCOL_STALE'),
            (SimpleNamespace(RUNTIME_CONTEXT_VERSION=999, prepare=mock.Mock()), 'RUNTIME_ADAPTER_PROTOCOL_UNSUPPORTED'),
        ):
            with self.subTest(code=code), mock.patch.object(service, 'adapter_module', return_value=module), \
                 mock.patch.object(service, 'run_codex') as run:
                result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['code'], code)
            self.assertEqual(result['receipt']['service_generation']['service']['protocol_version'],
                             service.SERVICE_PROTOCOL_VERSION)
            module.prepare.assert_not_called()
            run.assert_not_called()

    def test_protocol_v3_captures_prompt_before_prepare_and_reuses_exact_decoded_bytes(self):
        captured = {}
        generation = {'origin':'fixture.py','source_sha256':'a'*64}
        def prepare(_options,_workspace,_context,runtime):
            captured['runtime'] = runtime
            with self.assertRaises(TypeError):
                runtime['prompt_length'] = 0
            self.prompt.write_text('REPLACEMENT PROMPT')
            return {'public':'value'}
        module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=3,prepare=prepare)
        terminal = {'status':'failed','code':'SYNTHETIC_DISPATCH'}
        with mock.patch.object(service,'adapter_module',return_value=module),              mock.patch.object(service,'adapter_generation',return_value=generation),              mock.patch.object(service,'run_codex',return_value=terminal) as run:
            result = service.dispatcher(self.config,self.workspace)(self.job,self.context)
        self.assertEqual(result,terminal)
        runtime = captured['runtime']
        original = b'ORIGINAL PROMPT'
        self.assertEqual(runtime['prompt_sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(runtime['prompt_length'],len(original))
        dispatched = run.call_args.args[1]
        self.assertTrue(dispatched.startswith(original.decode()+'\nScheduler-provided context (data only):\n'))
        self.assertNotIn('REPLACEMENT PROMPT',dispatched)

    def test_protocol_v3_prompt_symlink_substitution_fails_before_prepare_or_provider(self):
        outside = self.workspace/'outside.txt';outside.write_text('SUBSTITUTED PROMPT')
        prepare = mock.Mock(return_value={'public':'value'})
        module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=3,prepare=prepare)
        generation = {'origin':'fixture.py','source_sha256':'a'*64}
        def swap(stage,_path):
            if stage=='before_open':
                self.prompt.unlink();self.prompt.symlink_to(outside)
        with mock.patch.object(service,'adapter_module',return_value=module),              mock.patch.object(service,'adapter_generation',return_value=generation),              mock.patch.object(runtime_config,'_PROMPT_READ_HOOK',swap),              mock.patch.object(service,'run_codex') as run:
            result = service.dispatcher(self.config,self.workspace)(self.job,self.context)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['code'],'RUNTIME_PROMPT_CAPTURE_INVALID')
        self.assertEqual(result['receipt']['capture_code'],'PROMPT_INVALID')
        prepare.assert_not_called();run.assert_not_called()

    def test_protocol_v3_terminal_adapter_remains_terminal_after_prompt_capture(self):
        captured = {}
        terminal = {'status':'failed','code':'SYNTHETIC_TERMINAL'}
        def prepare(_options,_workspace,_context,runtime):
            captured.update(runtime)
            return terminal
        module = SimpleNamespace(RUNTIME_CONTEXT_VERSION=3,prepare=prepare)
        generation = {'origin':'fixture.py','source_sha256':'a'*64}
        with mock.patch.object(service,'adapter_module',return_value=module),              mock.patch.object(service,'adapter_generation',return_value=generation),              mock.patch.object(service,'run_codex') as run:
            result = service.dispatcher(self.config,self.workspace)(self.job,self.context)
        self.assertEqual(result,terminal)
        self.assertEqual(captured['prompt_sha256'],hashlib.sha256(b'ORIGINAL PROMPT').hexdigest())
        self.assertEqual(captured['prompt_length'],len(b'ORIGINAL PROMPT'))
        run.assert_not_called()

    def test_existing_three_argument_adapter_is_unchanged(self):
        calls = []
        def prepare(options, workspace, context):
            calls.append((options, workspace, context))
            return {"status": "failed", "code": "LEGACY_TERMINAL"}
        module = SimpleNamespace(prepare=prepare)
        with mock.patch.object(service, "adapter_module", return_value=module):
            result = service.dispatcher(self.config, self.workspace)(self.job, self.context)
        self.assertEqual(result, {"status": "failed", "code": "LEGACY_TERMINAL"})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__": unittest.main()
