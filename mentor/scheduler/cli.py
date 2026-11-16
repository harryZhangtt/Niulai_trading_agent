"""Read-only CLI projection for canonical mentor work-order status JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, TextIO

from .contracts import ContractError, strict_json_loads

UTC = timezone.utc
MAX_FILE_BYTES = 1_048_576
MAX_WORK_ORDERS = 100
MAX_AGE_SECONDS = 900
MAX_FUTURE_SKEW_SECONDS = 5


class ProjectionError(ValueError):
    """A stable, sanitized projection failure."""

    def __init__(self, code: str, exit_code: int = 2) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def _fail(code: str, exit_code: int = 2) -> None:
    raise ProjectionError(code, exit_code)


def _keys(value: Any, expected: set[str], required: set[str] | None = None) -> None:
    if type(value) is not dict:
        _fail("SCHEMA_INVALID")
    if set(value) - expected or not (required or expected) <= set(value):
        _fail("SCHEMA_UNKNOWN_OR_MISSING_FIELD")


def _instant(value: Any, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > 40:
        _fail("TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("TIME_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("TIME_INVALID")
    return parsed.astimezone(UTC)


def _identifier(value: Any, *, maximum: int = 96) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        rf"[A-Za-z0-9][A-Za-z0-9_.:-]{{0,{maximum - 1}}}", value
    ):
        _fail("IDENTIFIER_INVALID")
    return value


def _number(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        _fail("NUMBER_INVALID")
    return value


_CREDENTIAL_PATTERNS = (
    # Labelled credentials, including cloud-provider environment variable forms.
    re.compile(
        r"(?i)\b(?:aws[_-]?(?:secret[_-]?access[_-]?key|access[_-]?key[_-]?id|session[_-]?token)|"
        r"api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|client[_-]?secret|"
        r"private[_-]?key|secret)\b\s*[=:]\s*\S+"
    ),
    re.compile(r"(?i)\bauthorization\s*:\s*(?:basic|bearer)\s+\S+"),
    re.compile(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:set-cookie|cookie)\s*:\s*[^\r\n]+"),
    re.compile(r"-----BEGIN [^-\r\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\r\n]*PRIVATE KEY-----|$)", re.I),
    # AWS IDs, JWTs, and common provider token prefixes.
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|"
        r"github_pat_[A-Za-z0-9_]{16,}|glpat-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|"
        r"npm_[A-Za-z0-9]{16,}|pypi-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{16,})\b"
    ),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.I),
)
_TOKEN_CANDIDATE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z0-9_+/=-]{32,}(?![A-Za-z0-9_])")
_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:/(?:[^\s/]+/)+[^\s,;]*|[A-Za-z]:\\(?:[^\s\\]+\\)+[^\s,;]*)")
_UNSAFE_TEXT = "[redacted unsafe text]"


def _looks_high_entropy(value: str) -> bool:
    """Catch unlabeled token material without rejecting ordinary status phrases."""
    for match in _TOKEN_CANDIDATE.finditer(value):
        token = match.group(0).rstrip("=")
        if len(token) < 32:
            continue
        counts = {character: token.count(character) for character in set(token)}
        entropy = -sum(
            (count / len(token)) * math.log2(count / len(token))
            for count in counts.values()
        )
        has_nonletter = any(ch.isdigit() or ch in "_+/-" for ch in token)
        mixed_case = any(ch.islower() for ch in token) and any(ch.isupper() for ch in token)
        if entropy >= 3.5 and (has_nonletter or mixed_case):
            return True
    return False


def _contains_credential(value: str) -> bool:
    return any(pattern.search(value) for pattern in _CREDENTIAL_PATTERNS) or _looks_high_entropy(value)


def _text(value: Any, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        _fail("TEXT_INVALID")
    # Redact the entire field: retaining surrounding attacker-controlled text can
    # leak split credentials or misleading partial provider responses.
    if _contains_credential(value):
        return _UNSAFE_TEXT
    # Flatten terminal controls/newlines so human output cannot inject rows or escapes.
    value = " ".join(value.split())
    value = _PATH_PATTERN.sub("[redacted path]", value)
    value = "".join(ch for ch in value if ch.isprintable())
    return value


def _status(value: Any, maximum: int = 80) -> str:
    value = _text(value, maximum)
    if not value or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.:/+()-]*", value):
        _fail("STATUS_INVALID")
    return value


def _read_state(path: str) -> Any:
    candidate = Path(path)
    try:
        before = candidate.lstat()
        if stat.S_ISLNK(before.st_mode):
            _fail("STATE_SYMLINK_REJECTED")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(candidate, flags)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                _fail("STATE_FILE_INVALID")
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            _fail("STATE_FILE_TOO_LARGE")
    except ProjectionError:
        raise
    except OSError:
        _fail("STATE_UNAVAILABLE")
    try:
        return strict_json_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ContractError):
        _fail("STATE_JSON_INVALID")


def _validate_item(raw: Any) -> dict[str, Any]:
    top = {"id", "logical_session", "schedule", "scheduler", "task", "budgets", "evaluation", "delivery"}
    _keys(raw, top)

    _keys(raw["schedule"], {"start_at", "end_at", "next_run_at"})
    start = _instant(raw["schedule"]["start_at"])
    end = _instant(raw["schedule"]["end_at"])
    next_run = _instant(raw["schedule"]["next_run_at"], nullable=True)
    if end <= start:
        _fail("SCHEDULE_INVALID")

    _keys(raw["scheduler"], {"status", "slot_id"}, {"status"})
    scheduler = {"status": _status(raw["scheduler"]["status"])}
    if "slot_id" in raw["scheduler"]:
        scheduler["slot_id"] = _identifier(raw["scheduler"]["slot_id"], maximum=128)

    _keys(raw["task"], {"status", "gates", "last_verified_progress", "current_obstacle", "next_action", "goal_drift"})
    _keys(raw["task"]["gates"], {"verified", "failed", "pending"})
    task = {
        "status": _status(raw["task"]["status"]),
        "gates": {name: _number(raw["task"]["gates"][name]) for name in ("verified", "failed", "pending")},
        "last_verified_progress": _text(raw["task"]["last_verified_progress"], 500),
        "current_obstacle": _text(raw["task"]["current_obstacle"], 500),
        "next_action": _text(raw["task"]["next_action"], 500),
        "goal_drift": _text(raw["task"]["goal_drift"], 240),
    }

    budget_keys = {"cycles_used", "max_cycles", "interventions_used", "intervention_limit", "variants_used", "variant_limit"}
    _keys(raw["budgets"], budget_keys)
    budgets = {key: _number(raw["budgets"][key]) for key in budget_keys}
    for used, limit in (("cycles_used", "max_cycles"), ("interventions_used", "intervention_limit"), ("variants_used", "variant_limit")):
        if budgets[used] > budgets[limit]:
            _fail("BUDGET_INVALID")

    _keys(raw["evaluation"], {"baseline", "holdout", "promotion"})
    evaluation = {key: _text(raw["evaluation"][key], 160) for key in ("baseline", "holdout", "promotion")}
    _keys(raw["delivery"], {"runtime_report", "email"})
    delivery = {key: _status(raw["delivery"][key], 120) for key in ("runtime_report", "email")}

    return {
        "id": _identifier(raw["id"]),
        "logical_session": _identifier(raw["logical_session"], maximum=128),
        "schedule": {
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "next_run_at": next_run.isoformat() if next_run else None,
        },
        "scheduler": scheduler,
        "task": task,
        "budgets": budgets,
        "evaluation": evaluation,
        "delivery": delivery,
    }


def load_projection(path: str, at: datetime) -> dict[str, Any]:
    raw = _read_state(path)
    _keys(raw, {"schema_version", "generated_at", "work_orders"})
    if raw["schema_version"] != 1:
        _fail("SCHEMA_VERSION_UNSUPPORTED")
    generated = _instant(raw["generated_at"])
    if not isinstance(raw["work_orders"], list):
        _fail("SCHEMA_INVALID")
    if len(raw["work_orders"]) > MAX_WORK_ORDERS:
        _fail("WORK_ORDER_LIMIT")
    age = (at - generated).total_seconds()
    if age > MAX_AGE_SECONDS:
        _fail("STATE_STALE")
    if age < -MAX_FUTURE_SKEW_SECONDS:
        _fail("STATE_FROM_FUTURE")
    items = [_validate_item(item) for item in raw["work_orders"]]
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        _fail("WORK_ORDER_DUPLICATE")
    return {"schema_version": 1, "generated_at": generated.isoformat(), "work_orders": items}


def _time_left(end_at: str, at: datetime) -> tuple[int, str]:
    seconds = max(0, int((_instant(end_at) - at).total_seconds()))
    if seconds == 0:
        return 0, "ended"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return seconds, " ".join(parts[:2])


def _clip(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def render_table(items: list[dict[str, Any]], at: datetime) -> str:
    headers = ("WORK ORDER", "SCHEDULER", "TASK", "NEXT RUN", "LEFT", "GATES V/F/P", "CYCLES", "EMAIL")
    rows = []
    for item in items:
        gates = item["task"]["gates"]
        _, remaining = _time_left(item["schedule"]["end_at"], at)
        rows.append((
            _clip(item["id"], 20), _clip(item["scheduler"]["status"], 12),
            _clip(item["task"]["status"], 12), item["schedule"]["next_run_at"] or "—",
            remaining, f'{gates["verified"]}/{gates["failed"]}/{gates["pending"]}',
            f'{item["budgets"]["cycles_used"]}/{item["budgets"]["max_cycles"]}',
            _clip(item["delivery"]["email"], 18),
        ))
    widths = [len(value) for value in headers]
    for row in rows:
        widths = [max(widths[index], len(value)) for index, value in enumerate(row)]
    line = lambda row: "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
    return "\n".join([line(headers), line(tuple("-" * width for width in widths)), *(line(row) for row in rows)])


def render_detail(item: dict[str, Any], at: datetime) -> str:
    seconds, remaining = _time_left(item["schedule"]["end_at"], at)
    gates, budgets = item["task"]["gates"], item["budgets"]
    lines = [
        f'Work order: {item["id"]}',
        f'Logical session: {item["logical_session"]}',
        f'Scheduler state: {item["scheduler"]["status"]}',
        f'Task state: {item["task"]["status"]}',
        f'Slot: {item["scheduler"].get("slot_id", "—")}',
        f'Window: {item["schedule"]["start_at"]} → {item["schedule"]["end_at"]}',
        f'Next run: {item["schedule"]["next_run_at"] or "—"}',
        f'Time remaining: {remaining} ({seconds}s)',
        f'Gates: verified={gates["verified"]} failed={gates["failed"]} pending={gates["pending"]}',
        f'Cycles: {budgets["cycles_used"]}/{budgets["max_cycles"]}',
        f'Interventions: {budgets["interventions_used"]}/{budgets["intervention_limit"]}',
        f'Variants: {budgets["variants_used"]}/{budgets["variant_limit"]}',
        f'Last verified progress: {item["task"]["last_verified_progress"]}',
        f'Current obstacle: {item["task"]["current_obstacle"]}',
        f'Next action: {item["task"]["next_action"]}',
        f'Goal drift: {item["task"]["goal_drift"]}',
        f'Evaluation baseline: {item["evaluation"]["baseline"]}',
        f'Holdout: {item["evaluation"]["holdout"]}',
        f'Promotion: {item["evaluation"]["promotion"]}',
        f'Runtime report: {item["delivery"]["runtime_report"]}',
        f'Email: {item["delivery"]["email"]}',
    ]
    return "\n".join(lines)


def _json_projection(projection: dict[str, Any], items: list[dict[str, Any]], at: datetime) -> dict[str, Any]:
    output_items = []
    for item in items:
        copied = json.loads(json.dumps(item))
        copied["time_remaining_seconds"] = _time_left(item["schedule"]["end_at"], at)[0]
        output_items.append(copied)
    return {
        "schema_version": projection["schema_version"],
        "generated_at": projection["generated_at"],
        "as_of": at.astimezone(UTC).isoformat(),
        "read_only": True,
        "work_orders": output_items,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="canonical projection JSON file")
    parser.add_argument("--work-order-id")
    parser.add_argument("--at", help="aware ISO timestamp for deterministic rendering")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    args = _parser().parse_args(argv)
    try:
        at = _instant(args.at) if args.at else datetime.now(UTC)
        if args.work_order_id is not None:
            selected_id = _identifier(args.work_order_id)
        else:
            selected_id = None
        projection = load_projection(args.state, at)
        items = projection["work_orders"]
        if selected_id is not None:
            items = [item for item in items if item["id"] == selected_id]
            if not items:
                _fail("WORK_ORDER_NOT_FOUND", 3)
        if args.json_output:
            print(json.dumps(_json_projection(projection, items, at), ensure_ascii=False, allow_nan=False, sort_keys=True), file=stdout)
        elif selected_id is not None:
            print(render_detail(items[0], at), file=stdout)
        else:
            print(render_table(items, at), file=stdout)
        return 0
    except ProjectionError as error:
        print(f"error: {error.code}", file=stderr)
        return error.exit_code
    except Exception:
        print("error: INTERNAL_ERROR", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
