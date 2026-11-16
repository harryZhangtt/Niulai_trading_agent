from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_allocation_design_v2';PARENT='b39bbd17ccfc54f8c47ddd964066a28af63bfb1260de96efb56f74b6a897ee2d';MANIFEST_SHA256='cd3aec4d07366cd0d1bcf6c91216ed850090ac19e3ca84e5f45111f16f370e12'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
