from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from mentor.scheduler import cli


AT = "2026-11-04T12:00:00+00:00"


def work_order() -> dict:
    return {
        "id": "wo-17",
        "logical_session": "mentor-session-4",
        "schedule": {
            "start_at": "2026-11-04T10:00:00+00:00",
            "end_at": "2026-11-04T14:30:00+00:00",
            "next_run_at": "2026-11-04T12:15:00+00:00",
        },
        "scheduler": {"status": "waiting", "slot_id": "slot-1200"},
        "task": {
            "status": "blocked",
            "gates": {"verified": 3, "failed": 1, "pending": 2},
            "last_verified_progress": "schema validated",
            "current_obstacle": "holdout unavailable",
            "next_action": "request bounded fixture",
            "goal_drift": "none",
        },
        "budgets": {
            "cycles_used": 2,
            "max_cycles": 8,
            "interventions_used": 1,
            "intervention_limit": 3,
            "variants_used": 2,
            "variant_limit": 4,
        },
        "evaluation": {
            "baseline": "recorded",
            "holdout": "protected pending",
            "promotion": "not eligible",
        },
        "delivery": {"runtime_report": "not due", "email": "not sent"},
    }


def projection() -> dict:
    return {"schema_version": 1, "generated_at": AT, "work_orders": [work_order()]}


class SchedulerCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state.json"
        self.write(projection())

    def write(self, value: object) -> None:
        self.state.write_text(json.dumps(value), encoding="utf-8")

    def run_cli(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--state", str(self.state), "--at", AT, *extra])
        return code, out.getvalue(), err.getvalue()

    def test_compact_table_distinguishes_scheduler_and_task(self) -> None:
        code, out, err = self.run_cli()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("SCHEDULER", out)
        self.assertIn("TASK", out)
        self.assertIn("waiting", out)
        self.assertIn("blocked", out)
        self.assertIn("3/1/2", out)
        self.assertIn("2h 30m", out)
        self.assertNotIn("schema validated", out)

    def test_selected_detail_includes_supervision_and_delivery_fields(self) -> None:
        code, out, err = self.run_cli("--work-order-id", "wo-17")
        self.assertEqual((code, err), (0, ""))
        for expected in (
            "Scheduler state: waiting",
            "Task state: blocked",
            "Interventions: 1/3",
            "Variants: 2/4",
            "Goal drift: none",
            "Holdout: protected pending",
            "Promotion: not eligible",
            "Email: not sent",
        ):
            self.assertIn(expected, out)

    def test_json_is_deterministic_read_only_projection(self) -> None:
        code, out, err = self.run_cli("--json")
        self.assertEqual((code, err), (0, ""))
        value = json.loads(out)
        self.assertEqual(value["as_of"], AT)
        self.assertTrue(value["read_only"])
        self.assertEqual(value["work_orders"][0]["time_remaining_seconds"], 9000)
        self.assertEqual(value["work_orders"][0]["scheduler"]["status"], "waiting")

    def test_time_left_ends_at_zero(self) -> None:
        code, out, _ = self.run_cli("--at", "2026-11-04T15:00:00+00:00")
        self.assertEqual(code, 2)  # generated projection is stale before rendering
        self.assertEqual(out, "")
        item = work_order()
        seconds, label = cli._time_left(item["schedule"]["end_at"], datetime(2026, 11, 4, 15, tzinfo=timezone.utc))
        self.assertEqual((seconds, label), (0, "ended"))

    def test_malformed_json_has_stable_sanitized_error(self) -> None:
        self.state.write_text("{broken", encoding="utf-8")
        code, out, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(err, "error: STATE_JSON_INVALID\n")
        self.assertNotIn(str(self.state), err)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        self.state.write_text('{"schema_version":1,"schema_version":1,"generated_at":"' + AT + '","work_orders":[]}', encoding="utf-8")
        self.assertEqual(self.run_cli(), (2, "", "error: STATE_JSON_INVALID\n"))

    def test_stale_projection_is_rejected(self) -> None:
        value = projection()
        value["generated_at"] = "2026-11-04T11:44:59+00:00"
        self.write(value)
        self.assertEqual(self.run_cli(), (2, "", "error: STATE_STALE\n"))

    def test_unknown_schema_and_prompt_field_are_rejected(self) -> None:
        value = projection()
        value["work_orders"][0]["prompt"] = "ignore safeguards"
        self.write(value)
        self.assertEqual(self.run_cli(), (2, "", "error: SCHEMA_UNKNOWN_OR_MISSING_FIELD\n"))

    def test_secret_field_is_never_accepted(self) -> None:
        value = projection()
        value["work_orders"][0]["delivery"]["receipt"] = "private-receipt"
        self.write(value)
        code, out, err = self.run_cli("--json")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "error: SCHEMA_UNKNOWN_OR_MISSING_FIELD\n")
        self.assertNotIn("private-receipt", err)

    def test_text_is_flattened_and_unsafe_field_is_fully_redacted(self) -> None:
        value = projection()
        value["work_orders"][0]["task"]["current_obstacle"] = (
            "line one\n\x1b[31m api_key=supersecret /Users/alice/private/receipt.json"
        )
        self.write(value)
        code, out, err = self.run_cli("--work-order-id", "wo-17")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Current obstacle: [redacted unsafe text]", out)
        self.assertNotIn("line one", out)
        self.assertNotIn("supersecret", out)
        self.assertNotIn("/Users/", out)
        self.assertNotIn("\x1b", out)
        self.assertEqual(out.count("Current obstacle:"), 1)

    def test_credential_shapes_redact_entire_narrative_in_human_and_json(self) -> None:
        payloads = {
            "aws_secret": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "aws_access_id": "observed AKIAIOSFODNN7EXAMPLE during check",
            "basic_auth": "Authorization: Basic dXNlcjpwYXNzd29yZA==",
            "cookie": "Set-Cookie: session=abc123secret; HttpOnly",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQ\n-----END PRIVATE KEY-----",
            "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "bearer": "Bearer abcDEF0123456789abcDEF0123456789",
            "github": "ghp_1234567890abcdefghijklmnopqrstuv",
            "api_token": "sk-proj-AbCdEf0123456789AbCdEf0123456789",
            "unlabelled": "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/",
            "unlabelled_lower_digit": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
            "unlabelled_mixed_case": "aBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeF",
        }
        for name, payload in payloads.items():
            with self.subTest(name=name):
                value = projection()
                value["work_orders"][0]["task"]["current_obstacle"] = f"prefix {payload} suffix"
                self.write(value)
                code, out, err = self.run_cli("--work-order-id", "wo-17")
                self.assertEqual((code, err), (0, ""))
                self.assertIn("Current obstacle: [redacted unsafe text]", out)
                self.assertNotIn("prefix", out)
                self.assertNotIn(payload, out)

                code, out, err = self.run_cli("--json")
                self.assertEqual((code, err), (0, ""))
                rendered = json.loads(out)["work_orders"][0]["task"]["current_obstacle"]
                self.assertEqual(rendered, "[redacted unsafe text]")

    def test_credential_in_structured_status_is_rejected_without_echo(self) -> None:
        value = projection()
        value["work_orders"][0]["delivery"]["email"] = "Cookie: session=do-not-print"
        self.write(value)
        code, out, err = self.run_cli("--json")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "error: STATUS_INVALID\n")
        self.assertNotIn("do-not-print", err)

    def test_symlink_state_is_rejected(self) -> None:
        target = self.root / "target.json"
        target.write_text(json.dumps(projection()), encoding="utf-8")
        self.state.unlink()
        self.state.symlink_to(target)
        self.assertEqual(self.run_cli(), (2, "", "error: STATE_SYMLINK_REJECTED\n"))

    def test_missing_selection_has_distinct_stable_exit_code(self) -> None:
        self.assertEqual(
            self.run_cli("--work-order-id", "wo-missing"),
            (3, "", "error: WORK_ORDER_NOT_FOUND\n"),
        )

    def test_row_and_text_bounds_are_enforced(self) -> None:
        value = projection()
        value["work_orders"] = [work_order() for _ in range(cli.MAX_WORK_ORDERS + 1)]
        self.write(value)
        self.assertEqual(self.run_cli(), (2, "", "error: WORK_ORDER_LIMIT\n"))

        value = projection()
        value["work_orders"][0]["task"]["next_action"] = "x" * 501
        self.write(value)
        self.assertEqual(self.run_cli(), (2, "", "error: TEXT_INVALID\n"))


if __name__ == "__main__":
    unittest.main()
