#!/usr/bin/env python3
"""Offline Niulai catalog and alert mirror. Never fetches prices or sends alerts."""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1
USER_TIMEZONE = "Asia/Shanghai"
SESSION_TIMEZONE = "America/New_York"
ALERT_FIELDS = ("id", "ticker", "direction", "threshold", "enabled", "note", "createdAt", "updatedAt")
INDEX_SYMBOLS = {"SP500", "SPX", "^GSPC", ".SPX", "S&P500", "S&P 500"}


class StateError(ValueError):
    pass


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle, parse_float=decimal.Decimal,
                         parse_constant=lambda value: (_ for _ in ()).throw(StateError("Nonfinite JSON number: " + value)))


def safe_json(value):
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise StateError("Nonfinite decimal")
        return str(value)
    raise TypeError(type(value).__name__)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False, default=safe_json) + "\n"


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(encoded(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def text_field(value, field):
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise StateError(field + " must be a nonempty string")
    return value


def decimal_price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, decimal.Decimal)):
        raise StateError("threshold must be a positive finite decimal")
    try:
        price = decimal.Decimal(str(value))
    except decimal.InvalidOperation as error:
        raise StateError("Invalid threshold") from error
    if not price.is_finite() or price <= 0:
        raise StateError("threshold must be a positive finite decimal")
    text = format(price, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def timestamp(value):
    try:
        instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as error:
        raise StateError("Timestamp must be ISO 8601") from error
    if instant.tzinfo is None:
        raise StateError("Timestamp must include a timezone")
    return instant.astimezone(dt.timezone.utc)


def normalize_alerts(payload, allow_operations=False):
    rows = payload.get("alerts") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise StateError("Expected {alerts: [...]} or an alert array")
    result, seen = [], set()
    for original in rows:
        if not isinstance(original, dict):
            raise StateError("Every alert must be an object")
        unsupported = set(original) - set(ALERT_FIELDS) - {'operation', 'ownerId', 'userId', 'accountId'}
        if unsupported:
            raise StateError('Unsupported alert fields require explicit mapping: ' + ', '.join(sorted(unsupported)))
        identifier = text_field(original.get("id"), "id")
        try:
            collision_key = str(uuid.UUID(identifier))
        except ValueError as error:
            raise StateError("Alert id must be an existing UUID") from error
        if collision_key in seen:
            raise StateError("Duplicate alert id: " + identifier)
        seen.add(collision_key)
        if original.get("operation") == "delete":
            if not allow_operations:
                raise StateError("Deletion is only accepted in an explicit sync plan")
            result.append({"id": identifier, "operation": "delete"})
            continue
        if "operation" in original and original["operation"] not in ("upsert", "update", "create"):
            raise StateError("Unknown operation")
        ticker = text_field(original.get("ticker"), "ticker")
        direction = original.get("direction")
        if direction not in ("above", "below"):
            raise StateError("direction must be above or below")
        enabled = original.get("enabled")
        if not isinstance(enabled, bool):
            raise StateError("enabled must be an explicit boolean")
        if ticker.upper() in INDEX_SYMBOLS and enabled:
            raise StateError("Unsupported index template cannot be enabled; resolve a supported instrument first")
        row = {"id": identifier, "ticker": ticker, "direction": direction,
               "threshold": decimal_price(original.get("threshold")), "enabled": enabled}
        for field in ("note", "createdAt", "updatedAt"):
            if field in original:
                if not isinstance(original[field], str):
                    raise StateError(field + " must be a string")
                if field in ("createdAt", "updatedAt"):
                    timestamp(original[field])
                row[field] = original[field]
        result.append(row)
    return sorted(result, key=lambda item: str(uuid.UUID(item["id"])))


def connect(root, name):
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(root / (name + ".sqlite"), timeout=30)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys=ON")
    database.execute("PRAGMA busy_timeout=30000")
    version = database.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, SCHEMA_VERSION):
        database.close()
        raise StateError("Unsupported database schema version: " + str(version))
    database.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    if name == "alerts":
        database.executescript("""
          CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY,ticker TEXT NOT NULL,direction TEXT NOT NULL CHECK(direction IN ('above','below')),threshold TEXT NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS import_events(fingerprint TEXT PRIMARY KEY,imported_at TEXT NOT NULL,row_count INTEGER NOT NULL);
        """)
    else:
        database.executescript("""
          CREATE TABLE IF NOT EXISTS issuers(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS securities(symbol TEXT PRIMARY KEY,issuer_id TEXT REFERENCES issuers(id),payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS artifacts(library_file_id TEXT PRIMARY KEY,version TEXT,filename TEXT NOT NULL,status TEXT,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS artifact_securities(library_file_id TEXT REFERENCES artifacts(library_file_id) ON DELETE CASCADE,symbol TEXT REFERENCES securities(symbol),PRIMARY KEY(library_file_id,symbol));
          CREATE TABLE IF NOT EXISTS sections(library_file_id TEXT REFERENCES artifacts(library_file_id) ON DELETE CASCADE,section_key TEXT,payload TEXT NOT NULL,PRIMARY KEY(library_file_id,section_key));
          CREATE TABLE IF NOT EXISTS themes(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS research_sections(id TEXT PRIMARY KEY,artifact_id TEXT REFERENCES artifacts(library_file_id),payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS security_artifact_relations(security_symbol TEXT REFERENCES securities(symbol),artifact_id TEXT REFERENCES artifacts(library_file_id),section_id TEXT REFERENCES research_sections(id),relationship TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(security_symbol,artifact_id,section_id,relationship));
          CREATE TABLE IF NOT EXISTS job_runs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,library_file_id TEXT REFERENCES artifacts(library_file_id),payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS model_revisions(id TEXT PRIMARY KEY,symbol TEXT REFERENCES securities(symbol),library_file_id TEXT REFERENCES artifacts(library_file_id),payload TEXT NOT NULL);
        """)
    database.execute("PRAGMA user_version=" + str(SCHEMA_VERSION))
    database.commit()
    return database


