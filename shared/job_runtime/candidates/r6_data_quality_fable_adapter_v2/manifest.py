from shared.job_runtime.candidates.r6_data_quality_fable_v2_common.contracts import validate as _validate,digest
STAGE='r6_data_quality_fable_adapter_v2';PARENT='6bca8d52cd031a535b7222646c9f6c89d83f5c2c4d2a90de360dfafbcee44f70';MANIFEST_SHA256='5561430bfb65394468ee8fbb792493fc07c60a61cd1351af2a42df79970cfff5'
def validate(value):
 result=_validate(value,STAGE,PARENT)
 if digest(result)!=MANIFEST_SHA256:raise ValueError("DIGEST")
 return result
