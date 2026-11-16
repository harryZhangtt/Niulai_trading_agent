"""Strict terminal translator with complete execution binding and no raw publication."""
from __future__ import annotations
from typing import Any, Dict, Mapping
from .contracts import MODEL, PROVIDER_ID, ContractError, ExecutionBinding, require, sha256_bytes, strict_json_loads
TERMINAL_KEYS=frozenset(('type','model','provider_id','request_id','output_sha256'))
def translate(stdout:bytes,gateway:Mapping[str,Any],binding:ExecutionBinding)->Dict[str,Any]:
 try: text=stdout.decode('utf-8','strict')
 except UnicodeDecodeError as exc: raise ContractError('TERMINAL_UTF8') from exc
 terminals=[]
 for line in text.splitlines():
  if not line.strip(): continue
  value=strict_json_loads(line); require(type(value) is dict,'TERMINAL_EVENT_SHAPE')
  if value.get('type')=='response.completed': terminals.append(value)
 require(len(terminals)==1,'TERMINAL_CARDINALITY')
 item=terminals[0]; require(set(item)==TERMINAL_KEYS,'TERMINAL_KEYS'); require(item['model']==MODEL and item['provider_id']==PROVIDER_ID,'TERMINAL_IDENTITY')
 require(gateway.get('upstream_attempts')==1 and gateway.get('terminal_present') is True,'TERMINAL_GATEWAY_DISAGREEMENT')
 return {'kind':'terminal','version':'terminal-translation-v1','binding':binding.public(),'exactly_one':True,'model':MODEL,'provider_id':PROVIDER_ID,'request_id_sha256':sha256_bytes(str(item['request_id']).encode()),'output_sha256':item['output_sha256'],'raw_public':False,'recognized':True}
