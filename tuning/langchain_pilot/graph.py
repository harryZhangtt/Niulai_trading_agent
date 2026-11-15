"""Fixed validation around a small LangChain agent using an existing calculator.

Synthetic development data only. There are no source, account, trading, email,
shell or scheduler tools. The original calculator remains unchanged.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from decimal import Decimal
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_model_call
from langchain.tools import ToolRuntime, tool
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime
from langgraph.errors import GraphBubbleUp
from pydantic import BaseModel, ConfigDict, Field, field_validator
from openai import APIError, APITimeoutError, APIConnectionError

from shared.calculation.legacy.valuation.valuation_core import equity_value
from .credentials import CredentialError, openai_api_key
from .session_model import SessionModelError

DEFAULT_MODEL = "gpt-6.1-sol"
OPENAI_BASE_URL = "https://api.openai.com/v1"


class ValuationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    case_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    fcff: list[Decimal] = Field(min_length=1, max_length=5)
    terminal_ev: Decimal = Field(ge=0)
    rate: Decimal = Field(gt=-1, le=1)
    net_debt: Decimal
    shares: Decimal = Field(gt=0)

    @field_validator("fcff")
    @classmethod
    def finite_cashflows(cls, values: list[Decimal]) -> list[Decimal]:
        if any(not item.is_finite() for item in values):
            raise ValueError("cash flows must be finite")
        return values


class PilotInput(TypedDict):
    case: dict[str, Any]


class PilotContext(TypedDict, total=False):
    variant: str


class PilotOutput(TypedDict):
    result: dict[str, Any]


class PilotState(MessagesState):
    case: dict[str, Any]
    result: dict[str, Any]


def calculate(case: dict[str, Any]) -> dict[str, str]:
    """Thin adapter: preserve the existing calculator's inputs and Decimal math."""
    item = ValuationCase.model_validate(case)
    values = equity_value(item.fcff, item.terminal_ev, item.rate, item.net_debt, item.shares)
    return {"case_id": item.case_id, **{key: str(value) for key, value in values.items()}}


@tool
def calculate_valuation(runtime: ToolRuntime[PilotContext, PilotState]) -> dict[str, str]:
    """Calculate per-share value for this run's validated synthetic case.

    Inputs come from workflow state, so the model cannot replace the cash flows,
    debt, shares or rate. Returns exact Decimal strings from the existing tool.
    """
    return calculate(runtime.state["case"])


def openai_model(*, http_async_client=None) -> BaseChatModel:
    model = os.environ.get("LANGCHAIN_PILOT_MODEL", DEFAULT_MODEL)
    if model.startswith(("ferry-", "claude-")):
        raise ValueError("OPENAI_MODEL_REQUIRED")
    return ChatOpenAI(
        model=model,
        # Explicit official endpoint: inherited proxy-provider base URLs cannot route to Ferry.
        base_url=OPENAI_BASE_URL,
        api_key=openai_api_key,
        http_async_client=http_async_client,
        max_tokens=1024,
        reasoning={"effort": "low"},
        timeout=60,
        streaming=True,
        use_responses_api=True,
        max_retries=0,
    )


def default_model() -> BaseChatModel:
    engine = os.environ.get('LANGCHAIN_PILOT_ENGINE', 'session')
    if engine == 'openai':
        return openai_model()
    if engine == 'session':
        from .session_model import SessionChatModel
        return SessionChatModel()
    raise ValueError('PILOT_ENGINE_UNKNOWN')


@wrap_model_call
async def bounded_model_call(request, handler):
    """Bound model time and keep raw SDK responses/credential errors out of state."""
    try:
        return await asyncio.wait_for(handler(request), timeout=90)
    except GraphBubbleUp:
        raise
    except (CredentialError, SessionModelError):
        raise
    except (APITimeoutError, APIConnectionError):
        raise TimeoutError("OPENAI_REQUEST_OUTCOME_UNKNOWN") from None
    except APIError as error:
        status = getattr(error, "status_code", None)
        code = str(status) if isinstance(status, int) else "SDK_ERROR"
        raise RuntimeError("OPENAI_REQUEST_FAILED_" + code) from None
    except Exception as error:
        # Integrations may wrap SDK errors; preserve outcome uncertainty and
        # avoid serializing a raw provider exception or credential into graph state.
        cause = error.__cause__
        if isinstance(cause, (APITimeoutError, APIConnectionError)):
            raise TimeoutError("OPENAI_REQUEST_OUTCOME_UNKNOWN") from None
        status = getattr(error, "status_code", None) or getattr(cause, "status_code", None)
        code = str(status) if isinstance(status, int) else type(error).__name__
        raise RuntimeError("OPENAI_REQUEST_FAILED_" + code) from None


