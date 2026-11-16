CREATE TABLE credential_commit_receipts (
  commit_id TEXT PRIMARY KEY NOT NULL,
  lease_id TEXT NOT NULL,
  profile_sha256 TEXT NOT NULL,
  request_sha256 TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision >= 0),
  committed_at TEXT NOT NULL,
  release_requested INTEGER NOT NULL CHECK(release_requested IN (0,1)),
  protocol INTEGER NOT NULL CHECK(protocol = 2)
);
--> statement-breakpoint
CREATE TABLE credential_history_activation (
  activation_id TEXT PRIMARY KEY NOT NULL,
  observed_revision INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  record_type TEXT NOT NULL CHECK(record_type = 'observed_legacy_baseline'),
  legacy_head_commit_id TEXT,
  cipher_sha256 TEXT NOT NULL,
  protocol INTEGER NOT NULL CHECK(protocol = 2)
);
