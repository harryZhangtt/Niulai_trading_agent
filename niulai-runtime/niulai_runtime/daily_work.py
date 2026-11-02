"""Small domain work ledger in the existing outbox DB; no second queue service.

The shared scheduler owns wakes and process lifetime. This ledger owns report
checkpoints and delayed data recovery. Gmail uncertainty remains in Outbox.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from .delivery import Outbox, DeliveryError

UTC = timezone.utc


def require(ok, code):
    if not ok:
        raise DeliveryError(code)


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'DAILY_AWARE_CLOCK_REQUIRED')
    return parsed.astimezone(UTC)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def private(root, path, directory=False):
    root = Path(root).resolve(strict=True)
    path = Path(os.path.abspath(path))
    boundary = root / '.niulai-state'
    require('..' not in path.parts and path.is_relative_to(boundary)
            and path.resolve().is_relative_to(boundary.resolve()), 'DAILY_PATH_ESCAPE')
    for p in (path, *path.parents):
        if p == root:
            break
        require(not p.is_symlink(), 'DAILY_PATH_SYMLINK')
        if p.exists():
            require(p.stat().st_uid == os.getuid(), 'DAILY_PATH_OWNER')
    if directory:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for p in (path, *path.parents):
            if p == root:
                break
            p.chmod(0o700)
    return path


def atomic(path, value):
    require(not path.is_symlink(), 'DAILY_PATH_SYMLINK')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.daily-')
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Work:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.outbox = Outbox(self.root / '.niulai-state/databases/outbox.sqlite', self.root)
        self.path = self.outbox.path
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS digest_work (
                id TEXT PRIMARY KEY, logical_key TEXT UNIQUE NOT NULL,
                meta TEXT NOT NULL, state TEXT NOT NULL, due_at TEXT,
                lease_owner TEXT, lease_until TEXT, tries INTEGER NOT NULL DEFAULT 0,
                initial_key TEXT, correction_key TEXT, last_code TEXT NOT NULL DEFAULT '')''')
            db.execute('CREATE INDEX IF NOT EXISTS digest_due ON digest_work(state,due_at)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def get(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT * FROM digest_work WHERE id=?', (identity,)).fetchone()
        if row:
            value = dict(row); value['meta'] = json.loads(value['meta']); return value

    def create(self, key, meta):
        identity = sha(key.encode())[:32]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT OR IGNORE INTO digest_work(id,logical_key,meta,state,due_at) VALUES(?,?,?,'pending',?)",
                       (identity, key, json.dumps(meta, sort_keys=True), meta['scheduled_at']))
        row = self.get(identity)
        require(row['logical_key'] == key, 'DAILY_IDENTITY_COLLISION')
        return row

    def claim(self, identity, owner, now=None):
        require(isinstance(owner, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', owner), 'DAILY_OWNER_INVALID')
        now = now or datetime.now(UTC)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM digest_work WHERE id=?', (identity,)).fetchone()
            require(row is not None, 'DAILY_WORK_MISSING')
            if row['state'] in ('done', 'expired', 'waiting_access', 'delivery_unknown'):
                return False
            if now >= stamp(json.loads(row['meta'])['deadline']):
                db.execute("UPDATE digest_work SET state='expired',last_code='DATA_RETRY_DEADLINE' WHERE id=?", (identity,))
                return False
            if row['lease_until'] and stamp(row['lease_until']) > now:
                return False
            if row['due_at'] and stamp(row['due_at']) > now:
                return False
            # Never rerun either branch to repair an uncertain/accepted-unverified send.
            for key in (row['initial_key'], row['correction_key']):
                sent = self.outbox.get(key) if key else None
                if sent and (sent['status'] in ('sending', 'unknown') or
                             sent['status'] == 'accepted' and not sent['verified_at']):
                    db.execute("UPDATE digest_work SET state='delivery_unknown',last_code='GMAIL_RECONCILIATION_REQUIRED' WHERE id=?", (identity,))
                    return False
            db.execute("UPDATE digest_work SET state='running',lease_owner=?,lease_until=?,tries=tries+1 WHERE id=?",
                       (owner, (now + timedelta(minutes=30)).isoformat(), identity))
        return True

    def due(self, purpose, now=None):
        now = now or datetime.now(UTC)
        with self.connect() as db:
            rows = db.execute("SELECT id FROM digest_work WHERE state IN ('pending','retry_wait','running') AND due_at<=? ORDER BY due_at", (now.isoformat(),)).fetchall()
        for row in rows:
            value = self.get(row['id'])
            if value['meta']['purpose'] == purpose:
                return value

    def bind_delivery(self, identity, key, correction=False):
        field = 'correction_key' if correction else 'initial_key'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(f'SELECT {field} FROM digest_work WHERE id=?', (identity,)).fetchone()
            require(row is not None and row[field] in (None, key), 'DAILY_DELIVERY_CONFLICT')
            db.execute(f'UPDATE digest_work SET {field}=? WHERE id=?', (key, identity))

    def settle(self, identity, *, pending=False, blocked=False, now=None):
        now = now or datetime.now(UTC); row = self.get(identity)
        require(row is not None, 'DAILY_WORK_MISSING')
        state = 'waiting_access' if blocked else 'done'
        due = None; code = 'DEPENDENCY_CHANGE_REQUIRED' if blocked else 'DAILY_WORK_COMPLETE'
        if pending and not blocked:
            delay = (120, 600, 1800)[min(max(row['tries'] - 1, 0), 2)]
            due_time = now + timedelta(seconds=delay)
            if row['tries'] < 4 and due_time < stamp(row['meta']['deadline']):
                state = 'retry_wait'; due = due_time.isoformat(); code = 'DATA_RETRY_SCHEDULED'
            else:
                state = 'expired'; code = 'DATA_RETRY_DEADLINE'
        with self.connect() as db:
            db.execute('UPDATE digest_work SET state=?,due_at=?,lease_owner=NULL,lease_until=NULL,last_code=? WHERE id=?',
                       (state, due, code, identity))
        return self.get(identity)