def prepare(state: PilotState, runtime: Runtime[PilotContext]) -> dict[str, Any]:
    raw = state.get("case")
    # Studio's Case field already supplies the outer key. Tolerate one exact
    # extra wrapper, without discarding any other supplied fields.
    if isinstance(raw, dict) and set(raw) == {"case"}:
        raw = raw["case"]
    if not isinstance(raw, dict):
        raise ValueError("CASE_REQUIRED: put the valuation object in Studio's Case field; "
                         "Raw input uses {\"case\": {...}}")
    item = ValuationCase.model_validate(raw)
    variant = (runtime.context or {}).get("variant", "baseline")
    if variant not in {"baseline", "concise"}:
        raise ValueError("unknown pilot variant")
    request = "Call calculate_valuation to calculate this synthetic case."
    if variant == "concise":
        request += " Keep the final answer minimal."
    return {
        "case": item.model_dump(mode="json"),
        "result": {},
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(content=request)],
    }


def verify(state: PilotState) -> dict[str, Any]:
    """Require actual tool use and check its result against an independent oracle."""
    messages = state["messages"]
    receipts = [message for message in messages if isinstance(message, ToolMessage)
                and message.name == "calculate_valuation" and message.status == "success"]
    if not receipts:
        raise ValueError("no successful calculator tool receipt")
    receipt = receipts[-1]
    selected = any(isinstance(message, AIMessage) and any(
        call.get("id") == receipt.tool_call_id and call.get("name") == "calculate_valuation"
        for call in message.tool_calls) for message in messages)
    if not selected:
        raise ValueError("calculator receipt is not bound to a model tool call")
    tool_result = json.loads(receipt.content)
    case = ValuationCase.model_validate(state["case"])
    # Independent rational arithmetic for the bounded synthetic check. This is
    # deliberately not the implementation function imported by the tool.
    from fractions import Fraction
    discount = 1 + Fraction(case.rate)
    enterprise = sum(Fraction(value) / discount ** period
                     for period, value in enumerate(case.fcff, 1))
    enterprise += Fraction(case.terminal_ev) / discount ** len(case.fcff)
    expected = (enterprise - Fraction(case.net_debt)) / Fraction(case.shares)
    observed = Fraction(Decimal(tool_result["per_share"]))
    if tool_result["case_id"] != case.case_id or not math.isclose(
            float(observed), float(expected), rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("calculator result failed independent check")
    last = messages[-1]
    if not isinstance(last, AIMessage) or last.tool_calls:
        raise ValueError("agent did not finish with an answer")
    text = last.content if isinstance(last.content, str) else "".join(
        block.get("text", "") for block in last.content if isinstance(block, dict)
        and block.get("type") == "text")
    answer = json.loads(text)
    if answer != {"per_share": tool_result["per_share"], "synthetic": True}:
        raise ValueError("agent answer differs from the calculator result")
    return {"result": {"status": "passed", "scope": "synthetic_local_pilot",
                       "case_id": case.case_id, "per_share": tool_result["per_share"],
                       "tool_calls": len(receipts), "answer": answer}}


def make_graph(model: BaseChatModel | None = None, *, checkpointer=None):
    agent = create_agent(
        model=model if model is not None else default_model(),
        tools=[calculate_valuation],
        state_schema=PilotState,
        context_schema=PilotContext,
        system_prompt=(
            "You are a bounded calculator adapter test. You must call calculate_valuation. "
            "After the tool returns, output exactly a JSON object with per_share copied "
            "as its exact string from the tool, and synthetic set to true. "
            "Do not add prose, markdown, rounding or other keys."
        ),
        middleware=[bounded_model_call, ModelCallLimitMiddleware(run_limit=3, exit_behavior="error")],
        name="valuation_agent",
    )
    builder = StateGraph(PilotState, input_schema=PilotInput, output_schema=PilotOutput,
                         context_schema=PilotContext)
    builder.add_node("validate_input", prepare)
    builder.add_node("agent", agent)
    builder.add_node("validate_result", verify)
    builder.add_edge(START, "validate_input")
    builder.add_edge("validate_input", "agent")
    builder.add_edge("agent", "validate_result")
    builder.add_edge("validate_result", END)
    return builder.compile(name="trading_agent_pilot", checkpointer=checkpointer)


graph = make_graph()
