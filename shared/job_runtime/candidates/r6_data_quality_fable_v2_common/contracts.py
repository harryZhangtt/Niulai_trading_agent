from __future__ import annotations
import hashlib,json
PROMPT_PATH="mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json:prompt_utf8"
PROMPT_SHA="3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b";PROMPT_BYTES=526;SOURCE_SHA="26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a";GENERATION="schema9-isolated-canary-q1-ab-payload-v1"
class V2Error(ValueError):pass
def canonical(v):
 try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
 except (TypeError,ValueError,UnicodeError):raise V2Error("CANONICAL") from None
def validate(v,stage,parent):
 if type(v) is not dict or set(v)!={"version","stage","parent_sha256","activation","countable","prompt","effects","payload"}:raise V2Error("SHAPE")
 if v["version"]!="v2" or v["stage"]!=stage or v["parent_sha256"]!=parent or v["activation"] is not False or v["countable"] is not False:raise V2Error("BINDING")
 p=v["prompt"];expected={"logical_path":PROMPT_PATH,"sha256":PROMPT_SHA,"bytes":PROMPT_BYTES,"source_sha256":SOURCE_SHA,"source_generation":GENERATION}
 if p!=expected or v["effects"]!={"provider":0,"network":0,"email":0,"publication":0,"service":0,"scheduler":0}:raise V2Error("PROMPT_OR_EFFECT")
 return v
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
