#!/usr/bin/env python3
"""Offline, auditable total-return prioritisation for a fixed research universe.

No network, quote fallback, thesis inference, order placement or persistent writes.
The sole non-stdlib dependency is exchange_calendars (XNYS session boundaries).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

BASIS = "split_and_dividend_adjusted_total_return"
NY = ZoneInfo("America/New_York")


class ValidationError(ValueError):
    pass


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("timestamp must be an ISO-8601 string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("invalid ISO-8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValidationError("timestamp must carry an explicit timezone")
    return result.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value) -> str:
    # Invalid endpoint prices still need a reproducible coverage record. Hash a
    # tagged representation of non-JSON numeric inputs rather than allowing NaN
    # to break the entire scan after that individual security has been excluded.
    def canonical(item):
        if isinstance(item, float) and not math.isfinite(item):
            return {"invalid_nonfinite_float": repr(item)}
        if isinstance(item, Decimal):
            return {"decimal_input": str(item)}
        if isinstance(item, dict):
            return {key: canonical(value) for key, value in item.items()}
        if isinstance(item, list):
            return [canonical(value) for value in item]
        return item
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def positive_decimal(value) -> Decimal:
    # JSON binary floats are rejected: callers must retain the provider's decimal text.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError("adjusted_close must be a positive finite decimal string or integer")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("invalid decimal adjusted_close") from exc
    if not number.is_finite() or number <= 0:
        raise ValidationError("adjusted_close must be positive and finite")
    return number


def decimal_text(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def fraction_decimal(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError("tail_fraction must be finite decimal text, greater than zero and at most 0.5")
    try:
        fraction = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("invalid tail_fraction decimal") from exc
    if not fraction.is_finite() or not Decimal("0") < fraction <= Decimal("0.5"):
        raise ValidationError("tail_fraction must be finite, greater than zero and at most 0.5")
    return fraction


def universe_rows(universe: list[dict]) -> list[dict]:
    if not isinstance(universe, list) or not universe:
        raise ValidationError("universe must be a nonempty list")
    symbols, identifiers, result = set(), set(), []
    for item in universe:
        if not isinstance(item, dict):
            raise ValidationError("universe entries must be objects")
        symbol = item.get("symbol")
        identifier = item.get("id", symbol)
        if not isinstance(symbol, str) or not symbol or symbol != symbol.strip() or symbol != symbol.upper():
            raise ValidationError("universe symbols must be nonempty uppercase strings without outer whitespace")
        if not isinstance(identifier, str) or not identifier:
            raise ValidationError("universe identifiers must be nonempty strings")
        if symbol in symbols or identifier in identifiers:
            raise ValidationError("duplicate universe symbol or identifier")
        symbols.add(symbol)
        identifiers.add(identifier)
        row = {key: item[key] for key in ("id", "symbol", "name", "security_type", "leverage_label", "leverage_factor") if key in item}
        row.setdefault("id", identifier)
        row.setdefault("security_type", "unspecified")
        if row["security_type"] == "leveraged_etf":
            row.setdefault("leverage_label", "Daily-reset leveraged ETF; factor not supplied in this input")
        result.append(row)
    return result


def completed_week(as_of: str, week_start: str | None = None, calendar=None) -> dict:
    """Use the latest week whose final scheduled XNYS session has actually closed.

    The preceding week's final session is the return baseline. A four-session
    holiday week is complete after its last scheduled close, not on calendar Friday.
    Explicit historical week_start is allowed; unfinished/future weeks are rejected.
    """
    now = timestamp(as_of)
    if calendar is None:
        import exchange_calendars
        calendar = exchange_calendars.get_calendar("XNYS")
    ny_date = now.astimezone(NY).date()
    monday = ny_date - timedelta(days=ny_date.weekday())
    if week_start is not None:
        try:
            requested = date.fromisoformat(week_start)
        except (TypeError, ValueError) as exc:
            raise ValidationError("week_start must be YYYY-MM-DD") from exc
        if requested.weekday() != 0:
            raise ValidationError("week_start must be a Monday in America/New_York")
        if requested > monday:
            raise ValidationError("future week requested")
        monday = requested
    for _ in range(54):
        try:
            sessions = calendar.sessions_in_range(monday.isoformat(), (monday + timedelta(days=6)).isoformat())
            if len(sessions):
                final_session = sessions[-1]
                final_close = calendar.session_close(final_session).to_pydatetime()
                if final_close <= now:
                    previous = calendar.previous_session(sessions[0])
                    baseline_close = calendar.session_close(previous).to_pydatetime()
                    return {
                        "calendar": "XNYS", "session_timezone": "America/New_York",
                        "week_start": monday.isoformat(),
                        "week_end": (monday + timedelta(days=6)).isoformat(),
                        "sessions": [s.date().isoformat() for s in sessions],
                        "baseline_session": previous.date().isoformat(),
                        "end_session": final_session.date().isoformat(),
                        "baseline_close_utc": iso(baseline_close),
                        "end_close_utc": iso(final_close),
                        "as_of_utc": iso(now),
                    }
        except (ValueError, IndexError) as exc:
            raise ValidationError("week outside the available XNYS calendar") from exc
        if week_start is not None:
            raise ValidationError("requested week is not completed")
        monday -= timedelta(days=7)
    raise ValidationError("no completed trading week found")


def rank_week(universe: list[dict], observations: list[dict], as_of: str,
              week_start: str | None = None, calendar=None, tail_fraction="0.20") -> dict:
    names = universe_rows(universe)
    fraction = fraction_decimal(tail_fraction)
    if not isinstance(observations, list):
        raise ValidationError("observations must be a list")
    boundary = completed_week(as_of, week_start, calendar)
    now = timestamp(as_of)
    endpoints = (boundary["baseline_session"], boundary["end_session"])
    known = {n["symbol"] for n in names}
    data, extras = {}, set()
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValidationError("observation entries must be objects")
        symbol, session = observation.get("symbol"), observation.get("session")
        if not isinstance(symbol, str) or not isinstance(session, str):
            raise ValidationError("observation symbol and session must be strings")
        try:
            date.fromisoformat(session)
        except ValueError as exc:
            raise ValidationError("observation session must be YYYY-MM-DD") from exc
        if symbol not in known:
            extras.add(symbol)
            continue
        if session not in endpoints:
            continue
        key = (symbol, session)
        if key in data:
            raise ValidationError(f"duplicate endpoint observation: {symbol} {session}")
        data[key] = observation
    excluded, ranking = [], []
    for security in names:
        symbol = security["symbol"]
        errors, values, valid_observations = [], [], []
        for session, close_key in zip(endpoints, ("baseline_close_utc", "end_close_utc")):
            row = data.get((symbol, session))
            if row is None:
                errors.append({"session": session, "reason": "missing_endpoint"})
                continue
            try:
                value = positive_decimal(row.get("adjusted_close"))
                if row.get("adjustment_basis") != BASIS:
                    raise ValidationError("requires split-and-dividend-adjusted total-return close")
                for key in ("currency", "source", "adjustment_snapshot"):
                    if not isinstance(row.get(key), str) or not row[key].strip():
                        raise ValidationError(f"missing {key}")
                if row["currency"] != row["currency"].upper() or len(row["currency"]) != 3 or not row["currency"].isalpha():
                    raise ValidationError("currency must be an uppercase three-letter code")
                if row.get("price_unit") != "currency_per_share":
                    raise ValidationError("price_unit must be currency_per_share")
                observed = timestamp(row.get("observed_at"))
                if observed < timestamp(boundary[close_key]):
                    raise ValidationError("observation predates scheduled session close")
                if observed > now:
                    raise ValidationError("observation timestamp is in the future")
                values.append(value)
                valid_observations.append(row)
            except ValidationError as exc:
                errors.append({"session": session, "reason": "invalid_endpoint", "detail": str(exc)})
        if not errors:
            baseline, end = valid_observations
            for key in ("currency", "price_unit", "source", "adjustment_basis", "adjustment_snapshot"):
                if baseline[key] != end[key]:
                    errors.append({"reason": "inconsistent_endpoint_basis", "detail": f"mixed {key}"})
            if not errors:
                with localcontext() as ctx:
                    ctx.prec = 40
                    change = values[1] / values[0] - 1
                ranking.append({**security, "weekly_total_return": decimal_text(change),
                    "baseline_adjusted_close": decimal_text(values[0]),
                    "end_adjusted_close": decimal_text(values[1]),
                    "currency": baseline["currency"], "price_unit": baseline["price_unit"],
                    "adjustment_snapshot": baseline["adjustment_snapshot"], "source": baseline["source"],
                    "baseline_observed_at": baseline["observed_at"], "end_observed_at": end["observed_at"]})
        if errors:
            excluded.append({**security, "reasons": errors})
    ranking.sort(key=lambda row: (-Decimal(row["weekly_total_return"]), row["symbol"]))
    count = len(ranking)
    with localcontext() as ctx:
        ctx.prec = max(40, len(fraction.as_tuple().digits) + len(str(count)) + 2)
        tail_count = min(int((Decimal(count) * fraction).to_integral_value(rounding=ROUND_CEILING)), count // 2)
    for index, row in enumerate(ranking, 1):
        row["rank_descending"] = index
    top = ranking[:tail_count]
    bottom = sorted(ranking[count - tail_count:] if tail_count else [],
                    key=lambda row: (Decimal(row["weekly_total_return"]), row["symbol"]))
    return {
        "schema_version": "niulai-weekly-scan-1", "purpose": "review_prioritisation_only",
        "price_move_is_thesis_evidence": False,
        "method": {"return": "end_adjusted_close / baseline_adjusted_close - 1",
            "basis": BASIS, "selection_fraction": decimal_text(fraction),
            "tail_count_rule": "min(ceil(valid_count * selection_fraction), floor(valid_count / 2))",
            "tie_rule": "One descending return order, symbol ascending within ties; top first k, bottom last k. No overlap.",
            "funds": "Included as configured; leveraged daily-reset returns are not normalised to equity risk.",
            "missing_data": "Exclude and disclose; never impute zero return or substitute unadjusted quotes."},
        "boundaries": boundary,
        "coverage": {"universe_count": len(names), "valid_count": count,
            "excluded_count": len(excluded), "tail_count_each": tail_count,
            "complete": count == len(names), "excluded": excluded,
            "ignored_symbols": sorted(extras)},
        "input_provenance": {"universe_sha256": digest(names),
            "endpoint_observations_sha256": digest([data[k] for k in sorted(data)]),
            "calendar_package": "exchange_calendars", "calendar_version": _calendar_version()},
        "ranking": ranking, "top_performing": top, "bottom_performing": bottom,
    }


def _calendar_version():
    import importlib.metadata
    return importlib.metadata.version("exchange_calendars")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True, help="JSON list, or research catalogue containing securities")
    parser.add_argument("--observations", required=True, help="JSON list of explicit adjusted-close observations")
    parser.add_argument("--as-of", required=True, help="timezone-aware ISO-8601 cutoff")
    parser.add_argument("--week-start", help="optional historical Monday YYYY-MM-DD")
    parser.add_argument("--tail-fraction", default="0.20", help="fraction per tail as decimal text, >0 and <=0.5 (default 0.20)")
    parser.add_argument("--output", help="default stdout; output is written only if this is explicitly supplied")
    args = parser.parse_args()
    universe = json.loads(Path(args.universe).read_text())
    if isinstance(universe, dict):
        universe = universe.get("securities")
    result = rank_week(universe, json.loads(Path(args.observations).read_text()), args.as_of,
                       args.week_start, tail_fraction=args.tail_fraction)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
