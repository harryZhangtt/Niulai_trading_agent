"""Pure treatment binding for authority v2. No invocation or I/O beyond authority loader."""
from hashlib import sha256
import json,re
from types import MappingProxyType
from typing import Mapping
from .authority import capability_gate, load_authority_manifest
from .contracts import AuthorityV2Error
KEYS={"configured_model","effort","profile_sha256","config_sha256","payload_sha256","source_cutoff_sha256"}
SHA=re.compile(r"[0-9a-f]{64}")
LOADER={"authority_py_sha256":"3992763efffffa7d49172791e4580326675808499e1be04a5b171258223b6dee","contracts_py_sha256":"028adf6b7194099510ca0f5f46bc7e82a71b50ebbf79a964443586a25aa3456d","init_py_sha256":"4e2e0789acc12cc928013aff2a256131138b70fcb5dbb5418799dd4ff8ec1dbc","verification_sha256":"4a10ac58d2a0f39f039e11a263eb599aa06535f01a97cf817938e4410fdcaa31"}
def _canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def _freeze(v):
 if type(v) is dict:return MappingProxyType({k:_freeze(x) for k,x in v.items()})
 if type(v) is list:return tuple(_freeze(x) for x in v)
 return v
def build_treatment_binding(config: Mapping[str,object]):
 if type(config) is not dict or set(config)!=KEYS or type(config["configured_model"]) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,128}",config["configured_model"]) is None or type(config["effort"]) is not str or config["effort"] not in {"low","medium","high"} or any(type(config[k]) is not str or SHA.fullmatch(config[k]) is None for k in ("profile_sha256","config_sha256","payload_sha256","source_cutoff_sha256")):
  raise AuthorityV2Error("CODEX_Q1_V2_TREATMENT_CONFIG_INVALID")
 manifest=load_authority_manifest();gate=capability_gate()
 body={"schema_version":"treatment-binding-v2","candidate_id":manifest["candidate_id"],"provider":"codex_cli","release":manifest["binary"]["version"],"configured_model":config["configured_model"],"model_authority":"configured_cli_argument_nonclaim","effort":config["effort"],"binary_sha256":manifest["binary"]["sha256"],"authority_manifest_sha256":"b542ec00324f58137f7ff7662ae6c980e8df8990f3a14a2c9f759339ad9209b6","loader":dict(LOADER),"retry":{"request":0,"stream":0},"profile_sha256":config["profile_sha256"],"config_sha256":config["config_sha256"],"payload_sha256":config["payload_sha256"],"source_cutoff_sha256":config["source_cutoff_sha256"],"predecessor_v1_sha256":manifest["predecessor"]["sha256"],"capabilities":{name:getattr(gate,name) for name in gate.__dataclass_fields__}}
 body["treatment_fingerprint_sha256"]=sha256(_canonical(body)).hexdigest();return _freeze(body)
def treatment_gate():return capability_gate()
