#!/usr/bin/env python3
"""Same-language editorial parity check, not semantic truth or publication approval.
Input: {version:1,before:{claims:[{id,text,evidence_class,certainty,polarity,
source_refs,units,horizon,protected_literals}],instrument:{...},action:{...}},after:{...}}.
"""
import argparse
from collections import Counter
import json
import re
from pathlib import Path
import hashlib
VERSION='2026-10-24-financial-communication-1'
CLASSES={'observed_fact','management_claim','model_output','assumption','judgment','unresolved'}
NUMBER=re.compile(r'(?<![\w])(?:[+\-−–]\s*)?(?:[$€£¥]\s*)?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|bps?|万|亿|million|billion|shares|contracts|days|months|years|股|张|天|个月|年))?(?![\w])',re.I)
CONTRACT=re.compile(r'\b[A-Z][A-Z0-9.]{0,5}\d{6}[CP]\d{8}\b')
STRONG=re.compile(r'\b(?:guaranteed|certainly|risk.free|will definitely|proven alpha)\b|稳赚|保证盈利|必然上涨|确定赚钱',re.I)
LEXICAL = {
 'currency_code': re.compile(r'\b(?:USD|EUR|GBP|JPY|CNY|RMB|HKD|CAD|AUD|CHF)\b',re.I),
 'month_name': re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b',re.I),
 'uncertain_modal': re.compile(r'\b(?:may|might|could)\b',re.I),
 'assertive_modal': re.compile(r'\b(?:will|must)\b',re.I),
 'positive_direction': re.compile(r'\b(?:gain|gains|gained|profit|profits|profitable|rise|rises|rising|increase|increases|increased)\b',re.I),
 'negative_direction': re.compile(r'\b(?:lose|loses|lost|loss|losses|fall|falls|falling|decline|declines|decrease|decreases|decreased)\b',re.I),
}
META=('evidence_class','certainty','polarity','source_refs','units','horizon','protected_literals')
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def numeric_tokens(text):return Counter(x.group().strip() for x in NUMBER.finditer(text))
def claims(obj):
 rows=obj.get('claims');out={}
 if not isinstance(rows,list) or not rows:raise ValueError('nonempty claims required')
 for r in rows:
  if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id'] or r['id'] in out:raise ValueError('unique claim IDs required')
  if not isinstance(r.get('text'),str) or not r['text'].strip():raise ValueError('text required')
  if any(k not in r for k in META):raise ValueError('complete protected metadata required')
  if r['evidence_class'] not in CLASSES or type(r['certainty']) is not int or r['certainty'] not in range(4):raise ValueError('evidence class / certainty invalid')
  if r['polarity'] not in {'positive','negative','mixed','neutral'}:raise ValueError('polarity required')
  if not isinstance(r['source_refs'],list) or not r['source_refs'] or not all(isinstance(x,str) and x for x in r['source_refs']):raise ValueError('source/model references required')
  if not isinstance(r['protected_literals'],list) or not all(isinstance(x,str) and x for x in r['protected_literals']):raise ValueError('protected literals must be strings')
  if not isinstance(r['horizon'],str) or not r['horizon'] or not isinstance(r['units'],str) or not r['units']:raise ValueError('horizon/units required; use explicit not_applicable')
  out[r['id']]=r
 return out

def check(packet):
 errors=[];warnings=[]
 if packet.get('version')!=1:raise ValueError('packet version1 required')
 before=packet.get('before');after=packet.get('after')
 if not isinstance(before,dict) or not isinstance(after,dict):raise ValueError('before/after required')
 a,b=claims(before),claims(after)
 if a.keys()!=b.keys():errors.append('claim IDs added/removed')
 for field in ('instrument','action'):
  if field not in before or field not in after or not isinstance(before[field],dict) or not before[field]:raise ValueError(field+' object required')
  if before[field]!=after[field]:errors.append(field+' changed')
 for key in sorted(a.keys() & b.keys()):
  x,y=a[key],b[key]
  for field in META:
   if x[field]!=y[field]:errors.append(key+': protected '+field+' changed')
  if numeric_tokens(x['text'])!=numeric_tokens(y['text']):errors.append(key+': signed numeric/currency/unit tokens changed')
  for category,pattern in LEXICAL.items():
   tx,ty=pattern.findall(x['text']),pattern.findall(y['text'])
   mismatch=(Counter(v.casefold() for v in tx)!=Counter(v.casefold() for v in ty)) if category in {'currency_code','month_name'} else len(tx)!=len(ty)
   if mismatch:errors.append(key+': protected lexical '+category+' changed; review as research revision')
  if Counter(CONTRACT.findall(x['text']))!=Counter(CONTRACT.findall(y['text'])):errors.append(key+': contract symbol changed')
  for phrase in x['protected_literals']:
   if phrase not in x['text'] or phrase not in y['text']:errors.append(key+': protected literal absent: '+phrase)
  if len(STRONG.findall(y['text']))>len(STRONG.findall(x['text'])):errors.append(key+': certainty-amplifying phrase introduced')
  if x['text']!=y['text']:warnings.append(key+': prose requires independent semantic review of negation, attribution, causality and certainty')
 return {'version':VERSION,'status':'rejected' if errors else 'parity_pass_semantic_review_required','before_sha256':digest(before),'after_sha256':digest(after),'errors':errors,'warnings':warnings,'semantic_truth_verified':False,'readability_verified':False,'publication_approved':False}
def decode(text):
 def unique(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('duplicate JSON key')
   d[k]=v
  return d
 return json.loads(text,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=check(decode(Path(a.input).read_text()));Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2));return bool(r['errors'])
if __name__=='__main__':raise SystemExit(main())
