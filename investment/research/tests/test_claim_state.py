from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from investment.research.claim_state import (
    MAX_INPUT_BYTES,
    ClaimStateError,
    atomic_write_json,
    authorize_use,
    canonical_sha256,
    loads_strict,
    seal_record,
    validate_claim_state,
)


CUTOFF = "2026-11-06T00:00:00Z"
AVAILABLE = "2026-11-05T00:00:00Z"
REVIEWED = "2026-11-08T01:00:00Z"
CONTENT = "The filing states that audited revenue increased by ten percent."
QUOTE = "audited revenue increased by ten percent"
_DEFAULT = object()


def evidence(evidence_id="evidence-1", relationship="supports", **changes):
    start = CONTENT.index(QUOTE)
    row = {
        "evidence_id": evidence_id,
        "collector_id": "collector-1",
        "source_id": "source-1",
        "source_version": "version-2",
        "current_version": "version-2",
        "available_at": AVAILABLE,
        "content": CONTENT,
        "quote": QUOTE,
        "quote_start": start,
        "quote_end": start + len(QUOTE),
        "relationship": relationship,
        "admissible": True,
        "assessable": True,
        "applicable": True,
    }
    row.update(changes)
    return row


def record(state="supported", *, rows=None, access=None, disposition=_DEFAULT,
           reasons=None, uses=None, atomicity="atomic", reviewed_at=REVIEWED,
           author_id="claim-author", operator_id="live-operator",
           reviewer_id="independent-reviewer"):
    if rows is None:
        rows = [evidence(relationship=(
            "contradicts" if state == "unsupported" else "supports"))]
    if access is None:
        access = [{"source_id": "source-1", "status": "content"}]
    if disposition is _DEFAULT:
        disposition = "contradiction" if state == "unsupported" else "approve"
    if reasons is None:
        reasons = []
    if uses is None:
        uses = {
            "supported": ["report_candidate"],
            "unsupported": ["opposing_evidence"],
            "unverifiable": ["gap"],
        }[state]
    review = None if disposition is None else {
        "reviewer_id": reviewer_id,
        "disposition": disposition,
        "rationale": "The exact bound passage was independently assessed.",
        "reviewed_at": reviewed_at,
    }
    return seal_record({
        "schema_version": 1,
        "state": state,
        "claim": {
            "id": "revenue-growth",
            "text": "Audited revenue increased by ten percent.",
            "author_id": author_id,
            "atomicity": atomicity,
        },
        "cutoff": CUTOFF,
        "operator_id": operator_id,
        "access": access,
        "evidence": rows,
        "review": review,
        "reason_codes": reasons,
        "requested_uses": uses,
    })


