import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from investment.research.audit import Audit
from investment.research.execution import run
from investment.research.run_pilot import configuration, execute
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save


class AuditTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.audit = Audit(self.out / 'audit')
        self.execution_id = str(uuid.uuid4())
        self.config = configuration()

    def start(self):
        return self.audit.start(self.execution_id, output_directory=self.out,
            config_ref=save(self.out, self.config), query='Explicit historical earnings regression')

    def test_lookup_by_id_and_duplicate_or_unsafe_ids(self):
        ref = self.start()
        self.assertEqual(self.audit.lookup(self.execution_id)['audit_ref'], ref)
        self.assertEqual(self.audit.list()[0]['pipeline_id'], 'earnings_revenue_query')
        with self.assertRaisesRegex(SourceError, 'AUDIT_EXECUTION_EXISTS'): self.start()
        with self.assertRaisesRegex(SourceError, 'AUDIT_EXECUTION_ID_INVALID'): self.audit.lookup('../outside')

    def test_report_binding_and_immutable_history(self):
        first = self.start()
        report = {'run_id': self.execution_id, 'input_manifest': {'config_ref': save(self.out, self.config)}}
        pointer = {'status': 'blocked', 'report_ref': save(self.out, report)}
        next_ref = self.audit.record(self.execution_id, pointer)
        self.assertEqual(read(next_ref)['previous_ref'], first)
        self.assertEqual(read(first)['status'], 'preparing')
        report['run_id'] = str(uuid.uuid4()); pointer['report_ref'] = save(self.out, report)
        with self.assertRaisesRegex(SourceError, 'AUDIT_REPORT_ID_MISMATCH'):
            self.audit.record(self.execution_id, pointer)

    def test_external_configuration_and_run_identity_contract(self):
        changed = dict(self.config, pipeline_version='0.2.1')
        path = self.out / 'recipe.json'; path.write_text(json.dumps(changed))
        self.assertEqual(configuration(path=path), changed)
        with self.assertRaisesRegex(ValueError, 'PIPELINE_EXECUTION_ID_INVALID'):
            run(self.config, {}, output_directory=self.out, execution_id='invalid')

    def test_optional_audit_and_render_failures_do_not_change_domain_result(self):
        # Stub only source/domain boundaries: the wrapper's status and exception
        # handling are under test; real worker/model acceptance is separate.
        from investment.research.pilot import Pilot
        request = {'source_ref': save(self.out, {'explicit': 'fixture'})}
        class StubPilot:
            def __init__(self):
                self.request = request
                self.critical_guard = lambda *args: None
                self.finalizer = lambda *args: None
        def completed(config, request, **kwargs):
            return {'schema_version': 1, 'run_id': kwargs['execution_id'], 'pipeline_id': config['pipeline_id'],
                'pipeline_version': config['pipeline_version'], 'status': 'completed', 'reason': None,
                'phases': {}, 'events': [], 'counts': {'actions': 0, 'model_turns': 0},
                'input_manifest': {'config_ref': save(self.out, config)}, 'final_ref': None}
        with patch('investment.research.pilot.prepare', return_value=StubPilot()), \
             patch('investment.research.run_pilot.run', side_effect=completed), \
             patch('investment.research.audit.Audit', side_effect=OSError('private diagnostic must not leak')), \
             patch('investment.research.run_pilot.render', side_effect=OSError('render failed')):
            result = execute(self.out, model_callback=lambda *args: None)
        self.assertEqual(result['status'], 'completed')
        self.assertIsNone(result['audit_ref']); self.assertIsNone(result['html_ref'])
        self.assertEqual([x['operation'] for x in result['observability_diagnostics']], ['audit.open', 'replay.render'])
        self.assertNotIn('private diagnostic', json.dumps(result))


if __name__ == '__main__': unittest.main()
