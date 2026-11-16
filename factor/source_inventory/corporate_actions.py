"""Value-free corporate-action normalization and synthetic total-return receipts."""
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import json
import re

from . import contract, handoff

SHA = re.compile(r"[a-f0-9]{64}\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIME = handoff.TIME
MAX_RECORDS = 128
RESPONSE_FIELDS = {"schema_version", "kind", "trust_class", "role",
                   "route_policy_sha256", "acquisition_receipt_sha256", "records"}
ACTION_FIELDS = {
    "record_id", "action_type", "event_unique_id", "event_action", "listing_id",
    "security_id", "mapping_version", "ts_created", "ts_record", "recorded_at",
    "effective_start", "effective_end", "ex_date", "record_date", "pay_date",
    "effective_date", "amount_present", "amount_commitment_sha256",
    "split_ratio_present", "split_ratio_commitment_sha256", "source_row_sha256",
}
NORMALIZED_FIELDS = ACTION_FIELDS - {"record_id", "amount_present", "split_ratio_present"} | {
    "semantic_action_id", "vintage_id", "supersedes_vintage_id", "available_at",
    "values_included",
}
RECEIPT_FIELDS = {"schema_version", "kind", "trust_class", "role",
                  "route_policy_sha256", "acquisition_receipt_sha256",
                  "response_sha256", "normalization_policy", "normalized_actions",
                  "values_included"}
REQUEST_FIELDS = {"schema_version", "kind", "trust_class", "role", "listing_id",
                  "security_id", "mapping_version", "as_of_cutoff",
                  "corporate_action_receipt_sha256", "action_commitments_sha256",
                  "unadjusted_close_commitment_sha256", "adjusted_input_allowed",
                  "reinvestment_convention", "formula_version", "values_included"}
TOTAL_RECEIPT_FIELDS = {"schema_version", "kind", "request_sha256",
                        "corporate_action_receipt_sha256",
                        "unadjusted_close_commitment_sha256",
                        "action_values_commitment_sha256", "output_commitment_sha256",
                        "output_rows", "formula_version", "values_included",
                        "performance_claim"}


class CorporateActionError(ValueError):
    pass


def require(condition, code):
    if not condition: raise CorporateActionError(code)


def canonical(value): return contract.canonical(value)
def digest(value): return contract.digest(value)

def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code); return value

