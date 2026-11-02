from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from investment.research.information_catalog import prepare_context,compile_plan
from shared.research_sources.artifacts import SOURCE_STATE,read,save,SourceError


class InformationCatalogTests(unittest.TestCase):
    def setUp(self):
        parent=SOURCE_STATE/'tmp';parent.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)
        self.row={'record_id':'old','entity':'NOW','title':'Existing business question',
            'kind':'evidence_note','content_access':'secondary_note','source_family':'synthetic',
            'available_at':'2025-01-01T00:00:00Z','content':{'note':'Synthetic context, not original evidence.'}}
        self.request={'subject':'NOW','objective':'What evidence should be obtained?',
            'cutoff':'2025-05-01T00:00:00Z','mode':'historical','required_facets':['mechanism','adoption'],
            'budget':{'max_questions':3,'max_prior_records':2,'max_expansions':1,'max_provider_calls':8}}
        self.roster=save(self.out,{'records':[self.row]});self.refs=prepare_context(self.request,self.roster,self.out)
        self.proposal={'context_sha256':self.refs['context_ref']['sha256'],'questions':[
            self.question('mechanism','mechanism'),self.question('adoption','adoption')],
            'expansion_reason':'Initial research needs, not conclusions.'}

    def question(self,name,facet):
        return {'id':name,'facet':facet,'question':'What original evidence resolves this need?',
            'why_needed':'Synthetic ambiguity.','evidence_to_seek':'Original scoped observation.',
            'source_roles':['issuer specification','customer operations'],'capability_ids':['web_search'],
            'depends_on':[],'priority':'required','stop_rule':'Stop at the budget and retain unfilled needs.'}

    def test_future_unknown_and_unauthenticated_body_never_enter_worker_packet(self):
        future={**self.row,'record_id':'future','title':'FUTURE_SECRET_TITLE','available_at':'2026-01-01T00:00:00Z'}
        unknown={**self.row,'record_id':'unknown','title':'UNKNOWN_SECRET_TITLE','available_at':None}
        body={**self.row,'record_id':'body','title':'UNVERIFIED_BODY_TITLE','kind':'source_document','content_access':'document'}
        refs=prepare_context(self.request,save(self.out,{'records':[self.row,future,unknown,body]}),self.out)
        worker=read(refs['context_ref']);diagnostic=read(refs['diagnostic_ref'])
        self.assertEqual([x['record_id'] for x in worker['prior_records']],['old'])
        for hidden in ['FUTURE_SECRET_TITLE','UNKNOWN_SECRET_TITLE','UNVERIFIED_BODY_TITLE','quarantined_counts']:
            self.assertNotIn(hidden,str(worker))
        self.assertEqual(sum(diagnostic['quarantined_counts'].values()),3)

    def test_live_unknown_is_qualified_context_not_original_evidence(self):
        refs=prepare_context({**self.request,'mode':'live'},save(self.out,{'records':[{**self.row,'available_at':None}]}),self.out)
        self.assertIsNone(read(refs['context_ref'])['prior_records'][0]['available_at'])
        self.assertIn('do not prove',read(refs['context_ref'])['prior_access_limitations'])

    def test_capability_registry_is_reloaded_and_readiness_not_invented(self):
        worker=read(self.refs['context_ref']);web=next(p for p in worker['capabilities'] if p['id']=='web_search')
        self.assertEqual(web['readiness'],'not_checked');self.assertEqual(web['execution_state'],'manual_workflow_not_cli_tool')
        self.assertIn('Questions are research needs',worker['skill'])
        plan=read(compile_plan(self.proposal,self.refs['context_ref'],self.out))
        self.assertEqual(plan['coverage_status'],'not_fetched');self.assertFalse(plan['production_registration'])

    def test_stale_context_missing_facets_unknown_capability_and_cycles_rejected(self):
        for fault in ['context','facet','downgrade','capability','cycle','budget']:
            p=deepcopy(self.proposal)
            if fault=='context':p['context_sha256']='0'*64
            if fault=='facet':p['questions']=p['questions'][:1]
            if fault=='downgrade':p['questions'][0]['priority']='optional'
            if fault=='capability':p['questions'][0]['capability_ids']=['invented_provider']
            if fault=='cycle':p['questions'][0]['depends_on']=['adoption']
            if fault=='budget':p['questions']+=[self.question('extra1','x'),self.question('extra2','x')]
            with self.subTest(fault=fault),self.assertRaises(SourceError):compile_plan(p,self.refs['context_ref'],self.out)

    def test_expansion_preserves_parent_and_stops_at_declared_budget(self):
        parent=compile_plan(self.proposal,self.refs['context_ref'],self.out)
        p=deepcopy(self.proposal);p['questions'].append(self.question('limits','mechanism'))
        child=compile_plan(p,self.refs['context_ref'],self.out,parent_ref=parent)
        self.assertEqual(read(child)['generation'],1)
        changed=deepcopy(p);changed['questions'][0]['question']='Quietly abandon original evidence need.'
        with self.assertRaisesRegex(SourceError,'REMOVED_OR_CHANGED'):compile_plan(changed,self.refs['context_ref'],self.out,parent_ref=parent)
        request=deepcopy(self.request);request['budget']['max_questions']=4
        refs=prepare_context(request,self.roster,self.out)
        with self.assertRaisesRegex(SourceError,'PARENT_CONTEXT_STALE'):compile_plan({**p,'context_sha256':refs['context_ref']['sha256']},refs['context_ref'],self.out,parent_ref=parent)
        # A generation already at the expansion ceiling cannot reopen itself.
        no_more={**p,'questions':p['questions']+[self.question('fourth','mechanism')]}
        with self.assertRaises(SourceError):compile_plan(no_more,self.refs['context_ref'],self.out,parent_ref=child)


if __name__=='__main__':unittest.main()
