"""Candidate runtime information-plan contracts, separate from stored evidence.

No provider/model calls, active registration, semantic admission or plan-head write.
Unknown-date history is quarantined before the worker packet is constructed.
"""
from collections import Counter
import json

from jsonschema import Draft202012Validator
from shared.research_sources.artifacts import ROOT,digest,read,require,save
from shared.research_sources.fetch import HOSTS
from shared.research_sources.store import instant

VERSION='information-catalog-0.1.0'
SKILL=ROOT/'investment/research/skills/information-catalog/SKILL.md'
ID={'type':'string','pattern':'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$'}
TEXT={'type':'string','minLength':1,'maxLength':1800}


def obj(properties):
    return {'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}


def arr(items,maximum=12):return {'type':'array','items':items,'maxItems':maximum}


QUESTION=obj({'id':ID,'facet':ID,'question':TEXT,'why_needed':TEXT,
    'evidence_to_seek':TEXT,'source_roles':arr(TEXT,6),'capability_ids':arr(ID,5),
    'depends_on':arr(ID),'priority':{'enum':['required','optional','exploration']},'stop_rule':TEXT})
PLAN_SCHEMA=obj({'context_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
    'questions':{**arr(QUESTION,24),'minItems':1},'expansion_reason':TEXT})
REQUEST_SCHEMA=obj({'subject':ID,'objective':TEXT,'cutoff':TEXT,
    'mode':{'enum':['live','historical']},
    'required_facets':{**arr(ID,12),'minItems':1,'uniqueItems':True},
    'budget':obj({'max_questions':{'type':'integer','minimum':1,'maximum':24},
                  'max_prior_records':{'type':'integer','minimum':1,'maximum':64},
                  'max_expansions':{'type':'integer','minimum':0,'maximum':2},
                  'max_provider_calls':{'type':'integer','minimum':1,'maximum':40}})})


def prepare_context(request,roster_ref,directory):
    """Return separate worker and host-only refs. Never give diagnostics to model."""
    require(Draft202012Validator(REQUEST_SCHEMA).is_valid(request),'INFO_REQUEST_SCHEMA')
    cutoff=instant(request['cutoff']);roster=read(roster_ref)
    providers=json.loads((ROOT/'shared/research_sources/catalog.json').read_text())
    selected=[];quarantine=Counter();eligible_count=0
    for row in roster['records']:
        if row['entity']!=request['subject']:continue
        at=row['available_at']
        if at is None and request['mode']=='historical':
            quarantine['availability_unknown']+=1;continue
        if at is not None and instant(at)>cutoff:
            quarantine['after_cutoff']+=1;continue
        # Only an independently established source-version boundary may support
        # point-in-time document access. A dated title or note cannot provide it.
        if request['mode']=='historical' and row['content_access']=='document':
            quarantine['source_version_not_authenticated']+=1;continue
        eligible_count+=1
        if len(selected)<request['budget']['max_prior_records']:
            selected.append({k:row[k] for k in ['record_id','title','kind','content_access',
                'source_family','available_at','content']})
    capabilities=[]
    for provider in providers['providers']:
        capabilities.append({**provider,'readiness':'not_checked',
            'execution_state':'manual_workflow_not_cli_tool' if provider['id']=='web_search' else
                'optional_not_default' if provider['id']=='arxiv_mcp_candidate' else 'library_only_not_connectivity_proof',
            'allowed_hosts':sorted(HOSTS) if provider['id']=='official_document' else []})
    worker={'version':VERSION,'request':request,'prior_records':selected,
        'prior_access_limitations':'Catalog metadata and secondary notes do not prove original document access or truth.',
        'capabilities':capabilities,'capability_catalog_sha256':digest(providers),
        'skill':SKILL.read_text(),'skill_sha256':digest(SKILL.read_text()),
        'output_schema':PLAN_SCHEMA,'scope':'question_planning_only_not_facts_or_coverage'}
    diagnostic={'source_roster_ref':roster_ref,'quarantined_counts':dict(quarantine),
        'eligible_prior_records':eligible_count,'truncated':eligible_count>len(selected),
        'historical_document_replay_broker':'not_implemented_by_this_catalog_context',
        'worker_excludes_quarantined_metadata':True}
    return {'context_ref':save(directory,worker),'diagnostic_ref':save(directory,diagnostic)}


def compile_plan(proposal,context_ref,directory,*,parent_ref=None):
    """Freeze a bounded plan, not a claim that its questions are sufficient."""
    require(Draft202012Validator(PLAN_SCHEMA).is_valid(proposal),'INFO_PLAN_SCHEMA')
    context=read(context_ref);require(context['version']==VERSION,'INFO_CONTEXT_VERSION')
    require(proposal['context_sha256']==context_ref['sha256'],'INFO_CONTEXT_STALE')
    request=context['request'];questions=proposal['questions'];budget=request['budget']
    require(len(questions)<=budget['max_questions'],'INFO_QUESTION_BUDGET')
    require(set(request['required_facets'])<={q['facet'] for q in questions},'INFO_REQUIRED_FACET_MISSING')
    require(set(request['required_facets'])<={q['facet'] for q in questions if q['priority']=='required'},
            'INFO_REQUIRED_FACET_DOWNGRADED')
    capabilities={p['id'] for p in context['capabilities']};seen=set()
    for q in questions:
        require(q['id'] not in seen,'INFO_QUESTION_DUPLICATE')
        require(set(q['depends_on'])<=seen,'INFO_DEPENDENCY_UNKNOWN_OR_CYCLIC')
        require(set(q['capability_ids'])<=capabilities,'INFO_CAPABILITY_UNKNOWN')
        require(bool(q['source_roles']) and bool(q['capability_ids']),'INFO_ROUTE_INTENT_REQUIRED')
        seen.add(q['id'])
    generation=0
    if parent_ref is not None:
        parent=read(parent_ref)
        require(parent['context_ref']['sha256']==context_ref['sha256'],'INFO_PARENT_CONTEXT_STALE')
        read(parent['context_ref'])
        generation=parent['generation']+1
        old={q['id']:q for q in parent['proposal']['questions']};new={q['id']:q for q in questions}
        require(all(new.get(key)==value for key,value in old.items()),'INFO_PARENT_QUESTION_REMOVED_OR_CHANGED')
        require(len(new)>len(old),'INFO_EXPANSION_WITHOUT_NEW_QUESTION')
    require(generation<=budget['max_expansions'],'INFO_EXPANSION_BUDGET')
    plan={'version':VERSION,'context_ref':context_ref,'parent_ref':parent_ref,'generation':generation,
        'proposal':proposal,'budget':budget,'scope':'retrieval_plan_only',
        'semantic_completeness':'requires_source_grounded_review','coverage_status':'not_fetched',
        'production_registration':False}
    return save(directory,plan)