def _sha(value, code="CORPORATE_ACTION_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code); return value

def _id(value, code="CORPORATE_ACTION_ID_INVALID"):
    return contract._id(value, code)

def _time(value):
    require(type(value) is str and TIME.fullmatch(value), "CORPORATE_ACTION_TIME_INVALID")
    try: return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError: raise CorporateActionError("CORPORATE_ACTION_TIME_INVALID") from None

def _date(value):
    require(type(value) is str and DATE.fullmatch(value), "CORPORATE_ACTION_DATE_INVALID")
    try: date.fromisoformat(value)
    except ValueError: raise CorporateActionError("CORPORATE_ACTION_DATE_INVALID") from None
    return value


def _version_semantic(row):
    return {key: row[key] for key in sorted(set(row) - {"record_id"})}


def _action_rank(action):
    return {"new": 0, "correct": 1, "cancel": 2}[action]


def _normalized_order(row):
    return (_time(row["available_at"]), _time(row["ts_record"]),
            _time(row["ts_created"]), _action_rank(row["event_action"]))


def validate_response(value):
    _strict(value, RESPONSE_FIELDS, "CORPORATE_ACTION_RESPONSE_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "synthetic_corporate_action_response" and
            value["trust_class"] == "synthetic_fixture" and
            value["role"] in {"spy_market", "oneq_market"} and
            value["route_policy_sha256"] == handoff._route_policy(value["role"], "databento") and
            type(value["records"]) is list and 1 <= len(value["records"]) <= MAX_RECORDS,
            "CORPORATE_ACTION_RESPONSE_INVALID")
    _sha(value["acquisition_receipt_sha256"])
    ids=set(); event_identity={}; versions=set(); groups={}; event_versions={}
    for row in value["records"]:
        _strict(row, ACTION_FIELDS, "CORPORATE_ACTION_ROW_SCHEMA")
        rid=_id(row["record_id"]); require(rid not in ids,"CORPORATE_ACTION_DUPLICATE")
        ids.add(rid); action=row["action_type"]
        require(action in {"DIV","SPLIT"} and row["event_action"] in {"new","correct","cancel"},
                "CORPORATE_ACTION_TYPE_INVALID")
        event=_id(row["event_unique_id"]); listing=_id(row["listing_id"])
        security=_id(row["security_id"]); mapping=_id(row["mapping_version"])
        require(event_identity.setdefault(event,(listing,security,mapping)) == (listing,security,mapping),
                "CORPORATE_ACTION_TICKER_SPLICE")
        versions.add(mapping); require(len(versions)==1,"CORPORATE_ACTION_MAPPING_DRIFT")
        for key in ("ts_created","ts_record","recorded_at","effective_start"):
            _time(row[key])
        if row["effective_end"] is not None: _time(row["effective_end"])
        require(_time(row["ts_created"]) <= _time(row["ts_record"]) <= _time(row["recorded_at"]),
                "CORPORATE_ACTION_RECORD_TIME")
        for key in ("ex_date","effective_date"): _date(row[key])
        for key in ("record_date","pay_date"):
            if row[key] is not None: _date(row[key])
        require(row["amount_present"] is False and row["split_ratio_present"] is False,
                "CORPORATE_ACTION_VALUE_FORBIDDEN")
        if action == "DIV":
            _sha(row["amount_commitment_sha256"])
            require(row["split_ratio_commitment_sha256"] is None,
                    "CORPORATE_ACTION_COMMITMENT_INVALID")
        else:
            _sha(row["split_ratio_commitment_sha256"])
            require(row["amount_commitment_sha256"] is None,
                    "CORPORATE_ACTION_COMMITMENT_INVALID")
        _sha(row["source_row_sha256"])
        version_key=(event,row["ts_record"]); semantic=_version_semantic(row)
        if version_key in event_versions:
            require(event_versions[version_key]==semantic,
                    "CORPORATE_ACTION_VERSION_AMBIGUOUS")
        else:
            event_versions[version_key]=semantic; groups.setdefault(event,[]).append(row)
    for rows in groups.values():
        ordered=sorted(rows,key=lambda item:_time(item["ts_record"]))
        require(ordered[0]["event_action"]=="new" and
                all(item["event_action"] in {"correct","cancel"} for item in ordered[1:]) and
                all(item["event_action"]!="cancel" for item in ordered[:-1]),
                "CORPORATE_ACTION_LIFECYCLE")
    contract._scan(value); return value


def normalize_response(value):
    value=validate_response(value); output=[]; prior={}; seen_versions=set()
    for row in sorted(value["records"],key=lambda item:
                      (_time(max((item["ts_record"],item["recorded_at"]),key=_time)),
                       _time(item["ts_record"]),_time(item["ts_created"]),
                       _action_rank(item["event_action"]),canonical(_version_semantic(item)))):
        version_key=(row["event_unique_id"],row["ts_record"])
        if version_key in seen_versions: continue
        seen_versions.add(version_key)
        event=row["event_unique_id"]
        available=max((row["ts_record"],row["recorded_at"]),key=_time)
        vintage=digest({"event_unique_id":event,"ts_record":row["ts_record"],
                        "source_row_sha256":row["source_row_sha256"]})
        normalized={key:row[key] for key in ACTION_FIELDS-
                    {"record_id","amount_present","split_ratio_present"}}
        normalized.update({"semantic_action_id":digest({"listing_id":row["listing_id"],
            "security_id":row["security_id"],"event_unique_id":event,
            "action_type":row["action_type"]}),"vintage_id":vintage,
            "supersedes_vintage_id":prior.get(event),"available_at":available,
            "values_included":False})
        prior[event]=vintage; output.append(normalized)
    receipt={"schema_version":1,"kind":"synthetic_corporate_action_receipt",
             "trust_class":"synthetic_fixture","role":value["role"],
             "route_policy_sha256":value["route_policy_sha256"],
             "acquisition_receipt_sha256":value["acquisition_receipt_sha256"],
             "response_sha256":digest(value),
             "normalization_policy":"databento-corporate-actions-ts-record-v1",
             "normalized_actions":output,"values_included":False}
    return validate_receipt(receipt)


def validate_receipt(value):
    _strict(value,RECEIPT_FIELDS,"CORPORATE_ACTION_RECEIPT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and
            value["kind"]=="synthetic_corporate_action_receipt" and
            value["trust_class"]=="synthetic_fixture" and
            value["role"] in {"spy_market","oneq_market"} and
            value["normalization_policy"]=="databento-corporate-actions-ts-record-v1" and
            value["values_included"] is False and type(value["normalized_actions"]) is list and
            value["normalized_actions"],"CORPORATE_ACTION_RECEIPT_INVALID")
    for key in ("route_policy_sha256","acquisition_receipt_sha256","response_sha256"):_sha(value[key])
    identities={}; versions=set(); events=set()
    for row in value["normalized_actions"]:
        _strict(row,NORMALIZED_FIELDS,"CORPORATE_ACTION_NORMALIZED_SCHEMA")
        for key in ("semantic_action_id","vintage_id","source_row_sha256"):_sha(row[key])
        require(row["supersedes_vintage_id"] is None or SHA.fullmatch(row["supersedes_vintage_id"]),
                "CORPORATE_ACTION_SUPERSESSION")
        require(row["values_included"] is False and row["action_type"] in {"DIV","SPLIT"} and
                row["event_action"] in {"new","correct","cancel"},
                "CORPORATE_ACTION_NORMALIZED_INVALID")
        event=_id(row["event_unique_id"]); listing=_id(row["listing_id"])
        security=_id(row["security_id"]); mapping=_id(row["mapping_version"])
        require(identities.setdefault(event,(listing,security,mapping))==(listing,security,mapping) and
                row["vintage_id"] not in events,"CORPORATE_ACTION_NORMALIZED_INVALID")
        events.add(row["vintage_id"]); versions.add(mapping)
        for key in ("ts_created","ts_record","recorded_at","effective_start",
                    "available_at"):_time(row[key])
        if row["effective_end"] is not None:_time(row["effective_end"])
        for key in ("ex_date","effective_date"):_date(row[key])
        for key in ("record_date","pay_date"):
            if row[key] is not None:_date(row[key])
        if row["action_type"]=="DIV":
            _sha(row["amount_commitment_sha256"])
            require(row["split_ratio_commitment_sha256"] is None,
                    "CORPORATE_ACTION_COMMITMENT_INVALID")
        else:
            _sha(row["split_ratio_commitment_sha256"])
            require(row["amount_commitment_sha256"] is None,
                    "CORPORATE_ACTION_COMMITMENT_INVALID")
    require(len(versions)==1,"CORPORATE_ACTION_MAPPING_DRIFT")
    contract._scan(value); return value


def select_actions_as_of(receipt,cutoff):
    receipt=validate_receipt(receipt); limit=_time(cutoff); chosen={}
    for row in receipt["normalized_actions"]:
        if _time(row["available_at"])<=limit:
            current=chosen.get(row["event_unique_id"])
            if current is None or _normalized_order(current)<_normalized_order(row):
                chosen[row["event_unique_id"]]=row
            elif _normalized_order(current)==_normalized_order(row):
                require(current==row,"CORPORATE_ACTION_VERSION_AMBIGUOUS")
    return [row for _,row in sorted(chosen.items()) if row["event_action"]!="cancel"]


def create_total_return_request(role,listing_id,security_id,mapping_version,as_of_cutoff,
                                close_commitment,action_receipt):
    action_receipt=validate_receipt(action_receipt)
    require(action_receipt["role"]==role,"TOTAL_RETURN_ACTION_ROLE_MISMATCH")
    selected=select_actions_as_of(action_receipt,as_of_cutoff)
    require(selected and all(row["listing_id"]==listing_id and
                             row["security_id"]==security_id and
                             row["mapping_version"]==mapping_version for row in selected),
            "TOTAL_RETURN_LISTING_BINDING_MISMATCH")
    commitments={row["event_unique_id"]:{"amount":row["amount_commitment_sha256"],
        "split_ratio":row["split_ratio_commitment_sha256"]} for row in selected}
    request={"schema_version":1,"kind":"synthetic_total_return_request",
             "trust_class":"synthetic_fixture","role":role,"listing_id":_id(listing_id),
             "security_id":_id(security_id),"mapping_version":_id(mapping_version),
             "as_of_cutoff":as_of_cutoff,
             "corporate_action_receipt_sha256":digest(action_receipt),
             "action_commitments_sha256":digest(commitments),
             "unadjusted_close_commitment_sha256":_sha(close_commitment),
             "adjusted_input_allowed":False,
             "reinvestment_convention":"effective-date-next-close-reinvestment-v1",
             "formula_version":"pit-total-return-log-v1","values_included":False}
    return validate_total_return_request(request)


def validate_total_return_request(value):
    _strict(value,REQUEST_FIELDS,"TOTAL_RETURN_REQUEST_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and
            value["kind"]=="synthetic_total_return_request" and
            value["trust_class"]=="synthetic_fixture" and
            value["role"] in {"spy_market","oneq_market"} and
            value["adjusted_input_allowed"] is False and value["values_included"] is False and
            value["reinvestment_convention"]=="effective-date-next-close-reinvestment-v1" and
            value["formula_version"]=="pit-total-return-log-v1",
            "TOTAL_RETURN_REQUEST_INVALID")
    for key in ("listing_id","security_id","mapping_version"):_id(value[key])
    _time(value["as_of_cutoff"])
    for key in ("corporate_action_receipt_sha256","action_commitments_sha256",
                "unadjusted_close_commitment_sha256"):_sha(value[key])
    return value


def _decimal(value):
    require(type(value) is str and re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?",value),
            "TOTAL_RETURN_DECIMAL_INVALID")
    return Decimal(value)


def compute_total_return_receipt(request,action_receipt,close_values,action_values):
    request=validate_total_return_request(request); action_receipt=validate_receipt(action_receipt)
    require(digest(action_receipt)==request["corporate_action_receipt_sha256"],
            "TOTAL_RETURN_ACTION_RECEIPT_MISMATCH")
    require(type(close_values) is list and close_values,"TOTAL_RETURN_CLOSE_INPUT_INVALID")
    require(digest(close_values)==request["unadjusted_close_commitment_sha256"],
            "TOTAL_RETURN_CLOSE_COMMITMENT_MISMATCH")
    selected=select_actions_as_of(action_receipt,request["as_of_cutoff"])
    expected={row["event_unique_id"]:{"amount":row["amount_commitment_sha256"],
        "split_ratio":row["split_ratio_commitment_sha256"]} for row in selected}
    require(digest(expected)==request["action_commitments_sha256"],
            "TOTAL_RETURN_ACTION_COMMITMENT_MISMATCH")
    require(type(action_values) is dict and set(action_values)==set(expected),
            "TOTAL_RETURN_ACTION_VALUES_INVALID")
    with localcontext(Context(prec=34,rounding=ROUND_HALF_EVEN)):
        closes=[]
        for row in close_values:
            _strict(row,{"session_date","unadjusted_close"},"TOTAL_RETURN_CLOSE_ROW_SCHEMA")
            _date(row["session_date"]); closes.append((row["session_date"],_decimal(row["unadjusted_close"])))
        require(closes==sorted(closes) and all(value>0 for _,value in closes),
                "TOTAL_RETURN_CLOSE_INPUT_INVALID")
        close_dates=[session for session,_ in closes]
        shares=Decimal(1); initial=closes[0][1]; outputs=[]
        actions_by_date={}
        commitments={}
        for action in selected:
            ratio=None
            values=action_values[action["event_unique_id"]]
            _strict(values,{"amount","split_ratio"},"TOTAL_RETURN_ACTION_VALUES_INVALID")
            if action["action_type"]=="DIV":
                amount=_decimal(values["amount"]); require(values["split_ratio"] is None,
                    "TOTAL_RETURN_ACTION_VALUES_INVALID")
                commitments[action["event_unique_id"]]={"amount":values["amount"]}
            else:
                amount=None; ratio=_decimal(values["split_ratio"]); require(values["amount"] is None and ratio>0,
                    "TOTAL_RETURN_ACTION_VALUES_INVALID")
                commitments[action["event_unique_id"]]={"split_ratio":values["split_ratio"]}
            expected_commit=(digest({"amount":values["amount"]}) if action["action_type"]=="DIV"
                             else digest({"split_ratio":values["split_ratio"]}))
            actual_commit=(action["amount_commitment_sha256"] if action["action_type"]=="DIV"
                           else action["split_ratio_commitment_sha256"])
            require(expected_commit==actual_commit,"TOTAL_RETURN_ACTION_VALUE_COMMITMENT_MISMATCH")
            application_date=next((session for session in close_dates
                                   if session>=action["effective_date"]),None)
            require(application_date is not None,"TOTAL_RETURN_ACTION_OUTSIDE_CLOSES")
            actions_by_date.setdefault(application_date,[]).append((action,amount,ratio))
        for session,close in closes:
            for action,amount,ratio in actions_by_date.get(session,[]):
                if action["action_type"]=="DIV": shares += amount/close
                else: shares *= ratio
            outputs.append({"session_date":session,"total_return_index":format((shares*close/initial).normalize(),"f")})
    receipt={"schema_version":1,"kind":"synthetic_total_return_receipt",
             "request_sha256":digest(request),
             "corporate_action_receipt_sha256":digest(action_receipt),
             "unadjusted_close_commitment_sha256":digest(close_values),
             "action_values_commitment_sha256":digest(commitments),
             "output_commitment_sha256":digest(outputs),"output_rows":len(outputs),
             "formula_version":"pit-total-return-log-v1","values_included":False,
             "performance_claim":"withheld"}
    return validate_total_return_receipt(receipt)


def validate_total_return_receipt(value):
    _strict(value,TOTAL_RECEIPT_FIELDS,"TOTAL_RETURN_RECEIPT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and
            value["kind"]=="synthetic_total_return_receipt" and
            value["formula_version"]=="pit-total-return-log-v1" and
            value["values_included"] is False and value["performance_claim"]=="withheld" and
            type(value["output_rows"]) is int and value["output_rows"]>0,
            "TOTAL_RETURN_RECEIPT_INVALID")
    for key in TOTAL_RECEIPT_FIELDS-{"schema_version","kind","output_rows","formula_version","values_included","performance_claim"}:_sha(value[key])
    return value
