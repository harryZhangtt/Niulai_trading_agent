"""Four-cell source-pinned noncaller authority for v3."""
from __future__ import annotations
import copy
from datetime import datetime,timezone
from typing import Any,Mapping
from .authority_v2 import ROOT,_read,_ref,_strict,validate_fixed_grant
from .contracts import ContractError,require,sha256_bytes
REGISTRY=("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-integration-owner-registry-v3.json",2026,"bc55c7de4a63a5cf032a779ee724fc43281cb54d00b0b10d7f90c8609c5bb6c6")
REFS={
"R6DQ-7F2C91A4":{"grant":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-v3-r6dq-7f2c91a4.json",2467,"dba69396f29e1f100d27fa36f6e16415323cf25383ce8de060734b6b5a220bba"),"review":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-review-v3-r6dq-7f2c91a4.json",601,"46c44d04fd4c7ec7129cf8c2b92b9fd86cb7aa277cdc21be8f7da8989f96880f")},
"R6DQ-1B8E43D7":{"grant":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-v3-r6dq-1b8e43d7.json",2467,"fea2949c2b6b627f03785b75c22c50b8511537a4e8078f973e125fc8155dcddd"),"review":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-review-v3-r6dq-1b8e43d7.json",601,"2582d603321e1e08a677e7e057dd5042c96e20e742d7c7f77a55023922abcbe4")},
"R6DQ-C4A7095E":{"grant":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-v3-r6dq-c4a7095e.json",2467,"a26d6e8348d66a38e37a6c03cd9e23087aaebf04dedbe322c35fd6148a0ae49a"),"review":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-review-v3-r6dq-c4a7095e.json",601,"f37fb043bb5f8bf0a7e19d2cc46b9718676063b3bbd43786479775c04bdd6115")},
"R6DQ-92D6F0B3":{"grant":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-v3-r6dq-92d6f0b3.json",2467,"1ede7d33a5858fe8cb8ca7bfc18c6dc4d4c7cf0583aba9120a7b9ea77483d2b5"),"review":("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-review-v3-r6dq-92d6f0b3.json",601,"320ce741775b76ae47d495b05582f0c23f91c8e5763e561b17b18f77b61c4cb8")}}
_MARKER=object()
class FixedAuthorityV3:
 __slots__=('grant','grant_sha256','review_sha256')
 def __init__(self,grant:Mapping[str,Any],gsha:str,rsha:str,marker:object)->None:require(marker is _MARKER,'V3_NONCALLER_REQUIRED');self.grant=grant;self.grant_sha256=gsha;self.review_sha256=rsha
def validate_fixed_grant_v3(value:Any,observed:datetime)->Mapping[str,Any]:
 require(type(value) is dict and value.get('version')==3 and value.get('authority_id')=='r6-codex-integration-owner-v3','V3_AUTH_IDENTITY');normalized=copy.deepcopy(value);normalized['version']=2;normalized['authority_id']='r6-codex-integration-owner-v2';validate_fixed_grant(normalized,observed);return value
def load_fixed_authority_v3(cell_id:str)->FixedAuthorityV3:
 require(cell_id in REFS,'V3_CELL_AUTHORITY');observed=datetime.now(timezone.utc);registry=_strict(_read(REGISTRY));expected_cells={cell:{'grant':_ref(refs['grant']),'review':_ref(refs['review'])} for cell,refs in REFS.items()};require(registry=={'version':3,'kind':'R6_CODEX_INTEGRATION_OWNER_TRUST_ROOT','owner':'independent_integration_owner','caller_may_mint':False,'caller_may_select_authority_artifact':False,'cells':expected_cells,'activation':False,'effects':'provider_free_only'},'V3_REGISTRY')
 refs=REFS[cell_id];grant_raw=_read(refs['grant']);review_raw=_read(refs['review']);grant=validate_fixed_grant_v3(_strict(grant_raw),observed);review=_strict(review_raw);require(type(review) is dict and review.get('version')==3 and review.get('kind')=='R6_CODEX_PRE_DISPATCH_CELL_GRANT_REVIEW' and review.get('reviewer_role')=='independent_reviewer' and review.get('verdict')=='CLEAN_PROVIDER_FREE_INTEGRATION_V3' and review.get('subject')==_ref(refs['grant']) and type(review.get('checks')) is dict and all(v is True for v in review['checks'].values()),'V3_REVIEW')
 return FixedAuthorityV3(grant,sha256_bytes(grant_raw),sha256_bytes(review_raw),_MARKER)
__all__=['FixedAuthorityV3','load_fixed_authority_v3','validate_fixed_grant_v3']
