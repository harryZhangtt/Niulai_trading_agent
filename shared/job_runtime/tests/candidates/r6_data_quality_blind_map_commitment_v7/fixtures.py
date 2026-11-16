"""Private test-only v7 chain fixtures. No production package imports this module."""
from __future__ import annotations
import hashlib
from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v7 import chronology, transaction
__all__ = ()

def _synthetic_ref(path: str, token: str):
    raw=("synthetic-"+token).encode("ascii")
    return {"path":path,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"mode":"0600"}

def _build_examples(g3_required: bool=False):
    aliases={c:hashlib.sha256(("schema-"+c).encode()).hexdigest()[:32] for c in chronology.CELL_IDS}
    binding={"transaction_id":"1"*32,"receipt_ref":_synthetic_ref(transaction.RECEIPT_NAME,"receipt"),"commitment_ref":_synthetic_ref(transaction.COMMITMENT_NAME,"commitment"),"canonical_digest":"2"*64,"canonical_bytes":897}
    human_pins={chronology.HUMAN_PATHS[x]:_synthetic_ref(chronology.HUMAN_PATHS[x],x) for x in ("REGISTRY","REGISTRY_REVIEW","G1","G1_REVIEW","G2","G2_REVIEW","G3","G3_REVIEW")}
    human=[human_pins[chronology.HUMAN_PATHS[x]] for x in ("REGISTRY","REGISTRY_REVIEW","G1","G1_REVIEW","G2","G2_REVIEW")]
    grant={"version":7,"schema":"r6-data-quality-blind-map-block-grant-v7","block_id":"R6DQ-BLOCK-SCHEMA-0001","commitment_binding":binding,"human_authority_refs":human,"cell_ids":list(chronology.CELL_IDS),"issued_sequence":1,"one_attempt_per_cell":True,"immutable":True}
    grant_ref=chronology._value_ref(chronology.BLOCK_GRANT_PATH,grant)
    review={"version":7,"schema":"r6-data-quality-blind-map-block-grant-review-v7","review_id":"review-schema-1","block_grant_ref":grant_ref,"status":"CLEAN","independent_reviewer_id":"HGRV-ABCD","reviewed_sequence":2,"immutable":True}
    review_ref=chronology._value_ref(chronology.BLOCK_GRANT_REVIEW_PATH,review)
    values={chronology.BLOCK_GRANT_PATH:grant,chronology.BLOCK_GRANT_REVIEW_PATH:review};attempts={};packets={};grades={}
    artifacts={p:{"version":7,"artifact_id":"artifact-"+hashlib.sha256(p.encode()).hexdigest()[:16],"payload_sha256":hashlib.sha256(("payload-"+p).encode()).hexdigest(),"immutable":True} for p in chronology._external_artifact_paths(g3_required)}
    for i,c in enumerate(chronology.CELL_IDS):
        aseq,rseq=chronology.ATTEMPT_SEQUENCES[c]
        attempt={"version":7,"schema":"r6-data-quality-blind-map-attempt-receipt-v7","attempt_id":"attempt-"+c,"cell_id":c,"blind_alias":aliases[c],"block_grant_ref":grant_ref,"block_grant_review_ref":review_ref,"commitment_binding":binding,"provider_request_ref":chronology._value_ref(chronology.REQUEST_PATHS[c],artifacts[chronology.REQUEST_PATHS[c]]),"provider_result_ref":chronology._value_ref(chronology.RESULT_PATHS[c],artifacts[chronology.RESULT_PATHS[c]]),"admitted_sequence":aseq,"result_sequence":rseq,"attempt_number":1,"immutable":True}
        attempts[c]=attempt;values[chronology.ATTEMPT_PATHS[c]]=attempt
        packet={"version":7,"schema":"r6-data-quality-blind-map-evaluation-packet-record-v7","packet_record_id":"packet-"+c,"cell_id":c,"blind_alias":aliases[c],"attempt_receipt_ref":chronology._value_ref(chronology.ATTEMPT_PATHS[c],attempt),"evaluation_packet_ref":chronology._value_ref(chronology.EVALUATION_ARTIFACT_PATHS[c],artifacts[chronology.EVALUATION_ARTIFACT_PATHS[c]]),"produced_sequence":chronology.PACKET_SEQUENCES[c],"immutable":True}
        packets[c]=packet;values[chronology.PACKET_PATHS[c]]=packet
    roles=("G1","G2","G3") if g3_required else ("G1","G2")
    for role in roles:
        for c in chronology.CELL_IDS:
            grade={"version":7,"schema":"r6-data-quality-blind-map-human-grade-record-v7","grade_record_id":f"grade-{c}-{role}","cell_id":c,"blind_alias":aliases[c],"grader_role":role,"packet_record_ref":chronology._value_ref(chronology.PACKET_PATHS[c],packets[c]),"human_grant_ref":human_pins[chronology.HUMAN_PATHS[role]],"human_grant_review_ref":human_pins[chronology.HUMAN_PATHS[role+"_REVIEW"]],"grade_artifact_ref":chronology._value_ref(chronology.GRADE_ARTIFACT_PATHS[(c,role)],artifacts[chronology.GRADE_ARTIFACT_PATHS[(c,role)]]),"produced_sequence":chronology.GRADE_SEQUENCES[(c,role)],"immutable":True}
            grades[(c,role)]=grade;values[chronology.GRADE_PATHS[(c,role)]]=grade
    mc=[]
    for c in chronology.CELL_IDS:mc.append({"cell_id":c,"blind_alias":aliases[c],"packet_record_ref":chronology._value_ref(chronology.PACKET_PATHS[c],packets[c]),"grade_record_refs":[chronology._value_ref(chronology.GRADE_PATHS[(c,r)],grades[(c,r)]) for r in roles]})
    metrics={"version":7,"schema":"r6-data-quality-blind-map-derived-metrics-record-v7","metrics_record_id":"metrics-schema-1","commitment_binding":binding,"g3_required":g3_required,"cells":mc,"derived_metric_ref":chronology._value_ref(chronology.DERIVED_METRIC_ARTIFACT_PATH,artifacts[chronology.DERIVED_METRIC_ARTIFACT_PATH]),"produced_sequence":chronology.METRICS_SEQUENCES[g3_required],"immutable":True};values[chronology.METRICS_PATH]=metrics
    grade_refs=[chronology._value_ref(chronology.GRADE_PATHS[(c,r)],grades[(c,r)]) for r in roles for c in chronology.CELL_IDS]
    manifest={"version":7,"schema":"r6-data-quality-blind-map-chronology-manifest-v7","chain_id":"chain-schema-1","commitment_binding":binding,"block_grant_ref":grant_ref,"block_grant_review_ref":review_ref,"attempt_receipt_refs":[chronology._value_ref(chronology.ATTEMPT_PATHS[c],attempts[c]) for c in chronology.CELL_IDS],"evaluation_packet_record_refs":[chronology._value_ref(chronology.PACKET_PATHS[c],packets[c]) for c in chronology.CELL_IDS],"human_grade_record_refs":grade_refs,"g3_required":g3_required,"derived_metrics_record_ref":chronology._value_ref(chronology.METRICS_PATH,metrics),"final_sequence":chronology.MANIFEST_SEQUENCES[g3_required],"immutable":True};values[chronology.MANIFEST_PATH]=manifest
    return {"binding":binding,"grant":grant,"grant_review":review,"attempt":attempts[chronology.CELL_IDS[0]],"packet":packets[chronology.CELL_IDS[0]],"grade":grades[(chronology.CELL_IDS[0],"G1")],"metrics":metrics,"manifest":manifest,"chain_values":values,"external_artifacts":artifacts,"human_pins":human_pins}
