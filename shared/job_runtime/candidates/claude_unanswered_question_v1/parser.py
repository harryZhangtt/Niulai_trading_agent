from __future__ import annotations
from typing import Any, Mapping
from .contracts import CAPABILITY_STATUS, ContractError, QuestionOption, SyntheticAuthority, SyntheticQuestionEvent, require, sanitize_tree
EVENT_KEYS=frozenset(("synthetic_schema","host_version_under_study","event_id","question_id","question_kind","caller_category","prompt","options","authority","observed_monotonic_ns","replaced_by_question_id"))
OPTION_KEYS=frozenset(("option_id","label","description","recommended"))
AUTHORITY_KEYS=frozenset(("safe_capability","forbidden_effects"))
def parse_live_host_event(_value): raise ContractError(CAPABILITY_STATUS)
def parse_live_answer_ack(_value): raise ContractError(CAPABILITY_STATUS)
def parse_synthetic_event(value: Mapping[str,Any]) -> SyntheticQuestionEvent:
    require(type(value) is dict and set(value)==EVENT_KEYS,"SYNTHETIC_EVENT_SHAPE_INVALID"); sanitize_tree(value)
    require(type(value["options"]) is list,"OPTIONS_INVALID"); options=[]
    for raw in value["options"]:
        require(type(raw) is dict and set(raw)==OPTION_KEYS,"OPTION_SHAPE_INVALID"); options.append(QuestionOption(**raw))
    auth=value["authority"]; require(type(auth) is dict and set(auth)==AUTHORITY_KEYS,"AUTHORITY_SHAPE_INVALID")
    require(type(auth["forbidden_effects"]) is list,"EFFECT_CLASSIFICATION_INVALID")
    authority=SyntheticAuthority(auth["safe_capability"],tuple(auth["forbidden_effects"]))
    return SyntheticQuestionEvent(value["synthetic_schema"],value["host_version_under_study"],value["event_id"],value["question_id"],value["question_kind"],value["caller_category"],value["prompt"],tuple(options),authority,value["observed_monotonic_ns"],value["replaced_by_question_id"])

FIXTURE_KEYS=frozenset(("schema_version","authority","host_contract_observed","host_version_under_study","cases"))
def load_synthetic_fixture(path):
    try:
        import json
        value=json.loads(path.read_text(encoding="ascii"))
    except (OSError,ValueError,UnicodeError):raise ContractError("FIXTURE_INVALID") from None
    require(type(value) is dict and set(value)==FIXTURE_KEYS,"FIXTURE_SHAPE_INVALID")
    require(value["schema_version"]==2 and value["authority"]=="SYNTHETIC_NON_AUTHORITATIVE_ONLY" and value["host_contract_observed"] is False and value["host_version_under_study"]=="2.1.322" and type(value["cases"]) is list,"FIXTURE_INVALID")
    sanitize_tree(value)
    return tuple(parse_synthetic_event(case) for case in value["cases"])
