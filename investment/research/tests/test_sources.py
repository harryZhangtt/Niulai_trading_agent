import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, READ_ROOTS, SourceError, atomic_write_private, digest, read, save
from shared.research_sources.fetch import document_receipt, passages
from investment.research.requirements import freeze
from investment.research.routing import routes
from investment.research.coverage import validate
from investment.research import pipeline

STATE = SOURCE_STATE / 'tmp'
STATE.mkdir(parents=True, exist_ok=True)


def request(subject='AAA', profile='business-economics', stamp='2026-10-30T23:59:59Z'):
    return {'subject': subject, 'as_of': stamp, 'profile': profile,
            'claims': [{'id': 'c1', 'question': 'What evidence supports the material economic mechanism?'}]}


def fixture(directory, *, subject='AAA', stamp='2026-10-30T23:59:59Z', author='author'):
    contract = freeze(request(subject=subject, stamp=stamp), directory)
    source = document_receipt(directory, provider='official_document', url='https://www.sec.gov/synthetic',
        raw=('<article><h1>Synthetic filing</h1><p>' + 'Synthetic operating evidence and explicit limitations. ' * 12 + '</p></article>').encode(),
        identifier='synthetic-only', published_at='2026-10-17T00:00:00Z')
    p = passages(source, 20, 160)
    model = save(directory, {'operating_metric': '1.234'})
    evidence = [{'requirement_id': 'c1:business_realization', 'source': source, 'passages': [p],
        'limitations': 'Synthetic functional fixture; no actual company evidence.', 'upstream_lineage': 'synthetic-issuer',
        'economic_link': {'artifact': model, 'pointer': '/operating_metric', 'effect': 'unchanged',
                          'reason': 'Synthetic no-change explanation checked by the fixture reviewer.'}}]
    packet = {'requirements_sha256': contract['expected_sha256'], 'evidence': evidence,
        'review': {'status': 'approved_source_coverage', 'author_id': author, 'reviewer_id': 'reviewer',
                  'evidence_sha256': digest(evidence), 'findings': [{'requirement_id': 'c1:business_realization',
                  'source_support_checked': True, 'applicability_checked': True, 'lineage_checked': True,
                  'economic_transfer_checked': True, 'finding': 'Synthetic review of bounded evidence and no-change rationale.'}]}}
    return contract, packet


class SourceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=STATE)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.contract, self.packet = fixture(self.directory)

    def check(self, packet=None, contract=None):
        return validate(contract or self.contract, save(self.directory, packet or self.packet))

    def test_buffered_contract_pointer_preserves_old_on_producer_or_validation_failure(self):
        pointer = self.directory / 'contract-pointer.json'
        atomic_write_private(pointer, json.dumps(self.contract).encode())
        old = pointer.read_bytes()
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_PRODUCER_FAILED'):
            pipeline.publish_contract_pointer(pointer,
                [sys.executable, '-c', 'import sys;print("{\"partial\":");sys.exit(9)'])
        self.assertEqual(pointer.read_bytes(), old)
        with self.assertRaises(SourceError):
            pipeline.publish_contract_pointer(pointer, [sys.executable, '-c', 'print("{}")'])
        self.assertEqual(pointer.read_bytes(), old)
        result = pipeline.publish_contract_pointer(pointer,
            [sys.executable, '-c', 'import json,sys;print(json.dumps(json.loads(sys.argv[1])))',
             json.dumps(self.contract)])
        self.assertEqual(result, self.contract)
        self.assertEqual(json.loads(pointer.read_text()), self.contract)

    def test_valid_evidence_and_reviewed_no_change(self):
        self.assertEqual(self.check()['status'], 'validated_source_coverage')
        self.assertFalse(self.check()['investment_alpha_established'])

    def test_discovery_and_routes_cannot_change_frozen_needs(self):
        contract = freeze(request('NVDA', 'accelerated-compute'), self.directory)
        before = read(contract['requirements'])
        route = next(r for r in routes(contract) if r['requirement_id'] == 'c1:technical_research')
        openalex = next(p for p in route['candidates'] if p['provider'] == 'openalex')
        self.assertFalse(openalex['read_access_available'])
        self.assertEqual(read(contract['requirements']), before)
        self.assertEqual(len(before['requirements']), 4)

    def test_bank_profile_has_no_arxiv_quota(self):
        self.assertEqual(len(routes(self.contract)), 1)
        self.assertNotIn('arxiv', [p['provider'] for p in routes(self.contract)[0]['candidates']])
        self.assertEqual(self.check()['requirements_checked'], 1)

    def test_unconfigured_issuer_cannot_inherit_nvidia_rules(self):
        with self.assertRaisesRegex(SourceError, 'ISSUER_PROFILE_OVERRIDE_REQUIRED'):
            freeze(request('AMD', 'accelerated-compute'), self.directory)

    def test_coordinator_pin_rejects_worker_rewritten_requirements(self):
        snapshot = read(self.contract['requirements']); snapshot['requirements'] = []
        altered = {**self.contract, 'requirements': save(self.directory, snapshot)}
        with self.assertRaisesRegex(SourceError, 'REQUIREMENTS_PIN_MISMATCH'):
            self.check(contract=altered)

    def test_metadata_cannot_be_counted_as_document(self):
        p = copy.deepcopy(self.packet)
        p['evidence'][0]['source'] = save(self.directory, {'access_level': 'metadata', 'provider': 'openalex'})
        with self.assertRaisesRegex(SourceError, 'SOURCE_ACCESS_INSUFFICIENT'):
            self.check(p)

    def test_missing_or_fabricated_passage_is_rejected(self):
        for replacement in ([], [{'start': 0, 'end': 30, 'text': 'invented material not in source'}]):
            p = copy.deepcopy(self.packet); p['evidence'][0]['passages'] = replacement
            with self.assertRaises(SourceError): self.check(p)

    def test_changed_source_model_or_review_is_rejected(self):
        p = copy.deepcopy(self.packet)
        model = Path(p['evidence'][0]['economic_link']['artifact']['path']); model.write_text('{}')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'): self.check(p)

    def test_economic_rationale_change_requires_new_review(self):
        p = copy.deepcopy(self.packet); p['evidence'][0]['economic_link']['reason'] = 'Changed after review'
        with self.assertRaisesRegex(SourceError, 'SOURCE_REVIEW_MISSING_OR_STALE'): self.check(p)

    def test_future_version_and_unknown_availability_rejected(self):
        for date in (None, '2026-11-01T00:00:00Z'):
            p = copy.deepcopy(self.packet); receipt = read(p['evidence'][0]['source']); receipt['available_at'] = date
            p['evidence'][0]['source'] = save(self.directory, receipt)
            with self.assertRaises(SourceError): self.check(p)

    def test_incomplete_coverage_and_self_review_rejected(self):
        p = copy.deepcopy(self.packet); p['review']['reviewer_id'] = 'other-path/author'
        with self.assertRaisesRegex(SourceError, 'INDEPENDENT_REVIEW_REQUIRED'): self.check(p)
        p = copy.deepcopy(self.packet); p['review']['findings'] = []
        with self.assertRaisesRegex(SourceError, 'REVIEW_COVERAGE_INCOMPLETE'): self.check(p)

    def test_finalize_cannot_bypass_source_gate(self):
        record = self.directory / 'draft.json'; record.write_text('{}')
        with patch.object(pipeline, 'legacy') as old:
            with self.assertRaises(Exception):
                pipeline.finalize({'record': str(record)}, self.directory, contract=self.contract,
                                  packet=save(self.directory, {'evidence': []}))
            old.assert_not_called()

    def test_complete_cannot_bypass_source_gate(self):
        with patch.object(pipeline, 'legacy') as old:
            with self.assertRaisesRegex(SourceError, 'COMPLETION_SOURCE_CONTRACT_REQUIRED'):
                pipeline.complete({'record': save(self.directory, {})}, 'run1', contract=self.contract)
            old.assert_not_called()

    def accelerator_packet(self):
        contract = freeze(request('NVDA', 'accelerated-compute'), self.directory)
        model = self.packet['evidence'][0]['economic_link']
        evidence = []
        hosts = ['docs.nvidia.com', 'arxiv.org', 'rocm.docs.amd.com', 'www.sec.gov']
        for rule, host in zip(read(contract['requirements'])['requirements'], hosts):
            raw = ('<h1>Synthetic ' + host + '</h1><p>' + 'Synthetic mechanism and limitations. ' * 20 + '</p>').encode()
            source = document_receipt(self.directory, provider='synthetic', url='https://' + host + '/synthetic',
                raw=raw, identifier=host, published_at='2026-10-17T00:00:00Z')
            evidence.append({'requirement_id': rule['id'], 'source': source,
                'passages': [passages(source, 20, 100)], 'economic_link': model,
                'upstream_lineage': 'competitor' if rule['family'] == 'comparative_technical' else 'issuer',
                'limitations': 'Synthetic mechanics only, not actual investment evidence.'})
        review = copy.deepcopy(self.packet['review'])
        review['evidence_sha256'] = digest(evidence)
        review['findings'] = [{**self.packet['review']['findings'][0], 'requirement_id': e['requirement_id']} for e in evidence]
        return contract, {'requirements_sha256': contract['expected_sha256'], 'evidence': evidence, 'review': review}

    def test_all_four_accelerator_evidence_families(self):
        contract, packet = self.accelerator_packet()
        self.assertEqual(self.check(packet, contract)['requirements_checked'], 4)
        packet['evidence'].pop()
        with self.assertRaisesRegex(SourceError, 'REQUIRED_SOURCE_COVERAGE_INCOMPLETE'):
            self.check(packet, contract)

    def test_repeated_vendor_evidence_cannot_be_independent_challenge(self):
        contract, packet = self.accelerator_packet()
        packet['evidence'][2]['upstream_lineage'] = 'issuer'
        packet['review']['evidence_sha256'] = digest(packet['evidence'])
        with self.assertRaisesRegex(SourceError, 'SHARED_UPSTREAM_NOT_INDEPENDENT'):
            self.check(packet, contract)

    def test_failed_applicability_review_blocks_completion(self):
        contract, packet = self.accelerator_packet()
        packet['review']['findings'][1]['applicability_checked'] = False
        with self.assertRaisesRegex(SourceError, 'SUBSTANTIVE_REVIEW_REQUIRED'):
            self.check(packet, contract)

    def test_full_nvda_cannot_use_weaker_business_only_profile(self):
        contract, packet = fixture(self.directory, subject='NVDA')
        record = {'subject': {'ticker': 'NVDA', 'cutoff': '2026-10-30T23:59:59Z'},
            'scope': 'company_full', 'claims': [{'id': 'c1'}], 'sources': [], 'artifacts': [],
            'model': {}, 'coverage': {'industry_technology': {'claim_ids': ['c1']}}}
        with self.assertRaisesRegex(SourceError, 'NVDA_FULL_TECHNICAL_PROFILE_REQUIRED'):
            validate(contract, save(self.directory, packet), record=record)

    def test_technical_claims_cannot_be_left_out_of_frozen_roster(self):
        record = {'subject': {'ticker': 'AAA', 'cutoff': '2026-10-30T23:59:59Z'},
            'scope': 'company_full', 'claims': [{'id': 'c1'}, {'id': 'omitted'}], 'sources': [], 'artifacts': [],
            'model': {}, 'coverage': {'industry_technology': {'claim_ids': ['c1', 'omitted']}}}
        with self.assertRaisesRegex(SourceError, 'TECHNICAL_CLAIM_ROSTER_INCOMPLETE'):
            validate(self.contract, save(self.directory, self.packet), record=record)


