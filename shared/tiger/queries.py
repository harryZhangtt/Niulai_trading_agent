"""Bounded data reads, independent of credential-store and report orchestration."""
from datetime import datetime, timezone

TOOLS = ("positions", "assets", "snapshot")
SECURITY_TYPES = ("STK", "OPT", "FUT", "FUND")
DEFAULT_TYPES = ("STK", "OPT", "FUT")


def validate_query(query, require):
    require(isinstance(query, dict) and set(query) == {"tool", "arguments"}, "TIGER_QUERY_INVALID")
    require(query["tool"] in TOOLS, "TIGER_TOOL_NOT_ALLOWED")
    args = query["arguments"]
    require(isinstance(args, dict), "TIGER_ARGUMENTS_INVALID")
    allowed = {"security_types"} if query["tool"] != "assets" else set()
    require(set(args) <= allowed, "TIGER_ARGUMENTS_INVALID")
    types = args.get("security_types", list(DEFAULT_TYPES))
    require(isinstance(types, list) and 1 <= len(types) <= 4
            and all(isinstance(t, str) and t in SECURITY_TYPES for t in types)
            and len(set(types)) == len(types), "TIGER_SECURITY_TYPES_INVALID")
    return {"tool": query["tool"], "arguments": {"security_types": types} if allowed else {}}


def execute_query(n, profile, query, require, write_json, out):
    """Called only while the lease, profile lock and rotation callback are held."""
    started = datetime.now(timezone.utc).isoformat()
    with n.profile_lock(profile):
        # Existing transferred grant includes quote consent. Preserve its exact
        # scope validation; this interface neither requests consent nor uses quotes.
        Session, make = n.sdk_classes(include_quotes=True)
        sdk = Session(issuer=n.ISSUER, home=str(profile), surface=n.SURFACE, client_name=n.CLIENT_NAME)
        n.validate_token(sdk.status(), require_quotes=True)
        broker = make(sdk)
        accounts = broker.get_managed_accounts()
        require(isinstance(accounts, list), "TIGER_ACCOUNTS_INVALID")
        standard = [a for a in accounts if getattr(a, "account_type", None) == "STANDARD"]
        require(len(standard) == 1, "STANDARD_ACCOUNT_AMBIGUOUS")
        refs = n.account_refs(profile, accounts)
        account = standard[0]
        pin = {"account": account.account, "ref": refs[account.account]}
        data = {}
        if query["tool"] in ("positions", "snapshot"):
            data["holdings"] = n.fetch_account(broker, pin, tuple(query["arguments"]["security_types"]))
        if query["tool"] in ("assets", "snapshot"):
            data["assets"] = n.fetch_assets_account(broker, pin)
        # Preserve partial evidence privately, but never call it a successful read.
        for name, payload in data.items():
            write_json(out / (name + ".json"), payload)
        require(all(p.get("ok") is True and p.get("sourceReadStatus") == "complete"
                    for p in data.values()), "TIGER_READ_INCOMPLETE")
        envelope = {"schema_version": 1, "provider": "tiger", "tool": query["tool"],
                    "query_started_at": started, "query_completed_at": datetime.now(timezone.utc).isoformat(),
                    "source_read_status": "complete", "cached_fallback_used": False,
                    "request": query, "data": data}
        # Original response timestamps, unknown quote times, scope evidence,
        # coverage limits and decimal strings stay in the normalized payloads.
        write_json(out / "query.json", envelope)
        result = {"status": "queried", "tool": query["tool"], "source_read_status": "complete",
                  "holdings_read": "holdings" in data, "assets_read": "assets" in data,
                  "files": [name + ".json" for name in data] + ["query.json"]}
        if "holdings" in data:
            result["holdings_count"] = len(data["holdings"]["positions"])
        return result
