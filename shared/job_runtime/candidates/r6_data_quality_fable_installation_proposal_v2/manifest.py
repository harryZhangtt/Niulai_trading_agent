from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_installation_proposal_v2';PARENT='8fb533abda3955a2c67e2cb2c61d11fde7d773e9503533ff2883a5cb58de3687';MANIFEST_SHA256='bfb199b7cc793ad4a1d75b4120a97173a4ca357e4bc1031b191b4ab6b7c9b982'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
