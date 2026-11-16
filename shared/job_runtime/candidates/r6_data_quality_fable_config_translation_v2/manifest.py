from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_config_translation_v2';PARENT='bfb199b7cc793ad4a1d75b4120a97173a4ca357e4bc1031b191b4ab6b7c9b982';MANIFEST_SHA256='ad6cbf3b89d79fcd6acac334cffb4fa76917c5589372aa638be6bc2216d6890d'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
