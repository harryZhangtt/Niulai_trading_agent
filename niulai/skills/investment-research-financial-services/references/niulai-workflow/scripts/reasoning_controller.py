#!/usr/bin/env python3
"""Thin incremental reasoning route. Plans work; never impersonates an agent/MCP.

Inputs are recorded evidence assessments, not automatic source authentication.
Budgets below are initial engineering defaults, not measured optimal allocations.
"""
import argparse,json
from pathlib import Path
VERSION='2026-10-24-reasoning-controller-1'
FLAGS=('required_checks_pass','material_contradiction','decision_sensitive','relevant_evidence_weak','baseline_valid','external_access_blocked')
DEFAULT={'FAST':{'calls':0,'tokens':0},'FOCUSED':{'calls':2,'tokens':1500},'DEEP':{'calls':5,'tokens':5000}}
def choose(packet):
 if type(packet.get('version')) is not int or packet['version']!=1:raise ValueError('version1 required')
 for f in FLAGS:
  if type(packet.get(f)) is not bool:raise ValueError('explicit boolean assessment required: '+f)
 for f in ('remaining_calls','remaining_tokens'):
  if type(packet.get(f)) is not int or packet[f]<0:raise ValueError('nonnegative integer budget required')
 refs=packet.get('evidence_refs')
 if not isinstance(refs,list) or not refs or not all(isinstance(r,str) and r.strip() for r in refs) or len(set(refs))!=len(refs):raise ValueError('unique actual evidence references required')
 if packet['external_access_blocked']:
  mode='BLOCKED_EXTERNAL';reason='Repair account/feed access; drain independent questions in current orchestrator.'
 elif not packet['required_checks_pass'] or packet['material_contradiction'] or not packet['baseline_valid']:
  mode='FOCUSED';reason='Repair or reconcile this exact evidence dependency; do not restart complete research.'
 elif packet['decision_sensitive'] and packet['relevant_evidence_weak']:
  mode='DEEP';reason='Compare two distinct causal/evidence paths and verify action-changing computation.'
 elif packet['decision_sensitive'] or packet['relevant_evidence_weak']:
  mode='FOCUSED';reason='One targeted investigation plus deterministic comparison.'
 else:
  mode='FAST';reason='Reuse valid evidence; no additional reasoning worker needed.'
 desired=DEFAULT.get(mode,{'calls':0,'tokens':0});calls=min(desired['calls'],packet['remaining_calls']);tokens=min(desired['tokens'],packet['remaining_tokens'])
 if mode in ('FOCUSED','DEEP') and (calls==0 or tokens==0):
  mode='BUDGET_WAIT';reason='Insufficient incremental budget; preserve exact checkpoint, not completed research.';calls=tokens=0
 elif mode=='DEEP' and (calls<2 or tokens<1500):
  mode='FOCUSED';reason='Budget fits only one targeted path; do not claim two-path independent verification.';calls=min(2,calls);tokens=min(1500,tokens)
 return {'version':VERSION,'route':mode,'reason':reason,'max_extra_tool_calls':calls,'incremental_model_token_budget':tokens,
   'evidence_refs':refs,'executes_agents':False,'validates_sources':False,'completes_research':False,
   'budget_enforcement':'Orchestrator must record actual usage; this deterministic planner cannot intercept native model/tool calls.'}
def decode(text):
 def unique(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('duplicate key')
   d[k]=v
  return d
 return json.loads(text,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=choose(decode(Path(a.input).read_text()));Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
