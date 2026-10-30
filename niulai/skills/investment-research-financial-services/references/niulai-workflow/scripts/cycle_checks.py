#!/usr/bin/env python3
"""Deterministic supplied-input economic arithmetic; no cycle prediction or score.

Public API: calculate(packet) -> JSON-safe dict, or CycleCheckError.
Financial inputs and outputs are decimal strings. See the worked packet for the
small versioned interface. No source is fetched, authenticated or forecast here.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


VERSION = "2026-10-23-cycle-economics-1"
PRECISION = 256
_CONTEXT = Context(prec=PRECISION, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999)
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_NUMBER = re.compile(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z"
)
_QUANTITY = re.compile(r"quantity:([A-Za-z][A-Za-z0-9_.-]{0,47})\Z")
_MONEY = re.compile(r"currency:([A-Z]{3})\Z")
_UNIT_PRICE = re.compile(
    r"currency:([A-Z]{3})/quantity:([A-Za-z][A-Za-z0-9_.-]{0,47})\Z"
)
_SHARE_PRICE = re.compile(r"currency:([A-Z]{3})/share\Z")
_SEGMENT_FIELDS = (
    "volume", "asp", "variable_cost_per_unit", "cash_fixed_cost", "da",
    "tax_rate", "cash_capex", "change_nwc",
)
_CASH_METRICS = (
    "revenue", "variable_cash_cost", "cash_fixed_cost", "ebitda", "da",
    "ebit", "cash_tax", "nopat", "cash_capex", "change_nwc", "fcff",
)
_BRIDGE_FIELDS = (
    "price", "current_shares", "valuation_shares", "net_debt",
)


class CycleCheckError(ValueError):
    """A stable machine-readable input/arithmetic error."""

    def __init__(self, code, path, message):
        self.code, self.path, self.message = code, path, message
        super().__init__(f"{code} at {path}: {message}")

    def as_dict(self):
        return {"version": VERSION, "status": "error", "error": {
            "code": self.code, "path": self.path, "message": self.message,
        }}


def _fail(code, path, message):
    raise CycleCheckError(code, path, message)


def _obj(value, path, required, optional=()):
    if type(value) is not dict or any(type(k) is not str for k in value):
        _fail("type", path, "Expected an object with string keys")
    missing = set(required) - set(value)
    extra = set(value) - set(required) - set(optional)
    if missing:
        _fail("missing_field", path, "Missing fields: " + ", ".join(sorted(missing)))
    if extra:
        _fail("unknown_field", path, "Unknown fields: " + ", ".join(sorted(extra)))
    return value


def _text(value, path, limit=4096):
    if (type(value) is not str or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(c) < 32 for c in value)):
        _fail("text", path, "Expected bounded, nonempty text without outer whitespace or controls")
    return value


def _identifier(value, path):
    if type(value) is not str or not _ID.fullmatch(value):
        _fail("identifier", path, "Expected an ASCII letter followed by up to 63 letters, digits, _ or -")
    return value


def _list(value, path, minimum=0, maximum=1000):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _fail("type", path, f"Expected a list with {minimum}..{maximum} items")
    return value


def _number(value, path):
    # Strings avoid binary-float contamination, bool-as-int, exponent explosions,
    # nonstandard JSON NaN/Infinity, and ambiguous percent conversions.
    if (type(value) is not str or len(value) > 80
            or not _NUMBER.fullmatch(value)):
        _fail("decimal", path, "Expected a finite plain decimal string (no exponent or JSON number)")
    result = Decimal(value)
    if not result.is_finite() or len(result.as_tuple().digits) > 72:
        _fail("decimal", path, "Decimal has too many digits or is not finite")
    return result


def _date(value, path):
    if type(value) is not str or not _DATE.fullmatch(value):
        _fail("date", path, "Expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail("date", path, "Invalid calendar date")


def _time(value, path):
    if type(value) is not str or not _TIME.fullmatch(value):
        _fail("timestamp", path, "Expected RFC3339 timestamp with seconds and timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _fail("timestamp", path, "Invalid timestamp")


def _period(value, path):
    _obj(value, path, ("start", "end"))
    start = _date(value["start"], path + ".start")
    end = _date(value["end"], path + ".end")
    if end < start:
        _fail("period", path, "Period end precedes its start")
    return start, end


def _unit(value, path):
    if type(value) is not str:
        _fail("unit", path, "Expected a supported explicit unit")
    for pattern, kind in ((_QUANTITY, "quantity"), (_MONEY, "money"),
                          (_UNIT_PRICE, "unit_price"), (_SHARE_PRICE, "share_price")):
        match = pattern.fullmatch(value)
        if match:
            return (kind,) + match.groups()
    if value in ("fraction", "multiple", "shares"):
        return (value,)
    _fail("unit", path, "Unsupported unit; fractions must use fraction, never percent")


def _out(value):
    if not value.is_finite():
        _fail("arithmetic", "$", "Nonfinite result")
    if not value:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _period_out(value):
    return {"start": value[0].isoformat(), "end": value[1].isoformat()}


def _same_period(observations, path):
    period = observations[0]["period"]
    if any(o["period"] != period for o in observations[1:]):
        _fail("period_mismatch", path, "Referenced observations must have exactly the same period")
    return period


def _positive(value, path, allow_zero=False):
    if value < 0 or (not allow_zero and value == 0):
        _fail("range", path, "Expected a nonnegative value" if allow_zero else "Expected a positive value")


def _annual(period, basis, path):
    if basis not in ("calendar_year", "fiscal_52_53_week"):
        _fail("annual_basis", path, "An annual metric requires declared calendar_year or fiscal_52_53_week basis")
    start, end = period
    if basis == "fiscal_52_53_week":
        if (end - start).days + 1 not in (364, 371):
            _fail("annual_period", path, "A declared 52/53-week fiscal year must contain exactly 364 or 371 inclusive days")
        return
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:
        if start.month == 2 and start.day == 29:
            anniversary = date(start.year + 1, 3, 1)
        else:
            _fail("annual_period", path, "Metric period is outside the supported calendar range")
    if end != anniversary - timedelta(days=1):
        _fail("annual_period", path, "EV/EBITDA requires an explicit full calendar-year metric period")


def _ratio(numerator, denominator, reason="nonpositive_denominator"):
    if denominator <= 0:
        return {"value": None, "status": "NM", "reason": reason}
    return {"value": _out(numerator / denominator), "status": "defined", "reason": None}


class _Calculator:
    def __init__(self, packet):
        _obj(packet, "$", ("version", "subject", "as_of", "observations", "calculations"))
        if packet["version"] != VERSION:
            _fail("version", "$.version", "Unsupported packet version")
        self.subject = _text(packet["subject"], "$.subject", 128)
        self.as_of = _time(packet["as_of"], "$.as_of")
        raw = packet["observations"]
        if type(raw) is not dict or not 1 <= len(raw) <= 2000:
            _fail("type", "$.observations", "Expected 1..2000 observations keyed by ID")
        self.obs = {}
        for oid, observation in raw.items():
            _identifier(oid, "$.observations")
            path = "$.observations." + oid
            _obj(observation, path, (
                "value", "unit", "period", "available_at", "source_ref", "definition", "origin",
            ), ("market_scope", "measurement_basis"))
            period = _period(observation["period"], path + ".period")
            available = _time(observation["available_at"], path + ".available_at")
            if available > self.as_of:
                _fail("future_availability", path + ".available_at", "Input was not available at as_of")
            if observation["origin"] not in ("reported", "assumption"):
                _fail("origin", path + ".origin", "Expected reported or assumption; source_ref is not verification")
            if observation["origin"] == "reported" and period[1] > available.date():
                _fail("future_reported_period", path + ".period", "A future-period value must be labeled assumption")
            self.obs[oid] = {
                "value": _number(observation["value"], path + ".value"),
                "unit": _unit(observation["unit"], path + ".unit"),
                "period": period,
                "definition": _text(observation["definition"], path + ".definition"),
                "source_ref": _text(observation["source_ref"], path + ".source_ref"),
                "origin": observation["origin"],
            }
            for field in ("market_scope", "measurement_basis"):
                if field in observation:
                    self.obs[oid][field] = _text(observation[field], path + "." + field)
        self.calculations = {}
        for i, calculation in enumerate(_list(packet["calculations"], "$.calculations", 1, 500)):
            path = f"$.calculations[{i}]"
            if type(calculation) is not dict or "id" not in calculation or "kind" not in calculation:
                _fail("type", path, "Calculation requires id and kind")
            cid = _identifier(calculation["id"], path + ".id")
            if cid in self.calculations:
                _fail("duplicate_id", path + ".id", "Calculation IDs must be unique")
            if calculation["kind"] not in ("supply_demand", "state_bridge", "valuation", "reverse_ebitda"):
                _fail("kind", path + ".kind", "Unsupported calculation kind")
            self.calculations[cid] = calculation
        self.results = {}

    def ref(self, value, path, unit=None):
        oid = _identifier(value, path)
        if oid not in self.obs:
            _fail("unknown_reference", path, "Unknown observation ID: " + oid)
        observation = self.obs[oid]
        if unit is not None and observation["unit"] != unit:
            _fail("unit_mismatch", path, "Observation has an incompatible unit")
        return observation

    def provenance(self, refs):
        refs = sorted(set(refs))
        return {"observation_refs": refs, "assumption_refs": [
            r for r in refs if self.obs[r]["origin"] == "assumption"
        ]}

    def supply_demand(self, calculation, path):
        fields = ("supply_start", "supply_end", "demand_start", "demand_end")
        _obj(calculation, path, ("id", "kind") + fields)
        observations = [self.ref(calculation[k], path + "." + k) for k in fields]
        ss, se, ds, de = observations
        unit = ss["unit"]
        if unit[0] != "quantity" or any(o["unit"] != unit for o in observations):
            _fail("unit_mismatch", path, "All supply/demand values must use the same physical quantity unit")
        for metadata in ("market_scope", "measurement_basis"):
            if any(metadata not in o for o in observations):
                _fail("missing_field", path, "Every supply/demand observation requires " + metadata)
            if any(o[metadata] != ss[metadata] for o in observations[1:]):
                _fail("comparability_mismatch", path, "Supply/demand observations must declare exactly matching " + metadata)
        start = _same_period([ss, ds], path)
        end = _same_period([se, de], path)
        if start[0] != start[1] or end[0] != end[1] or end[0] <= start[0]:
            _fail("period_mismatch", path, "Supply/demand comparisons need matched, strictly increasing point-in-time dates")
        if ss["definition"] != se["definition"] or ds["definition"] != de["definition"]:
            _fail("definition_mismatch", path, "Each start/end series must use exactly the same measurement definition")
        for field, observation in zip(fields, observations):
            _positive(observation["value"], path + "." + field, allow_zero=(field == "demand_end"))
        supply_growth = se["value"] / ss["value"] - 1
        demand_growth = de["value"] / ds["value"] - 1
        ratio_start = ds["value"] / ss["value"]
        ratio_end = de["value"] / se["value"]
        return {
            "kind": "supply_demand", "quantity_unit": "quantity:" + unit[1],
            "market_scope": ss["market_scope"], "measurement_basis": ss["measurement_basis"],
            "start_period": _period_out(start), "end_period": _period_out(end),
            "supply_growth_fraction": _out(supply_growth),
            "demand_growth_fraction": _out(demand_growth),
            "demand_minus_supply_growth_percentage_points": _out((demand_growth - supply_growth) * 100),
            "demand_to_supply_start_ratio": _out(ratio_start),
            "demand_to_supply_end_ratio": _out(ratio_end),
            "relative_end_utilization_index_start_1": _out(ratio_end / ratio_start),
            "interpretation": "Comparable-quantity arithmetic only; matching scope/basis text is not semantic verification and ratios are not independently verified plant utilization.",
            **self.provenance([calculation[k] for k in fields]),
        }

    def state_bridge(self, calculation, path):
        _obj(calculation, path, ("id", "kind", "state", "financing_excluded", "segments", "approximation_notes"),
             ("reported_totals", "annual_basis"))
        if calculation["state"] not in ("peak", "normalized", "adverse"):
            _fail("state", path + ".state", "Expected a supplied peak, normalized or adverse state")
        if calculation["financing_excluded"] is not True:
            _fail("financing_scope", path + ".financing_excluded", "FCFF inputs must explicitly exclude interest and financing flows")
        notes = [_text(n, path + ".approximation_notes") for n in
                 _list(calculation["approximation_notes"], path + ".approximation_notes", 1, 50)]
        segments, all_obs, refs = {}, [], []
        totals = dict.fromkeys(_CASH_METRICS, Decimal(0))
        currency = None
        for segment in _list(calculation["segments"], path + ".segments", 1, 100):
            _obj(segment, path + ".segments", ("id",) + _SEGMENT_FIELDS)
            sid = _identifier(segment["id"], path + ".segments.id")
            spath = path + ".segments." + sid
            if sid in segments:
                _fail("duplicate_id", spath, "Segment IDs must be unique within a state")
            obs = {k: self.ref(segment[k], spath + "." + k) for k in _SEGMENT_FIELDS}
            q = obs["volume"]["unit"]
            asp_unit = obs["asp"]["unit"]
            if q[0] != "quantity" or asp_unit[0] != "unit_price" or asp_unit[2] != q[1]:
                _fail("unit_mismatch", spath, "Volume and ASP must use the same explicit physical quantity")
            ccy = asp_unit[1]
            if currency is not None and currency != ccy:
                _fail("unit_mismatch", spath, "Segment totals cannot mix currencies")
            currency = ccy
            if obs["variable_cost_per_unit"]["unit"] != asp_unit:
                _fail("unit_mismatch", spath + ".variable_cost_per_unit", "Variable cost and ASP units must match")
            for k in ("cash_fixed_cost", "da", "cash_capex", "change_nwc"):
                if obs[k]["unit"] != ("money", ccy):
                    _fail("unit_mismatch", spath + "." + k, "Expected the segment currency")
            if obs["tax_rate"]["unit"] != ("fraction",):
                _fail("unit_mismatch", spath + ".tax_rate", "Tax rate must be a fraction, not a percent")
            for k in _SEGMENT_FIELDS:
                if k not in ("change_nwc",):
                    _positive(obs[k]["value"], spath + "." + k, allow_zero=True)
            if obs["tax_rate"]["value"] > 1:
                _fail("range", spath + ".tax_rate", "Tax fraction must lie in [0,1]; 25 means 2500%, not 25%")
            period = _same_period(list(obs.values()), spath)
            if period[0] == period[1]:
                _fail("period", spath, "Operating cash flows require a flow period, not a snapshot")
            values = {k: o["value"] for k, o in obs.items()}
            result = {
                "revenue": values["volume"] * values["asp"],
                "variable_cash_cost": values["volume"] * values["variable_cost_per_unit"],
                "cash_fixed_cost": values["cash_fixed_cost"], "da": values["da"],
                "cash_capex": values["cash_capex"], "change_nwc": values["change_nwc"],
            }
            result["ebitda"] = result["revenue"] - result["variable_cash_cost"] - result["cash_fixed_cost"]
            result["ebit"] = result["ebitda"] - result["da"]
            result["cash_tax"] = max(result["ebit"], Decimal(0)) * values["tax_rate"]
            result["nopat"] = result["ebit"] - result["cash_tax"]
            result["fcff"] = result["nopat"] + result["da"] - result["cash_capex"] - result["change_nwc"]
            for k in _CASH_METRICS:
                totals[k] += result[k]
            segments[sid] = {k: _out(result[k]) for k in _CASH_METRICS}
            all_obs.extend(obs.values())
            refs.extend(segment[k] for k in _SEGMENT_FIELDS)
        period = _same_period(all_obs, path)
        annual_basis = calculation.get("annual_basis")
        if "annual_basis" in calculation:
            _annual(period, annual_basis, path + ".annual_basis")
        controls = calculation.get("reported_totals", {})
        _obj(controls, path + ".reported_totals", (), _CASH_METRICS)
        reconciliation = {}
        for metric, ref in controls.items():
            rpath = path + ".reported_totals." + metric
            observation = self.ref(ref, rpath, ("money", currency))
            _same_period([all_obs[0], observation], rpath)
            if observation["origin"] != "reported":
                _fail("origin", rpath, "A reported-total control must have reported origin")
            difference = totals[metric] - observation["value"]
            if difference:
                _fail("reconciliation", rpath, "Computed segment total differs from supplied reported total (exact check)")
            refs.append(ref)
            reconciliation[metric] = {"computed": _out(totals[metric]), "reported": _out(observation["value"]), "difference": "0"}
        return {
            "kind": "state_bridge", "state": calculation["state"],
            "period": _period_out(period), "currency_unit": "currency:" + currency,
            "annual_basis": annual_basis,
            "cash_flow_measure": "FCFF", "financing_excluded": True,
            "segments": segments, "totals": {k: _out(totals[k]) for k in _CASH_METRICS},
            "ebitda_margin_fraction": _ratio(totals["ebitda"], totals["revenue"], "zero_revenue"),
            "reported_total_reconciliation": reconciliation,
            "reconciliation_scope": "segment_sums_and_supplied_controls" if controls else "segment_sums_only_no_reported_controls",
            "is_approximation": True, "approximation_notes": notes,
            "tax_method": "max(segment_EBIT,0)*segment_tax_fraction; no loss tax benefit or cross-segment tax offset",
            "scope": "Simplified unlevered operating bridge, not FCFE, an integrated three-statement model or verified cash taxes.",
            **self.provenance(refs),
        }

    def bridge(self, calculation, path):
        observations = {k: self.ref(calculation[k], path + "." + k) for k in _BRIDGE_FIELDS}
        price = observations["price"]
        unit = price["unit"]
        if unit[0] != "share_price":
            _fail("unit_mismatch", path + ".price", "Expected currency:CCY/share")
        currency = unit[1]
        for k in ("current_shares", "valuation_shares"):
            if observations[k]["unit"] != ("shares",):
                _fail("unit_mismatch", path + "." + k, "Expected shares")
            _positive(observations[k]["value"], path + "." + k)
        if observations["net_debt"]["unit"] != ("money", currency):
            _fail("unit_mismatch", path + ".net_debt", "Net debt must use the price currency")
        _positive(price["value"], path + ".price", allow_zero=True)
        period = _same_period(list(observations.values()), path)
        if period[0] != period[1]:
            _fail("period", path, "Price/share/net-debt equity bridge requires a matched snapshot date")
        if period[1] > self.as_of.date():
            _fail("future_snapshot", path, "Current equity bridge snapshot cannot follow as_of")
        note = _text(calculation["share_count_assumption"], path + ".share_count_assumption")
        p, current, assumed, net_debt = (observations[k]["value"] for k in _BRIDGE_FIELDS)
        market_cap = p * current
        return {
            "currency_unit": "currency:" + currency, "snapshot_period": _period_out(period),
            "price_per_share": _out(p), "current_shares": _out(current), "valuation_shares": _out(assumed),
            "share_change": _out(assumed - current),
            "dilution_or_buyback_fraction": _out(assumed / current - 1),
            "share_count_assumption": note,
            "current_market_equity_value": _out(market_cap),
            "net_debt": _out(net_debt),
            "current_market_enterprise_value": _out(market_cap + net_debt),
            "unchanged_equity_value_per_valuation_share": _out(market_cap / assumed),
            "financing_convention": "EV=equity+net_debt; signed net cash allowed; no interest deducted from EBITDA or FCFF. Net debt must already include declared EV adjustments and any modeled share-issuance/buyback cash effects.",
            "share_sensitivity_scope": "Unchanged aggregate equity value for dilution sensitivity; no automatic issuance proceeds or buyback cost.",
        }

    def state_ref(self, ref, path, currency):
        cid = _identifier(ref, path)
        if cid not in self.results or self.results[cid]["kind"] != "state_bridge":
            _fail("unknown_reference", path, "Expected a state_bridge calculation ID")
        result = self.results[cid]
        if result["currency_unit"] != currency:
            _fail("unit_mismatch", path, "State and equity bridge currencies differ")
        _annual(_period(result["period"], path + ".period"), result["annual_basis"], path)
        return result

    def valuation(self, calculation, path):
        _obj(calculation, path, ("id", "kind", "states", "share_count_assumption") + _BRIDGE_FIELDS)
        bridge = self.bridge(calculation, path)
        refs = [calculation[k] for k in _BRIDGE_FIELDS]
        states, labels = {}, set()
        for ref in _list(calculation["states"], path + ".states", 1, 3):
            state = self.state_ref(ref, path + ".states", bridge["currency_unit"])
            if ref in states or state["state"] in labels:
                _fail("duplicate_id", path + ".states", "Use at most one calculation per supplied economic state")
            labels.add(state["state"])
            ebitda = Decimal(state["totals"]["ebitda"])
            ev = Decimal(bridge["current_market_enterprise_value"])
            multiple = _ratio(ev, ebitda, "nonpositive_ebitda")
            if ev <= 0 and ebitda > 0:
                multiple = {"value": None, "status": "NM", "reason": "nonpositive_enterprise_value"}
            states[ref] = {
                "state": state["state"], "metric_period": state["period"],
                "annual_basis": state["annual_basis"],
                "ebitda": state["totals"]["ebitda"], "fcff": state["totals"]["fcff"],
                "ev_to_ebitda": multiple,
            }
            refs.extend(state["observation_refs"])
        return {"kind": "valuation", "equity_bridge": bridge, "states": states,
                "interpretation": "Current snapshot EV divided by each explicitly dated annual supplied state; no cycle label, threshold or valuation forecast.",
                **self.provenance(refs)}

    def reverse_ebitda(self, calculation, path):
        _obj(calculation, path, ("id", "kind", "normalized_state", "target_ev_ebitda", "share_count_assumption") + _BRIDGE_FIELDS)
        bridge = self.bridge(calculation, path)
        state = self.state_ref(calculation["normalized_state"], path + ".normalized_state", bridge["currency_unit"])
        if state["state"] != "normalized":
            _fail("state", path + ".normalized_state", "Required state must be labeled normalized")
        target = self.ref(calculation["target_ev_ebitda"], path + ".target_ev_ebitda", ("multiple",))
        if target["period"] != _period(state["period"], path + ".normalized_state.period"):
            _fail("period_mismatch", path + ".target_ev_ebitda", "Target multiple must name the normalized state's annual period")
        _positive(target["value"], path + ".target_ev_ebitda")
        target_equity = Decimal(bridge["price_per_share"]) * Decimal(bridge["valuation_shares"])
        target_ev = target_equity + Decimal(bridge["net_debt"])
        _positive(target_ev, path + ".target_enterprise_value")
        required = target_ev / target["value"]
        revenue = Decimal(state["totals"]["revenue"])
        baseline_ebitda = Decimal(state["totals"]["ebitda"])
        refs = [calculation[k] for k in _BRIDGE_FIELDS] + [calculation["target_ev_ebitda"]] + state["observation_refs"]
        return {
            "kind": "reverse_ebitda", "normalized_state": calculation["normalized_state"],
            "metric_period": state["period"], "equity_bridge": bridge,
            "annual_basis": state["annual_basis"],
            "target_ev_ebitda": _out(target["value"]),
            "target_equity_value_at_valuation_shares": _out(target_equity),
            "target_enterprise_value_at_valuation_shares": _out(target_ev),
            "required_normalized_ebitda": _out(required),
            "normalized_revenue_assumption": _out(revenue),
            "required_ebitda_margin_fraction": _ratio(required, revenue, "zero_revenue"),
            "baseline_normalized_ebitda": _out(baseline_ebitda),
            "required_minus_baseline_ebitda": _out(required - baseline_ebitda),
            "interpretation": "Conditional equation, not consensus or a forecast: required_EBITDA=(specified_price*valuation_shares+signed_net_debt)/specified_multiple. Revenue and share/EV adjustments are supplied assumptions; no probability or feasibility inferred.",
            **self.provenance(refs),
        }

    def run(self):
        # Only valuations depend on state calculations, so arbitrary packet order
        # is supported without a general expression language or hidden constants.
        for kinds in (("supply_demand", "state_bridge"), ("valuation", "reverse_ebitda")):
            for cid, calculation in self.calculations.items():
                if calculation["kind"] in kinds:
                    self.results[cid] = getattr(self, calculation["kind"])(calculation, "$.calculations." + cid)
        used = {r for result in self.results.values() for r in result["observation_refs"]}
        return {
            "version": VERSION, "status": "ok", "subject": self.subject,
            "as_of": self.as_of.isoformat().replace("+00:00", "Z"),
            "provenance_scope": "Supplied provenance is retained by reference, not externally authenticated; arithmetic checks are not evidence verification.",
            "results": self.results, "unused_observation_refs": sorted(set(self.obs) - used),
        }


def canonical_json(value):
    """Canonical JSON for hashing/recomputation; financial values stay strings."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def calculate(packet):
    """Validate all inputs, then return deterministic arithmetic or raise CycleCheckError.

    Decimal precision is fixed locally and independent of callers' Decimal context.
    The caller remains responsible for the truth and sufficiency of observations.
    """
    try:
        with localcontext(_CONTEXT):
            result = _Calculator(packet).run()
            result["input_sha256"] = hashlib.sha256(canonical_json(packet).encode("utf-8")).hexdigest()
            return result
    except CycleCheckError:
        raise
    except DecimalException:
        _fail("arithmetic", "$", "Decimal arithmetic failed")
    except (RecursionError, TypeError, ValueError, OverflowError):
        _fail("input", "$", "Malformed or unsupported input")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key", "$", "JSON object contains a duplicate key")
        result[key] = value
    return result


