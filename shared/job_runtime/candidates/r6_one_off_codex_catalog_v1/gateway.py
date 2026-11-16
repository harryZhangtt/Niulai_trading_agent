"""One-admission loopback catalog gateway with immutable first-200 capture."""
from __future__ import annotations
from dataclasses import dataclass,field
import hashlib,http.client,json,threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from typing import Any,Dict,Mapping,Optional,Sequence,Tuple
TARGET="/backend-api/codex/models?client_version=0.167.0";MAX_UPSTREAM_BODY=1024*1024;MAX_MODELS=512
_SENSITIVE=("Authorization","Cookie","ChatGPT-Account-Id","OpenAI-Organization","OpenAI-Project")
class GatewayError(RuntimeError):pass
def _pairs(pairs:Sequence[Tuple[str,Any]])->Dict[str,Any]:
 out={}
 for key,value in pairs:
  if key in out:raise GatewayError("duplicate JSON key")
  out[key]=value
 return out
@dataclass(frozen=True)
class ProviderCatalog:
 slugs:Tuple[str,...];body_sha256:str;body_bytes:int;body:bytes=field(repr=False)
@dataclass(frozen=True)
class _Endpoint:host:str;port:int;tls:bool
def _production_endpoint()->_Endpoint:return _Endpoint("chatgpt.com",443,True)
def parse_provider_catalog(raw:bytes)->ProviderCatalog:
 if not raw or len(raw)>MAX_UPSTREAM_BODY:raise GatewayError("provider catalog size rejected")
 try:value=json.loads(raw.decode("utf-8","strict"),object_pairs_hook=_pairs,parse_constant=lambda _:(_ for _ in()).throw(GatewayError("non-finite JSON")))
 except GatewayError:raise
 except (UnicodeError,ValueError,json.JSONDecodeError) as exc:raise GatewayError("malformed provider catalog") from exc
 if type(value) is not dict or set(value)!={"models"} or type(value["models"]) is not list or not(1<=len(value["models"])<=MAX_MODELS):raise GatewayError("provider catalog schema rejected")
 slugs=[];seen=set()
 for model in value["models"]:
  if type(model) is not dict or "slug" not in model or not all(type(k) is str and 0<len(k)<=128 for k in model):raise GatewayError("provider model schema rejected")
  slug=model["slug"]
  if type(slug) is not str or not slug or slug!=slug.strip() or len(slug)>128 or slug in seen:raise GatewayError("provider model slug rejected")
  seen.add(slug);slugs.append(slug)
 immutable=bytes(raw);return ProviderCatalog(tuple(slugs),hashlib.sha256(immutable).hexdigest(),len(immutable),immutable)
def _forward(endpoint:_Endpoint,headers:Mapping[str,str],timeout:float)->Tuple[int,bytes]:
 cls=http.client.HTTPSConnection if endpoint.tls else http.client.HTTPConnection;connection=cls(endpoint.host,endpoint.port,timeout=timeout)
 try:
  connection.request("GET",TARGET,headers=dict(headers));response=connection.getresponse();body=response.read(MAX_UPSTREAM_BODY+1)
  if len(body)>MAX_UPSTREAM_BODY:raise GatewayError("provider catalog size rejected")
  return response.status,body
 finally:connection.close()
class GatewayObserver:
 def __init__(self,timeout:float)->None:
  self.timeout=timeout;self.lock=threading.Lock();self.local_requests=0;self.local_admissions=0;self.provider_forwards=0;self.subsequent_rejections=0;self.first=None;self.first_200:Optional[ProviderCatalog]=None;observer=self
  class Handler(BaseHTTPRequestHandler):
   protocol_version="HTTP/1.0"
   def log_message(self,*args:Any)->None:return
   def do_GET(self)->None:self._handle()
   def do_POST(self)->None:self._handle()
   def do_PUT(self)->None:self._handle()
   def do_DELETE(self)->None:self._handle()
   def do_PATCH(self)->None:self._handle()
   def do_HEAD(self)->None:self._handle()
   def do_OPTIONS(self)->None:self._handle()
   def do_CONNECT(self)->None:self._handle()
   def __getattr__(self,name:str)->Any:
    if name.startswith("do_"):return self._handle
    raise AttributeError(name)
   def _reply(self,status:int,body:bytes=b"")->None:
    self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.send_header("Connection","close");self.end_headers()
    if body and self.command!="HEAD":self.wfile.write(body)
    self.close_connection=True
   def _handle(self)->None:
    with observer.lock:
     observer.local_requests+=1;number=observer.local_requests
     if number>1:observer.subsequent_rejections+=1
    if number>1:self._reply(409);return
    length_header=self.headers.get("Content-Length")
    try:length=0 if length_header is None else int(length_header)
    except ValueError:length=-1
    valid=self.command=="GET" and self.path==TARGET and length==0 and "Transfer-Encoding" not in self.headers
    if not valid:
     status=405 if self.command!="GET" else 400
     with observer.lock:observer.first={"status":status,"upstream_status":None}
     self._reply(status);return
    sensitive={name:self.headers[name] for name in _SENSITIVE if name in self.headers}
    with observer.lock:observer.local_admissions+=1;observer.provider_forwards+=1
    try:
     upstream_status,upstream_body=_forward(_production_endpoint(),sensitive,observer.timeout)
     if upstream_status==200:
      captured=parse_provider_catalog(upstream_body)
      with observer.lock:
       if observer.first_200 is None:observer.first_200=captured
     status=upstream_status
    except Exception:upstream_status=None;upstream_body=b"";status=502
    with observer.lock:observer.first={"status":status,"upstream_status":upstream_status}
    self._reply(status,upstream_body)
  self.server=HTTPServer(("127.0.0.1",0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,name="r6-catalog-v8-gateway",daemon=True)
 def start(self)->int:self.thread.start();return int(self.server.server_address[1])
 def close(self)->Mapping[str,Any]:
  self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);captured=self.first_200;first=self.first or {"status":None,"upstream_status":None}
  return {"local_requests":self.local_requests,"local_admissions":self.local_admissions,"provider_forwards":self.provider_forwards,"subsequent_rejections":self.subsequent_rejections,"status":first["status"],"upstream_status":first["upstream_status"],"first_200":{"captured":captured is not None,"body_sha256":captured.body_sha256 if captured else None,"body_bytes":captured.body_bytes if captured else None,"model_count":len(captured.slugs) if captured else 0},"sensitive_headers_persisted":False,"listener_closed":True,"thread_stopped":not self.thread.is_alive()}
