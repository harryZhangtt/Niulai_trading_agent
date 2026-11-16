---
name: progress-and-recovery
description: "Diagnose stalled investment-agent work and tool failures using the Superpowers four-phase systematic-debugging workflow; recover with evidence or report a precise external dependency."
license: MIT
metadata:
  version: "1.0"
---

## Workspace application

Read [Investment-agent context](references/investment-context.md) when applying this skill. This is a project-local adaptation of the pinned sources in [UPSTREAM.md](UPSTREAM.md). Its workflow and bundled resources are active through `mentor/AGENTS.md`; it is not a daemon.

# Progress recovery through systematic debugging

## Overview

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Manager wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully**
   - Don't skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible → gather more data, don't guess

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **Gather Evidence in Multi-Component Systems**

   **WHEN system has multiple components (CI → build → signing, API → service → database):**

   **BEFORE proposing fixes, add diagnostic instrumentation:**
   ```
   For EACH component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing WHERE it breaks
   THEN analyze evidence to identify failing component
   THEN investigate that specific component
   ```

   **Example (multi-layer system):**
   ```bash
   # Layer 1: Workflow
   echo "=== Secrets available in workflow: ==="
   echo "IDENTITY: $([ -n "${IDENTITY:-}" ] && echo SET || echo UNSET)"

   # Layer 2: Build script
   echo "=== Env vars in build script: ==="
   printenv IDENTITY >/dev/null 2>&1 && echo "IDENTITY in environment" || echo "IDENTITY not in environment"

   # Layer 3: Signing script
   echo "=== Keychain state: ==="
   security list-keychains
   security find-identity -v

   # Layer 4: Actual signing
   codesign --sign "$IDENTITY" --verbose=4 "$APP"
   ```

   **This reveals:** Which layer fails (secrets → workflow ✓, workflow → build ✗)

5. **Trace Data Flow**

   **WHEN error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that's similar to what's broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation COMPLETELY
   - Don't skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What's different between working and broken?
   - List every difference, however small
   - Don't assume "that can't matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis and Testing

**Scientific method:**

1. **Form Single Hypothesis**
   - State clearly: "I think X is the root cause because Y"
   - Write it down
   - Be specific, not vague

2. **Test Minimally**
   - Make the SMALLEST possible change to test hypothesis
   - One variable at a time
   - Don't fix multiple things at once

3. **Verify Before Continuing**
   - Did it work? Yes → Phase 4
   - Didn't work? Form NEW hypothesis
   - DON'T add more fixes on top

4. **When You Don't Know**
   - Say "I don't understand X"
   - Don't pretend to know
   - Ask for help
   - Research more

### Phase 4: Implementation

**Fix the root cause, not the symptom:**

1. **Create Failing Test Case**
   - Simplest possible reproduction
   - Automated test if possible
   - One-off test script if no framework
   - MUST have before fixing
   - For code defects, use a minimal reproducer or meaningful regression check; do not add tests for trivial reversible edits.

2. **Implement Single Fix**
   - Address the root cause identified
   - ONE change at a time
   - No "while I'm here" improvements
   - No bundled refactoring

3. **Verify Fix**
   - Test passes now?
   - No other tests broken?
   - Issue actually resolved?
   - Apply [verification-before-completion](../research-supervisor/references/verification-before-completion.md) before claiming recovery.

4. **If the fix does not work**
   - Preserve the failure and re-examine the hypothesis before another change.
   - Repeated fixes exposing shared state or coupling are evidence to review the architecture. A fixed attempt count is not proof of an architectural defect.
   - Continue independent authorized diagnosis within the task budget. Escalate only a concrete dependency that requires external action.

## Red Flags - STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **Another attempt without a changed hypothesis or new evidence**
- **Each fix reveals new problem in different place**

**ALL of these mean: STOP. Return to Phase 1.**

Repeated coupled failures justify architectural review; do not infer it from a numerical retry count alone.

## Deterministic architecture-research escalation

Count confirmed, deduplicated findings against one sealed candidate fingerprint and
declared owner/module set. A reopen is a finding declared closed and later
reconfirmed at the same contract boundary. Stop patch-by-patch work and open an
architecture decision when any condition holds:

1. one critical external-effect, trust, credential/path, duplicate-effect,
   unknown-outcome or recovery defect spans at least two modules or owners;
