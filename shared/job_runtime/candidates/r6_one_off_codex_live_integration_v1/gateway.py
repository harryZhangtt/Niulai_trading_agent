"""Request-local one-forward Responses gateway; production target is fixed and default denied."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,http.client,socket,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from typing import Any,Dict,Mapping,Optional,Tuple
from .contracts import OFFICIAL_HOST,ROUTE,ContractError
MAX_BODY=4*1024*1024;SENSITIVE=("Authorization","Cookie","ChatGPT-Account-Id","OpenAI-Organization","OpenAI-Project")
@dataclass(frozen=True)
class Endpoint:host:str;port:int;tls:bool
OFFICIAL=Endpoint(OFFICIAL_HOST,443,True)
def _forward(endpoint:Endpoint,body:bytes,headers:Mapping[str,str],timeout:float)->Tuple[int,bytes,Mapping[str,str]]:
 cls=http.client.HTTPSConnection if endpoint.tls else http.client.HTTPConnection;c=cls(endpoint.host,endpoint.port,timeout=timeout)
 try:
  c.request("POST",ROUTE,body=body,headers=dict(headers));r=c.getresponse();declared=r.getheader("Content-Length");raw=r.read(MAX_BODY+1)
  if len(raw)>MAX_BODY:raise ContractError("UPSTREAM_TRUNCATED")
  if declared is not None:
   try:expected=int(declared)
   except ValueError as exc:raise ContractError("UPSTREAM_LENGTH_INVALID") from exc
   if expected!=len(raw):raise ContractError("UPSTREAM_TRUNCATED")
  return r.status,raw,{"Content-Type":r.getheader("Content-Type","application/json")}
 finally:c.close()
class ResponsesGateway:
 def __init__(self,request_fingerprint:str,admission_key:str,timeout:float,*,fixture_endpoint:Optional[Endpoint]=None,provider_free_fixture:bool=False)->None:
  if fixture_endpoint is not None and (not provider_free_fixture or fixture_endpoint.host not in ("127.0.0.1","localhost") or fixture_endpoint.tls):raise ContractError("FIXTURE_ENDPOINT_DENIED")
  self.endpoint=fixture_endpoint or OFFICIAL;self.production_enabled=False;self.fingerprint=request_fingerprint;self.admission_key=admission_key;self.timeout=timeout;self.requests=self.admissions=self.provider_forwards=self.second_rejections=0;self.terminal_present=False;self._lock=threading.Lock();outer=self
  class H(BaseHTTPRequestHandler):
   def log_message(self,*a:Any)->None:return
   def do_GET(self)->None:self._handle()
   def do_POST(self)->None:self._handle()
   def _reply(self,status:int,raw:bytes=b"")->None:self.send_response(status);self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw) if raw else None
   def _handle(self)->None:
    try:n=int(self.headers.get("Content-Length","-1"))
    except ValueError:n=-1
    raw=self.rfile.read(n) if 0<=n<=MAX_BODY else b""
    with outer._lock:outer.requests+=1;number=outer.requests
    if number>1:
     with outer._lock:outer.second_rejections+=1
     self._reply(409);return
    path,sep,query=self.path.partition("?");valid=self.command=="POST" and path==ROUTE and not sep and 0<=n<=MAX_BODY and n==len(raw) and self.headers.get("X-R6-Fingerprint")==outer.fingerprint and self.headers.get("X-R6-Admission")==outer.admission_key
    auth=self.headers.get("Authorization")
    if not valid or not auth:
     self._reply(401 if valid else 400);return
    if outer.endpoint==OFFICIAL and not outer.production_enabled:self._reply(403);return
    sensitive={k:self.headers[k] for k in SENSITIVE if k in self.headers};safe={"Content-Type":self.headers.get("Content-Type","application/json"),**sensitive}
    with outer._lock:outer.admissions=1;outer.provider_forwards=1
    try:status,response,_=_forward(outer.endpoint,raw,safe,outer.timeout)
    except Exception:self._reply(502);return
    outer.terminal_present=b'"type":"response.completed"' in response.replace(b" ",b"");self._reply(status,response)
  self.server=ThreadingHTTPServer(("127.0.0.1",0),H);self.server.daemon_threads=True;self.thread=threading.Thread(target=self.server.serve_forever,name="r6-codex-inference-gateway",daemon=True)
 def start(self)->int:self.thread.start();return int(self.server.server_address[1])
 def close(self)->Dict[str,Any]:
  self.server.shutdown();self.server.server_close();self.thread.join(2);probe=socket.socket();probe.settimeout(.1);closed=probe.connect_ex(("127.0.0.1",self.server.server_address[1]))!=0;probe.close();return {"identity":"r6-request-local-responses-gateway-v1","bound_host":"127.0.0.1","requests":self.requests,"admissions":self.admissions,"provider_forwards":self.provider_forwards,"second_rejections":self.second_rejections,"terminal_present":self.terminal_present,"sensitive_headers_persisted":False,"listener_closed":closed,"thread_stopped":not self.thread.is_alive(),"official_endpoint":"https://chatgpt.com/backend-api/codex/responses"}