class LegacyCompositionTests(unittest.TestCase):
    def legacy_fixture(self):
        fixture_module = pipeline.legacy('test_finalize_research')
        # The preserved migration fixture uses the process default temp root.
        # Bound only its setup to the approved private synthetic state root;
        # production path allowlists and the legacy fixture remain unchanged.
        with patch.object(tempfile, 'tempdir', str(STATE)):
            f = fixture_module.FinalizeTests(); f.setUp()
        self.addCleanup(f.tearDown)
        self.assertTrue(any(f.root.is_relative_to(root) for root in READ_ROOTS))
        return fixture_module, f

    def test_future_legacy_siblings_are_private_atomic_and_reject_symlink_output(self):
        _, f = self.legacy_fixture()
        finalizer = pipeline.legacy('finalize_research')
        previous = os.umask(0o022)
        try:
            item = finalizer.assemble(f.request, f.out)
        finally:
            os.umask(previous)

        record = Path(item['record']['path'])
        completion_item = f.out / 'AAA_completion_item.json'
        pointer = json.loads(completion_item.read_text())
        self.assertEqual(read(pointer['completion']), item)
        self.assertEqual(stat.S_IMODE(f.out.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(completion_item.stat().st_mode), 0o600)
        self.assertFalse((f.out / 'AAA_candidate_record.json').exists())
        self.assertFalse((f.out / 'AAA_finalized_record.json').exists())

        before = completion_item.read_bytes()
        changed = {**f.request, 'publications': []}
        with patch.object(finalizer, 'atomic_write_private', side_effect=OSError('synthetic replace failure')):
            with self.assertRaisesRegex(OSError, 'synthetic replace failure'):
                finalizer.assemble(changed, f.out)
        self.assertEqual(completion_item.read_bytes(), before)
        self.assertEqual(list(f.out.glob('.*.pending-*')), [])

        run_pointer = f.out / 'completion_run.json'
        finalizer.publish_completion_run(f.out, {'run_id': 'old'}, {'status': 'old'})
        old_run = run_pointer.read_bytes()
        with patch.object(finalizer, 'atomic_write_private', side_effect=OSError('synthetic pointer failure')):
            with self.assertRaisesRegex(OSError, 'synthetic pointer failure'):
                finalizer.publish_completion_run(f.out, {'run_id': 'new'}, {'status': 'new'})
        self.assertEqual(run_pointer.read_bytes(), old_run)

        target = f.root / 'symlink-output-target'; target.mkdir(mode=0o700)
        linked = f.root / 'symlink-output'; linked.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_SYMLINK_REJECTED'):
            finalizer.assemble(f.request, linked)
        self.assertEqual(list(target.iterdir()), [])

    def test_real_legacy_finalization_and_completion_with_added_source_contract(self):
        # Reuse the existing synthetic complete-record fixture, not a stubbed legacy gate.
        _, f = self.legacy_fixture()
        record = f.fixture.rec
        contract, packet = fixture(f.root, subject='AAA', stamp=record['subject']['cutoff'],
                                   author=record['audit']['author_id'])
        receipt = read(packet['evidence'][0]['source'])
        source = record['sources'][0]
        source['url'] = receipt['source_url']
        selected = packet['evidence'][0]['passages'][0]
        source['passages'][0]['text'] = selected['text']
        selected['record_source_id'] = source['id']; selected['record_passage_id'] = source['passages'][0]['id']
        artifact = next(a for a in record['artifacts'] if a['id'] == source['snapshot_artifact_id'])
        artifact.update(receipt['raw'])
        model = next(a for a in record['artifacts'] if a['id'] == 'inputs')
        packet['evidence'][0]['economic_link'].update(artifact={'path': model['path'], 'sha256': model['sha256']},
                                                   pointer='/synthetic_fixture')
        packet['review']['evidence_sha256'] = digest(packet['evidence'])
        Path(f.request['record']).write_text(json.dumps(record))
        packet_ref = save(f.root, packet)
        with patch.object(pipeline, 'validate', wraps=validate) as final_validation:
            item = pipeline.finalize(f.request, f.out, contract=contract, packet=packet_ref)
        self.assertEqual(final_validation.call_count, 2)
        transformed = final_validation.call_args_list[-1].kwargs['record']
        self.assertEqual(transformed['stages']['review']['status'], 'complete')
        saved_final = read(item['record'])
        self.assertEqual(saved_final['source_coverage_evidence']['receipt'],
                         validate(contract, packet_ref, record=saved_final))
        pointer = json.loads((f.out / 'AAA_completion_item.json').read_text())
        self.assertEqual(read(pointer['completion']), item)
        result = pipeline.complete(item, 'run1', contract=contract)
        self.assertEqual(result['source_coverage']['status'], 'validated_source_coverage')
        # A valid old completed record alone no longer passes the maintained entry point.
        old_record = read(item['record']); del old_record['source_coverage_evidence']
        with self.assertRaisesRegex(SourceError, 'COMPLETION_SOURCE_CONTRACT_REQUIRED'):
            pipeline.complete({**item, 'record': save(f.root, old_record)}, 'run1', contract=contract)
