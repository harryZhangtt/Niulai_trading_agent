"""Synthetic completion-gate fixtures; never actual quotes or source verification."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import options_evidence as g
import options_payoff_checks as p
import options_scenario_checks as s
import evidence_crosscheck as c
from test_options_payoff_checks import example_packet


class Fixture:
    def __init__(self, root, kind='long_call'):
        self.root = Path(root); self.arts = {}
        self.packet = example_packet(kind)
        self.record = {'instrument_profile': 'equity_options', 'scope': 'company_full', 'status': 'complete',
                       'subject': {'ticker': self.packet['subject'], 'cutoff': self.packet['as_of']},
                       'result': {'report_artifact_id': 'report', 'recommendation': 'conditional_investment_conclusion'},
                       'audit': {'author_id': '/team/author', 'independent_review': {'reviewer_id': '/team/reviewer'}}}
        block = {'version': g.VERSION, 'status': 'actionable', 'method_sha256': g.method_hashes(),
                 'payoff': self.pair('payoff', self.packet, p), 'scenario_cases': [], 'crosschecks': [],
                 'visualization_artifact_id': 'figure', 'review_artifact_id': 'review', 'contract_terms_artifact_id': 'terms'}
        self.record['options_evidence'] = block
        legs = {k: self.packet['strategy'][k] for k in ('long_leg', 'short_leg') if self.packet['strategy'][k]}
        fields = ('underlying', 'contract_id', 'right', 'strike', 'expiry', 'exercise_style', 'multiplier', 'standard_deliverable_confirmed')
        block['contracts'] = [{k: leg[k] for k in fields} for leg in legs.values()]
        self.put('terms', {'contracts': block['contracts'], 'available_at': self.packet['as_of'], 'source_ref': 'synthetic contract reference'})
        for key, leg in legs.items():
            expiry = leg['expiry'] + 'T20:00:00Z'
            years = (g.stamp(expiry) - g.stamp(self.packet['as_of'])).total_seconds() / (365*86400)
            packet = {'version': s.VERSION, 'kind': 'call', 'spot': 100, 'strike': float(leg['strike']), 'years': years,
                      'rate': 0.05, 'yield': 0, 'volatility': 0.2,
                      'quotes': {k: float(leg['quote'][k]) for k in ('bid', 'ask')},
                      'scenarios': [{'id': 'down', 'spot': 90, 'elapsed_days': 0, 'volatility': 0.2},
                                    {'id': 'delay', 'spot': 100, 'elapsed_days': 30, 'volatility': 0.2},
                                    {'id': 'crush', 'spot': 100, 'elapsed_days': 0, 'volatility': 0.1},
                                    {'id': 'combined', 'spot': 90, 'elapsed_days': 30, 'volatility': 0.1}]}
            iv_id = key + '-iv'
            self.put(iv_id, {'contract_id': leg['contract_id'], 'basis': 'assumed', 'value': 0.2,
                             'available_at': self.packet['as_of'], 'source_ref': 'synthetic assumption, not observed market IV'})
            block['scenario_cases'].append({**self.pair(key+'-scenario', packet, s), 'contract_id': leg['contract_id'],
                'expiry_at': expiry, 'iv': {'basis': 'assumed', 'value': 0.2, 'source_artifact_id': iv_id,
                'rationale': 'Explicit synthetic volatility sensitivity, not observed IV'},
                'stress_case_ids': {'price_down': 'down', 'delay': 'delay', 'iv_crush': 'crush', 'combined': 'combined'}})
        targets = {'underlying.ask': (self.packet['underlying_quote']['quote'], 'ask', None)}
        for key, leg in legs.items():
            for side in ('bid', 'ask'): targets[key+'.'+side] = (leg['quote'], side, leg['contract_id'])
        for target, (quote, side, cid) in targets.items():
            observations, snapshots = [], []
            for i in range(2):
                source_id = target + '-source' + str(i)
                self.put(source_id, {'synthetic_source': i, 'target': target, 'value': quote[side]})
                snapshots.append(source_id)
                obs = {'subject': self.packet['subject'], 'metric': 'option_premium' if cid else 'underlying_ask',
                       'definition': 'synthetic exact quoted side', 'period': {'start': '2026-10-23', 'end': '2026-10-23'},
                       'unit': 'USD/share', 'basis': 'quote', 'observed_at': quote['timestamp'], 'available_at': self.packet['as_of'],
                       'value': quote[side], 'source': {'origin': f'origin-{i}', 'provider': f'provider-{i}',
                        'upstream_family': f'family-{i}', 'ref': f'synthetic:{source_id}', 'sha256': self.arts[source_id]['sha256']}}
                if cid: obs.update(contract_key=cid, side=side)
                observations.append(obs)
            packet = {'version': c.VERSION, 'as_of': self.packet['as_of'], 'comparison_kind': 'option_quote' if cid else 'numeric',
                      'max_age_seconds': 60, 'max_time_skew_seconds': 10, 'absolute_tolerance': '0', 'relative_tolerance': '0',
                      'require_source_hashes': True, 'observations': observations}
            block['crosschecks'].append({'target': target, 'source_artifact_ids': snapshots, **self.pair(target+'-cross', packet, c)})
        calculated = p.calculate(self.packet)
        figure = g.payoff_svg(calculated); self.put('figure', figure)
        labels = '\n'.join('IV basis: '+case['contract_id']+': assumed' for case in block['scenario_cases'])
        self.put('report', '<html><body>'+figure+'<p>'+labels+'</p></body></html>')
        self.put('thesis', {'horizon': 'synthetic', 'catalyst': 'synthetic', 'falsifier': 'synthetic'})
        self.review = {'version': g.VERSION, 'status': 'approved_options', 'reviewer_id': '/team/reviewer',
                       'contracts': block['contracts'], 'method_sha256': block['method_sha256'],
                       'visual_inspection_method': 'rendered_html',
                       'checks': {key: {'status': 'reviewed', 'finding': 'Synthetic fixture only, no real evidence review.',
                                        'artifact_refs': ['thesis', 'report']} for key in g.CHECKS}}
        self.refresh()

    def put(self, aid, value):
        path = self.root / (aid + '.txt')
        path.write_text(value if isinstance(value, str) else json.dumps(value, sort_keys=True))
        self.arts[aid] = {'id': aid, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'kind': 'other'}
    def get(self, aid): return json.loads(Path(self.arts[aid]['path']).read_text())
    def pair(self, aid, packet, module):
        self.put(aid+'-in', packet); self.put(aid+'-out', module.calculate(packet))
        return {'input_artifact_id': aid+'-in', 'output_artifact_id': aid+'-out'}
    def refresh(self, repin=True):
        if repin: self.review['artifact_hashes'] = {k: a['sha256'] for k, a in self.arts.items() if k != 'review'}
        self.put('review', self.review)
        self.record['artifacts'] = list(self.arts.values())
        self.record['audit']['independent_review']['reviewed_artifact_ids'] = list(self.arts)
        self.record['persistence'] = {'receipts': [{'artifact_id': aid, 'sha256': a['sha256']} for aid, a in self.arts.items()]}


class OptionsEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.f = Fixture(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def reject(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern): g.validate(self.f.record)
    def test_full_synthetic_package_validates_not_truth_or_delivery(self):
        r = g.validate(self.f.record)
        self.assertEqual(r['status'], 'validated'); self.assertTrue(r['actionable_evidence_validated'])
        self.assertFalse(r['actionable_certified']); self.assertFalse(r['semantic_truth_verified'])
    def test_debit_spread_requires_both_leg_evidence(self):
        f = Fixture(self.tmp.name, 'bull_call_debit_spread')
        self.assertEqual(g.validate(f.record)['status'], 'validated')
        f.record['options_evidence']['scenario_cases'].pop()
        with self.assertRaisesRegex(ValueError, 'one scenario'): g.validate(f.record)
    def test_legacy_ordinary_record_exempt(self): self.assertEqual(g.validate({'scope':'company_full'})['status'], 'exempt')
    def test_profile_cannot_skip_block(self):
        del self.f.record['options_evidence']; self.reject('versioned')
    def test_security_type_cannot_hide_profile(self):
        self.f.record['subject']['security_type'] = 'equity_options'; del self.f.record['instrument_profile']; self.reject('instrument_profile')
    def test_research_only_partial_allowed_not_actionable(self):
        self.f.record.update(status='partial'); self.f.record['result']['recommendation'] = 'none'
        self.f.record['options_evidence'] = {'version': g.VERSION, 'status': 'research_only', 'blockers': ['No independently corroborated live quote']}
        r = g.validate(self.f.record); self.assertEqual(r['status'], 'research_only'); self.assertFalse(r['actionable_certified'])
        self.f.record['status'] = 'complete'; self.reject('cannot claim')
    def test_research_only_recommendation_rejected(self):
        self.f.record['status'] = 'partial'; self.f.record['options_evidence']['status'] = 'research_only'
        self.reject('cannot claim')
    def test_calculator_hash_mismatch(self):
        self.f.record['options_evidence']['method_sha256']['options_payoff_checks.py'] = '0'*64; self.reject('calculator revision')
    def test_missing_artifact(self):
        Path(self.f.arts['payoff-out']['path']).unlink(); self.reject('missing/relative')
    def test_changed_bytes(self):
        Path(self.f.arts['payoff-out']['path']).write_text('{}'); self.reject('stale hash')
    def test_rehashed_wrong_calculation_rejected(self):
        data = self.f.get('payoff-out'); data['conservative_debit_per_share'] = '0.01'
        self.f.put('payoff-out', data); self.f.refresh(); self.reject('recomputation')
    def test_rehashed_wrong_occ_strike_cannot_pass_report_gate(self):
        data = self.f.get('payoff-in'); data['strategy']['long_leg']['contract_id'] = 'SYNTH270618C00100001'
        self.f.put('payoff-in', data); self.f.refresh(); self.reject('contract_identity')
    def test_root_mapping_is_bound_to_report_contract_terms(self):
        data = self.f.get('payoff-in')
        data['strategy']['long_leg']['root_mapping'] = {'root': 'SYNTH', 'underlying': 'SYNTH',
            'verified': True, 'source_ref': 'synthetic root directory'}
        self.f.pair('payoff', data, p); self.f.refresh(); self.reject('exact contract terms')
    def test_historical_quote_cannot_be_actionable(self):
        packet = copy.deepcopy(self.f.packet); packet['mode'] = 'historical'
        self.f.record['options_evidence']['payoff'] = self.f.pair('payoff', packet, p); self.f.refresh()
        self.reject('live quote')
    def test_contract_terms_bound(self):
        self.f.record['options_evidence']['contracts'][0]['strike'] = '101'; self.reject('contract terms')
    def test_contract_source_terms_bound(self):
        data = self.f.get('terms'); data['contracts'][0]['multiplier'] = 10; self.f.put('terms', data); self.f.refresh()
        self.reject('contract source')
    def test_scenario_strike_binding(self):
        data = self.f.get('long_leg-scenario-in'); data['strike'] = 101
        self.f.pair('long_leg-scenario', data, s); self.f.refresh(); self.reject('identity/spot/strike')
    def test_horizon_binding(self):
        self.f.record['options_evidence']['scenario_cases'][0]['expiry_at'] = '2027-06-19T20:00:00Z'; self.reject('horizon')
    def test_assumption_cannot_relabel_observed(self):
        self.f.record['options_evidence']['scenario_cases'][0]['iv']['basis'] = 'observed_model_implied'; self.reject('IV provenance')
    def test_required_stress_steps(self):
        del self.f.record['options_evidence']['scenario_cases'][0]['stress_case_ids']['delay']; self.reject('four distinct')
    def test_stress_must_change_input(self):
        data = self.f.get('long_leg-scenario-in'); data['scenarios'][2]['volatility'] = 0.2
        self.f.pair('long_leg-scenario', data, s); self.f.refresh(); self.reject('IV-crush')
    def test_missing_crosscheck(self):
        self.f.record['options_evidence']['crosschecks'].pop(); self.reject('every used')
    def test_same_upstream_not_independent(self):
        data = self.f.get('long_leg.ask-cross-in'); data['observations'][1]['source']['upstream_family'] = 'family-0'
        self.f.pair('long_leg.ask-cross', data, c); self.f.refresh(); self.reject('independent current')
    def test_source_hash_bound_to_saved_bytes(self):
        data = self.f.get('long_leg.ask-cross-in'); data['observations'][0]['source']['sha256'] = '0'*64
        self.f.pair('long_leg.ask-cross', data, c); self.f.refresh(); self.reject('source payload hash')
    def test_crosscheck_cannot_relax_quote_freshness(self):
        data = self.f.get('long_leg.ask-cross-in'); data['max_age_seconds'] = 3600
        self.f.pair('long_leg.ask-cross', data, c); self.f.refresh(); self.reject('weaken payoff')
    def test_crosscheck_cannot_use_other_contract(self):
        data = self.f.get('long_leg.ask-cross-in')
        for o in data['observations']: o['contract_key'] = 'unrelated'
        self.f.pair('long_leg.ask-cross', data, c); self.f.refresh(); self.reject('contract/side')
    def test_stale_review_after_rehash(self):
        self.f.put('thesis', {'changed': 'material new evidence'}); self.f.refresh(repin=False); self.reject('review hash')
    def test_independent_reviewer_required(self):
        self.f.record['audit']['author_id'] = '/elsewhere/reviewer'; self.reject('independent options review')
    def test_missing_critic_step(self):
        del self.f.review['checks']['exercise_and_carry']; self.f.refresh(); self.reject('critic steps')
    def test_visual_must_be_canonical_and_visible(self):
        self.f.put('figure', '<svg/>'); self.f.refresh(); self.reject('visualization')
    def test_report_cannot_omit_iv_label(self):
        text = Path(self.f.arts['report']['path']).read_text().replace('IV basis:', 'Hidden basis:')
        self.f.put('report', text); self.f.refresh(); self.reject('explicit per-contract IV')
    def test_hidden_parent_report_rejected_after_rehash_and_review(self):
        text = Path(self.f.arts['report']['path']).read_text()
        self.f.put('report', '<div hidden>'+text+'</div>'); self.f.refresh(); self.reject('presentation is hidden')
    def test_hidden_or_nonrendering_containers_rejected(self):
        figure = Path(self.f.arts['figure']['path']).read_text()
        original = Path(self.f.arts['report']['path']).read_text()
        for wrapper in ('<div aria-hidden="true">FIGURE</div>', '<template>FIGURE</template>', '<details>FIGURE</details>', '<!--FIGURE-->'):
            with self.subTest(wrapper=wrapper):
                self.f.put('report', original.replace(figure, wrapper.replace('FIGURE', figure)))
                self.f.refresh(); self.reject('presentation is hidden')
    def test_known_inline_hiding_and_offscreen_styles_rejected(self):
        original = Path(self.f.arts['report']['path']).read_text()
        for style in ('display:none', 'visibility:hidden', 'opacity:0', 'position:absolute;left:-9999px', 'height:0;overflow:hidden'):
            with self.subTest(style=style):
                self.f.put('report', original.replace('<body>', '<body style="'+style+'">'))
                self.f.refresh(); self.reject('presentation is hidden')
    def test_script_hidden_or_external_styles_rejected(self):
        original = Path(self.f.arts['report']['path']).read_text()
        for content in ('<script>document.body.hidden=true</script>', '<link rel="stylesheet" href="https://example.invalid/style.css">',
                        '<style>svg{display:none}</style>', '<img src="x" onerror="document.body.hidden=true">'):
            with self.subTest(content=content):
                self.f.put('report', original.replace('</body>', content+'</body>'))
                self.f.refresh(); self.reject('presentation is hidden')
    def test_hidden_iv_labels_rejected(self):
        original = Path(self.f.arts['report']['path']).read_text()
        self.f.put('report', original.replace('<p>', '<p hidden>')); self.f.refresh(); self.reject('presentation is hidden')
    def test_trusted_static_stylesheet_accepted(self):
        original = Path(self.f.arts['report']['path']).read_text()
        self.f.put('report', original.replace('<html>', '<html><head><style>'+g.REPORT_CSS+'</style></head>'))
        self.f.refresh(); self.assertEqual(g.validate(self.f.record)['status'], 'validated')
        self.assertFalse(g.validate(self.f.record)['visual_layout_certified'])
    def test_saved_receipts_required(self):
        self.f.record['persistence']['receipts'].pop(); self.reject('save receipts')
    def test_main_review_must_cover_package(self):
        self.f.record['audit']['independent_review']['reviewed_artifact_ids'] = ['report']; self.reject('main independent review')


if __name__ == '__main__': unittest.main()
