from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from investment.research.contribution import validate_proposal, calculate_scenario,locate_quote
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.research_sources.store import Store


class ContributionTests(unittest.TestCase):
    def setUp(self):
        parent=SOURCE_STATE/'tmp';parent.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'store')
        raw=save(self.root,b'Synthetic source: one managed asset consumes one subscription unit.',suffix='txt')
        self.source={'provider':'synthetic','source_url':'https://example.com/synthetic','upstream_id':'synthetic',
            'raw':raw,'text':raw,'available_at':'2025-05-01T23:59:59Z','modified_at':None,
            'access_level':'document','availability_basis':'issuer_dated_reconstruction'}
        self.ref=save(self.root,self.source)
        self.payload={'entity':'NOW','metric':'meter','period':'2025_contract','currency':'not_applicable',
            'unit':'SU/asset','basis':'contract meter','available_at':self.source['available_at'],'source_ref':self.ref}
        self.store.create('create','e1',self.payload)
        baseline={'entity':'NOW','as_of':'2025-04-30T23:59:59Z','hypotheses':[{'id':'h1','text':'Synthetic prior'}],
            'forecast':{'period':'FY2025Q2','currency':'USD','unit':'USD millions','basis':'GAAP subscription revenue','point':'100'}}
        self.context={'case_id':'synthetic','entity':'NOW','cutoff':'2025-05-07T23:59:59Z',
            'baseline_ref':save(self.root,baseline),'store_directory':str(self.root/'store'),
            'bindings':[{'observation_id':'e1','revision':1,'lifecycle_revision':1}],
            'allow_reconstructed_history':True}
        self.proposal={'case_id':'synthetic','entity':'NOW','baseline_sha256':self.context['baseline_ref']['sha256'],
            'observed_facts':[{'evidence_id':'e1','revision':1,'lifecycle_revision':1,'source_sha256':self.ref['sha256'],
                **{k:self.payload[k] for k in ['entity','period','currency','unit','basis']},
                'claim':'A synthetic meter exists.','quote':'one managed asset consumes one subscription unit'}],
            'incremental_contribution':{'kind':'refinement','prior_hypothesis_ids':['h1'],'explanation':'Synthetic refinement'},
            'economic_inference':'Possible per-asset economics, not proved billing.','unproved_links':['paid price unknown'],
            'suggested_change':{'operation':'add_pending_driver','rationale':'Do not auto-commit.'},
            'forecast':{'period':'FY2025Q2','currency':'USD','unit':'USD millions','basis':'GAAP subscription revenue',
                'point':'110','assumption_status':'proposed_assumption','supporting_evidence_ids':['e1'],
                'rationale':'Synthetic explicit assumption, not established by this meter.'}}

    def test_valid_handoff_does_not_establish_economics(self):
        checked=validate_proposal(self.proposal,self.context)
        self.assertEqual(checked['forecast_arithmetic']['delta'],'10')
        self.assertEqual(checked['semantic_support'],'requires_independent_review')
        self.assertFalse(checked['auto_commit_research'])
        self.assertTrue(checked['limitations'])

    def test_reference_scope_and_baseline_faults(self):
        for where,key,value in [('fact','evidence_id','invented'),('fact','revision',2),
            ('fact','lifecycle_revision',2),('fact','source_sha256','b'*64),('fact','entity','CRM'),
            ('fact','period','FY2026'),('fact','currency','EUR'),('fact','unit','USD billions'),
            ('fact','basis','recognized revenue'),('fact','quote','not present in the actual source'),
            ('proposal','baseline_sha256','c'*64)]:
            p=deepcopy(self.proposal);target=p['observed_facts'][0] if where=='fact' else p;target[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(SourceError):validate_proposal(p,self.context)

    def test_distinct_claims_may_share_one_source_but_duplicate_claims_rejected(self):
        p=deepcopy(self.proposal)
        p['observed_facts'].append({**p['observed_facts'][0],
            'claim':'The source defines a subscription unit, not a public dollar price.',
            'quote':'subscription unit'})
        self.assertEqual(len(validate_proposal(p,self.context)['checks']),2)
        p['observed_facts'].append(deepcopy(p['observed_facts'][0]))
        with self.assertRaisesRegex(SourceError,'CONTRIBUTION_DUPLICATE_CLAIM'):validate_proposal(p,self.context)

    def test_whitespace_only_quote_matching_retains_exact_archived_span(self):
        original='Header\nSubscription gross profit  | $2,444  | 81.5%  | \u00a0  | $2,532\nEnd'
        quote='Subscription gross profit | $2,444 | 81.5% | | $2,532'
        found=locate_quote(quote,original,self.source['text'])
        self.assertEqual(original[found['start']:found['end']],found['text'])
        self.assertEqual(found['text_ref'],self.source['text'])
        self.assertNotEqual(found['text'],quote)
        for changed in [quote.replace('81.5%','81.6%'),quote.replace('profit','loss'),' '*12]:
            with self.subTest(changed=changed),self.assertRaisesRegex(SourceError,'QUOTE_NOT_IN_SOURCE'):
                locate_quote(changed,original,self.source['text'])
        p=deepcopy(self.proposal);p['observed_facts'].append({**p['observed_facts'][0],
            'quote':'one managed asset\nconsumes one subscription unit'})
        with self.assertRaisesRegex(SourceError,'DUPLICATE_CLAIM'):validate_proposal(p,self.context)

    def test_forecast_scope_and_nonfinite_rejected(self):
        for key,value in [('period','FY2025Q3'),('currency','EUR'),('unit','USD billions'),
                          ('point','NaN'),('point','-1'),('assumption_status','unchanged_assumption')]:
            p=deepcopy(self.proposal);p['forecast'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_proposal(p,self.context)

    def test_future_unknown_and_revised_sources_rejected(self):
        for i,changes in enumerate([{'available_at':'2026-01-01T00:00:00Z'},
            {'available_at':None},{'modified_at':'2026-01-01T00:00:00Z'}, {'access_level':'metadata'}]):
            source={**self.source,**changes};ref=save(self.root,source)
            payload={**self.payload,'source_ref':ref,'available_at':source['available_at']}
            row=self.store.revise('mutate-'+str(i),'e1',payload,i+1)
            c=deepcopy(self.context);c['bindings'][0].update(revision=row['revision'],lifecycle_revision=row['lifecycle_revision'])
            p=deepcopy(self.proposal);p['observed_facts'][0].update(revision=row['revision'],lifecycle_revision=row['lifecycle_revision'],source_sha256=ref['sha256'])
            with self.assertRaises(SourceError):validate_proposal(p,c)

    def test_withdrawal_corruption_and_unapproved_vintage(self):
        c={**self.context,'allow_reconstructed_history':False}
        with self.assertRaisesRegex(SourceError,'HISTORICAL_VERSION'):validate_proposal(self.proposal,c)
        Path(self.source['raw']['path']).write_bytes(b'corruption')
        with self.assertRaisesRegex(SourceError,'HASH_MISMATCH'):validate_proposal(self.proposal,self.context)

    def test_exact_conditional_revenue_profit_fcff_and_pv(self):
        v={'billed_units':'1000','annual_net_price_usd':'120','incremental_margin':'0.25',
           'cash_conversion':'0.8','years':1,'wacc':'0.2'}
        out=calculate_scenario(v)
        self.assertEqual(Decimal(out['annual_revenue_usd']),Decimal('120000'))
        self.assertEqual(Decimal(out['annual_operating_profit_usd']),Decimal('30000'))
        self.assertEqual(Decimal(out['annual_fcff_usd']),Decimal('24000'))
        self.assertEqual(Decimal(out['finite_horizon_fcff_pv_usd']),Decimal('20000'))
        self.assertFalse(out['terminal_value_included'])
        for key,value in [('years',True),('years',11),('incremental_margin','1.2'),('wacc','NaN'),('billed_units','-1')]:
            with self.subTest(key=key),self.assertRaises(ValueError):calculate_scenario({**v,key:value})


if __name__=='__main__':unittest.main()