def init(root):
    for name in ("research", "alerts"):
        connect(root, name).close()
    return export(root)


def import_alerts(root, payload):
    rows = normalize_alerts(payload)
    digest = fingerprint(rows)
    database = connect(root, "alerts")
    try:
        database.execute("BEGIN IMMEDIATE")
        for row in rows:
            old = database.execute("SELECT payload FROM alerts WHERE id=?", (row["id"],)).fetchone()
            if old:
                previous = json.loads(old[0])
                if previous.get("updatedAt") and row.get("updatedAt"):
                    previous_time, new_time = timestamp(previous["updatedAt"]), timestamp(row["updatedAt"])
                    if new_time < previous_time:
                        raise StateError("Stale alert update for " + row["id"])
                    if new_time == previous_time and row != previous:
                        raise StateError("Alert timestamp collision for " + row["id"])
            database.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ticker=excluded.ticker,direction=excluded.direction,threshold=excluded.threshold,enabled=excluded.enabled,payload=excluded.payload",
                             (row["id"], row["ticker"], row["direction"], row["threshold"], int(row["enabled"]), encoded(row)))
        # This is a snapshot mirror, but absence is NOT authorization to delete.
        database.execute("INSERT OR IGNORE INTO import_events VALUES(?,?,?)", (digest, dt.datetime.now(dt.timezone.utc).isoformat(), len(rows)))
        database.execute("INSERT OR REPLACE INTO metadata VALUES('latest_observed_fingerprint',?)", (digest,))
        database.execute("INSERT OR REPLACE INTO metadata VALUES('latest_observed_ids',?)", (encoded([row["id"] for row in rows]),))
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()
    return export(root)


