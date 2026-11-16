# Task Plan: [Brief Description]

Use this file as the durable roadmap for the task. Create it before complex work and keep it current as phases change.

## Goal

State the intended end result in one clear sentence.

[One sentence describing the end state]

## Next Step

Record the single action that should happen next. Update it whenever the active phase or immediate action changes.

[The single next action. Update whenever phase status changes.]

## Current Phase

Name the phase currently being worked on.

Phase 1

## Phases

Break the task into three to seven verifiable phases. Use only `pending`, `in_progress`, or `complete` for each status and update the value when work advances.

### Phase 1: Requirements & Discovery

- [ ] Understand user intent
- [ ] Identify constraints and requirements
- [ ] Document findings in findings.md
- **Status:** in_progress

### Phase 2: Planning & Structure

- [ ] Define technical approach
- [ ] Create project structure if needed
- [ ] Document decisions with rationale
- **Status:** pending

### Phase 3: Implementation

- [ ] Execute the plan step by step
- [ ] Write code to files before executing
- [ ] Test incrementally
- **Status:** pending

### Phase 4: Testing & Verification

- [ ] Verify all requirements met
- [ ] Document test results in progress.md
- [ ] Fix any issues found
- **Status:** pending

### Phase 5: Delivery

- [ ] Review all output files
- [ ] Ensure deliverables are complete
- [ ] Deliver to user
- **Status:** pending

## Key Questions

Record important questions and replace them with answers as they are resolved.

1. [Question to answer]
2. [Question to answer]

## Decisions Made

Record significant choices and the reason for each one.

| Decision | Rationale |
|----------|-----------|
|          |           |

## Architecture Escalation (optional)

Use only when the measurable progress-and-recovery trigger fires. Keep ordinary
localized fixes out of this section.

- **Declaration:** [path to `architecture-escalation-1` JSON]
- **Candidate fingerprint/family:** [full SHA-256 plus sorted path/SHA-256/owner/boundary entries]
- **Integration owner:** [one owner]
- **Stable finding IDs / deduplicated counters:** [IDs plus critical, high, breadth, reopen, drift and green-suite counts]
- **Evidence packet:** [reproducer, producer/consumer schemas, state map, chronology, and web sources with role, route, version/date, semantics and applicability]
- **O0/O1/O2 comparison:** [trust, contract fit, migration/failure radius, maintenance/runtime cost, fixture realism, rollback]
- **Falsifiable hypothesis / falsifier:** [claim and observation that rejects it]
- **Vertical experiment:** [one nominal path, one material failure, zero external effects]
- **Decision / allowed claim:** [selected option, rationale, rollback owner, unresolved evidence]
- **Stop/revert rules:** [conditions]

Validate a machine-readable declaration when one is maintained; the validator
checks structure and trigger arithmetic, not truth or completion.

## Errors Encountered

Record each distinct error, the attempt number, and the resolution. Change the approach before retrying a failed action.

| Error | Attempt | Resolution |
|-------|---------|------------|
|       | 1       |            |

## Notes

- Update phase status as work progresses: `pending` to `in_progress` to `complete`.
- Re-read the goal and next step before major decisions.
- Log errors promptly so failed approaches are not repeated.
