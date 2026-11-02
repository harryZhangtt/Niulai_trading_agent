"""Small typed boolean/enum contract; classification never approves evidence."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType


VERSION = 'typed-judge-1.1.0'
PROVIDER = 'typesafe'
ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
CREDENTIAL_REF = '.job-runtime/credentials/jev.api-key'
MAX_ATTEMPT_TIMEOUT_SECONDS = 60
MAX_TOTAL_TIMEOUT_SECONDS = 120
PROBABILITY_SUM_TOLERANCE = 0.001
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,79}')


class JudgeError(ValueError):
    """Stable diagnostics only; never construct from provider/body/key text."""


def require(condition, code):
    if not condition:
        raise JudgeError(code)


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def probability(value):
    return number(value) and 0 <= value <= 1


def identifier(value):
    require(isinstance(value, str) and _ID.fullmatch(value), 'JUDGE_REQUEST_INVALID')


@dataclass(frozen=True)
class DecisionPolicy:
    """Caller-owned thresholds, to be calibrated on its separate labeled data."""
    min_probability: float
    min_margin: float = 0.0

    def __post_init__(self):
        require(probability(self.min_probability) and probability(self.min_margin), 'JUDGE_POLICY_INVALID')


@dataclass(frozen=True)
class BooleanQuestion:
    id: str
    instructions: str
    true_criteria: str = ''
    false_criteria: str = ''
    policy: DecisionPolicy | None = None

    def __post_init__(self):
        identifier(self.id)
        require(isinstance(self.instructions, str) and 0 < len(self.instructions) <= 4000 and
                all(isinstance(value, str) and len(value) <= 2000 for value in (self.true_criteria, self.false_criteria)) and
                (self.policy is None or isinstance(self.policy, DecisionPolicy)), 'JUDGE_REQUEST_INVALID')

    def wire(self):
        result = {'type': 'noul', 'instructions': self.instructions}
        if self.true_criteria or self.false_criteria:
            result['criteria'] = {'true': self.true_criteria, 'false': self.false_criteria}
        return result

    def contract(self):
        return {'type': 'boolean', 'wire': self.wire(), 'policy': policy_value(self.policy)}


@dataclass(frozen=True)
class EnumQuestion:
    id: str
    instructions: str
    options: dict[str, str]
    policy: DecisionPolicy | None = None
    abstain_options: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.id)
        require(isinstance(self.instructions, str) and 0 < len(self.instructions) <= 4000 and
                isinstance(self.options, dict) and 2 <= len(self.options) <= 32 and
                all(isinstance(key, str) and _ID.fullmatch(key) and isinstance(value, str) and
                    0 < len(value) <= 2000 for key, value in self.options.items()) and
                (self.policy is None or isinstance(self.policy, DecisionPolicy)) and
                isinstance(self.abstain_options, (list, tuple)) and len(set(self.abstain_options)) == len(self.abstain_options) and
                set(self.abstain_options) <= set(self.options), 'JUDGE_REQUEST_INVALID')
        object.__setattr__(self, 'options', MappingProxyType(dict(self.options)))
        object.__setattr__(self, 'abstain_options', tuple(self.abstain_options))

    def wire(self):
        return {'type': 'choice', 'instructions': self.instructions, 'criteria': dict(self.options)}

    def contract(self):
        return {'type': 'enum', 'wire': self.wire(), 'policy': policy_value(self.policy),
            'abstain_options': list(self.abstain_options)}


def policy_value(policy):
    return None if policy is None else {'min_probability': policy.min_probability, 'min_margin': policy.min_margin}


@dataclass(frozen=True)
class Decision:
    question_id: str
    type: str
    status: str
    value: bool | str | None
    candidate: bool | str
    probabilities: dict[str, float]
    confidence: float | None
    reason_code: str | None
    model_resolved: str
    schema_sha256: str

    def to_dict(self):
        return {**self.__dict__, 'probabilities': dict(self.probabilities)}


@dataclass(frozen=True)
class JudgeResult:
    status: str
    decisions: dict[str, Decision]
    receipt: dict
    error_code: str | None = None

    def to_dict(self):
        return {'status': self.status, 'decisions': {key: value.to_dict() for key, value in self.decisions.items()},
            'receipt': dict(self.receipt), 'error_code': self.error_code}


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: bytes
    retry_after_seconds: float | None = None