def normalize_research(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
        raise StateError("Research inventory requires artifacts array")
    result = dict(payload)
    result.setdefault("issuers", [])
    result.setdefault("securities", [])
    for key in ("themes", "research_sections", "security_artifact_relations"):
        result.setdefault(key, [])
    issuer_ids, symbols, files = set(), set(), set()
    for issuer in result["issuers"]:
        identifier = text_field(issuer.get("id"), "issuer.id")
        if identifier in issuer_ids:
            raise StateError("Duplicate issuer id")
        issuer_ids.add(identifier)
    for security in result["securities"]:
        symbol = text_field(security.get("symbol"), "security.symbol")
        if symbol in symbols:
            raise StateError("Duplicate security symbol")
        symbols.add(symbol)
    for artifact in result["artifacts"]:
        identifier = text_field(artifact.get("library_file_id"), "library_file_id")
        if identifier in files:
            raise StateError("Duplicate Library file id")
        files.add(identifier)
        version = artifact.get("version", artifact.get("version_id"))
        if version is not None and (isinstance(version, bool) or not isinstance(version, (str, int)) or not str(version).strip()):
            raise StateError("Artifact version must be an exact string, integer, or unknown/null")
        if isinstance(version, int) and version < 1:
            raise StateError("Numeric artifact version must be positive")
        text_field(artifact.get("filename", artifact.get("name")), "filename/name")
        section_keys = set()
        for position, section in enumerate(artifact.get("sections", [])):
            if not isinstance(section, dict):
                raise StateError("section must be an object")
            key = str(section.get("id", section.get("title", position)))
            if key in section_keys:
                raise StateError("Duplicate section key")
            section_keys.add(key)
    return result


def guard_version(identifier, old_version, old_payload, artifact):
    version = artifact.get("version", artifact.get("version_id"))
    normalized = None if version is None else str(version)
    old = json.loads(old_payload)
    if old_version is not None and normalized is None:
        raise StateError("Known artifact version cannot be replaced by unknown: " + identifier)
    if old_version is not None and normalized is not None:
        if old_version.isdecimal() and normalized.isdecimal() and int(normalized) < int(old_version):
            raise StateError("Stale artifact version: " + identifier)
        if normalized == old_version and encoded(artifact) != old_payload:
            raise StateError("Artifact version collision; same version has different contents: " + identifier)
        if normalized != old_version and not (old_version.isdecimal() and normalized.isdecimal()):
            old_time, new_time = old.get("modified_at"), artifact.get("modified_at")
            if not old_time or not new_time or timestamp(new_time) <= timestamp(old_time):
                raise StateError("Opaque version requires a later authoritative modified_at: " + identifier)
    elif normalized is None and encoded(artifact) != old_payload:
        old_time, new_time = old.get("modified_at"), artifact.get("modified_at")
        if not old_time or not new_time or timestamp(new_time) <= timestamp(old_time):
            raise StateError("Unknown-version update requires a later authoritative modified_at: " + identifier)


def import_research(root, payload):
    payload = normalize_research(payload)
    database = connect(root, "research")
    try:
        database.execute("BEGIN IMMEDIATE")
        for issuer in payload["issuers"]:
            database.execute("INSERT INTO issuers VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (issuer["id"], encoded(issuer)))
        for security in payload["securities"]:
            database.execute("INSERT INTO securities VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET issuer_id=excluded.issuer_id,payload=excluded.payload", (security["symbol"], security.get("issuer_id"), encoded(security)))
        for artifact in payload["artifacts"]:
            identifier = artifact["library_file_id"]
            version = artifact.get("version", artifact.get("version_id"))
            old = database.execute("SELECT version,payload FROM artifacts WHERE library_file_id=?", (identifier,)).fetchone()
            if old:
                guard_version(identifier, old["version"], old["payload"], artifact)
            database.execute("INSERT INTO artifacts VALUES(?,?,?,?,?) ON CONFLICT(library_file_id) DO UPDATE SET version=excluded.version,filename=excluded.filename,status=excluded.status,payload=excluded.payload", (identifier, None if version is None else str(version), artifact.get("filename", artifact.get("name")), artifact.get("status"), encoded(artifact)))
            database.execute("DELETE FROM artifact_securities WHERE library_file_id=?", (identifier,))
            for link in artifact.get("security_symbols", artifact.get("securities", [])):
                symbol = link if isinstance(link, str) else link.get("symbol")
                text_field(symbol, "artifact security symbol")
                database.execute("INSERT INTO artifact_securities VALUES(?,?)", (identifier, symbol))
            database.execute("DELETE FROM sections WHERE library_file_id=?", (identifier,))
            for position, section in enumerate(artifact.get("sections", [])):
                key = str(section.get("id", section.get("title", position)))
                database.execute("INSERT INTO sections VALUES(?,?,?)", (identifier, key, encoded(section)))
        for theme in payload["themes"]:
            database.execute("INSERT INTO themes VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (theme["id"], encoded(theme)))
        for section in payload["research_sections"]:
            database.execute("INSERT INTO research_sections VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET artifact_id=excluded.artifact_id,payload=excluded.payload", (section["id"], section["artifact_id"], encoded(section)))
        symbol_by_id = {row.get("id", row["symbol"]): row["symbol"] for row in payload["securities"]}
        for relation in payload["security_artifact_relations"]:
            symbol = symbol_by_id.get(relation["security_id"])
            if symbol is None:
                raise StateError("Unresolved security relation: " + relation["security_id"])
            database.execute("INSERT INTO security_artifact_relations VALUES(?,?,?,?,?) ON CONFLICT(security_symbol,artifact_id,section_id,relationship) DO UPDATE SET payload=excluded.payload", (symbol, relation["artifact_id"], relation.get("section_id"), relation.get("relationship", "research"), encoded(relation)))
        extras = {key: value for key, value in payload.items() if key not in ("issuers", "securities", "artifacts", "themes", "research_sections", "security_artifact_relations", "_meta")}
        database.execute("INSERT OR REPLACE INTO metadata VALUES('inventory_metadata',?)", (encoded(extras),))
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()
    return export(root)


def meta(role):
    return {"schema_version": SCHEMA_VERSION, "role": role, "user_timezone": USER_TIMEZONE,
            "session_timezone": SESSION_TIMEZONE, "execution": "offline_only"}


def export(root):
    root = Path(root).expanduser().resolve()
    research = connect(root, "research")
    alerts = connect(root, "alerts")
    try:
        catalog = {"_meta": meta("canonical_research_catalog"), "issuers": [], "securities": [], "artifacts": []}
        extras = research.execute("SELECT value FROM metadata WHERE key='inventory_metadata'").fetchone()
        if extras:
            catalog.update(json.loads(extras[0]))
        for table, key in (("issuers", "id"), ("securities", "symbol"), ("artifacts", "library_file_id")):
            catalog[table] = [json.loads(row[0]) for row in research.execute("SELECT payload FROM " + table + " ORDER BY " + key)]
        for table, key in (("themes", "id"), ("research_sections", "id"), ("security_artifact_relations", "security_symbol,artifact_id,section_id,relationship")):
            catalog[table] = [json.loads(row[0]) for row in research.execute("SELECT payload FROM " + table + " ORDER BY " + key)]
        rows = [json.loads(row[0]) for row in alerts.execute("SELECT payload FROM alerts ORDER BY id")]
        snapshot = alerts.execute("SELECT value FROM metadata WHERE key='latest_observed_fingerprint'").fetchone()
        observed_ids = alerts.execute("SELECT value FROM metadata WHERE key='latest_observed_ids'").fetchone()
        alert_meta = meta("alert_app_mirror")
        alert_meta.update({"canonical_source": "price_alert_studio_D1", "observed_fingerprint": snapshot[0] if snapshot else fingerprint([]),
                           "observed_ids": json.loads(observed_ids[0]) if observed_ids else [], "missing_rows_are_not_deletions": True,
                           "local_price_detection_enabled": False, "local_notification_delivery_enabled": False})
        mirror = {"_meta": alert_meta, "alerts": rows}
        atomic_json(root / "research.json", catalog)
        standalone = (root / "workflow.json").exists() and load_json(root / "workflow.json").get("alert_authority") == "niulai_saved_json_sqlite"
        if standalone:
            # Saved JSON is authoritative after migration; a research export must not overwrite it with an old SQL mirror.
            if not (root / "alerts.json").exists():raise StateError("Restore authoritative alerts.json before export")
            rows = normalize_alerts(load_json(root / "alerts.json"))
        else:
            atomic_json(root / "alerts.json", mirror)
        config = {"_meta": meta("workflow_configuration"), "databases": {"research": "research.sqlite", "alerts": "alerts.sqlite"},
                  "research_catalog": "research.json", "alert_mirror": "alerts.json", "alert_authority": "price_alert_studio_D1",
                  "schedules": [], "notifications": {"authority": "price_alert_studio", "local_delivery_enabled": False}}
        # Preserve user-managed workflow settings across exports.
        if not (root / "workflow.json").exists():
            atomic_json(root / "workflow.json", config)
        return {"root": str(root), "artifacts": len(catalog["artifacts"]), "securities": len(catalog["securities"]),
                "alerts": len(rows), "enabled_alerts": sum(row["enabled"] for row in rows), "observed_fingerprint": alert_meta["observed_fingerprint"]}
    finally:
        research.close()
        alerts.close()


def plan_alert_sync(desired_payload, observed_payload):
    desired = normalize_alerts(desired_payload, allow_operations=True)
    observed = normalize_alerts(observed_payload)
    observed_hash = fingerprint(observed)
    baseline = desired_payload.get("_meta", {}).get("observed_fingerprint") if isinstance(desired_payload, dict) else None
    if baseline != observed_hash:
        raise StateError("Stale or missing observed_fingerprint; refresh the observed snapshot before planning")
    before = {str(uuid.UUID(row["id"])): row for row in observed}
    changes = []
    for row in desired:
        identifier = str(uuid.UUID(row["id"]))
        old = before.get(identifier)
        if row.get("operation") == "delete":
            if old:
                changes.append({"operation": "delete", "id": row["id"], "before": old})
        elif old is None:
            changes.append({"operation": "create", "id": row["id"], "after": row})
        elif row != old:
            changes.append({"operation": "update", "id": row["id"], "before": old, "after": row})
    return {"_meta": meta("review_only_sync_plan"), "observed_fingerprint": observed_hash,
            "operations": changes, "omitted_observed_rows": sum(key not in {str(uuid.UUID(r["id"])) for r in desired} for key in before),
            "deletes_require_explicit_operation": True, "executed": False}


def status(root):
    root = Path(root).expanduser().resolve()
    result = {"root": str(root), "initialized": all((root / (name + ".sqlite")).is_file() for name in ("research", "alerts")),
              "schema_version": SCHEMA_VERSION, "alert_authority": "price_alert_studio_D1", "local_detection_or_delivery": False}
    if (root / "workflow.json").exists():
        result["alert_authority"] = load_json(root / "workflow.json").get("alert_authority")
        result["local_detection_or_delivery"] = result["alert_authority"] == "niulai_saved_json_sqlite"
    for name, tables in (("research", ("artifacts", "securities", "research_sections", "security_artifact_relations", "themes")), ("alerts", ("alerts",))):
        path = root / (name + ".sqlite")
        if not path.is_file():
            continue
        database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            result[name + "_schema_version"] = database.execute("PRAGMA user_version").fetchone()[0]
            result[name + "_foreign_key_violations"] = len(database.execute("PRAGMA foreign_key_check").fetchall())
            for table in tables:
                result[table] = database.execute("SELECT count(*) FROM " + table).fetchone()[0]
            if name == "alerts":
                result["enabled_alerts"] = database.execute("SELECT count(*) FROM alerts WHERE enabled=1").fetchone()[0]
                result["alert_tickers"] = database.execute("SELECT count(DISTINCT ticker) FROM alerts").fetchone()[0]
        finally:
            database.close()
    return result


def record_run(root, payload):
    if not isinstance(payload, dict):
        raise StateError('Run record must be an object')
    required = ('id', 'kind', 'status', 'started_at', 'finished_at')
    for key in required:
        text_field(payload.get(key), key)
    if payload['status'] not in ('completed', 'partial', 'failed', 'skipped'):
        raise StateError('Invalid final run status')
    value = encoded(payload)
    db = connect(root, 'research')
    try:
        with db:
            old = db.execute('SELECT payload FROM job_runs WHERE id=?', (payload['id'],)).fetchone()
            if old:
                if old[0] != value:
                    raise StateError('Run ID conflict; preserve the original result and use a distinct attempt ID')
                return {'id': payload['id'], 'idempotent': True, 'recorded': False}
            db.execute('INSERT INTO job_runs(id,kind,status,started_at,finished_at,payload) VALUES(?,?,?,?,?,?)',
                       (payload['id'],payload['kind'],payload['status'],payload['started_at'],payload['finished_at'],value))
        return {'id': payload['id'], 'idempotent': False, 'recorded': True}
    finally:
        db.close()


def get_run(root, identifier):
    path=Path(root).expanduser().resolve()/'research.sqlite'
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute('SELECT payload FROM job_runs WHERE id=?',(identifier,)).fetchone()
        return {'id':identifier,'found':bool(row),'run':json.loads(row[0]) if row else None}
    finally:
        db.close()


def validate_config(payload):
    if not isinstance(payload, dict):
        raise StateError('Configuration must be an object')
    revision=payload.get('config_revision')
    if isinstance(revision,bool) or not isinstance(revision,int) or revision<1:
        raise StateError('config_revision must be a positive integer')
    if payload.get('alert_authority') not in ('price_alert_studio_D1','niulai_saved_json_sqlite'):
        raise StateError('Changing the alert authority requires a reviewed migration')
    if payload.get('alert_authority')=='niulai_saved_json_sqlite':
        monitor=payload.get('price_monitor',{})
        if monitor.get('studio_dependency') is not False or monitor.get('engine')!='scripts/price_watch.py':raise StateError('Standalone engine contract missing')
        try:
            band=Decimal(str(monitor['buffer_fraction']))
            if not band.is_finite() or not 0<=band<=Decimal('.05'):raise ValueError()
            for value in monitor.get('leverage_multipliers',{}).values():
                if isinstance(value,bool) or not Decimal(str(value)).is_finite() or not 1<=abs(Decimal(str(value)))<=5:raise ValueError()
        except (KeyError,ValueError,InvalidOperation):raise StateError('Invalid buffer or leverage map')
    meta=payload.get('_meta',{})
    for key in ('user_timezone','session_timezone'):
        try:ZoneInfo(meta[key])
        except (KeyError,TypeError,ZoneInfoNotFoundError) as e:raise StateError('Invalid '+key) from e
    schedules=payload.get('schedules')
    if not isinstance(schedules,list):raise StateError('schedules must be an array')
    roles=set()
    for s in schedules:
        role=text_field(s.get('role'),'schedule role')
        if role in roles:raise StateError('Duplicate schedule role')
        roles.add(role)
        if 'enabled' in s and not isinstance(s['enabled'],bool):raise StateError('Schedule enabled must be boolean')
        if s.get('enabled') is True and not s.get('automation_id'):raise StateError('Enabled schedule needs a saved automation identity')
    for draft in payload.get('draft_alerts',[]):
        if draft.get('enabled') is not False:raise StateError('Unresolved draft alerts must remain explicitly disabled')
    notifications=payload.get('notifications',{})
    if notifications.get('configuration_managed') is True:
        if notifications.get('transport')!='native_scheduled_task_output':raise StateError('Unsupported configured notification transport')
        policies=notifications.get('policies')
        if not isinstance(policies,dict):raise StateError('Configured notification policies are required')
        for schedule in schedules:
            role=schedule['role']
            if not schedule.get('automation_id') or schedule.get('enabled') is not True:continue
            policy=policies.get(role)
            if not isinstance(policy,dict) or not isinstance(policy.get('enabled'),bool):raise StateError('Missing enabled notification policy for '+role)
        summary=policies.get('existing_summary')
        if summary:
            if payload.get('alert_authority')=='price_alert_studio_D1' and summary.get('read_only') is not True:raise StateError('Legacy alert summary must remain read-only')
            if not isinstance(summary.get('notify_on_quiet_days'),bool):raise StateError('Invalid quiet-summary policy')
            windows=summary.get('windows')
            if not isinstance(windows,list) or not windows or any(w not in ('today','3d','7d','10d') for w in windows):raise StateError('Unsupported summary windows')
        for schedule in schedules:
            grace=schedule.get('runtime_slot_grace_minutes')
            if grace is not None and (isinstance(grace,bool) or not isinstance(grace,int) or not 1<=grace<=120):raise StateError('Invalid schedule grace window')
    weekly=payload.get('research',{}).get('weekly_review')
    if weekly is not None:
        if not isinstance(weekly,dict):raise StateError('weekly_review must be an object')
        if not isinstance(weekly.get('enabled'),bool):raise StateError('weekly_review enabled must be boolean')
        if weekly.get('enabled'):
            if 'weekly_thesis_review' not in roles:raise StateError('Weekly review needs its saved schedule')
            tail=weekly.get('tail_fraction')
            if isinstance(tail,bool):raise StateError('Invalid weekly tail_fraction')
            try:tail=decimal.Decimal(str(tail))
            except decimal.InvalidOperation as error:raise StateError('Invalid weekly tail_fraction') from error
            if not tail.is_finite() or not 0<tail<=decimal.Decimal('0.5'):raise StateError('Invalid weekly tail_fraction')
            if weekly.get('universe_source')!='research_catalog.securities':raise StateError('Unreviewed weekly universe source')
            if weekly.get('return_basis')!='split_and_distribution_adjusted_close':raise StateError('Unreviewed weekly return basis')
            if weekly.get('model_availability_gate') is not True:raise StateError('Weekly EV requires the model availability gate')
    triggered=payload.get('research',{}).get('daily_triggered_review')
    if triggered is not None:
        if not isinstance(triggered,dict) or type(triggered.get('enabled')) is not bool:
            raise StateError('Invalid daily_triggered_review policy')
        if triggered['enabled']:
            if 'daily_triggered_research' not in roles:raise StateError('Triggered research needs saved schedule')
            for key in ('batch_size','max_concurrency'):
                value=triggered.get(key)
                if type(value) is not int or not 1<=value<=8:raise StateError('Invalid triggered research '+key)
            for key in ('read_original_documents','incremental_evidence_required','allow_no_new_edge'):
                if triggered.get(key) is not True:raise StateError('Triggered research missing '+key)
            for key in ('automatic_trading','automatic_alert_edits'):
                if triggered.get(key) is not False:raise StateError('Triggered research must preserve proposal-only '+key)
        orchestration_version=triggered.get('orchestration_policy_version')
        if orchestration_version is not None and orchestration_version!='2026-10-20-native-ticker-1':
            raise StateError('Unknown triggered orchestration policy version')
        orchestration=triggered.get('orchestration')
        if triggered['enabled'] and orchestration_version is not None and orchestration is None:
            raise StateError('Versioned triggered research requires native ticker orchestration')
        if orchestration is not None:
            if not isinstance(orchestration,dict):raise StateError('Invalid triggered orchestration object')
            required={'engine':'native_subagents','orchestrator':'single_parent','unit':'ticker',
                      'shared_db_writer':'orchestrator_only'}
            for key,value in required.items():
                if orchestration.get(key)!=value:raise StateError('Unsupported triggered orchestration '+key)
            for key in ('independent_review','per_ticker_checkpoints'):
                if orchestration.get(key) is not True:raise StateError('Triggered orchestration requires '+key)
            active=orchestration.get('max_active_ticker_pipelines')
            if type(active) is not int or not 1<=active<=8:
                raise StateError('Invalid max_active_ticker_pipelines')
            for key in ('max_concurrency','batch_size'):
                bound=triggered.get(key)
                if type(bound) is not int or not 1<=bound<=8 or active>bound:
                    raise StateError('Active ticker pipelines exceed configured '+key)
    return {'valid':True,'config_revision':revision,'schedule_roles':sorted(roles),'activated_anything':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "import-research", "import-alerts", "export", "status", "plan-alert-sync", "record-run", "get-run", "validate-config"):
        child = commands.add_parser(command)
        child.add_argument("--root", required=True)
        if command.startswith("import-") or command in ('record-run','validate-config'):
            child.add_argument("--file", required=True)
        if command == "plan-alert-sync":
            child.add_argument("--desired", required=True)
            child.add_argument("--observed", required=True)
        if command == 'get-run':
            child.add_argument('--id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init(args.root)
        elif args.command == "import-research":
            result = import_research(args.root, load_json(args.file))
        elif args.command == "import-alerts":
            result = import_alerts(args.root, load_json(args.file))
        elif args.command == "plan-alert-sync":
            result = plan_alert_sync(load_json(args.desired), load_json(args.observed))
        elif args.command == "status":
            result = status(args.root)
        elif args.command == 'record-run':
            result = record_run(args.root, load_json(args.file))
        elif args.command == 'get-run':
            result = get_run(args.root, args.id)
        elif args.command == 'validate-config':
            result = validate_config(load_json(args.file))
        else:
            result = export(args.root)
        print(encoded(result), end="")
        return 0
    except (StateError, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as error:
        print(encoded({"error": str(error), "executed": False}), file=sys.stderr, end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
