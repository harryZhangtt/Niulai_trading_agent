"""Closed provider-free contracts for unanswered-question readiness."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, math, re, unicodedata
from typing import Any, Mapping, Tuple

CAPABILITY = "claude_unanswered_question_v1"
CAPABILITY_STATUS = "BLOCKED_HOST_CONTRACT_UNOBSERVED"
HOST_VERSION = "2.1.322"
DUE_NS = 300_000_000_000
SAFE_CAPABILITIES = frozenset(("local_noop_preference",))
FORBIDDEN_EFFECTS = frozenset((
    "permission", "approval", "credential", "account", "destructive_write", "message_delivery",
    "business_transaction", "deployment", "production", "trading", "host_change", "config_change",
    "hook_change", "daemon_change", "scheduler_change", "installation", "persistence",
))
FENCE_TERMS = (
    "approve", "authorize", "allow", "grant", "permission", "oauth", "access token", "private key",
    "credential", "login", "account", "delete", "edit", "save", "modify", "write", "send", "email",
    "payment", "purchase", "deploy", "production", "trade", "order", "host", "config", "hook", "daemon",
    "scheduler", "install", "persist",
)
SECRET_NAMES = frozenset((
    "secret", "password", "credential", "credentials", "api_key", "apikey", "auth", "authorization",
    "auth_token", "access_token", "private_key", "oauth_token",
))
SECRET_VALUE_TERMS = ("bearer ", "access token", "private key", "api key", "api_key", "auth token", "password", "secret")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")

class ContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code; super().__init__(code)

def require(ok: bool, code: str) -> None:
    if not ok: raise ContractError(code)

def canonical_bytes(value: Any) -> bytes:
    try: return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError): raise ContractError("CANONICAL_JSON_INVALID") from None

def digest(value: Any) -> str: return hashlib.sha256(canonical_bytes(value)).hexdigest()

def exact_int_ns(value: Any, code: str) -> int:
    require(type(value) is int and value >= 0, code)
    return value

def sanitize_tree(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            require(type(key) is str and key.lower().replace("-", "_") not in SECRET_NAMES, "SECRET_SANITIZATION_FAILED")
            sanitize_tree(child)
    elif isinstance(value, (list, tuple)):
        for child in value: sanitize_tree(child)
    elif type(value) is str:
        low = unicodedata.normalize("NFKC", value).lower()
        require(not any(term in low for term in SECRET_VALUE_TERMS), "SECRET_SANITIZATION_FAILED")

def normalized_text(value: str) -> Tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    spaced = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return spaced, re.sub(r"[^a-z0-9]", "", normalized)

def contains_fenced_text(value: str) -> bool:
    spaced, compact = normalized_text(value)
    padded = " " + spaced + " "
    for term in FENCE_TERMS:
        term_spaced, term_compact = normalized_text(term)
        if " " + term_spaced + " " in padded or term_compact in compact:
            return True
    return False

@dataclass(frozen=True)
class QuestionOption:
    option_id: str
    label: str
    description: str
    recommended: bool
    def __post_init__(self) -> None:
        require(type(self.option_id) is str and _ID.fullmatch(self.option_id) is not None, "OPTION_ID_INVALID")
        require(type(self.label) is str and 1 <= len(self.label) <= 240, "OPTION_LABEL_INVALID")
        require(type(self.description) is str and len(self.description) <= 500, "OPTION_DESCRIPTION_INVALID")
        require(type(self.recommended) is bool, "OPTION_RECOMMENDATION_NOT_EXPLICIT")
        sanitize_tree({"label": self.label, "description": self.description})

@dataclass(frozen=True)
class SyntheticAuthority:
    """Synthetic typed authority only; never establishes real host authority."""
    safe_capability: str
    forbidden_effects: Tuple[str, ...]
    def __post_init__(self) -> None:
        require(type(self.safe_capability) is str and self.safe_capability in SAFE_CAPABILITIES, "SAFE_CAPABILITY_INVALID")
        require(type(self.forbidden_effects) is tuple, "EFFECT_CLASSIFICATION_INVALID")
        require(len(set(self.forbidden_effects)) == len(self.forbidden_effects), "EFFECT_CLASSIFICATION_INVALID")
        require(all(type(x) is str and x in FORBIDDEN_EFFECTS for x in self.forbidden_effects), "EFFECT_CLASSIFICATION_INVALID")

@dataclass(frozen=True)
class SyntheticQuestionEvent:
    synthetic_schema: str
    host_version_under_study: str
    event_id: str
    question_id: str
    question_kind: str
    caller_category: str
    prompt: str
    options: Tuple[QuestionOption, ...]
    authority: SyntheticAuthority
    observed_monotonic_ns: int
    replaced_by_question_id: str
    def __post_init__(self) -> None:
        require(self.synthetic_schema == "synthetic-nonauthoritative-question-v2", "SYNTHETIC_SCHEMA_INVALID")
        require(self.host_version_under_study == HOST_VERSION, "HOST_VERSION_INVALID")
        require(type(self.event_id) is str and _ID.fullmatch(self.event_id) is not None, "EVENT_ID_INVALID")
        require(type(self.question_id) is str and _ID.fullmatch(self.question_id) is not None, "QUESTION_ID_INVALID")
        require(self.question_kind in ("single", "multi"), "FREEFORM_FORBIDDEN")
        require(type(self.caller_category) is str and len(self.caller_category) <= 120, "CALLER_CATEGORY_INVALID")
        require(type(self.prompt) is str and 1 <= len(self.prompt) <= 1000, "PROMPT_INVALID")
        require(type(self.options) is tuple and 1 <= len(self.options) <= 20, "OPTIONS_INVALID")
        exact_int_ns(self.observed_monotonic_ns, "MONOTONIC_INVALID")
        require(type(self.replaced_by_question_id) is str, "REPLACEMENT_INVALID")
        if self.replaced_by_question_id: require(_ID.fullmatch(self.replaced_by_question_id) is not None, "REPLACEMENT_INVALID")
        ids = [x.option_id for x in self.options]; require(len(ids) == len(set(ids)), "DUPLICATE_OPTIONS")
        sanitize_tree({"caller_category": self.caller_category, "prompt": self.prompt})
    def identity_body(self) -> Mapping[str, Any]:
        return {"event_id":self.event_id,"question_id":self.question_id,"question_kind":self.question_kind,
            "caller_category":self.caller_category,"safe_capability":self.authority.safe_capability,
            "forbidden_effects":list(self.authority.forbidden_effects),"prompt_sha256":hashlib.sha256(self.prompt.encode()).hexdigest(),
            "options_sha256":digest([{"option_id":x.option_id,"label":x.label,"description":x.description,"recommended":x.recommended} for x in self.options]),
            "observed_monotonic_ns":self.observed_monotonic_ns}

@dataclass(frozen=True)
class QuestionJobIdentity:
    job_id: str; question_id: str; event_id: str; question_identity_sha256: str
    @classmethod
    def from_event(cls, event: SyntheticQuestionEvent) -> "QuestionJobIdentity":
        sha=digest(event.identity_body()); return cls("question-job/"+sha,event.question_id,event.event_id,sha)
    def __post_init__(self) -> None:
        require(type(self.job_id) is str and self.job_id.startswith("question-job/") and _SHA.fullmatch(self.job_id[13:]) is not None, "JOB_ID_INVALID")
        require(self.job_id == "question-job/"+self.question_identity_sha256 and _SHA.fullmatch(self.question_identity_sha256) is not None, "JOB_ID_MISMATCH")

@dataclass(frozen=True)
class AnswerDecision:
    job: QuestionJobIdentity; option_ids: Tuple[str, ...]; observed_monotonic_ns: int; due_ns: int = DUE_NS
    def __post_init__(self) -> None:
        require(type(self.option_ids) is tuple and self.option_ids and len(set(self.option_ids)) == len(self.option_ids), "ANSWER_OPTIONS_INVALID")
        require(all(type(x) is str and _ID.fullmatch(x) is not None for x in self.option_ids), "ANSWER_OPTIONS_INVALID")
        exact_int_ns(self.observed_monotonic_ns,"MONOTONIC_INVALID"); require(self.due_ns == DUE_NS,"DUE_WINDOW_INVALID")
    @property
    def operation_sha256(self) -> str:
        return digest({"job_id":self.job.job_id,"question_identity_sha256":self.job.question_identity_sha256,"selected_option_ids":list(self.option_ids)})
