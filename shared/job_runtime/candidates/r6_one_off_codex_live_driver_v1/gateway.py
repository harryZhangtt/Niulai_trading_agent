"""Request-local provider-free loopback HTTP observer with a single durable admission."""
from __future__ import annotations
import http.server, socket, threading
from typing import Any, Callable, Dict, Mapping, Optional
from .contracts import PATH, ContractError, EffectGuard, ExecutionBinding, require, sha256_bytes

class GatewayObserver:
    def __init__(self,expected_fingerprint:str,expected_admission_key:str,upstream:Callable[[bytes],bytes],binding:Optional[ExecutionBinding]=None,guard:Optional[EffectGuard]=None)->None:
        self.expected_fingerprint=expected_fingerprint; self.expected_admission_key=expected_admission_key; self.upstream=upstream; self.binding=binding; self.guard=guard
        self.admissions=self.dispatches=self.upstream_attempts=self.second_rejections=0; self.closed=False; self.terminal_present=False; self._lock=threading.Lock(); self._server=None; self._thread=None; self.port=0
    def _admit(self,method,path,query,fingerprint,key,body,headers):
        require(not self.closed,"GATEWAY_CLOSED")
        with self._lock:
            if self.admissions: self.second_rejections+=1; raise ContractError("SECOND_REQUEST_REJECTED")
            require((method,path,query)==('POST',PATH,''),"GATEWAY_ROUTE_REJECTED"); require(fingerprint==self.expected_fingerprint and key==self.expected_admission_key,"GATEWAY_FINGERPRINT_REJECTED")
            if self.guard: self.guard.check('gateway_admission'); self.guard.check('upstream_attempt', '0.01')
            self.admissions=1; self.dispatches=1; self.upstream_attempts=1
        response=self.upstream(body); self.terminal_present=b'"type":"response.completed"' in response.replace(b' ',b''); return response
    def dispatch(self,method,path,query,fingerprint,admission_key,body,headers): return self._admit(method,path,query,fingerprint,admission_key,body,headers)
    def start(self)->int:
        require(self._server is None,"GATEWAY_ALREADY_STARTED")
        if self.guard: self.guard.check('gateway_bind')
        outer=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args): return
            def do_POST(self):
                length=int(self.headers.get('Content-Length','0')); body=self.rfile.read(length)
                try:
                    response=outer._admit('POST',self.path.split('?',1)[0],'' if '?' not in self.path else self.path.split('?',1)[1],self.headers.get('X-R6-Fingerprint',''),self.headers.get('X-R6-Admission',''),body,dict(self.headers)); self.send_response(200)
                except ContractError as exc:
                    response=str(exc).encode(); self.send_response(409 if str(exc)=='SECOND_REQUEST_REJECTED' else 400)
                self.send_header('Content-Length',str(len(response))); self.end_headers(); self.wfile.write(response)
        self._server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler); self._server.daemon_threads=True; self.port=self._server.server_address[1]
        self._thread=threading.Thread(target=self._server.serve_forever,name='r6-fixture-gateway',daemon=True); self._thread.start(); return self.port
    def close(self)->Dict[str,Any]:
        cleanup_deadline_ok=True
        if not self.closed:
            if self.guard:
                try: self.guard.check('gateway_cleanup')
                except ContractError: cleanup_deadline_ok=False
            self.closed=True
            if self._server:
                self._server.shutdown(); self._server.server_close()
            if self._thread: self._thread.join(timeout=2)
        listener_closed=True
        if self.port:
            probe=socket.socket(); probe.settimeout(.1); listener_closed=probe.connect_ex(('127.0.0.1',self.port))!=0; probe.close()
        binding=self.binding.public() if self.binding else {}
        return {'kind':'gateway','binding':binding,'identity':'fixture-loopback-observer-v2','bound_host':'127.0.0.1','bound_port':self.port,'ephemeral_fixture':True,'listener_closed':listener_closed,'server_fd_closed':self._server is None or self._server.socket.fileno()==-1,'thread_stopped':self._thread is None or not self._thread.is_alive(),'cleanup_deadline_ok':cleanup_deadline_ok,'admissions':self.admissions,'dispatches':self.dispatches,'upstream_attempts':self.upstream_attempts,'second_rejections':self.second_rejections,'terminal_present':self.terminal_present,'request_fingerprint_sha256':sha256_bytes(self.expected_fingerprint.encode()),'captures_secret_values':False,'status_api':False,'reconciliation_api':False}
