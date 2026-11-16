"""Disabled v8 one-shot Codex app-server first-200 catalog executor."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,os,re,selectors,shutil,signal,stat,subprocess,threading,time
from pathlib import Path
from typing import Any,Dict,Mapping,Optional,Sequence,Tuple
from .integration import _consume_transient_token
from .gateway import GatewayObserver,ProviderCatalog

RELEASE="0.167.0";MODEL="gpt-6.1-sol";PROVIDER_ID="chatgpt-codex-catalog-r9"
ARGV_SUFFIX=("-c",f'model_provider="{PROVIDER_ID}"',"-c",f'model_providers.{PROVIDER_ID}={{name="ChatGPT Codex Catalog R9",base_url="<SEALED_LOOPBACK_BASE>/backend-api/codex",wire_api="responses",requires_openai_auth=true,supports_websockets=true,request_max_retries=0,stream_max_retries=0}}',"app-server","--listen","stdio://")
FIXED_GRANT=("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-preflight-r9-gateway-grant.json",1497,"1d4fbed0723c7c444666c2f5e1b0fb11a94b22d7150d065528de6922b8e76a45")
FIXED_REVIEW=("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-preflight-r9-gateway-independent-review.json",7228,"f905268fd2ea077c5030824f5dff132cc77a27b82af73a4e3ae787733e6ed531")
V7_PRODUCER=("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v7-producer-verification.json",10079,"11cf2f102fc953acfb8468edcad77dda94195c846eac886ac5b9855a167308b5")
V7_REVIEW=("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v7-independent-review.json",15664,"7f84134641537c5264853e5ca0b193a064a2d5710cba34f504cb772941e211fd")
SOURCE_RESEARCH=("tuning/architecture/r6_one_off_codex_catalog_v1/source-research-v8.json",2840,"2ca78dceef8353c2fa56d655e7a294b7b6ad4152b9897dd353467b22651c1353")
HISTORY=(
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-producer-verification.json",5592,"2320ef9eb6fd411645a8c940bf6d7ec1285038e46dc6e0411443654dd55bb71c"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v2-producer-verification.json",6788,"3ed3cf694587b093654298121ea620a1265c782999ccb9df6d1218a57d159374"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v3-producer-verification.json",7291,"62750794ab234e7253f6ef2fda7fe5b3788734ce6414dbeadf9eb18731642648"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v4-producer-verification.json",8056,"1d029bff9382d38a110d77a9bb511e17acc62a246e52a21fee79dc20aecd404c"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v4-independent-review.json",9023,"5a4322f6746f8e2a18f18a77f7263c851af338cf0299fed15e037c41329592f7"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v5-producer-verification.json",8931,"fec97e735126e85627ef4d9dcaa3ea05d667f8a9a222899bb5cb3a61dc3ec732"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v6-producer-verification.json",9264,"6bf5f1e7ca251707d6e9d1eb487a5481d0b86241240b37aaf81f606292564a9b"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v6-independent-review.json",10584,"2669d2254af3a91049c6a9068ca2b3729a854687ee95eaca88e4c30935eb2112"),V7_PRODUCER,V7_REVIEW)
_ID=re.compile(r"^[a-z0-9][a-z0-9._-]{7,127}$");MAX_RPC_LINE=1024*1024
INIT={"id":1,"method":"initialize","params":{"clientInfo":{"name":"r6-one-off-codex-catalog-v8","version":"8"}}}
INITIALIZED={"method":"initialized"};MODEL_LIST={"id":2,"method":"model/list","params":{"includeHidden":True}}
class CatalogError(RuntimeError):pass

def _digest(raw:bytes)->str:return hashlib.sha256(raw).hexdigest()
def _repository_root()->Path:return Path(__file__).resolve().parents[4]
def _read_bound(root:Path,ref:Tuple[str,int,str])->bytes:
    relative=Path(ref[0])
    if relative.is_absolute() or ".." in relative.parts:raise CatalogError("bound artifact path rejected")
    root_real=root.resolve();current=root_real
    for part in relative.parts[:-1]:
        current=current/part
        try:info=os.lstat(current)
        except OSError as exc:raise CatalogError("bound artifact unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise CatalogError("bound artifact parent rejected")
    path=root_real/relative;flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)
    try:fd=os.open(str(path),flags)
    except OSError as exc:raise CatalogError("bound artifact unavailable") from exc
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:raise CatalogError("bound artifact ownership rejected")
        chunks=[]
        while True:
            chunk=os.read(fd,1024*1024)
            if not chunk:break
            chunks.append(chunk)
    finally:os.close(fd)
    raw=b"".join(chunks)
    if len(raw)!=ref[1] or _digest(raw)!=ref[2]:raise CatalogError("bound artifact identity mismatch")
    return raw

def _strict(raw:bytes)->Any:
    def pairs(items:Sequence[Tuple[str,Any]])->Dict[str,Any]:
        out={}
        for key,value in items:
            if key in out:raise CatalogError("duplicate JSON key")
            out[key]=value
        return out
    try:return json.loads(raw.decode("utf-8","strict"),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in()).throw(CatalogError("non-finite JSON")))
    except CatalogError:raise
    except Exception as exc:raise CatalogError("malformed JSON") from exc

def _read_verified_binary(path:Path,size:int,sha:str)->bytes:
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)
    try:fd=os.open(str(path),flags)
    except OSError as exc:raise CatalogError("binary open rejected") from exc
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022:raise CatalogError("binary ownership rejected")
        chunks=[]
        while True:
            chunk=os.read(fd,1024*1024)
            if not chunk:break
            chunks.append(chunk)
    finally:os.close(fd)
    raw=b"".join(chunks)
    if len(raw)!=size or _digest(raw)!=sha:raise CatalogError("binary identity mismatch")
    return raw

def _private_parent(path:Path)->Path:
    parent=Path(os.path.abspath(str(path)))
    try:info=os.lstat(parent)
    except FileNotFoundError:parent.mkdir(mode=0o700,parents=True,exist_ok=False);info=os.lstat(parent)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise CatalogError("custody parent must already be owner-private")
    return parent

def _sealed(port:int)->Tuple[str,...]:
    base=f"http://127.0.0.1:{port}";result=tuple(v.replace("<SEALED_LOOPBACK_BASE>",base) for v in ARGV_SUFFIX)
    if sum(v.count("<SEALED_LOOPBACK_BASE>") for v in ARGV_SUFFIX)!=1 or any("<SEALED_LOOPBACK_BASE>" in v for v in result):raise CatalogError("loopback seal rejected")
    return result

def _write(proc:subprocess.Popen[bytes],message:Mapping[str,Any])->None:
    if proc.stdin is None:raise CatalogError("app-server stdin unavailable")
    proc.stdin.write(json.dumps(message,separators=(",",":"),sort_keys=True).encode()+b"\n");proc.stdin.flush()

def _await_id(proc:subprocess.Popen[bytes],identifier:int,deadline:float,buffer:bytearray)->Mapping[str,Any]:
    if proc.stdout is None:raise CatalogError("app-server stdout unavailable")
    selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
    try:
        while time.monotonic()<deadline:
            events=selector.select(max(0,deadline-time.monotonic()))
            if not events:break
            chunk=os.read(proc.stdout.fileno(),65536)
            if not chunk:raise CatalogError("app-server exited before RPC response")
            buffer.extend(chunk)
            if len(buffer)>MAX_RPC_LINE:raise CatalogError("RPC line size rejected")
            while b"\n" in buffer:
                line,rest=bytes(buffer).split(b"\n",1);buffer[:]=rest
                if not line:continue
                message=_strict(line)
                if type(message) is dict and type(message.get("id")) is int and message["id"]==identifier:return message
        raise TimeoutError("RPC response timeout")
    finally:selector.close()

def _rpc_slugs(message:Optional[Mapping[str,Any]])->Optional[Tuple[str,...]]:
    if message is None or set(message)!={"id","result"} or type(message["id"]) is not int or message["id"]!=2:return None
    result=message["result"]
    if type(result) is not dict or set(result)!={"data","nextCursor"} or result["nextCursor"] is not None or type(result["data"]) is not list:return None
    slugs=[];seen=set()
    for item in result["data"]:
        if type(item) is not dict or type(item.get("id")) is not str or not item["id"] or item["id"] in seen:return None
        seen.add(item["id"]);slugs.append(item["id"])
    return tuple(slugs)

def _group_exists(pgid:int)->bool:
    try:os.killpg(pgid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

def _cleanup(proc:Optional[subprocess.Popen[bytes]])->Mapping[str,Any]:
    if proc is None:return {"term_sent":False,"kill_sent":False,"parent_gone":True,"group_gone":True}
    term=kill=False
    if _group_exists(proc.pid):
        try:os.killpg(proc.pid,signal.SIGTERM);term=True
        except ProcessLookupError:pass
    try:proc.wait(timeout=.5)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL);kill=True
        except ProcessLookupError:pass
        try:proc.wait(timeout=1)
        except subprocess.TimeoutExpired:pass
    end=time.monotonic()+1
    while _group_exists(proc.pid) and time.monotonic()<end:time.sleep(.01)
    return {"term_sent":term,"kill_sent":kill,"parent_gone":proc.poll() is not None,"group_gone":not _group_exists(proc.pid)}

def _drain_stderr(stream:Any,counter:list[int])->None:
    try:
        while True:
            chunk=stream.read(65536)
            if not chunk:break
            counter[0]+=len(chunk)
    finally:
        try:stream.close()
        except OSError:pass

@dataclass(frozen=True)
class CatalogResult:
    catalog:Optional[ProviderCatalog]
    receipt:Mapping[str,Any]

class CatalogExecutor:
    def __init__(self)->None:
        root=_repository_root();grant_raw=_read_bound(root,FIXED_GRANT);review_raw=_read_bound(root,FIXED_REVIEW)
        for ref in HISTORY+(SOURCE_RESEARCH,):_read_bound(root,ref)
        grant=_strict(grant_raw);review=_strict(review_raw)
        if grant.get("version")!="r6-one-off-codex-catalog-gateway-grant-v2" or review.get("verdict")!="CLEAN_GATEWAY_CATALOG_ONLY":raise CatalogError("r9 authority rejected")
        self._root=root;self._grant=grant;self._admitted=False
    def execute(self,*,custody_parent:Path,execution_id:str,timeout_seconds:float,auth_token:Optional[object]=None)->CatalogResult:
        if self._admitted:raise CatalogError("second execution rejected")
        self._admitted=True
        if auth_token is None:raise CatalogError("transient authentication required")
        if not _ID.fullmatch(execution_id) or not(0<timeout_seconds<=30):raise CatalogError("execution bounds rejected")
        binary=self._grant["binary"];raw=_read_verified_binary(Path(binary["path"]),binary["bytes"],binary["sha256"])
        parent=_private_parent(custody_parent);run=parent/execution_id
        try:run.mkdir(mode=0o700)
        except FileExistsError as exc:raise CatalogError("custody destination exists") from exc
        gateway=None;proc=None;rpc2=None;rpc_error=None;stderr_thread=None;stderr_counter=[0]
        cleanup={"term_sent":False,"kill_sent":False,"parent_gone":True,"group_gone":True};started=datetime.now(timezone.utc).isoformat()
        init_sent=initialized_sent=model_list_sent=stdin_closed=False;contained=("private_binary","codex_home","home","tmp","cache")
        try:
            private=run/"codex";private.write_bytes(raw);os.chmod(private,0o700)
            if _read_verified_binary(private,binary["bytes"],binary["sha256"])!=raw:raise CatalogError("private binary verification failed")
            if _read_verified_binary(Path(binary["path"]),binary["bytes"],binary["sha256"])!=raw:raise CatalogError("installed binary changed before spawn")
            dirs={name:run/name for name in ("codex_home","home","tmp","cache")}
            for path in dirs.values():path.mkdir(mode=0o700)
            gateway=GatewayObserver(timeout_seconds);port=gateway.start();suffix=_sealed(port)
            try:material=_consume_transient_token(auth_token)
            except TypeError as exc:raise CatalogError("transient authentication rejected") from exc
            try:
                try:token_text=material.decode("utf-8","strict")
                except UnicodeError as exc:raise CatalogError("transient authentication encoding rejected") from exc
                env={"PATH":os.environ.get("PATH","/usr/bin:/bin"),"CODEX_HOME":str(dirs["codex_home"]),"HOME":str(dirs["home"]),"TMPDIR":str(dirs["tmp"]),"XDG_CACHE_HOME":str(dirs["cache"]),"CODEX_API_KEY":token_text,"NO_COLOR":"1"}
                proc=subprocess.Popen((str(private),)+suffix,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd=str(run),shell=False,close_fds=True,start_new_session=True)
            finally:
                for index in range(len(material)):material[index]=0
                if "env" in locals():env.pop("CODEX_API_KEY",None)
                if "token_text" in locals():token_text=""
            if proc.stderr is None:raise CatalogError("app-server stderr unavailable")
            stderr_thread=threading.Thread(target=_drain_stderr,args=(proc.stderr,stderr_counter),name="r6-catalog-v8-stderr",daemon=True);stderr_thread.start()
            deadline=time.monotonic()+timeout_seconds;buffer=bytearray()
            try:
                _write(proc,INIT);init_sent=True;reply1=_await_id(proc,1,deadline,buffer)
                if set(reply1)!={"id","result"} or type(reply1["id"]) is not int or reply1["id"]!=1:raise CatalogError("initialize response rejected")
                _write(proc,INITIALIZED);initialized_sent=True
                _write(proc,MODEL_LIST);model_list_sent=True
                try:rpc2=_await_id(proc,2,deadline,buffer)
                except (CatalogError,TimeoutError) as exc:rpc_error=type(exc).__name__
            except (CatalogError,TimeoutError) as exc:rpc_error=type(exc).__name__
            finally:
                if proc.stdin is not None:
                    try:proc.stdin.close();stdin_closed=True
                    except OSError:pass
            try:proc.wait(timeout=.25)
            except subprocess.TimeoutExpired:pass
        except Exception as exc:
            rpc_error=type(exc).__name__
            if proc is None:raise
        finally:
            cleanup=_cleanup(proc)
            if proc is not None:
                for stream in (proc.stdin,proc.stdout):
                    if stream is not None and not stream.closed:
                        try:stream.close()
                        except OSError:pass
            if stderr_thread is not None:stderr_thread.join(timeout=1)
            gateway_receipt=gateway.close() if gateway is not None else {"local_requests":0,"local_admissions":0,"provider_forwards":0,"subsequent_rejections":0,"status":None,"upstream_status":None,"first_200":{"captured":False,"body_sha256":None,"body_bytes":None,"model_count":0},"sensitive_headers_persisted":False,"listener_closed":True,"thread_stopped":True}
            captured=gateway.first_200 if gateway is not None else None
            safe_cleanup=cleanup["parent_gone"] and cleanup["group_gone"] and gateway_receipt["listener_closed"] and gateway_receipt["thread_stopped"] and (stderr_thread is None or not stderr_thread.is_alive())
            if safe_cleanup:shutil.rmtree(run,ignore_errors=False)
        if not safe_cleanup:raise CatalogError("cleanup failed; owner-private custody retained")
        rpc_slugs=_rpc_slugs(rpc2);corroborated=captured is not None and rpc_slugs is not None and set(captured.slugs)==set(rpc_slugs)
        if captured is not None:status="PASS_FIRST_200_CORROBORATED" if corroborated else "PASS_FIRST_200_UNCORROBORATED";reason="FIRST_200_AND_MODEL_LIST" if corroborated else "FIRST_200_AUTHORITATIVE"
        else:status="STOP_NO_VALID_FIRST_200";reason="NO_VALIDATED_UPSTREAM_200"
        receipt={"version":"r6-one-off-codex-catalog-receipt-v8","status":status,"reason":reason,"execution_id":execution_id,"provider":"codex","release":RELEASE,"model":MODEL,"binary_sha256":binary["sha256"],"grant_sha256":FIXED_GRANT[2],"review_sha256":FIXED_REVIEW[2],"v7_producer_sha256":V7_PRODUCER[2],"v7_review_sha256":V7_REVIEW[2],"source_research_sha256":SOURCE_RESEARCH[2],"rpc":{"initialize_sent":init_sent,"initialized_sent":initialized_sent,"model_list_sent":model_list_sent,"model_list_corroborated":corroborated,"error_class":rpc_error},"gateway":gateway_receipt,"process":{"started_at":started,"shell":False,"stdin_closed":stdin_closed,"stderr_bytes_discarded":stderr_counter[0],"cleanup":cleanup},"contained_writes":{"root":"temporary_owner_private","entries":len(contained),"global_codex_home_mutated":False,"cleaned":not run.exists()},"auth":{"source":"transient_child_env_only","wiped_after_spawn":auth_token.wiped,"executor_persisted":False,"executor_logged":False,"executor_hashed":False,"executor_returned":False}}
        return CatalogResult(captured,receipt)