def decode_packet(content):
    """Strict-decode already-read UTF-8 JSON bytes; does not re-open a path."""
    try:
        if type(content) is not bytes:
            _fail("input_file", "$", "Expected UTF-8 JSON bytes")
        if len(content) > 2_000_000:
            _fail("input_size", "$", "Input packet exceeds 2 MB")
        return json.loads(content.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda _: _fail("decimal", "$", "Nonfinite JSON constant"))
    except CycleCheckError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _fail("input_file", "$", "Cannot read valid UTF-8 JSON input")


def load_packet(path):
    """Read a bounded UTF-8 JSON packet, using the same strict byte decoder."""
    try:
        with Path(path).open("rb") as stream:
            content = stream.read(2_000_001)
    except OSError:
        _fail("input_file", "$", "Cannot read valid UTF-8 JSON input")
    return decode_packet(content)


def _atomic_output(path, result):
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix="." + destination.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    except (OSError, ValueError):
        _fail("output_file", "$", "Cannot atomically write output file")
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        try:
            same_path = args.input.resolve() == args.output.resolve()
        except OSError:
            _fail("input_file", "$", "Cannot resolve input/output path")
        if same_path:
            _fail("output_file", "$", "Input and output paths must differ")
        result = calculate(load_packet(args.input))
        _atomic_output(args.output, result)
    except CycleCheckError as error:
        print(canonical_json(error.as_dict()), file=sys.stderr)
        return 2
    print(canonical_json({"version": VERSION, "status": "ok", "subject": result["subject"],
                          "calculation_ids": sorted(result["results"]), "input_sha256": result["input_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
