from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from shared.research_sources.acquisition_contracts import CheckedEiyEvaluationManifestV4,ContractError
from investment.research.acquisition_eiy_checker import check_eiy_evaluation_v4,EiyCheckerError
from .contracts import InformationYieldError,safe_rel
from .evaluator import evaluate_fresh_eiy_evaluation,evaluate_fresh_now_evaluation
from .manifest import HeldWorkspace
class Parser(argparse.ArgumentParser):
 def error(self,_message):raise InformationYieldError('EIY_CLI_ARGUMENT')
def evaluate_path(manifest_relative:str,*,workspace_root:Path,checker=check_eiy_evaluation_v4,output_relative=None,expected_mode=None):
 with HeldWorkspace(Path(workspace_root)) as held:
  raw=held.read_json(safe_rel(manifest_relative))
  if isinstance(raw,dict) and raw.get('schema_version') in {'information-yield-evaluation-1','information-yield-evaluation-2'}:raise InformationYieldError('EIY_SELF_ASSERTED_BUNDLE_DISABLED')
  if isinstance(raw,dict) and raw.get('schema_version')=='information-yield-evaluation-3':raise InformationYieldError('EIY_V3_EVALUATION_CONTEXT_REQUIRED')
  try:manifest=CheckedEiyEvaluationManifestV4.from_mapping(raw);evaluation=checker(manifest.evaluation_custody_ref,read_ref=held.reopen_json,workspace_root=Path(workspace_root))
  except (ContractError,EiyCheckerError) as error:raise InformationYieldError(str(error)) from None
  audit=evaluation.to_audit_mapping();mode=audit['context']['mode']
  if expected_mode is not None and mode!=expected_mode:raise InformationYieldError('EIY_NOW_CONFIRMATION_FORBIDDEN' if expected_mode=='evaluation' else 'EIY_NOW_ONLY')
  result=evaluate_fresh_now_evaluation(fresh_evaluation=evaluation) if mode=='now_diagnostic' else evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation)
  inputs=evaluation.input_paths|{safe_rel(manifest_relative)}
  if output_relative is not None:return result,inputs,held.publish(output_relative,result,input_paths=inputs)
  return result,inputs
def main(argv=None):
 parser=Parser(prog='information-yield-v4');sub=parser.add_subparsers(dest='command',required=True)
 for command in ('evaluate','diagnose-now'):
  p=sub.add_parser(command);p.add_argument('--workspace-root',required=True);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
 try:
  a=parser.parse_args(argv);root=Path(a.workspace_root)
  if not root.is_absolute():raise InformationYieldError('EIY_ROOT_ABSOLUTE_REQUIRED')
  expected_mode='now_diagnostic' if a.command=='diagnose-now' else 'evaluation';result,_inputs,reused=evaluate_path(a.manifest,workspace_root=root,output_relative=a.output,expected_mode=expected_mode);expected='information-yield-now-diagnostic-result-4' if a.command=='diagnose-now' else 'information-yield-result-4'
  if result['schema_version']!=expected:raise InformationYieldError('EIY_CLI_MODE')
  print(json.dumps({'status':'ok','summary_sha256':result['summary_sha256'],'reused':reused},sort_keys=True,separators=(',',':')));return 0
 except InformationYieldError as error:
  code=str(error);print(json.dumps({'status':'error','code':code},sort_keys=True,separators=(',',':')));return 2 if code.startswith(('EIY_CLI','EIY_PATH','EIY_ROOT','EIY_MANIFEST','EIY_OUTPUT')) else 1
 except Exception:
  print('{"code":"EIY_INTERNAL","status":"error"}');return 2
if __name__=='__main__':sys.exit(main())
