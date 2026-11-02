# Calculation validation acceptance v1 — frozen before aggregate execution

Date: 2026-10-31. Owner: coordinator. Specialist numerical domains, cases,
reference algorithms and tolerances are frozen in the three adjacent protocols.
Any later correction or criterion change retains the original result as a tried
variant; it is not relabeled as a first-pass success.

## Required deliverables
1. Independently computed reference checks, relevant numeric boundaries and a
   bounded workload stress case for valuation, options/surfaces and paths/replay.
2. At least one freshly acquired public sample per suite with URL, retrieval and
   data-as-of dates, units, content hash and extraction lineage. A current retrieval
   of dated prices/filings must be labeled as such. Public facts validate inputs;
   forecasts, discount assumptions, physical probabilities and model prices remain
   explicitly conditional. Two hosts publishing one filing are not independent facts.
3. Public acquisition and offline computation are separate. Workers receive no
   account credentials or private reports. No outbound network during calculation;
   verify blocked network and blocked private-account reads with synthetic probes.
4. Report observed defects, unsupported domains, skipped checks and evidence gaps
   distinctly. No default equal-NaN success, hidden zero substitution, changed
   tolerance after results or averaging away a critical failure.
5. Source/protocol/sample/environment fingerprints bind aggregate evidence. A real
   future-triggered Codex session runs the assembled checks and reports the actual
   verdict. A supervisor may send the acceptance email after verification; that is
   labeled as supervisor-sent and cannot prove a scheduled child sent mail itself.

## Bounds and verdicts
- Worker wall-time cap: 180 seconds per suite; retained output capped at 2 MiB.
- Sample files and result directories remain under .job-runtime/calculation/.
- Candidate legacy copies remain byte-identical. Fixes, if justified, are separate
  maintained operators and compared with the frozen baseline/counterexample.
- A suite pass requires all its declared required checks, valid evidence and
  no unresolved numerical failure. Missing live acquisition is unverified public
  sample evidence, even if synthetic checks pass. A completed test harness that
  reports a failure is not an accepted calculator.
- Scheduled orchestration acceptance and numerical/operator acceptance are
  separate fields. Final status cannot become full pass through model self-report.
- No production imports, trading, recurring allocation, new consent or credential
  refresh is part of this validation. No claim of calibration/alpha or universal
  numerical correctness follows from this finite development campaign.

## Scheduled request bridge after observed host restriction

The first two scheduled attempts remain failures. A real diagnostic confirmed
macOS rejects sandbox_apply inside Codex's existing seatbelt shell sandbox.
The scheduled session therefore invokes the fixed calculation client: it writes
an attempt/source-bound request and waits while the existing scheduler host runs
the original offline OS-restricted workers. This is a computation-tool boundary,
not precomputation presented as Codex work. No always-on service, network socket,
new auth or approval bypass is introduced. The host retains its result digest in
memory for independent completion verification. Coordinator criteria stay outside
the model's writable directory. Numeric criteria and OS worker denies are unchanged.

Codex's final writable grant is only the request inbox. Reports, response files,
source captures, environment and coordinator declarations are outside that grant.
The host reads requests through anchored no-follow descriptors and binds result
digests from in-memory report bytes; file rereads do not establish authenticity.
