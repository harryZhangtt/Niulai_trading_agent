"""Trace-grader checks; these are not model persistence evidence."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('persistence_probe', Path(__file__).with_name('run.py'))
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def event(command, output='', exit_code=0):
    return {'method': 'item/completed', 'params': {'item': {
        'type': 'commandExecution', 'command': command, 'aggregatedOutput': output,
        'exitCode': exit_code, 'status': 'completed'}}}


class GradingTests(unittest.TestCase):
    def setUp(self):
        probe.EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=probe.EVIDENCE, prefix='grader-')
        self.bundle = Path(self.temp.name) / 'harry-ui-skill-set'
        guide = self.bundle / 'experts/impeccable/GUIDE.md'
        guide.parent.mkdir(parents=True)
        self.body = 'Unique guide content with a meaningful long line that must actually be returned to the model.'
        guide.write_text(self.body)
        (self.bundle / 'manifest.json').write_text('{"fixture":true}')
        self.patch = patch.object(probe, 'BUNDLE', self.bundle)
        self.patch.start()
        self.case = {'id': 'later-ui', 'expect': 'positive', 'expert': 'impeccable'}

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def route(self, code=0):
        return event("python3 -B '" + str(self.bundle / 'scripts/resolve.py') + "' --decision hardening",
                     '{"status":"UI_ROUTE_OK","selected":[{"skill":"impeccable"}]}', code)

    def test_final_claims_do_not_count(self):
        claim = {'method': 'item/completed', 'params': {'item': {
            'type': 'agentMessage', 'text': 'UI_ROUTE_OK read guide and changed artifact'}}}
        result = probe.grade(self.case, [claim], None, 'new', set())
        self.assertFalse(result['passed'])

    def test_success_requires_route_guide_and_effect(self):
        read = event('cat ' + str(self.bundle / 'experts/impeccable/GUIDE.md'), self.body)
        self.assertTrue(probe.grade(self.case, [self.route(), read], 'old', 'new', set())['passed'])
        self.assertFalse(probe.grade(self.case, [self.route(), read], 'old', 'old', set())['passed'])
        self.assertFalse(probe.grade(self.case, [self.route(1), read], 'old', 'new', set())['passed'])

    def test_reuse_before_compaction_and_lost_context(self):
        self.assertTrue(probe.grade(self.case, [self.route()], 'old', 'new', {'impeccable'})['passed'])
        self.assertFalse(probe.grade(self.case, [self.route()], 'old', 'new', set())['passed'])

    def test_negative_cases_reject_bundle_activity(self):
        case = {'id': 'backend', 'expect': 'negative'}
        self.assertTrue(probe.grade(case, [], None, 'new', set())['passed'])
        self.assertFalse(probe.grade(case, [self.route()], None, 'new', set())['passed'])

    def test_successful_silent_command_has_null_output(self):
        silent = event('python3 create_artifact.py', None)
        self.assertTrue(probe.grade({'id': 'backend', 'expect': 'negative'}, [silent], None, 'new', set())['passed'])

    def test_later_turn_rejects_repeated_activation(self):
        activate = event('python3 scripts/activate.py', 'HARRY_UI_SESSION_ENABLED')
        self.assertFalse(probe.grade(self.case, [self.route(), activate], 'old', 'new', {'impeccable'})['passed'])

    def test_same_upstream_text_from_workspace_is_not_bundle_read(self):
        canonical = event('cat /workspace/ui/skills/impeccable/SKILL.md', self.body)
        self.assertTrue(probe.grade({'id': 'fresh', 'expect': 'negative'}, [canonical], None, 'new', set())['passed'])

    def test_cancel_stops_before_new_rpc_is_sent(self):
        rpc = probe.RPC.__new__(probe.RPC)
        rpc.cancel_event = threading.Event()
        rpc.cancel_event.set()
        with self.assertRaisesRegex(RuntimeError, 'CANCELLED_BEFORE_RPC_SEND'):
            rpc.send({'method': 'turn/start'})

    def test_distinguishes_persistence_from_exact_route_conformance(self):
        read = event('cat ' + str(self.bundle / 'experts/impeccable/GUIDE.md'), self.body)
        case = {'id': 'layout', 'expect': 'positive', 'expert': 'ui-ux-pro-max'}
        result = probe.grade(case, [self.route(), read], 'old', 'new', set())
        self.assertTrue(result['persistence_passed'])
        self.assertFalse(result['passed'])

    def test_prospective_allowed_route_retains_preferred_score(self):
        read = event('cat ' + str(self.bundle / 'experts/impeccable/GUIDE.md'), self.body)
        case = {'id': 'layout', 'expect': 'positive', 'expert': 'ui-ux-pro-max',
                'allowed_experts': ['ui-ux-pro-max', 'impeccable']}
        result = probe.grade(case, [self.route(), read], 'old', 'new', set())
        self.assertTrue(result['passed'])
        self.assertFalse(result['preferred_expert_selected'])

    def restore(self, status='HARRY_UI_SESSION_ACTIVE', action='restore'):
        return event('python3 -B ' + str(self.bundle / 'scripts/session.py') + ' ' + action,
                     json.dumps({'status': status}))

    def test_actual_restore_status_and_order_are_required(self):
        case = {'session_check': 'active'}
        self.assertTrue(probe.session_trace_postcondition(case, [self.restore(), self.route()])['passed'])
        self.assertFalse(probe.session_trace_postcondition(case, [self.route(), self.restore()])['passed'])
        self.assertFalse(probe.session_trace_postcondition(case, [self.restore('HARRY_UI_SESSION_INACTIVE'), self.route()])['passed'])
        self.assertFalse(probe.session_trace_postcondition({'session_check':'none'}, [self.restore()])['passed'])

    def test_disable_and_inactive_fresh_scope(self):
        disabled = self.restore('HARRY_UI_SESSION_DISABLED', 'disable')
        self.assertTrue(probe.session_trace_postcondition({'session_check':'disable'}, [disabled])['passed'])
        self.assertTrue(probe.session_trace_postcondition({'session_check':'inactive_optional'}, [])['passed'])
        self.assertFalse(probe.session_trace_postcondition({'session_check':'inactive_optional'}, [self.restore()])['passed'])

    def test_v2_required_disabled_restore_remains_strict(self):
        result = probe.session_trace_postcondition({'session_check':'disabled'}, [])
        self.assertFalse(result['passed'])
        self.assertFalse(result['disabled_receipt_consulted'])

    def test_v3_known_disabled_allows_no_helper_without_claiming_consult(self):
        claim = {'method':'item/completed', 'params':{'item':{
            'type':'agentMessage','text':'I restored HARRY_UI_SESSION_DISABLED from the receipt.'}}}
        result = probe.session_trace_postcondition({'session_check':'disabled_optional'}, [claim])
        self.assertTrue(result['passed'])
        self.assertFalse(result['disabled_receipt_consulted'])

    def test_v3_optional_disabled_helper_must_succeed_and_report_disabled(self):
        case = {'session_check':'disabled_optional'}
        valid = probe.session_trace_postcondition(case, [self.restore('HARRY_UI_SESSION_DISABLED')])
        self.assertTrue(valid['passed'])
        self.assertTrue(valid['disabled_receipt_consulted'])
        self.assertFalse(probe.session_trace_postcondition(case, [self.restore()])['passed'])
        failed = self.restore('HARRY_UI_SESSION_DISABLED');failed['params']['item']['exitCode']=1
        self.assertFalse(probe.session_trace_postcondition(case, [failed])['passed'])
        self.assertFalse(probe.session_trace_postcondition(case, [self.restore('HARRY_UI_SESSION_DISABLED','disable')])['passed'])
        read = event('cat ' + str(self.bundle/'scripts/session.py'), 'HARRY_UI_SESSION_DISABLED')
        self.assertFalse(probe.session_trace_postcondition(case, [read])['passed'])

    def test_v3_preserves_frozen_prompts_active_contract_and_v2_history(self):
        directory = Path(__file__).parent
        v2_path = directory/'protocol-v2.json'
        self.assertEqual(probe.sha(v2_path), 'faddd29f08503552a56ede48787c97a475e44b0ee73391e73ed12e8fe966a147')
        v2 = json.loads(v2_path.read_text())
        v3 = json.loads((directory/'protocol-v3.json').read_text())
        self.assertEqual(len(v2['cases']), len(v3['cases']))
        for original, prospective in zip(v2['cases'], v3['cases']):
            expected = dict(original)
            if original['id']=='unnamed_disabled_after_compaction':
                expected['session_check']='disabled_optional'
            self.assertEqual(expected, prospective)
            if prospective.get('expect')=='positive' and not prospective.get('attach_skill'):
                self.assertEqual(prospective['session_check'],'active')
                for reminder in ('harry','session.py','resolve.py'):
                    self.assertNotIn(reminder,prospective['prompt'].lower())

    def create_receipt(self, thread='native-thread-1', project=None, state='enabled'):
        project = project or Path(self.temp.name)
        key = hashlib.sha256(('harry-ui-thread-v1:' + thread).encode()).hexdigest()
        path = project / '.ui-skill-runtime/harry-ui-sessions' / (key + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {'schema_version':1, 'thread_key':key,
                'project_key':hashlib.sha256(str(project).encode()).hexdigest(), 'state':state,
                'bundle_fingerprint':probe.sha(self.bundle/'manifest.json'),
                'created_at':'2026-11-02T00:00:00+00:00', 'updated_at':'2026-11-02T00:00:00+00:00'}
        path.write_text(json.dumps(data)+'\n');path.chmod(0o600)
        return path

    def test_direct_receipt_scope_fingerprint_and_private_mode(self):
        project = Path(self.temp.name)
        path = self.create_receipt(project=project)
        self.assertTrue(probe.receipt_postcondition(project,'native-thread-1','enabled')[0]['passed'])
        self.assertFalse(probe.receipt_postcondition(project,'native-thread-1','disabled')[0]['passed'])
        self.assertTrue(probe.receipt_postcondition(project,'fresh-thread','absent')[0]['passed'])
        path.chmod(0o644)
        self.assertFalse(probe.receipt_postcondition(project,'native-thread-1','enabled')[0]['passed'])
        path.chmod(0o600)
        data=json.loads(path.read_text());data['project_key']='0'*64;path.write_text(json.dumps(data))
        self.assertFalse(probe.receipt_postcondition(project,'native-thread-1','enabled')[0]['passed'])


if __name__ == '__main__':
    unittest.main()
