import importlib.util, json, hashlib
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[5]
PKG=ROOT/'shared/job_runtime/candidates/claude_502_authority_process_v1'; FIX=ROOT/'shared/job_runtime/tests/fixtures/claude_502_authority_process_v1'
NAME='shared.job_runtime.candidates.claude_502_authority_process_v1'
def load_package():
    if NAME not in sys.modules:
        spec=importlib.util.spec_from_file_location(NAME,PKG/'__init__.py',submodule_search_locations=[str(PKG)]); module=importlib.util.module_from_spec(spec); sys.modules[NAME]=module; spec.loader.exec_module(module)
    return sys.modules[NAME]
def fixture(name): return json.loads((FIX/name).read_text())
CAP=(b'RUNTIME_CAPABILITY!'*2)[:32]; REG=(b'REGISTRAR_CAPABILITY!'*2)[:32]; KEY=(b'AUTHORITY_TEST_KEY!'*2)[:32]
def make_authority(uid=501,generation=1):
    p=load_package(); return p.Authority(uid,CAP,REG,generation,key=KEY,clock=p.ManualClock(1000))
def session(authority,role='runtime',sid='session-1',cap=None):
    p=load_package(); from shared.job_runtime.candidates.claude_502_authority_process_v1.authority import MemoryServerSession
    _,server_ep=p.MemoryTransport.pair(501); server=MemoryServerSession(authority,server_ep)
    return p.AuthorityClient(server.exchange,cap or (REG if role=='registrar' else CAP),sid,role)
def state(binding_result,phase='READY',retry=0,attempt='attempt-1'):
    return {'version':1,'run':'run-1','campaign':'R7','job':'job-1','slot':'slot-1','attempt':attempt,'phase':phase,'retry_count':retry,'binding_handle':binding_result['binding_handle'],'binding_digest':binding_result['binding_digest']}
def setup(authority):
    b=fixture('binding.json'); reg=session(authority,'registrar','registrar-1').call('register_expected_binding',b); return b,reg
def observe(client,reg,retry=5):
    return client.call('observe_pre_forward_502',{'binding_handle':reg['binding_handle'],'request_ordinal':1,'status':502,'upstream_attempts':0,'upstream_count_delta':0,'submission':'not_submitted','retry_after_seconds':retry})
