from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_allocation_materialization_v2';PARENT='cd3aec4d07366cd0d1bcf6c91216ed850090ac19e3ca84e5f45111f16f370e12';MANIFEST_SHA256='8fb533abda3955a2c67e2cb2c61d11fde7d773e9503533ff2883a5cb58de3687'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
