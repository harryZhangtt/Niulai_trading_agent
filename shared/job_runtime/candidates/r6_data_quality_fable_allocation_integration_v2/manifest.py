from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_allocation_integration_v2';PARENT='3b2b006cdcb9e33c3a9ca1c6f045359bf38d8e9ee58f02a33e989a707d10f895';MANIFEST_SHA256='b39bbd17ccfc54f8c47ddd964066a28af63bfb1260de96efb56f74b6a897ee2d'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
