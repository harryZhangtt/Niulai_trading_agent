"""Immutable held CLI and launch specification; no process execution."""
from __future__ import annotations
from typing import Any,Dict,Optional
from .contracts import EFFORT,MODEL,canonical_bytes,sha256_bytes,validate_held_manifest,validate_launch_spec
def _d(identity,raw):return {"identity":identity,"bytes":len(raw),"sha256":sha256_bytes(raw),"regular":True,"no_symlink":True}
def synthetic_held_manifest(prompt:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    argv=canonical_bytes({"executable":"held/claude","argv":["--model",MODEL,"--effort",EFFORT,"--print"],"stdin":"native_prompt","shell":False});config=canonical_bytes({"request_retries":0,"stream_retries":0,"max_attempts":1,"concurrency":1,"env_allowlist":["CLAUDE_CONFIG_DIR","HOME","LANG","PATH","TMPDIR"]})
    raw={"binary":b"synthetic non-executable descriptor\n","argv":argv,"config":config,"catalog":canonical_bytes({"models":[MODEL]}),"prompt":b"synthetic native prompt\n","parser":canonical_bytes({"name":"claude_terminal_v1","partial_is_success":False}),"cleanup_policy":canonical_bytes({"process_group":True,"terminate":True,"kill_after_timeout":True,"reap":True})}
    x={k:_d("held/"+k+".artifact",v) for k,v in raw.items()}
    if prompt is not None:x["prompt"]={"identity":"held/native-prompt.artifact","bytes":prompt["bytes"],"sha256":prompt["sha256"],"regular":True,"no_symlink":True}
    x.update({"model":MODEL,"effort":EFFORT,"model_membership":True,"no_shell":True,"env_allowlist":["CLAUDE_CONFIG_DIR","HOME","LANG","PATH","TMPDIR"]});x["digest"]=sha256_bytes(canonical_bytes(x));validate_held_manifest(x);return x
def launch_spec(manifest,readback):
    x={"version":1,"binary":dict(manifest["binary"]),"argv":dict(manifest["argv"]),"shell":False,"env_allowlist":list(manifest["env_allowlist"]),"config":dict(manifest["config"]),"catalog":dict(manifest["catalog"]),"model":manifest["model"],"prompt":dict(manifest["prompt"]),"process_group":True,"deadline_seconds":30,"terminate":True,"kill":True,"reap":True,"engine_readback_digest":readback["digest"]};x["digest"]=sha256_bytes(canonical_bytes(x));validate_launch_spec(x);return x
