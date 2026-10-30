"""Synthetic failure fixtures for provenance, visible rationale and forecast scoring."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import rationale_guard as g
from test_cycle_checks import example_packet

STAMP = '2026-10-23T15:00:00Z'
FUTURE = '2027-02-01T00:00:00Z'


class RationaleFixture:
    def __init__(self, directory):
        self.path = Path(directory)
        self.install = self.path / 'install'
        self.install.mkdir()
        files = set(g.required_paths('company_full')) | set(g.required_paths('fund_full')) | set(g.required_paths('crypto_full'))
        for manifest in g.MANIFESTS:
            m = json.loads((g.ROOT / manifest).read_text())
            if isinstance(m['files'], list):
                files.update(r['path'] for r in m['files'])
            else:
                files.update('references/ai-berkshire/references/upstream/' + name for name in m['files'])
        for name in files:
            target = self.install / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(g.ROOT / name, target)
        for args in [['init', '-q'], ['add', '.'], ['-c', 'user.name=Synthetic fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Synthetic installed dependency fixture']]:
            subprocess.run(['git', '-C', str(self.install), *args], check=True, capture_output=True)
        self.lock = g.dependency_lock('company_full', self.install)
        self.rec = {'schema_version': g.SCHEMA_VERSION, 'scope': 'company_full', 'status': 'complete',
                    'skill_revision': self.lock['skill_revision'], 'policy_versions': {'rationale': g.VERSION},
                    'subject': {'ticker': 'SYNTHETIC', 'cutoff': STAMP, 'economics_classification': 'cyclical'},
                    'claims': [{'id': 'c1'}], 'artifacts': [],
                    'audit': {'author_id': 'author', 'independent_review': {'reviewer_id': 'reviewer', 'reviewed_artifact_ids': []}},
                    'result': {'report_artifact_id': 'report'}, 'persistence': {'status': 'saved', 'receipts': []}}
        self.output = {'entry_low': 70, 'entry_high': 80, 'horizon_months': 60,
                       'peak': 120, 'normalized': 95, 'adverse': 40,
                       'forecast_mean': 100, 'forecast_median': 98, 'forecast_binary': .7, 'forecast_interval': [80, 120]}
        self.save('outputs', self.output)
        self.save('lock', self.lock)
        self.cycle_packet = example_packet()
        self.cycle_packet['as_of'] = STAMP
        self.save('cycle_packet', self.cycle_packet)
        self.save('cycle_result', g.cycle_math.calculate(self.cycle_packet))
        self.card = {'version': g.VERSION, 'ticker': 'SYNTHETIC', 'scope': 'company_full',
                     'as_of': STAMP, 'issued_at': STAMP, 'cohort_id': 'synthetic-cohort',
                     'quote_unit': 'USD/share', 'entry_period': 'FY2027Q1',
                     'thesis_family': 'synthetic-memory', 'origin': 'prospective', 'action': 'wait',
                     'limitations': 'Synthetic functional fixture, not real investment evidence.',
                     'methodology_applications': {
                         'ai_berkshire': {**self.link(), 'workflow_paths': ['references/ai-berkshire/WORKFLOW.md']},
                         'anthropic_financial_services': {**self.link(), 'workflow_paths': ['references/upstream/sector-overview/WORKFLOW.md']}},
                     'nodes': {k: {**self.link(), 'status': 'mixed'} for k in g.NODE_TITLES},
                     'beat_test': {**self.link(), 'basis': 'unavailable', 'period': 'FY2027Q1', 'revenue_metric': 'Synthetic revenue', 'profit_metric': 'Synthetic owner profit'},
                     'metrics': {k: self.binding('/' + k, 'USD/share' if k != 'horizon_months' else 'months') for k in ['entry_low', 'entry_high', 'horizon_months']},
                     'catalyst_limitations': 'Magnitude unidentified; test the explicitly declared operating forecast.',
                     'cycle_challenge': {
                         'industry': 'memory', 'adoption_stage': 'mixed', 'industry_state': 'expansion with supply risk',
                         'expectations_state': 'not established',
                         'economic_questions': {k: self.link() for k in g.ECONOMIC_QUESTIONS},
                         'numerical_check': {'input_artifact_id': 'cycle_packet', 'output_artifact_id': 'cycle_result',
                                             'case_calculation_ids': {k: k for k in ['peak', 'normalized', 'adverse']}},
                         'indicators': [{**self.link(), 'family': k, 'available_at': STAMP, 'units': 'synthetic units'} for k in ['demand', 'supply', 'inventory']],
                         'hypotheses': [{**self.link(), 'next_observation': 'Next dated unit result', 'falsifier': 'Opposite unit result'} for _ in range(2)],
                         'normalization': {'status': 'applied', 'cases': {k: self.binding('/' + k, 'USD/share') for k in ['peak', 'normalized', 'adverse']}}},
                     'forecasts': []}
        self.card['nodes']['double_beat']['status'] = 'not_established'
        computed = g.cycle_math.calculate(self.cycle_packet)
        self.card['cycle_challenge']['numerical_check']['display_fcff_bindings'] = {
            label: {'artifact_id': 'cycle_result', 'pointer': '/results/' + label + '/totals/fcff',
                    'units': computed['results'][label]['currency_unit'],
                    'period': computed['results'][label]['period']['start'] + '/' + computed['results'][label]['period']['end']}
            for label in ['peak', 'normalized', 'adverse']}
        for kind in ['mean', 'median', 'binary', 'interval']:
            f = {'id': kind, 'target': 'Synthetic observable ' + kind, 'units': 'units', 'period': 'FY2027Q1', 'kind': kind,
                 'resolve_after': FUTURE, 'resolution_rule': 'First reported synthetic actual',
                 'resolution_source': 'https://example.invalid/primary',
                 'model_binding': self.binding('/forecast_' + kind, 'units'), 'prediction': self.output['forecast_' + kind]}
            if kind == 'interval': f['coverage'] = .8
            self.card['forecasts'].append(f)
        self.rec['rationale_evidence'] = {'version': g.VERSION, 'status': 'reviewed', 'dependency_lock_artifact_id': 'lock',
                                          'card_artifact_id': 'card', 'diagram_artifact_id': 'figure', 'review_artifact_id': 'r_review'}
        self.refresh()

    def link(self):
        return {'finding': 'Synthetic fixture: normal supply may erase the peak margin; this is not a recommendation.', 'claim_ids': ['c1'], 'model_artifact_ids': ['outputs']}

    def binding(self, pointer, units):
        key = pointer[1:]
        self.output.setdefault('metric_metadata', {})[key] = {'units': units, 'period': 'FY2027Q1'}
        return {'artifact_id': 'outputs', 'pointer': pointer, 'units': units, 'period': 'FY2027Q1',
                'units_pointer': '/metric_metadata/' + key + '/units', 'period_pointer': '/metric_metadata/' + key + '/period'}

    def save(self, aid, content, suffix='.json'):
        path = self.path / (aid + suffix)
        raw = content if isinstance(content, str) else g.encoded(content)
        path.write_text(raw)
        row = {'id': aid, 'path': str(path), 'sha256': g.digest(path.read_bytes()), 'kind': 'other', 'depends_on': []}
        self.rec['artifacts'] = [a for a in self.rec['artifacts'] if a['id'] != aid] + [row]
        return row

    def refresh(self, format='svg'):
        self.save('outputs', self.output)
        self.save('lock', self.lock)
        self.save('cycle_packet', self.cycle_packet)
        self.save('cycle_result', g.cycle_math.calculate(self.cycle_packet))
        card_ref = self.save('card', self.card)
        values = self.values()
        figure = g.diagram(self.card, values, card_ref['sha256'], format)
        self.save('figure', figure, '.mmd' if format == 'mermaid' else '.svg')
        self.save('report', '<!doctype html><html><body><section data-investment-rationale="' + card_ref['sha256'] + '">' + figure + '</section></body></html>' if format == 'svg' else '# Synthetic fixture\n```mermaid\n' + figure + '```', '.html' if format == 'svg' else '.md')
        self.review = {'version': g.VERSION, 'ticker': 'SYNTHETIC', 'reviewer_id': 'reviewer', 'status': 'approved_rationale',
                       'artifact_hashes': {a['id']: a['sha256'] for a in self.rec['artifacts'] if a['id'] != 'r_review'},
                       'visual_inspection': {'method': 'rendered_html', 'finding': 'Synthetic reviewer fixture; production must actually inspect rendered output.'},
                       'critic_checks': {k: self.link() for k in g.CRITIC_CHECKS}, 'findings': []}
        self.save('r_review', self.review)
        self.rec['audit']['independent_review']['reviewed_artifact_ids'] = ['lock', 'card', 'figure', 'report']
        self.rec['persistence']['receipts'] = [{'artifact_id': a['id'], 'confirmed_at': STAMP} for a in self.rec['artifacts'] if a['id'] != 'outputs']

    def values(self):
        values = {k: self.output[v['pointer'][1:]] for k, v in self.card['metrics'].items()}
        computed = g.cycle_math.calculate(self.cycle_packet)['results']
        values['_cycle_display'] = {label: {'value': computed[label]['totals']['fcff'], 'units': computed[label]['currency_unit'],
                                          'period': computed[label]['period']['start'] + '/' + computed[label]['period']['end']}
                                    for label in ['peak', 'normalized', 'adverse']}
        return values

    def outcomes(self):
        return {'card_sha256': next(a['sha256'] for a in self.rec['artifacts'] if a['id'] == 'card'),
                'observations': [{'forecast_id': k, 'actual': 1 if k == 'binary' else 90,
                                  'units': 'units', 'period': 'FY2027Q1', 'available_at': '2027-02-02T00:00:00Z',
                                  'source': 'https://example.invalid/actual'} for k in ['mean', 'median', 'binary', 'interval']]}


class RationaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = RationaleFixture(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.f = self.base
        # One committed install is shared; mutable run artifacts are reset each test.
        self.saved = copy.deepcopy((self.f.rec, self.f.card, self.f.lock, self.f.output))

    def tearDown(self):
        self.f.rec, self.f.card, self.f.lock, self.f.output = self.saved
        self.f.refresh()

    def validate(self): return g.validate(self.f.rec, root=self.f.install)

    def test_complete_wait_is_valid_and_not_truth_certification(self):
        result = self.validate()
        self.assertEqual(result['status'], 'validated'); self.assertFalse(result['semantic_truth_verified'])

    def test_missing_policy_rejected_for_new_publication_even_old_schema(self):
        self.f.rec['schema_version'] = '2026-10-18-research-run-2'; self.f.rec['policy_versions'] = {}
        with self.assertRaisesRegex(ValueError, 'policy declaration'):
            g.validate(self.f.rec, root=self.f.install, observed_publication_times=['2026-10-24T00:00:00Z'])

    def test_historical_record_is_not_retroactively_certified(self):
        rec = {'scope': 'company_full', 'schema_version': '2026-10-18-research-run-2', 'persistence': {'receipts': [{'confirmed_at': STAMP}]}}
        self.assertEqual(g.validate(rec)['status'], 'historical_not_certified')

    def test_narrow_output_exempt(self): self.assertEqual(g.validate({'scope': 'narrow'})['status'], 'exempt')

    def test_missing_second_framework_rejected(self):
        self.f.card['methodology_applications'].pop('anthropic_financial_services'); self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'Both AI'): self.validate()

    def test_wrong_framework_path_rejected(self):
        self.f.card['methodology_applications']['anthropic_financial_services']['workflow_paths'] = ['references/ai-berkshire/WORKFLOW.md']; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'wrong dependency'): self.validate()

    def test_dependency_hash_forgery_rejected(self):
        self.f.lock['files']['SKILL.md'] = '0' * 64; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'citation hash'): self.validate()

    def test_unsafe_dependency_path_rejected(self):
        self.f.lock['files']['../external'] = '0' * 64; self.f.refresh()
        with self.assertRaises(ValueError): self.validate()

    def test_missing_git_history_rejected(self):
        self.f.rec['skill_revision'] = '0' * 40; self.f.lock['skill_revision'] = '0' * 40; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'history unavailable'): self.validate()

    def test_snapshot_rejects_dirty_dependency(self):
        p = self.f.install / 'SKILL.md'; original = p.read_bytes(); p.write_bytes(original + b'\nmodified')
        try:
            with self.assertRaisesRegex(ValueError, 'Commit the installed'): g.dependency_lock('company_full', self.f.install)
        finally: p.write_bytes(original)

    def test_missing_rationale_topic_rejected(self):
        self.f.card['nodes'].pop('expectations'); self.f.save('card', self.f.card)
        with self.assertRaisesRegex(ValueError, 'eight'): self.validate()

    def test_unknown_is_allowed_with_evidence_links(self):
        self.f.card['nodes']['double_beat']['status'] = 'not_established'; self.f.refresh()
        self.assertEqual(self.validate()['status'], 'validated')

    def test_double_beat_requires_expectations_basis(self):
        self.f.card['nodes']['double_beat']['status'] = 'supported'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'without an expectations'): self.validate()

    def test_reverse_implied_is_explicit_and_metric_definitions_match(self):
        self.f.card['beat_test'].update(basis='price_implied', revenue_forecast=self.f.binding('/forecast_mean','units'),
                                      revenue_expectation=self.f.binding('/forecast_median','units'),
                                      profit_forecast=self.f.binding('/normalized','USD/share'), profit_expectation=self.f.binding('/adverse','USD/share'))
        self.f.refresh(); self.assertEqual(self.validate()['status'], 'validated')

    def test_unresolved_claim_rejected(self):
        self.f.card['nodes']['moat']['claim_ids'] = ['missing']; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'claim IDs'): self.validate()

    def test_future_indicator_rejected(self):
        self.f.card['cycle_challenge']['indicators'][0]['available_at'] = '2026-11-01T00:00:00Z'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'future information'): self.validate()

    def test_repeated_indicator_family_rejected(self):
        for row in self.f.card['cycle_challenge']['indicators']: row['family'] = 'demand'
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'distinct indicator'): self.validate()

    def test_cyclical_normalization_exception_rejected(self):
        self.f.card['cycle_challenge']['normalization'] = {'status': 'not_applicable', 'reason': 'wishful exemption'}; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'cannot skip'): self.validate()

    def test_noncyclical_exception_must_be_explained(self):
        self.f.rec['subject']['economics_classification'] = 'mature'; self.f.card['cycle_challenge']['industry'] = 'other'
        self.f.card['cycle_challenge']['normalization'] = {'status': 'not_applicable', 'reason': 'No identified inventory/capacity cycle; other downside scenarios remain.'}; self.f.refresh()
        self.assertEqual(self.validate()['status'], 'validated')

    def test_capital_light_and_noncyclical_are_not_false_cycle_flags(self):
        self.f.card['cycle_challenge']['industry'] = 'other'
        self.f.card['cycle_challenge']['normalization'] = {'status': 'not_applicable', 'reason': 'No identified capacity/inventory cycle.'}
        for classification in ['capital-light recurring software', 'non-cyclical recurring software']:
            self.f.rec['subject']['economics_classification'] = classification; self.f.refresh()
            self.assertEqual(self.validate()['status'], 'validated')

    def test_memory_case_cannot_evade_normalization_by_case(self):
        self.f.rec['subject']['economics_classification'] = 'growth'; self.f.card['cycle_challenge']['industry'] = 'Memory'
        self.f.card['cycle_challenge']['normalization'] = {'status': 'not_applicable', 'reason': 'Invalid exemption'}; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'cannot skip'): self.validate()

    def test_incompatible_endpoint_or_horizon_metadata_rejected(self):
        self.f.card['metrics']['entry_high']['units'] = 'EUR billion'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'): self.validate()

    def test_years_cannot_be_rendered_as_months(self):
        self.f.card['metrics']['horizon_months']['units'] = 'years'
        self.f.output['metric_metadata']['horizon_months']['units'] = 'years'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'must use months'): self.validate()

    def test_unbound_quantitative_prose_rejected_and_bound_placeholder_renders(self):
        self.f.card['nodes']['double_beat']['finding'] = 'Owner profit will grow 99%.'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'bound metric'): self.validate()
        self.f.card['nodes']['double_beat']['finding'] = 'The tested entry starts at {{entry_low}}; a beat is not established.'; self.f.refresh()
        self.assertEqual(self.validate()['status'], 'validated')

    def test_financial_suffix_and_scientific_estimates_need_bindings(self):
        for finding in ['Margin expands by 500bps and valuation reaches 30x.', 'Revenue grows by 1e9% then 2e9%.']:
            self.f.card['nodes']['capture']['finding']=finding; self.f.refresh()
            with self.assertRaisesRegex(ValueError, 'bound metric'): self.validate()
        self.f.card['nodes']['capture']['finding']='HBM4 and 3D NAND are technical identifiers; cash capture is not established.'; self.f.refresh()
        self.assertEqual(self.validate()['status'],'validated')

    def test_unbound_model_pointer_rejected(self):
        self.f.card['metrics']['entry_low']['pointer'] = '/missing'; self.f.save('card', self.f.card)
        with self.assertRaisesRegex(ValueError, 'JSON pointer'): self.validate()

    def test_nan_model_rejected(self):
        output = next(a for a in self.f.rec['artifacts'] if a['id'] == 'outputs')
        p = Path(output['path']); p.write_text(p.read_text().replace('"entry_low": 70', '"entry_low": NaN')); output['sha256'] = g.digest(p.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Finite'): self.validate()

    def test_frozen_prediction_cannot_diverge_from_model(self):
        self.f.card['forecasts'][0]['prediction'] = 999; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'differs from actual model'): self.validate()

    def test_report_omitting_diagram_rejected_even_rehashed(self):
        self.f.save('report', '<html>Diagram omitted</html>', '.html')
        self.f.review['artifact_hashes']['report'] = next(a['sha256'] for a in self.f.rec['artifacts'] if a['id'] == 'report')
        self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'does not display'): self.validate()

    def test_hidden_or_commented_diagram_is_not_visible(self):
        report = next(a for a in self.f.rec['artifacts'] if a['id'] == 'report')
        original = Path(report['path']).read_text()
        for hidden in ['<div hidden>' + original + '</div>', '<!--' + original + '-->', '<style>svg {display:none}</style>' + original]:
            self.f.save('report', hidden, '.html')
            self.f.review['artifact_hashes']['report'] = next(a['sha256'] for a in self.f.rec['artifacts'] if a['id'] == 'report')
            self.f.save('r_review', self.f.review)
            with self.assertRaises(ValueError): self.validate()

    def test_clipped_section_and_custom_css_are_rejected(self):
        report=next(a for a in self.f.rec['artifacts'] if a['id']=='report');original=Path(report['path']).read_text()
        for content in [original.replace('<section ', '<section style="height:0;overflow:hidden" '), '<style>section{height:0;overflow:hidden}</style>'+original]:
            self.f.save('report',content,'.html')
            self.f.review['artifact_hashes']['report']=next(a['sha256'] for a in self.f.rec['artifacts'] if a['id']=='report');self.f.save('r_review',self.f.review)
            with self.assertRaisesRegex(ValueError,'visible prominent'): self.validate()

    def test_canonical_html_presentation_is_accepted(self):
        card_hash=next(a['sha256'] for a in self.f.rec['artifacts'] if a['id']=='card')
        values=self.f.values()
        self.f.save('report',g.presentation(self.f.card,values,card_hash),'.html')
        self.f.review['artifact_hashes']['report']=next(a['sha256'] for a in self.f.rec['artifacts'] if a['id']=='report');self.f.save('r_review',self.f.review)
        self.assertEqual(self.validate()['status'],'validated')

    def test_mermaid_inside_html_pre_is_not_rendered(self):
        self.f.refresh('mermaid');report=next(a for a in self.f.rec['artifacts'] if a['id']=='report')
        self.f.save('report','<pre>\n'+Path(report['path']).read_text()+'\n</pre>','.md')
        self.f.review['artifact_hashes']['report']=next(a['sha256'] for a in self.f.rec['artifacts'] if a['id']=='report');self.f.save('r_review',self.f.review)
        with self.assertRaisesRegex(ValueError,'may hide'): self.validate()

    def test_literal_nested_markdown_fence_is_not_a_rendered_graph(self):
        self.f.refresh('mermaid')
        report = next(a for a in self.f.rec['artifacts'] if a['id'] == 'report')
        original = Path(report['path']).read_text()
        self.f.save('report', '````text\n' + original + '\n````', '.md')
        self.f.review['artifact_hashes']['report'] = next(a['sha256'] for a in self.f.rec['artifacts'] if a['id'] == 'report')
        self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'rendered rationale'): self.validate()

    def test_cycle_only_model_change_invalidates_its_review(self):
        self.f.save('cycle_outputs', copy.deepcopy(self.f.output))
        for binding in self.f.card['cycle_challenge']['normalization']['cases'].values(): binding['artifact_id'] = 'cycle_outputs'
        self.f.refresh(); self.assertEqual(self.validate()['status'], 'validated')
        changed = copy.deepcopy(self.f.output); changed['normalized'] = 999999999
        self.f.save('cycle_outputs', changed)
        with self.assertRaisesRegex(ValueError, 'review hash'): self.validate()

    def test_missing_economic_question_is_rejected(self):
        self.f.card['cycle_challenge']['economic_questions'].pop('funding_and_survival'); self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'Six evidence-linked'): self.validate()

    def test_cyclical_company_requires_calculation_packet(self):
        self.f.card['cycle_challenge'].pop('numerical_check'); self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'arithmetic input/output'): self.validate()

    def test_cycle_calculation_cutoff_cannot_be_substituted(self):
        packet = copy.deepcopy(self.f.cycle_packet); packet['as_of'] = '2026-10-23T14:59:00Z'
        self.f.save('cycle_packet', packet)
        with self.assertRaisesRegex(ValueError, 'subject/cutoff'): self.validate()

    def test_cycle_calculation_is_recomputed_not_self_attested(self):
        output = g.cycle_math.calculate(self.f.cycle_packet)
        output['results']['normalized']['totals']['fcff'] = '999999'
        self.f.save('cycle_result', output)
        with self.assertRaisesRegex(ValueError, 'recomputation'): self.validate()

    def test_duplicate_packet_keys_are_rejected_integration_and_cli(self):
        raw = g.encoded(self.f.cycle_packet).replace('"subject": "SYNTHETIC"', '"subject": "WRONG", "subject": "SYNTHETIC"')
        self.f.save('cycle_packet', raw)
        with self.assertRaisesRegex(ValueError, 'duplicate_key'): self.validate()

    def test_nonobject_cycle_packet_has_structured_rejection(self):
        self.f.save('cycle_packet', [])
        with self.assertRaisesRegex(ValueError, 'must be an object'): self.validate()

    def test_unrelated_displayed_cycle_values_are_rejected(self):
        display = self.f.card['cycle_challenge']['numerical_check']['display_fcff_bindings']['normalized']
        display.update({'artifact_id': 'outputs', 'pointer': '/normalized'})
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'Displayed cycle FCFF'): self.validate()

    def test_cycle_display_units_and_period_are_checked(self):
        original = copy.deepcopy(self.f.card['cycle_challenge']['numerical_check']['display_fcff_bindings']['normalized'])
        for key, value in [('units', 'currency:EUR'), ('period', 'FY2027')]:
            self.f.card['cycle_challenge']['numerical_check']['display_fcff_bindings']['normalized'] = {**original, key: value}
            self.f.refresh()
            with self.assertRaisesRegex(ValueError, 'Displayed cycle FCFF'): self.validate()

    def test_cycle_cases_cannot_alias_one_bridge(self):
        self.f.card['cycle_challenge']['numerical_check']['case_calculation_ids']['adverse'] = 'normalized'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'distinct cycle arithmetic'): self.validate()

    def test_cycle_calculation_pair_needs_independent_hash_review(self):
        packet = copy.deepcopy(self.f.cycle_packet)
        packet['observations']['price']['source_ref'] = 'synthetic:revised-source-vintage'
        self.f.save('cycle_packet', packet); self.f.save('cycle_result', g.cycle_math.calculate(packet))
        with self.assertRaisesRegex(ValueError, 'review hash'): self.validate()

    def test_cycle_calculation_pair_needs_persistence(self):
        self.f.rec['persistence']['receipts'] = [r for r in self.f.rec['persistence']['receipts'] if r['artifact_id'] != 'cycle_result']
        with self.assertRaisesRegex(ValueError, 'persistence receipts'): self.validate()

    def test_economic_question_requires_resolved_evidence(self):
        self.f.card['cycle_challenge']['economic_questions']['demand_quality']['claim_ids'] = ['missing']; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'resolved claim IDs'): self.validate()

    def test_economic_only_model_change_invalidates_review(self):
        self.f.save('economic_outputs', {'cash_runway': 12})
        self.f.card['cycle_challenge']['economic_questions']['funding_and_survival']['model_artifact_ids'] = ['economic_outputs']
        self.f.refresh(); self.assertEqual(self.validate()['status'], 'validated')
        self.f.save('economic_outputs', {'cash_runway': 1})
        with self.assertRaisesRegex(ValueError, 'review hash'): self.validate()

    def test_changed_figure_rejected_even_rehashed(self):
        self.f.save('figure', '<svg>Different rationale</svg>', '.svg')
        with self.assertRaisesRegex(ValueError, 'differs from canonical'): self.validate()

    def test_stale_review_hash_rejected(self):
        self.f.review['artifact_hashes']['card'] = '0' * 64; self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'review hash'): self.validate()

    def test_missing_cycle_critic_rejected(self):
        self.f.review['critic_checks'].pop('priced_in'); self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'challenge incomplete'): self.validate()

    def test_rendered_report_review_is_required(self):
        self.f.review.pop('visual_inspection'); self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'visual inspection'): self.validate()

    def test_same_author_reviewer_rejected(self):
        self.f.rec['audit']['independent_review']['reviewer_id'] = 'author'; self.f.review['reviewer_id'] = 'author'; self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'not independent'): self.validate()

    def test_unresolved_finding_rejected(self):
        self.f.review['findings'] = [{'disposition': 'unresolved', 'rationale': 'unresolved source issue'}]; self.f.save('r_review', self.f.review)
        with self.assertRaisesRegex(ValueError, 'Unresolved rationale'): self.validate()

    def test_missing_persistence_rejected(self):
        self.f.rec['persistence']['receipts'] = []
        with self.assertRaisesRegex(ValueError, 'persistence receipts'): self.validate()

    def test_mermaid_report_supported(self):
        self.f.refresh('mermaid'); self.assertEqual(self.validate()['status'], 'validated')

    def test_no_feasible_entry_does_not_force_price(self):
        self.f.card.update(entry_feasibility='none', no_feasible_entry_reason='Synthetic tested domain fails risk budget.')
        self.f.card['metrics']['tested_entry_low'] = self.f.card['metrics'].pop('entry_low')
        self.f.card['metrics']['tested_entry_high'] = self.f.card['metrics'].pop('entry_high')
        self.f.refresh(); self.assertEqual(self.validate()['status'], 'validated')
        self.f.card['action'] = 'buy'; self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'Cannot recommend'): self.validate()

    def test_atomic_failure_preserves_existing_output(self):
        target = self.f.path / 'safe.json'; target.write_text('previous valid result')
        with patch.object(g.os, 'replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): g.atomic_write(target, 'replacement')
        self.assertEqual(target.read_text(), 'previous valid result')

    def test_scores_and_unmatured_denominator(self):
        outcomes = self.f.outcomes(); h = outcomes['card_sha256']
        result = g.score(self.f.card, outcomes, as_of='2027-02-03T00:00:00Z', card_sha256=h)
        rows = {r['forecast_id']: r for r in result['items']}
        self.assertEqual(rows['mean']['signed_error'], 10); self.assertEqual(rows['median']['absolute_error'], 8)
        self.assertAlmostEqual(rows['binary']['brier_loss'], .09); self.assertTrue(rows['interval']['covered'])
        self.assertEqual(rows['interval']['interval_score'], 40)
        result = g.score(self.f.card, outcomes, as_of='2027-01-01T00:00:00Z', card_sha256=h)
        self.assertEqual((result['resolved'], result['pending']), (0, 4))

    def test_score_wrong_vintage_units_duplicate_unknown_rejected(self):
        for mutate in [lambda o: o.update(card_sha256='0'*64), lambda o: o['observations'][0].update(units='USD'),
                       lambda o: o['observations'].append(o['observations'][0]), lambda o: o['observations'][0].update(forecast_id='unknown')]:
            outcomes = self.f.outcomes(); h = outcomes['card_sha256']; mutate(outcomes)
            with self.assertRaises(ValueError): g.score(self.f.card, outcomes, as_of='2027-02-03T00:00:00Z', card_sha256=h)

    def test_actual_source_and_availability_required(self):
        outcomes = self.f.outcomes(); h = outcomes['card_sha256']; outcomes['observations'][0]['source'] = ''
        with self.assertRaisesRegex(ValueError, 'source'): g.score(self.f.card, outcomes, as_of='2027-02-03T00:00:00Z', card_sha256=h)


if __name__ == '__main__': unittest.main()
