from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_allocation_bridge_v2';PARENT='5561430bfb65394468ee8fbb792493fc07c60a61cd1351af2a42df79970cfff5';MANIFEST_SHA256='3b2b006cdcb9e33c3a9ca1c6f045359bf38d8e9ee58f02a33e989a707d10f895'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