class ClaimStateTests(unittest.TestCase):
    def test_valid_each_state_and_state_projection(self):
        supported = validate_claim_state(record())
        unsupported = validate_claim_state(record("unsupported"))
        unverifiable = validate_claim_state(record(
            "unverifiable", rows=[],
            access=[{"source_id": "source-1", "status": "missing"}],
            disposition=None, reasons=["missing", "no_relevant_evidence"], uses=["gap"],
        ))
        self.assertEqual(supported["state"], "supported")
        self.assertEqual(supported["allowed_uses"], ["report_candidate"])
        self.assertEqual(unsupported["allowed_uses"], ["opposing_evidence"])
        self.assertEqual(unverifiable["allowed_uses"], ["gap"])
        self.assertTrue(all(row["source_access_separate"]
                            for row in (supported, unsupported, unverifiable)))
        self.assertTrue(all(row["validation_scope"] == "structural_only"
                            for row in (supported, unsupported, unverifiable)))
        self.assertTrue(all(row["authenticity_verified"] is False
                            for row in (supported, unsupported, unverifiable)))
        self.assertTrue(all(row["consequential_authority"] is False
                            for row in (supported, unsupported, unverifiable)))

    def test_missing_evidence_is_never_unsupported(self):
        candidate = record(
            "unsupported", rows=[],
            access=[{"source_id": "source-1", "status": "missing"}],
            disposition="reject", uses=[],
        )
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_CONTRADICTORY_EVIDENCE_REQUIRED"):
            validate_claim_state(candidate)

    def test_zero_text_source_cannot_support(self):
        candidate = record(
            "supported", rows=[],
            access=[{"source_id": "source-1", "status": "zero_text"}],
            disposition="approve", uses=[],
        )
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_CONTENT_SOURCE_REQUIRED"):
            validate_claim_state(candidate)

    def test_reviewer_must_be_independent(self):
        candidate = record()
        candidate["review"]["reviewer_id"] = "claim-author"
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_REVIEWER_NOT_INDEPENDENT"):
            validate_claim_state(candidate)

    def test_quote_and_hash_binding_must_match(self):
        candidate = record()
        candidate["evidence"][0]["quote_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_QUOTE_HASH_MISMATCH"):
            validate_claim_state(candidate)
        bad_slice = evidence(quote_start=0, quote_end=len(QUOTE))
        candidate = record(rows=[bad_slice])
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_QUOTE_BINDING_MISMATCH"):
            validate_claim_state(candidate)

    def test_stale_source_cannot_support(self):
        candidate = record(rows=[evidence(
            source_version="version-1", current_version="version-2")])
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_CONTENT_SOURCE_REQUIRED"):
            validate_claim_state(candidate)

    def test_unresolved_conflicting_support_is_not_supported(self):
        candidate = record(rows=[
            evidence("support", "supports"),
            evidence("contrary", "contradicts", collector_id="collector-2"),
        ])
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_UNRESOLVED_CONFLICT"):
            validate_claim_state(candidate)

    def test_composite_claim_requires_explicit_split(self):
        candidate = record(atomicity="composite")
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_COMPOSITE_REQUIRES_SPLIT"):
            validate_claim_state(candidate)

    def test_no_evidence_state_authorizes_consequential_use(self):
        consequential = (
            "affirmative_conclusion", "model_input", "affirmative_probability",
            "affirmative_action", "affirmative_sizing", "affirmative_alert",
        )
        candidates = [
            record("supported", uses=[]),
            record("unsupported", uses=[]),
            record(
                "unverifiable", rows=[],
                access=[{"source_id": "source-1", "status": "missing"}],
                disposition=None, reasons=["missing", "no_relevant_evidence"], uses=[],
            ),
        ]
        for candidate in candidates:
            for use in consequential:
                with self.subTest(state=candidate["state"], use=use):
                    with self.assertRaisesRegex(
                            ClaimStateError, "CLAIM_STATE_USE_FORBIDDEN"):
                        authorize_use(candidate, use)
        authorize_use(record("supported", uses=["report_candidate"]),
                      "report_candidate")
        authorize_use(record("unsupported", uses=["opposing_evidence"]),
                      "opposing_evidence")
        authorize_use(record(
            "unverifiable", rows=[],
            access=[{"source_id": "source-1", "status": "missing"}],
            disposition=None, reasons=["missing", "no_relevant_evidence"],
            uses=["gap"],
        ), "gap")

    def test_forged_principals_and_self_sealed_evidence_remain_structural_only(self):
        forged = record(
            rows=[evidence(collector_id="attacker-collector")],
            uses=["report_candidate"],
            author_id="attacker-author",
            operator_id="attacker-operator",
            reviewer_id="attacker-reviewer",
        )
        projection = validate_claim_state(forged)
        self.assertEqual(projection["status"], "valid")
        self.assertEqual(projection["allowed_uses"], ["report_candidate"])
        self.assertEqual(projection["validation_scope"], "structural_only")
        self.assertFalse(projection["authenticity_verified"])
        self.assertFalse(projection["consequential_authority"])
        self.assertEqual(
            forged["evidence"][0]["claim_sha256"], forged["claim"]["sha256"]
        )
        self.assertEqual(
            forged["review"]["evidence_sha256"],
            canonical_sha256([forged["evidence"][0]["binding_sha256"]]),
        )
        for use in (
            "affirmative_conclusion", "model_input", "affirmative_probability",
            "affirmative_action", "affirmative_sizing", "affirmative_alert",
        ):
            with self.subTest(use=use), self.assertRaisesRegex(
                    ClaimStateError, "CLAIM_STATE_USE_FORBIDDEN"):
                authorize_use(forged, use)

    def test_excluded_contrary_evidence_is_disclosed_without_becoming_unsupported(self):
        rows = [
            evidence("support", "supports"),
            evidence("stale", "contradicts", source_version="version-1"),
            evidence("future", "contradicts", available_at="2026-11-07T00:00:00Z"),
            evidence("inapplicable", "contradicts", applicable=False),
            evidence("inadmissible", "contradicts", admissible=False),
            evidence("gated", "contradicts", source_id="source-gated"),
            evidence("zero-text", "contradicts", source_id="source-zero"),
        ]
        access = [
            {"source_id": "source-1", "status": "content"},
            {"source_id": "source-gated", "status": "gated"},
            {"source_id": "source-zero", "status": "zero_text"},
        ]
        projection = validate_claim_state(record(rows=rows, access=access))
        self.assertEqual(projection["state"], "supported")
        self.assertTrue(projection["has_excluded_gap_inputs"])
        excluded = {
            row["evidence_id"]: row["reasons"]
            for row in projection["excluded_evidence"]
        }
        self.assertEqual(excluded, {
            "stale": ["stale"],
            "future": ["future"],
            "inapplicable": ["inapplicable"],
            "inadmissible": ["inadmissible"],
            "gated": ["gated"],
            "zero-text": ["zero_text"],
        })

    def test_unverifiable_reasons_are_complete_ordered_and_cover_no_evidence(self):
        cases = [
            (
                "content-no-evidence", [],
                [{"source_id": "source-1", "status": "content"}],
                ["no_relevant_evidence"],
            ),
            (
                "future", [evidence(available_at="2026-11-07T00:00:00Z")],
                [{"source_id": "source-1", "status": "content"}],
                ["future", "no_relevant_evidence"],
            ),
            (
                "inadmissible-unassessable",
                [evidence("inadmissible", admissible=False),
                 evidence("unassessable", assessable=False)],
                [{"source_id": "source-1", "status": "content"}],
                ["inadmissible", "unassessable", "no_relevant_evidence"],
            ),
            (
                "mixed-stale-inapplicable",
                [evidence("stale", source_version="version-1"),
                 evidence("inapplicable", applicable=False)],
                [{"source_id": "source-1", "status": "content"}],
                ["stale", "inapplicable", "no_relevant_evidence"],
            ),
        ]
        for name, rows, access, reasons in cases:
            with self.subTest(name=name):
                projection = validate_claim_state(record(
                    "unverifiable", rows=rows, access=access,
                    disposition=None, reasons=reasons, uses=["gap"],
                ))
                self.assertEqual(projection["state"], "unverifiable")
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_UNVERIFIABLE_REASONS_MISMATCH"):
            validate_claim_state(record(
                "unverifiable", rows=[],
                access=[{"source_id": "source-1", "status": "content"}],
                disposition=None, reasons=["missing"], uses=[],
            ))

    def test_eligible_evidence_without_conclusive_review_is_unverifiable(self):
        projection = validate_claim_state(record(
            "unverifiable", disposition=None, reasons=["missing_review"],
            uses=["gap"],
        ))
        self.assertEqual(projection["state"], "unverifiable")

    def test_review_must_be_at_or_after_cutoff(self):
        candidate = record(reviewed_at="2026-11-05T12:00:00Z")
        with self.assertRaisesRegex(ClaimStateError, "CLAIM_STATE_REVIEW_STALE"):
            validate_claim_state(candidate)

    def test_exact_types_surrogates_and_depth_fail_with_stable_errors(self):
        candidate = record()
        candidate["schema_version"] = True
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_SCHEMA_VERSION_INVALID"):
            validate_claim_state(candidate)
        candidate = record()
        candidate["reason_codes"] = [[]]
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_REASON_CODES_INVALID"):
            validate_claim_state(candidate)
        candidate = record()
        candidate["requested_uses"] = [{}]
        with self.assertRaisesRegex(ClaimStateError, "CLAIM_STATE_USES_INVALID"):
            validate_claim_state(candidate)
        with self.assertRaisesRegex(ClaimStateError, "CLAIM_STATE_JSON_SURROGATE"):
            loads_strict('"\ud800"')
        with self.assertRaisesRegex(ClaimStateError, "CLAIM_STATE_JSON_(DEPTH|INVALID)"):
            loads_strict("[" * 1000 + "0" + "]" * 1000)
        bad = {
            "schema_version": 1, "state": "supported",
            "claim": {"id": "x", "text": "\ud800", "author_id": "a",
                      "atomicity": "atomic"},
            "cutoff": CUTOFF, "operator_id": "o", "access": [],
            "evidence": [], "review": None, "reason_codes": [],
            "requested_uses": [],
        }
        with self.assertRaisesRegex(ClaimStateError, "CLAIM_STATE_JSON_SURROGATE"):
            seal_record(bad)

    def test_post_replace_failures_are_durability_unknown_not_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            target = Path(temporary) / "result.json"
            target.write_text('{"old":true}\n')
            real_replace = os.replace

            def replace_then_raise(source, destination):
                real_replace(source, destination)
                raise OSError("synthetic post-effect failure")

            with mock.patch(
                    "investment.research.claim_state.os.replace",
                    side_effect=replace_then_raise):
                with self.assertRaisesRegex(
                        ClaimStateError, "CLAIM_STATE_OUTPUT_DURABILITY_UNKNOWN"):
                    atomic_write_json(target, {"new": True})
            self.assertEqual(json.loads(target.read_text()), {"new": True})

            calls = 0
            real_fsync = os.fsync

            def fail_parent_fsync(descriptor):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic parent fsync failure")
                return real_fsync(descriptor)

            with mock.patch(
                    "investment.research.claim_state.os.fsync",
                    side_effect=fail_parent_fsync):
                with self.assertRaisesRegex(
                        ClaimStateError, "CLAIM_STATE_OUTPUT_DURABILITY_UNKNOWN"):
                    atomic_write_json(target, {"newer": True})
            self.assertEqual(json.loads(target.read_text()), {"newer": True})

    def test_strict_json_rejects_duplicate_and_nonfinite_values(self):
        with self.assertRaisesRegex(
                ClaimStateError, "CLAIM_STATE_JSON_DUPLICATE_KEY"):
            loads_strict('{"state":"supported","state":"unsupported"}')
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                with self.assertRaisesRegex(
                        ClaimStateError, "CLAIM_STATE_JSON_NONFINITE"):
                    loads_strict('{"value":' + literal + '}')

    def test_cli_success_is_atomic_and_failure_preserves_previous_output(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            temporary = Path(temporary)
            input_path = temporary / "input.json"
            output_path = temporary / "output.json"
            input_path.write_text(json.dumps(record(), allow_nan=False))
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            command = [
                sys.executable, "-m", "investment.research.claim_state", "validate",
                "--input", str(input_path), "--output", str(output_path),
            ]
            passed = subprocess.run(
                command, cwd=root, env=environment, capture_output=True, text=True,
                check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertEqual(json.loads(output_path.read_text())["status"], "valid")

            sentinel = b"previous-complete-output\n"
            output_path.write_bytes(sentinel)
            input_path.write_text('{"state":"supported","state":"unsupported"}')
            failed = subprocess.run(
                command, cwd=root, env=environment, capture_output=True, text=True,
                check=False,
            )
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(output_path.read_bytes(), sentinel)
            self.assertEqual(
                json.loads(failed.stdout),
                {"status": "failed", "code": "CLAIM_STATE_JSON_DUPLICATE_KEY"},
            )
            input_path.write_text("[" * 1000 + "0" + "]" * 1000)
            deep = subprocess.run(
                command, cwd=root, env=environment, capture_output=True, text=True,
                check=False,
            )
            self.assertEqual(deep.returncode, 2)
            self.assertEqual(output_path.read_bytes(), sentinel)
            self.assertRegex(
                json.loads(deep.stdout)["code"],
                r"^CLAIM_STATE_JSON_(DEPTH|INVALID)$",
            )

            # A sparse oversized file proves the CLI rejects from regular-file
            # metadata/bounded I/O rather than allocating the complete payload.
            with input_path.open("wb") as stream:
                stream.truncate(MAX_INPUT_BYTES + 1)
            oversized = subprocess.run(
                command, cwd=root, env=environment, capture_output=True, text=True,
                check=False,
            )
            self.assertEqual(oversized.returncode, 2)
            self.assertEqual(output_path.read_bytes(), sentinel)
            self.assertEqual(
                json.loads(oversized.stdout),
                {"status": "failed", "code": "CLAIM_STATE_INPUT_LIMIT"},
            )


if __name__ == "__main__":
    unittest.main()
