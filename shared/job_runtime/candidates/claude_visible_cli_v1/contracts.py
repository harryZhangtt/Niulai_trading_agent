"""Pinned, disabled Claude visible-session CLI grammar contract."""
from pathlib import Path
from types import MappingProxyType
import hashlib,json,re
ROOT=Path(__file__).parent
FIXTURE_ROOT=ROOT.parents[1]/"tests"/"fixtures"/"claude_visible_cli_v1"
class CliContractError(ValueError):pass
EXPECTED={
 "launch":tuple(sorted(("--background","--name","--model","--effort","--permission-mode","--setting-sources","--settings","--strict-mcp-config","--mcp-config","--tools","--allowedTools","--disallowedTools"))),
 "list":("agents","--json","--all","--cwd"),"logs":("logs","<id|name>"),"attach":("attach","<id|name>"),"stop":("stop","<id>"),
 "persistence":"on_by_absence_of_no_session_persistence","resume_allowed":False,"max_turns_cli_supported":False,"max_budget_cli_supported":False}
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _file_sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while True:
   chunk=f.read(1024*1024)
   if not chunk:break
   h.update(chunk)
 return h.hexdigest()
def _freeze(value):
 if type(value) is dict:return MappingProxyType({k:_freeze(v) for k,v in value.items()})
 if type(value) is list:return tuple(_freeze(v) for v in value)
 return value
def load_contract(binary_path, contract_path=None):
 binary=Path(binary_path).resolve(strict=True);source=Path(contract_path) if contract_path is not None else ROOT/'contract.json';value=json.loads(source.read_text())
 if set(value)!={"schema_version","enabled","invocation_prohibited","binary_sha256","binary_bytes","fixtures","semantics"}:raise CliContractError("CLI_CONTRACT_SHAPE")
 if value["schema_version"]!="claude-visible-cli-contract-1" or value["enabled"] is not False or value["invocation_prohibited"] is not True:raise CliContractError("CLI_CONTRACT_OPEN")
 if not binary.is_file() or binary.stat().st_size!=value['binary_bytes'] or _file_sha(binary)!=value['binary_sha256']:raise CliContractError("CLI_BINARY_DRIFT")
 names=set();expected_names={"agents-help.txt","attach-help.txt","logs-help.txt","root-help.txt","stop-help.txt","version.txt"}
 for row in value["fixtures"]:
  if type(row) is not dict or set(row)!={"name","sha256","bytes"} or row["name"] in names:raise CliContractError("CLI_FIXTURE_INVALID")
  if Path(row["name"]).name!=row["name"]:raise CliContractError("CLI_FIXTURE_INVALID")
  names.add(row["name"]);raw=(FIXTURE_ROOT/row["name"]).read_bytes()
  if _sha(raw)!=row["sha256"] or len(raw)!=row["bytes"]:raise CliContractError("CLI_FIXTURE_DRIFT")
 if names!=expected_names:raise CliContractError("CLI_FIXTURE_SET_INVALID")
 semantics=value['semantics'];normalized={k:(tuple(v) if type(v) is list else v) for k,v in semantics.items()}
 if normalized!=EXPECTED:raise CliContractError("CLI_SEMANTICS_INVALID")
 root=(FIXTURE_ROOT/'root-help.txt').read_text();agents=(FIXTURE_ROOT/'agents-help.txt').read_text();logs=(FIXTURE_ROOT/'logs-help.txt').read_text();attach=(FIXTURE_ROOT/'attach-help.txt').read_text();stop=(FIXTURE_ROOT/'stop-help.txt').read_text()
 if any(flag not in root for flag in EXPECTED['launch']) or '--max-turns' in root:raise CliContractError("CLI_LAUNCH_GRAMMAR_MISSING")
 if '--max-budget-usd' not in root or 'only works with --print' not in root.replace('`',''):raise CliContractError("CLI_BUDGET_SCOPE_INVALID")
 if any(flag not in agents for flag in ('--json','--all','--cwd')):raise CliContractError("CLI_LIST_GRAMMAR_MISSING")
 if '<id|name>' not in logs or '<id|name>' not in attach or '<id>' not in stop or '<id|name>' in stop:raise CliContractError("CLI_CONTROL_GRAMMAR_MISSING")
 return _freeze(value)