2. two high/critical findings share a root-cause class across at least two module
   boundaries in one review cycle;
3. four confirmed findings span at least three modules or two owners;
4. one critical reopen, one reopen of the same high-severity boundary, or two
   lower-severity reopens share a root cause;
5. two reviews/runs are invalidated by hash drift, stale worktrees, missing
   candidate files or competing writers; or
6. two high/critical real-shape or adversarial findings survive a declared green
   full suite.

On trigger, freeze outward effects, nominate one integration owner, seal candidate
hashes and producer/consumer schemas, classify the root cause, and compare
architecture before another fix. Required internal evidence is: a full sorted
candidate family (path, SHA-256, owner and module boundary), stable unique finding
IDs with deduplicated counters, a minimal reproducer or sanitized real-shape
fixture, producer and consumer schemas, a state/authority map, and the reopen
chronology. The candidate fingerprint is the SHA-256 of canonical candidate-family
JSON, not a label or truncated hash.

When the decision depends on external protocol, provider, filesystem, framework or
service semantics, also require one primary official source and one independent
authoritative implementation, incident analysis or counterexample. Record direct
URLs, primary/independent role, search/open route, source version/date,
relevant semantics, applicability limits and access date. A search snippet or
model answer is not evidence; a
sanitized intended-host event outranks a synthetic wire fixture.

Compare at least O0 (retain/revert and keep blocked), O1 (narrow repair at the
canonical owner) and O2 (consolidate one shared contract/state owner). Consider a
new service/framework only when O1/O2 fail a concrete requirement. Compare trust,
contract fit, migration/failure radius, maintenance/runtime cost, fixture realism
and rollback. The O0/O1/O2 table must explicitly compare trust, contract fit,
migration/failure radius, maintenance/runtime cost, fixture realism and rollback.
Then preregister one provider-free vertical experiment with an explicit falsifiable
hypothesis and falsifier, one real-shaped input, one nominal path, one material
failure and explicit identity, transition, fence/rollback and zero-external-effect
assertions.

Stop research once primary evidence resolves disputed semantics and one option
passes the experiment. Permit one research pass and one experiment per hypothesis;
a failed experiment needs a new hypothesis, not another layered patch. Revert on
path/secret escape, duplicate effect, unreconciled unknown, lost messaging or
candidate drift. If no option passes, keep the capability disabled.

Do not trigger this gate for a localized reproducible defect with a clear owner,
import/PYTHONPATH mistakes, stale test paths, formatting/plan syntax, a known
schema mismatch with the authoritative producer already available, emergency
rollback, missing credentials/authorization, documentation-only corrections, or
a case with no materially different architecture options. Web research never
substitutes for intended-runtime acceptance.

A task may store the declaration in JSON and validate it read-only with:

```bash
python3 mentor/skills/progress-and-recovery/scripts/validate_architecture_escalation.py record.json
```

The validator checks trigger arithmetic and required declaration fields only. It
never verifies truth, chooses an option, modifies files, blocks user prompts or
establishes completion.

## your human partner's Signals You're Doing It Wrong

**Watch for these redirections:**
- "Is that not happening?" - You assumed without verifying
- "Will it show us...?" - You should have added evidence gathering
- "Stop guessing" - You're proposing fixes without understanding
- "Ultra-think this" - Question fundamentals, not just symptoms
- "We're stuck?" (frustrated) - Your approach isn't working

**When you see these:** STOP. Return to Phase 1.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write test after confirming fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "One more fix attempt" | State what new evidence or changed condition makes it useful. |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Form theory, test minimally | Confirmed or new hypothesis |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |

## When Process Reveals "No Root Cause"

If systematic investigation reveals issue is truly environmental, timing-dependent, or external:

1. You've completed the process
2. Document what you investigated
3. Implement appropriate handling (retry, timeout, error message)
4. Add monitoring/logging for future investigation

An unresolved cause stays unresolved. Report which boundaries were tested and which remain inaccessible.

## Supporting Techniques

These techniques are part of systematic debugging and available in this directory:

- **`root-cause-tracing.md`** - Trace bugs backward through call stack to find original trigger
- **`defense-in-depth.md`** - Add validation at multiple layers after finding root cause
- **`condition-based-waiting.md`** - Replace arbitrary timeouts with condition polling
