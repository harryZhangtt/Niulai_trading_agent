# Market research integration contract

## Execution boundary

Let the Dot coordinate scheduled and background research. Keep numeric ingestion, historical coverage, calculations, SQL persistence, deduplication, and revision-safe publication in the backend. This skill installs methodology only: no scheduler, database, market subscription, app integration, or background worker is activated by installation.

Proposed operations are refresh_market(session), get_research_context(subject), list_due_work(cutoff), save_evidence(record), and submit_research_result(result, expected_revision, idempotency_key). Discover and inspect actual tools before calling them. Do not simulate success when these operations are absent.

## Inputs

Use run_id, subject_ids, task_kind, cutoff, input_revision, tracker_revision, skill_revision, prior_evidence_ids, snapshot_id, question, budget, and publication_policy. Resolve completed trading sessions with a deterministic exchange calendar. Do not equate weekdays with trading days. Keep session timezone America/New_York distinct from delivery timezone Asia/Shanghai; no delivery hour is enabled by this skill.

## Output fields

Return a JSON-compatible record with:
- run_id, subject_ids, task_kind, cutoff, input_revision, tracker_revision, skill_revision
- execution_status: completed, partial, blocked, or failed
- publication_status: draft, published, awaiting_review, or superseded (published requires confirmed persistence)
- conclusion, confidence, coverage_summary, evidence_gaps
- evidence[]: source_url, title, published_at (nullable), retrieved_at, reporting_period (nullable), passage_locator, excerpt_or_summary, source_type, claim_ids
- claims[]: id, statement, fact_or_interpretation, supports_or_opposes, thesis_pillar, evidence_ids
- calculations[]: definition_version, input_refs, units, period, value, quality_status
- proposed_changes[]: subject_id, expected_revision, change, rationale, evidence_ids
- next_checks[]: question, trigger_or_due_date, priority
- result_reference: confirmed storage reference or null

Do not invent IDs when the backend owns them; use temporary local labels in drafts and resolve them at save time. Preserve unknown timestamps as null, not retrieval time. Distinguish a partial successful search from evidence that nothing changed.

## Async and publication

Persist work identity from subject + task kind + cutoff + input revision + tracker/skill revision. Reuse unfinished matching work. Save source/evidence checkpoints when a persistence tool is available. Reject stale revisions, preserve historical output, and request reconciliation. Publish numeric snapshots independently from research. On interruption, resume from saved artifacts without claiming exact recovery of hidden reasoning. Treat hard time/spend limits as backend capabilities; skill instructions alone do not enforce them.

## Policy defaults

Within an authorized daily pipeline, run lightweight evidence checks for all active themes, including robotics; use configured weekly reviews and material-change triggers for deeper research. Installation does not save these schedules. Keep manual requests optional. Publish factual evidence under the existing authorized policy; keep thesis/membership changes as proposals unless explicit auto-adoption is configured. Do not send third-party messages, calendar invitations, or trading orders through this workflow.

## Composition

Use this bundle as the methodology layer for evidence research, theme maintenance, earnings review, and thesis review. The updated AI Berkshire bundle is an installed mandatory applicable dependency, not an optional future integration. Keep original upstream definitions pinned; the parent's explicit growth-aware precedence controls revised mode. New full reports bind both AI Berkshire and applicable Anthropic methods to source/model artifacts under the visual-rationale policy. Framework agreement is not independent factual corroboration. Shared run/evidence/revision contracts preserve storage and phone UI boundaries.
