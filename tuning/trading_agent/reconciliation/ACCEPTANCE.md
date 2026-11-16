# Frozen reconciliation verification contract

Status: FROZEN  
Revision: trading-reconciliation-v1.0  
Verification level: Balanced, offline worker boundary plus independent client controls and deliberate breaks. The level is inherited from the explicitly selected backend verification scope; no production/live layer is authorized here.

This packet is independent of the canonical Trading Agent acceptance packet. It covers only a diagnostic reconciliation path. It does not authorize credential acquisition, rotation, profile repair, lease release, replay, a new broker query, orders, email, scheduler work, deployment or activation.

Requirement sources: R1 owner task specifying exact recovered worker and original-ID diagnostic semantics; R2 owner client requirements supplied before helper implementation; R3 workspace/mentor/backend-testing instructions and preservation policy. Criteria were derived from these requirements before inspecting the recovered worker's body or any proposed diagnostic client.

Target worker: `.niulai-state/reports/trading-agent-smoke/53cbbf3b-1c8f-48c8-af34-f621bec276d6/owner-source-supported/.sites-checkout/worker/index.js`, supplied commit `ce58b639c137abda72f0bdea65118300355f4478`, file SHA256 `ed1b7a20b85b2444dd30039c94e67cc9594e6a7923c00b689b312b9193172ac0`. The hash was read without inspecting source content before freezing. All fixtures use synthetic IDs, authentication canaries and store state. Source execution must be isolated from network, real storage, credentials and private fences.

## Worker criteria

| ID | Preconditions / action | Required observable result | Forbidden result / cases |
| --- | --- | --- | --- |
| REC-W-001 | Synthetic store in absent, active, expired and last-commit states; GET `/health` | Read-only response; zero mutator calls and identical durable state, including after expiry | Lazy expiry cleanup, lease refresh, touched timestamp or profile mutation |
| REC-W-002 | Stored last_commit matches original commit_id AND lease_id; POST `/lease/checkpoint` with exactly those two fields | Can acknowledge the already matching last commit without any write or profile/release requirement; same diagnostic repeated/concurrent remains read-only | Ack requiring a new profile/release, overwrite, lease renewal or another checkpoint |
| REC-W-003 | Wrong/missing commit_id or lease_id, absent/malformed last_commit, active/expired/absent lease; diagnostic contains no profile or release | Cannot acknowledge a mismatching tuple as the original commit and cannot write; actual status/error semantics recorded | Matching only one ID, creating a commit, replacing profile, resetting lease/fence |
| REC-W-004 | Invalid body/method/authentication or storage read failure | No durable writes; failure stays distinguishable from matched commit acknowledgement | Success-shaped fallback, implicit credential/lease acquisition or raw-error claims promoted to proof |
| REC-W-005 | Isolated fake store only; replay an old acquire after its lease expired | Source demonstrably creates a new lease/effect; acquire is classified NOT READ-ONLY and excluded from the diagnostic route | Claiming old request_id guarantees permanent safe read-only replay after expiry |
| REC-W-006 | Run each fixture and deliberate break against the pinned worker | Exact source hash/identity recorded; real worker handler is exercised against an instrumented in-memory store, with writes trapped and state independently compared | Source-pattern-only proof, zero tests, fake passing control or modified recovered/production source |

## Client criteria, frozen before helper implementation

| ID | Preconditions / action | Required observable result | Forbidden result / cases |
| --- | --- | --- | --- |
| REC-C-001 | Synthetic fresh native Sites context and owner-private policy; correct and adversarial origin/project/audience/path cases | Existing validate_site/load_policy ownership validation is reused; validation occurs before dispatch | Invented credential owner, foreign endpoint, userinfo/redirect/base-URL override, context copied into arguments/environment/logs |
| REC-C-002 | Original synthetic fence/private profile; valid, absent, malformed and changed identities | Original fence is read/hashed only; lock held across diagnostic; original immutable commit_id and lease_id used | Caller substitutes new IDs, reset/delete/replace fence or profile, acquiring a new lease to inspect the old one |
| REC-C-003 | Injected transport captures all requests | Only GET `/health` and POST `/lease/checkpoint`; POST body exactly `{commit_id,lease_id}`, no profile/release/acquire | Any other route/method, extra secret/profile field, alternate recovery mutation |
| REC-C-004 | Success, timeout, malformed and permanent-error fake responses | At most one HTTP attempt per diagnostic operation, timeout <=15s, redirects forbidden, decoded response <=65536 bytes | Retry/fallback, redirect credential forwarding, unbounded body/time |
| REC-C-005 | Canary bearer and provider error/body fields | Closed-schema scalar diagnostic output only; allowlisted status/boolean/count/hash metadata, no bearer, raw remote error/body, profile or nested private store data | Arbitrary scalar echo, raw error interpolation, sensitive stdout/stderr/log/exception |
| REC-C-006 | Unknown fence and matching/nonmatching remote diagnostic replies | Matching response supports only original-commit recognition; unknown/local fence remains immutable; lease release/profile correctness/current authorization are not inferred | "Recovered/cleared" fence, "lease released" based solely on last_commit, another Tiger query or replay |
| REC-C-007 | Source fingerprint pinned; deployment readback prerequisite provided/injected | Reject missing/mismatched prerequisite before network; record exact source/bounds/outcome and preserve all failed attempts | Source drift silently accepted, successful deployment/GET described as broker/runtime acceptance |

## Evidence and omissions

Every criterion maps to executed IDs or NOT RUN with a reason. Count normal cases and deliberate breaks separately, preserve failed evidence, and compare state independently of the worker's return value. A fake acquire is permitted only inside the isolated in-memory fixture to discriminate a write-capable route; it is not a lease acquisition against any service. Live/native/production calls, private credentials/policy/fence contents, worker deployment, real lease acquisition and global changes are NOT RUN. Major future scheduled/business/email acceptance remains UNVERIFIED.

The client public function/output field names are not yet implemented. Fixed scalar output categories are frozen above; exact named response semantics will be recorded from the implementation without relaxing the no-secret/no-write constraints. Worker response status/body details not specified by R1 will be recorded as observed behavior rather than retroactively made into independent pre-inspection requirements.
