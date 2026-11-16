from __future__ import annotations
from .contracts import AnswerDecision, DUE_NS, QuestionJobIdentity, SyntheticQuestionEvent, contains_fenced_text, exact_int_ns, require

def decide_answer(event: SyntheticQuestionEvent, *, now_monotonic_ns: int) -> AnswerDecision:
    exact_int_ns(now_monotonic_ns,"MONOTONIC_INVALID")
    require(now_monotonic_ns >= event.observed_monotonic_ns,"MONOTONIC_INVALID")
    require(now_monotonic_ns-event.observed_monotonic_ns >= DUE_NS,"QUESTION_NOT_DUE")
    require(event.replaced_by_question_id=="","QUESTION_REPLACED")
    require(event.authority.safe_capability=="local_noop_preference","SAFE_CAPABILITY_INVALID")
    require(not event.authority.forbidden_effects,"QUESTION_EFFECT_FENCED")
    texts=[event.prompt,event.caller_category]
    for option in event.options: texts.extend((option.label,option.description))
    require(not any(contains_fenced_text(text) for text in texts),"QUESTION_TEXT_FENCED")
    recommended=tuple(x.option_id for x in event.options if x.recommended)
    if event.question_kind=="single": require(len(recommended)==1,"SINGLE_RECOMMENDATION_INVALID")
    else: require(len(recommended)>=1,"MULTI_RECOMMENDATION_MISSING")
    return AnswerDecision(QuestionJobIdentity.from_event(event),recommended,event.observed_monotonic_ns)
