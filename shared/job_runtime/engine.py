"""Durable schedule admission and retry state, independent of models and jobs.

The supervisor owns process lifetime. Dispatchers own external execution and must
return transport receipts, not treat a model's statement as delivery evidence.
Unknown outcomes block a job until an operator reconciles its exact attempt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

UTC = timezone.utc
TERMINAL = ("succeeded", "failed", "unknown", "missed", "coalesced")


class EngineError(ValueError):
    """Fixed, non-content diagnostic suitable for private operational logs."""


def require(test, code):
    if not test:
        raise EngineError(code)


def instant(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise EngineError("INVALID_AWARE_TIME") from None
    require(isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None, "AWARE_TIME_REQUIRED")
    return value.astimezone(UTC)


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def validate_job(job):
    require(isinstance(job, dict), "JOB_INVALID")
    require(isinstance(job.get("id"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", job["id"]), "JOB_ID_INVALID")
    require(type(job.get("enabled")) is bool and type(job.get("replay_safe")) is bool, "JOB_FLAGS_INVALID")
    # This is injected by infrastructure after allocation-schema validation.
    # Job allocations must not choose their own authentication/resource fence.
    if "_resource_key" in job:
        require(isinstance(job["_resource_key"], str) and 1 <= len(job["_resource_key"]) <= 2048,
                "RESOURCE_KEY_INVALID")
    s = job.get("schedule")
    require(isinstance(s, dict), "JOB_SCHEDULE_INVALID")
    kind = s.get("kind")
    if kind == "interval":
        require(set(s) <= {"kind", "seconds", "grace_seconds"} and _int(s.get("seconds"), 1, 86400 * 365), "INTERVAL_INVALID")
        require(_int(s.get("grace_seconds", s["seconds"]), 1, 86400 * 7), "GRACE_INVALID")
    elif kind == "daily":
        require(set(s) == {"kind", "timezone", "times", "grace_seconds"}, "DAILY_KEYS_INVALID")
        require(isinstance(s["timezone"], str), "TIMEZONE_INVALID")
        try:
            ZoneInfo(s["timezone"])
        except (ValueError, KeyError):
            raise EngineError("TIMEZONE_INVALID") from None
        times = s["times"]
        require(isinstance(times, list) and 1 <= len(times) <= 24
                and all(isinstance(t, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t) for t in times)
                and len(set(times)) == len(times), "DAILY_TIMES_INVALID")
        require(_int(s["grace_seconds"], 1, 86400 * 7), "GRACE_INVALID")
    elif kind == "once":
        require(set(s) == {"kind", "at", "grace_seconds"}, "ONCE_KEYS_INVALID")
        instant(s["at"])
        require(_int(s["grace_seconds"], 1, 86400 * 7), "GRACE_INVALID")
    else:
        raise EngineError("SCHEDULE_KIND_INVALID")


def _private_state(path, workspace_root):
    root = Path(workspace_root).resolve(strict=True)
    allowed = root / ".job-runtime"
    p = Path(os.path.abspath(path))
    require(".." not in Path(path).parts and p.is_relative_to(allowed)
            and p.resolve().is_relative_to(allowed.resolve()), "STATE_OUTSIDE_WORKSPACE")
    for x in [p, *p.parents]:
        if x == root:
            break
        require(not x.is_symlink(), "STATE_SYMLINK_REJECTED")
        if x.exists():
            require(x.is_dir() and x.stat().st_uid == os.getuid(), "STATE_OWNER_INVALID")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    for x in [p, *p.parents]:
        if x == root:
            break
        x.chmod(0o700)
    return p


class Engine:
    """A synchronous durable dispatcher; safe for competing tick processes.

    ``tick`` never automatically retries a dispatcher exception. Only an
    explicit ``retryable`` response for a replay-safe job authorizes retry.
    The supervisor must not use ``recover_running`` while an old worker lives.
    """

    def __init__(self, state_dir, jobs, retry_policy, dispatcher, workspace_root=None, clock=None, max_workers=2):
        self.workspace = Path(workspace_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
        self.state = _private_state(state_dir, self.workspace)
        require(isinstance(jobs, list), "JOBS_INVALID")
        for job in jobs:
            validate_job(job)
        require(len({j["id"] for j in jobs}) == len(jobs), "DUPLICATE_JOB_ID")
        require(isinstance(retry_policy, dict) and set(retry_policy) == {"max_attempts", "backoff_seconds", "max_backoff_seconds"}, "RETRY_POLICY_INVALID")
        require(_int(retry_policy["max_attempts"], 1, 10)
                and _int(retry_policy["backoff_seconds"], 1, 3600)
                and _int(retry_policy["max_backoff_seconds"], retry_policy["backoff_seconds"], 86400), "RETRY_POLICY_INVALID")
        require(callable(dispatcher), "DISPATCHER_REQUIRED")
        require(_int(max_workers, 1, 8), "MAX_WORKERS_INVALID")
        self.jobs = {j["id"]: json.loads(json.dumps(j)) for j in jobs}
        self.retry = dict(retry_policy)
        self.dispatcher = dispatcher
        self.max_workers = max_workers
        self.clock = clock or (lambda: datetime.now(UTC))
        self.instance_id = str(uuid.uuid4())
        self.path = self.state / "schedule.sqlite"
        require(not self.path.is_symlink(), "DATABASE_SYMLINK_REJECTED")
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self._db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, schedule_hash TEXT NOT NULL, cursor REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS slots(slot_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,scheduled_at REAL NOT NULL,
                expires_at REAL NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL,updated_at REAL NOT NULL,code TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS slot_due ON slots(status,next_attempt_at,scheduled_at);
              CREATE UNIQUE INDEX IF NOT EXISTS job_one_running ON slots(job_id) WHERE status='running';
              CREATE TABLE IF NOT EXISTS attempts(attempt_id TEXT PRIMARY KEY,slot_id TEXT NOT NULL,attempt_no INTEGER NOT NULL,
                started_at REAL NOT NULL,ended_at REAL,status TEXT NOT NULL,code TEXT NOT NULL,receipt TEXT);
              CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS delivery_reconciliations(slot_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL,
                message_id TEXT NOT NULL,payload_digest TEXT NOT NULL,verified_at TEXT NOT NULL,recorded_at REAL NOT NULL,
                receipt TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS immutable_delivery_reconciliation_update BEFORE UPDATE ON delivery_reconciliations
                BEGIN SELECT RAISE(ABORT,'delivery reconciliation is immutable'); END;
              CREATE TRIGGER IF NOT EXISTS immutable_delivery_reconciliation_delete BEFORE DELETE ON delivery_reconciliations
                BEGIN SELECT RAISE(ABORT,'delivery reconciliation is immutable'); END;
            ''')

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        return db

    def heartbeat(self, now):
        value = instant(now).isoformat()
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('heartbeat',?)", (value,))
        return value

    def _insert(self, db, slot_id, job_id, scheduled, expiry, now, status=None, code=None):
        status = status or ("ready" if now <= expiry else "missed")
        code = code or ("DUE" if status == "ready" else "GRACE_EXPIRED")
        db.execute("INSERT OR IGNORE INTO slots(slot_id,job_id,scheduled_at,expires_at,status,updated_at,code) VALUES(?,?,?,?,?,?,?)",
                   (slot_id, job_id, scheduled, expiry, status, now, code))

    def _allocate(self, db, job, now):
        s, job_id = job["schedule"], job["id"]
        digest = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
        previous = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if previous:
            require(previous["schedule_hash"] == digest, "SCHEDULE_CHANGE_REQUIRES_NEW_JOB_ID")
            require(now >= previous["cursor"], "CLOCK_MOVED_BACKWARDS")
        cursor = previous["cursor"] if previous else None
        if s["kind"] == "interval":
            seconds = s["seconds"]
            index = math.floor(now / seconds)
            scheduled = index * seconds
            if cursor is None or scheduled > math.floor(cursor / seconds) * seconds:
                if cursor is not None:
                    first = math.floor(cursor / seconds) + 1
                    skipped = index - first
                    if skipped > 0:
                        self._insert(db, f"{job_id}:coalesced:{first}-{index - 1}", job_id, first * seconds,
                                     scheduled, now, "coalesced", f"INTERVALS_COALESCED_{min(skipped, 999999)}")
                self._insert(db, f"{job_id}:interval:{index}", job_id, scheduled,
                             scheduled + s.get("grace_seconds", seconds), now)
        elif s["kind"] == "once":
            scheduled = instant(s["at"]).timestamp()
            if scheduled <= now:
                self._insert(db, f"{job_id}:once:{instant(s['at']).isoformat()}", job_id,
                             scheduled, scheduled + s["grace_seconds"], now)
        else:
            zone = ZoneInfo(s["timezone"])
            today = datetime.fromtimestamp(now, UTC).astimezone(zone).date()
            day = datetime.fromtimestamp(cursor, UTC).astimezone(zone).date() if cursor is not None else today
            # Long outages are coalesced to a bounded daily history. Every
            # currently eligible slot remains included; old history is one row.
            if (today - day).days > 366:
                self._insert(db, f"{job_id}:coalesced-days:{day}:{today}", job_id, cursor,
                             now, now, "coalesced", "OLD_DAYS_COALESCED")
                day = today - timedelta(days=366)
            while day <= today:
                for slot in sorted(s["times"]):
                    hour, minute = map(int, slot.split(":"))
                    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
                    scheduled = local.astimezone(UTC).timestamp()
                    if scheduled > now or (cursor is not None and scheduled <= cursor):
                        continue
                    slot_id = f"{job_id}:daily:{day.isoformat()}:{slot}"
                    roundtrip = datetime.fromtimestamp(scheduled, UTC).astimezone(zone)
                    if (roundtrip.hour, roundtrip.minute, roundtrip.date()) != (hour, minute, day):
                        self._insert(db, slot_id, job_id, scheduled, scheduled, now, "missed", "LOCAL_TIME_NONEXISTENT")
                    else:
                        self._insert(db, slot_id, job_id, scheduled, scheduled + s["grace_seconds"], now)
                day += timedelta(days=1)
        db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?)", (job_id, digest, now))

    def _claim(self, job_id, now):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            # An unresolved prior effect blocks all later slots for this job.
            if db.execute("SELECT 1 FROM slots WHERE job_id=? AND status IN ('running','unknown') LIMIT 1", (job_id,)).fetchone():
                return None
            db.execute("UPDATE slots SET status='missed',code='GRACE_EXPIRED',updated_at=? WHERE job_id=? AND status IN ('ready','retry_wait') AND expires_at<?", (now, job_id, now))
            row = db.execute("SELECT * FROM slots WHERE job_id=? AND status IN ('ready','retry_wait') AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY scheduled_at,slot_id LIMIT 1", (job_id, now)).fetchone()
            if not row:
                return None
            attempt_id = str(uuid.uuid4())
            number = row["attempts"] + 1
            db.execute("UPDATE slots SET status='running',attempts=?,updated_at=?,code='DISPATCHING' WHERE slot_id=?", (number, now, row["slot_id"]))
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,NULL,'running','DISPATCHING',NULL)", (attempt_id, row["slot_id"], number, now))
            return {"slot_id": row["slot_id"], "attempt_id": attempt_id, "scheduled_at": datetime.fromtimestamp(row["scheduled_at"], UTC).isoformat(),
                    "attempt_no": number, "expires_at": row["expires_at"]}

    def _finish(self, job, context, result, now):
        if not isinstance(result, dict) or result.get("status") not in ("succeeded", "retryable", "failed", "unknown"):
            result = {"status": "unknown", "code": "INVALID_DISPATCH_RESULT"}
        status = result["status"]
        code = result.get("code", "COMPLETED" if status == "succeeded" else "DISPATCH_FAILED")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
            code = "INVALID_DISPATCH_CODE"
        receipt = result.get("receipt")
        try:
            encoded = json.dumps(receipt, sort_keys=True) if isinstance(receipt, dict) and receipt else None
            require(encoded is None or len(encoded) <= 65536, "RECEIPT_TOO_LARGE")
        except (TypeError, ValueError, EngineError):
            status, code, encoded = "unknown", "INVALID_TRANSPORT_RECEIPT", None
        if status == "succeeded" and encoded is None:
            status, code = "unknown", "TRANSPORT_RECEIPT_REQUIRED"
        next_at = None
        if status == "retryable":
            if not job["replay_safe"]:
                status, code = "failed", "NON_REPLAY_SAFE_RETRY_BLOCKED"
            elif context["attempt_no"] >= self.retry["max_attempts"]:
                status, code = "failed", "RETRY_LIMIT_EXHAUSTED"
            else:
                delay = min(self.retry["backoff_seconds"] * 2 ** (context["attempt_no"] - 1), self.retry["max_backoff_seconds"])
                next_at = now + delay
                if next_at > context["expires_at"]:
                    status, code, next_at = "failed", "RETRY_WINDOW_EXPIRED", None
                else:
                    status = "retry_wait"
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM attempts WHERE attempt_id=?", (context["attempt_id"],)).fetchone()
            require(row and row["status"] == "running", "ATTEMPT_NO_LONGER_OWNED")
            db.execute("UPDATE attempts SET status=?,code=?,receipt=?,ended_at=? WHERE attempt_id=?", (status, code, encoded, now, context["attempt_id"]))
            db.execute("UPDATE slots SET status=?,code=?,next_attempt_at=?,updated_at=? WHERE slot_id=? AND status='running'", (status, code, next_at, now, context["slot_id"]))
        return status

    def tick(self, now):
        now = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for job in self.jobs.values():
                if job["enabled"]:
                    self._allocate(db, job, now)
            db.execute("INSERT OR REPLACE INTO metadata VALUES('heartbeat',?)", (datetime.fromtimestamp(now, UTC).isoformat(),))
        summary = {"dispatched": 0, "succeeded": 0, "retry_wait": 0, "failed": 0, "unknown": 0}
        def dispatch_job(job):
            # Claims happen when a worker actually starts, not when a long queue
            # is submitted. A queued slot may expire before capacity is free.
            claimed_at = max(now, instant(self.clock()).timestamp())
            context = self._claim(job["id"], claimed_at)
            if context is None:
                return None
            try:
                result = self.dispatcher(job, {k: v for k, v in context.items() if k != "expires_at"})
            except Exception:
                result = {"status": "unknown", "code": "DISPATCH_EXCEPTION_OUTCOME_UNKNOWN"}
            ended = max(claimed_at, instant(self.clock()).timestamp())
            return self._finish(job, context, result, ended)

        # The transport adapter must enforce its own subprocess/network timeout.
        # Threads are joined before returning; the engine never detaches work
        # whose outcome could later be falsely treated as safe to retry.
        groups = {}
        for job in self.jobs.values():
            if job["enabled"]:
                key = ("shared", job["_resource_key"]) if "_resource_key" in job else ("job", job["id"])
                groups.setdefault(key, []).append(job)

        def dispatch_group(jobs):
            # Jobs sharing a single-writer credential cache queue here without
            # claiming a slot or consuming an external retry attempt. Other
            # resource groups can still use the remaining worker capacity.
            return [dispatch_job(job) for job in jobs]

        if groups:
            with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="job-runtime") as pool:
                for statuses in pool.map(dispatch_group, groups.values()):
                    for status in statuses:
                        if status is not None:
                            summary["dispatched"] += 1
                            summary[status] += 1
        return summary

    def recover_running(self, now):
        """Only call after supervisor proves no prior worker can still execute."""
        at = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM slots WHERE status='running'").fetchone()[0]
            db.execute("UPDATE slots SET status='unknown',code='PROCESS_EXITED_OUTCOME_UNKNOWN',updated_at=? WHERE status='running'", (at,))
            db.execute("UPDATE attempts SET status='unknown',code='PROCESS_EXITED_OUTCOME_UNKNOWN',ended_at=? WHERE status='running'", (at,))
        return count

    def resolve_unknown(self, slot_id, outcome, receipt, now):
        """Manual evidence handoff; never a timed automatic reset or resend."""
        require(outcome in ("failed", "succeeded") and isinstance(receipt, dict) and receipt, "RECONCILIATION_EVIDENCE_REQUIRED")
        encoded = json.dumps(receipt, sort_keys=True)
        require(len(encoded) <= 65536, "RECEIPT_TOO_LARGE")
        at = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM slots WHERE slot_id=?", (slot_id,)).fetchone()
            require(row and row["status"] == "unknown", "UNKNOWN_SLOT_REQUIRED")
            db.execute("UPDATE slots SET status=?,code='OPERATOR_RECONCILED',updated_at=? WHERE slot_id=?", (outcome, at, slot_id))
            db.execute("UPDATE attempts SET status=?,code='OPERATOR_RECONCILED',receipt=?,ended_at=? WHERE slot_id=? AND status='unknown'", (outcome, encoded, at, slot_id))

    def reconcile_failed_delivery(self, slot_id, receipt, now):
        """Record independent delivery evidence for a final-format false negative.

        The caller must actually verify the exact business message and canonical
        payload through authenticated transport. This method performs no remote
        lookup, dispatch, retry or reset, and never rewrites the failed attempt.
        """
        allowed = {'BUSINESS_FINAL_VALUE_INVALID', 'BUSINESS_FINAL_JSON_REQUIRED', 'BUSINESS_FINAL_FIELDS_REJECTED'}
        require(isinstance(receipt, dict) and receipt.get('evidence_type') == 'independent_business_delivery_verification',
                'INDEPENDENT_DELIVERY_EVIDENCE_REQUIRED')
        message, payload = receipt.get('message_id'), receipt.get('payload_digest')
        require(isinstance(message, str) and re.fullmatch(r'[a-fA-F0-9]{8,64}', message)
                and isinstance(payload, str) and re.fullmatch(r'[a-fA-F0-9]{64}', payload), 'DELIVERY_IDENTIFIERS_INVALID')
        verified = instant(receipt.get('verified_at'));at = instant(now)
        require(verified <= at, 'FUTURE_DELIVERY_VERIFICATION')
        encoded = json.dumps(receipt, sort_keys=True)
        require(len(encoded) <= 65536, 'RECEIPT_TOO_LARGE')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM delivery_reconciliations WHERE slot_id=?', (slot_id,)).fetchone()
            if old:
                require(old['message_id'] == message.lower() and old['payload_digest'] == payload.lower(),
                        'DELIVERY_RECONCILIATION_CONFLICT')
                created = False
            else:
                slot = db.execute('SELECT * FROM slots WHERE slot_id=?', (slot_id,)).fetchone()
                require(slot and slot['status'] == 'failed' and slot['code'] in allowed, 'FAILED_FORMAT_SLOT_REQUIRED')
                attempt = db.execute('SELECT * FROM attempts WHERE slot_id=? ORDER BY attempt_no DESC LIMIT 1', (slot_id,)).fetchone()
                require(attempt and attempt['status'] == 'failed' and attempt['code'] == slot['code'], 'FAILED_FORMAT_ATTEMPT_REQUIRED')
                prior = json.loads(attempt['receipt'] or 'null')
                require(isinstance(prior, dict) and prior.get('turn_completed') is True
                        and type(prior.get('exit_code')) is int and prior['exit_code'] == 0,
                        'COMPLETED_MODEL_TRANSPORT_REQUIRED')
                require(verified.timestamp() >= attempt['started_at'], 'VERIFICATION_PREDATES_ATTEMPT')
                db.execute('INSERT INTO delivery_reconciliations VALUES(?,?,?,?,?,?,?)',
                           (slot_id, attempt['attempt_id'], message.lower(), payload.lower(), verified.isoformat(), at.timestamp(), encoded))
                db.execute("UPDATE slots SET status='succeeded',code='OPERATOR_VERIFIED_DELIVERY',next_attempt_at=NULL,updated_at=? WHERE slot_id=?",
                           (at.timestamp(), slot_id))
                created = True
        return {'slot_id': slot_id, 'status': 'succeeded', 'code': 'OPERATOR_VERIFIED_DELIVERY',
                'message_id': message.lower(), 'payload_digest': payload.lower(), 'reconciliation_created': created}

    def status(self):
        """Content-free summary; raw receipts and job prompts stay private."""
        with self._db() as db:
            heartbeat = db.execute("SELECT value FROM metadata WHERE key='heartbeat'").fetchone()
            counts = {row["status"]: row["n"] for row in db.execute("SELECT status,count(*) n FROM slots GROUP BY status")}
            jobs = []
            for job_id, job in self.jobs.items():
                latest = db.execute("SELECT slot_id,status,code,attempts,scheduled_at,updated_at FROM slots WHERE job_id=? ORDER BY scheduled_at DESC LIMIT 1", (job_id,)).fetchone()
                jobs.append({"id": job_id, "enabled": job["enabled"], "latest": dict(latest) if latest else None})
            return {"heartbeat": heartbeat[0] if heartbeat else None, "counts": counts, "jobs": jobs}
