import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT, SourceError, read as artifact
from shared.web_access.egolite import _execute, doctor, read
from shared.web_access.policy import Session, fingerprint, load_config, origin, validate_config


class CandidateTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.research-sources/web-access-test-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.config = load_config()

    def configured(self):
        cli = self.out / 'fake-ego'
        cli.write_text('#!' + sys.executable + '\nimport json,re,sys\n'
            's=sys.stdin.read()\ni=json.loads(re.search(r"const input = (.*);",s).group(1))\n'
            'print(json.dumps(dict(schema_version=1,nonce=i["nonce"],status="observed",observed_url=i["url"],'
            'snapshot="Observed public example",truncated=False,cleanup_verified=True)))\n')
        cli.chmod(0o700)
        self.config['egolite'].update(enabled=True, executable=str(cli), sha256=fingerprint(cli))
        return cli

    def decision(self):
        return Session(self.config).plan(operation='read', url='https://investor.nvidia.com/', interactive=True)

    def test_default_does_not_activate_browser(self):
        self.assertEqual(doctor(self.config)['code'], 'EGOLITE_NOT_CONFIGURED')
        self.assertEqual(self.decision()['route'], 'blocked')

    def test_native_discovery_and_static_source_first(self):
        session = Session(self.config)
        self.assertEqual(session.plan(operation='discover')['route'], 'native_search')
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/html/1')['route'], 'native_open')

    def test_native_circuit_breaker_and_chrome_comparison_route(self):
        session = Session(self.config)
        session.record_native('transport_error')
        session.record_native('success')
        self.assertEqual(session.plan(operation='discover')['route'], 'work_browser_discovery')
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/html/1', browser='chrome')['route'], 'chrome')

    def test_insufficient_source_escalates_without_claiming_search_failed(self):
        self.configured()
        session = Session(self.config)
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/html/1', native_outcome='insufficient_content')['route'], 'egolite')
        self.assertEqual(session.plan(operation='discover')['route'], 'native_search')

    def test_pdf_uses_explicit_pdf_route(self):
        session = Session(self.config)
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/paper.pdf')['route'], 'native_pdf_reader')
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/pdf/2106.09685v2')['route'], 'native_pdf_reader')
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/download', document_format='pdf')['route'], 'native_pdf_reader')
        session.record_native('transport_error')
        self.assertEqual(session.plan(operation='read', url='https://arxiv.org/paper.pdf')['route'], 'existing_pdf_adapter')

    def test_authentication_is_explicit(self):
        with self.assertRaises(SourceError):
            Session(self.config).plan(operation='read', url='https://arxiv.org/', authenticated=True)

    def test_url_and_exact_origin_controls(self):
        for url in ['http://arxiv.org/', 'file:///etc/passwd', 'https://user:pass@arxiv.org/',
                    'https://127.0.0.1/', 'https://localhost/', 'https://arxiv.org:444/',
                    'https://arxiv.org/?token=CANARY', 'https://arxiv.org/#secret', 'https://arxiv.org/\nfoo']:
            with self.subTest(url=url), self.assertRaises(SourceError): origin(url)
        for url in ['https://arxiv.org.evil.example/', 'https://other.arxiv.org/']:
            with self.assertRaises(SourceError): Session(self.config).plan(operation='read', url=url)

    def test_read_and_time_budgets(self):
        ticks = [0]
        session = Session(self.config, clock=lambda: ticks[0])
        for _ in range(self.config['limits']['max_reads']): session.plan(operation='read', url='https://arxiv.org/')
        with self.assertRaises(SourceError): session.plan(operation='read', url='https://arxiv.org/')
        ticks[0] = 301
        with self.assertRaises(SourceError): session.plan(operation='discover')

    def test_invalid_config_and_duplicate_json(self):
        self.config['limits']['timeout_seconds'] = True
        with self.assertRaises(SourceError): validate_config(self.config)
        path = self.out/'duplicate.json'; path.write_text('{"x":1,"x":2}')
        with self.assertRaises(SourceError): load_config(path)

    def test_real_child_protocol_receipt_and_snapshot_hash(self):
        self.configured()
        result = read(self.config, self.decision(), output_directory=self.out/'run')
        self.assertEqual(result['status'], 'observed')
        receipt = artifact(result['receipt_ref'])
        self.assertEqual(artifact(receipt['snapshot_ref'], json_value=False), b'Observed public example')
        self.assertEqual(receipt['access_level'], 'rendered_extract')
        self.assertIsNone(receipt['approval_events'])
        self.assertFalse(receipt['source_truth_verified'])
        self.assertEqual(artifact(receipt['intent_ref'])['operation_id'], receipt['operation_id'])

    def test_drift_is_blocked_before_spawn(self):
        cli = self.configured(); cli.write_text('changed')
        with self.assertRaises(SourceError): read(self.config, self.decision(), output_directory=self.out/'run')

    def test_protocol_failure_is_sanitized_and_not_retried(self):
        self.configured(); calls = []
        def fail(*args): calls.append(args); return b'Bearer SYNTHETIC_PRIVATE_CANARY'
        result = read(self.config, self.decision(), output_directory=self.out/'run', runner=fail)
        receipt = artifact(result['receipt_ref'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(receipt['status'], 'blocked')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(receipt))
        self.assertEqual(receipt['task_state'], 'unknown_reconcile_before_reuse')

    def test_forged_deadline_is_rejected(self):
        self.configured()
        for number in [float('nan'), float('inf'), -1, 10000, True]:
            decision = {**self.decision(), 'timeout_seconds': number}
            with self.assertRaises(SourceError): read(self.config, decision, output_directory=self.out/'run')

    def test_nonce_redirect_cleanup_and_duplicate_fields(self):
        self.configured()
        def run_variant(update):
            def worker(command, script, *args):
                inputs = json.loads(re.search(r'const input = (.*);', script).group(1))
                value = dict(schema_version=1, nonce=inputs['nonce'], status='observed',
                    observed_url=inputs['url'], snapshot='text', truncated=False, cleanup_verified=True)
                value.update(update)
                return json.dumps(value).encode()
            return worker
        for update in [{'nonce':'wrong'}, {'observed_url':'https://evil.example/'},
                       {'cleanup_verified':False}, {'extra':'payload'}, {'schema_version':True}]:
            result = read(self.config, self.decision(), output_directory=self.out/'run', runner=run_variant(update))
            self.assertEqual(result['status'], 'blocked')

    def test_child_timeout_and_output_limits(self):
        for code, timeout, maximum, expected in [
            ('import time;time.sleep(10)', .1, 1024, 'EGO_TIMEOUT'),
            ('print("x"*10000)', 2, 1024, 'EGO_OUTPUT_LIMIT')]:
            with self.assertRaisesRegex(SourceError, expected):
                _execute([sys.executable, '-B', '-c', code], '', timeout, maximum, self.out)

    def test_unconsumed_input_cannot_block_timeout(self):
        with self.assertRaisesRegex(SourceError, 'EGO_TIMEOUT'):
            _execute([sys.executable, '-B', '-c', 'import time;time.sleep(2)'], 'x'*1000000, .1, 1024, self.out)

    def test_installed_sdk_stderr_and_blank_line_protocol(self):
        cli = self.configured()
        cli.write_text(cli.read_text().replace('print(json.dumps(', 'sys.stderr.write(json.dumps(')
                       .replace('cleanup_verified=True)))', 'cleanup_verified=True))+"\\n\\n")'))
        self.config['egolite']['sha256'] = fingerprint(cli)
        result = read(self.config, self.decision(), output_directory=self.out/'sdk-stderr')
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(artifact(artifact(result['receipt_ref'])['snapshot_ref'], json_value=False),
                         b'Observed public example')

    def test_extra_protocol_records_and_logs_fail_closed(self):
        cli = self.configured()
        cli.write_text(cli.read_text() + '\nprint("SYNTHETIC_PRIVATE_CANARY")\n')
        self.config['egolite']['sha256'] = fingerprint(cli)
        result = read(self.config, self.decision(), output_directory=self.out/'extra-log')
        receipt = artifact(result['receipt_ref'])
        self.assertEqual(receipt['status'], 'blocked')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(receipt))
        self.assertFalse(receipt['cleanup_verified'])

    def test_combined_child_output_budget(self):
        with self.assertRaisesRegex(SourceError, 'EGO_OUTPUT_LIMIT'):
            _execute([sys.executable, '-B', '-c',
                      'import sys;sys.stdout.write("x"*700);sys.stderr.write("y"*700)'],
                     '', 2, 1024, self.out)

    def test_concurrent_session_admission_keeps_exact_budget(self):
        session = Session(self.config)
        def admit(_):
            try:
                return session.plan(operation='read', url='https://arxiv.org/')['read_ordinal']
            except SourceError as error:
                self.assertEqual(str(error), 'WEB_READ_BUDGET')
                return None
        with ThreadPoolExecutor(max_workers=16) as pool:
            admitted = [x for x in pool.map(admit, range(128)) if x is not None]
        self.assertEqual(sorted(admitted), list(range(1, self.config['limits']['max_reads']+1)))
        self.assertEqual(session.reads, self.config['limits']['max_reads'])

    def test_intent_write_failure_cannot_launch_provider(self):
        self.configured()
        with patch('shared.web_access.egolite.save', side_effect=OSError('SYNTHETIC_PRIVATE_CANARY')), \
             patch('shared.web_access.egolite._execute') as provider:
            with self.assertRaises(OSError):
                read(self.config, self.decision(), output_directory=self.out/'no-intent')
        provider.assert_not_called()


if __name__ == '__main__': unittest.main()
