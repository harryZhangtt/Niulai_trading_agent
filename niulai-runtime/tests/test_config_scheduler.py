import copy
from datetime import datetime, date
import json
from pathlib import Path
import tempfile
import unittest

from niulai_runtime.config import ConfigError, assert_recipient, load_config, validate_config
from niulai_runtime.scheduler import CutoverEvidence, admit


class FixtureCalendar:
    """Explicit synthetic session inventory; not an exchange calendar."""
    name = "XNYS"
    def is_session(self, day):
        return day in {date(2026, 10, 30), date(2026, 11, 2)}


class ConfigSchedulerTests(unittest.TestCase):
    def setUp(self):
        # Every task-created file stays inside the workspace.
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.state = self.workspace / ".niulai-state"
        self.state.mkdir(mode=0o700)
        self.raw = {
            "schema_version": 1, "mode": "dry_run", "recipient": "fixture@example.com",
            "automation_id": "fixture-automation", "scheduler_owner": "fixture-runtime",
            "production_enabled": False, "state_directory": ".niulai-state",
            "schedule": {"timezone": "America/New_York", "slots": ["13:00", "19:00"],
                         "grace_minutes": 60, "calendar": "XNYS"}}
        self.calendar = FixtureCalendar()

    def config(self, **overrides):
        return validate_config(dict(self.raw, **overrides), self.workspace)

    def admit(self, when="2026-10-30T17:00:00+00:00", **kwargs):
        return admit(kwargs.pop("config", self.config()), datetime.fromisoformat(when),
                     kwargs.pop("calendar", self.calendar), "fixture-runtime", **kwargs)

    def test_private_config_load(self):
        path = self.state / "runtime.json"
        path.write_text(json.dumps(self.raw)); path.chmod(0o600)
        self.assertEqual(load_config(path, self.workspace).recipient, "fixture@example.com")

    def test_world_readable_config_rejected(self):
        path = self.state / "runtime.json"
        path.write_text(json.dumps(self.raw)); path.chmod(0o644)
        with self.assertRaisesRegex(ConfigError, "PERMISSIONS"):
            load_config(path, self.workspace)

    def test_duplicate_json_keys_rejected(self):
        path = self.state / "runtime.json"
        path.write_text('{"mode":"dry_run","mode":"production"}'); path.chmod(0o600)
        with self.assertRaisesRegex(ConfigError, "DUPLICATE"):
            load_config(path, self.workspace)

    def test_symlink_state_rejected(self):
        self.state.rmdir()
        target = self.workspace / "other"
        target.mkdir(mode=0o700)
        self.state.symlink_to(target)
        with self.assertRaisesRegex(ConfigError, "ESCAPE"):
            self.config()

    def test_config_outside_private_root_rejected(self):
        path = self.workspace / "runtime.json"
        path.write_text(json.dumps(self.raw)); path.chmod(0o600)
        with self.assertRaisesRegex(ConfigError, "OUTSIDE"):
            load_config(path, self.workspace)

    def test_fixed_schedule_and_unknown_keys(self):
        for key, value in (("timezone", "UTC"), ("slots", ["12:00"]),
                           ("grace_minutes", True), ("calendar", "weekdays")):
            raw = copy.deepcopy(self.raw); raw["schedule"][key] = value
            with self.subTest(key=key), self.assertRaises(ConfigError):
                validate_config(raw, self.workspace)
        with self.assertRaisesRegex(ConfigError, "KEYS"):
            self.config(allow_trade=True)

    def test_email_injection_and_alias_rejected(self):
        for recipient in ("fixture@example.com\nBcc: other@example.com", "a@b.com,c@d.com",
                          "REPLACE", "owner@example.invalid"):
            with self.subTest(recipient=recipient), self.assertRaises(ConfigError):
                self.config(recipient=recipient)
        with self.assertRaisesRegex(ConfigError, "IDENTITY"):
            assert_recipient(self.config(), "other@example.com", "fixture@example.com")
        with self.assertRaisesRegex(ConfigError, "RECIPIENT"):
            assert_recipient(self.config(), "fixture@example.com", "fixture+alias@example.com")

    def test_dst_changes_utc_hour_without_changing_ny_slot(self):
        before = self.admit("2026-10-30T17:00:00+00:00")
        after = self.admit("2026-11-02T18:00:00+00:00")
        self.assertTrue(before.allowed and after.allowed)
        self.assertEqual((before.slot, after.slot), ("13:00", "13:00"))
        self.assertFalse(self.admit("2026-11-02T17:00:00+00:00").allowed)

    def test_grace_boundary(self):
        self.assertTrue(self.admit("2026-10-30T18:00:00+00:00").allowed)
        self.assertFalse(self.admit("2026-10-30T18:00:00.000001+00:00").allowed)
        self.assertFalse(self.admit("2026-10-30T16:59:59+00:00").allowed)

    def test_holiday_and_weekend_require_calendar(self):
        for when in ("2026-10-31T17:00:00+00:00", "2026-11-26T18:00:00+00:00"):
            self.assertEqual(self.admit(when).reason, "NOT_XNYS_SESSION")

    def test_calendar_missing_or_failure_is_not_weekday_success(self):
        self.assertEqual(self.admit(calendar=None).reason, "XNYS_CALENDAR_REQUIRED")
        class Unavailable:
            name = "XNYS"
            def is_session(self, day):
                raise RuntimeError("secret provider details")
        self.assertEqual(self.admit(calendar=Unavailable()).reason, "CALENDAR_UNAVAILABLE")

    def test_production_requires_enablement_and_external_cutover_receipts(self):
        disabled = self.config(mode="production")
        self.assertEqual(self.admit(config=disabled).reason, "PRODUCTION_DISABLED")
        enabled = self.config(mode="production", production_enabled=True)
        self.assertEqual(self.admit(config=enabled).reason, "CUTOVER_EVIDENCE_REQUIRED")
        result = self.admit(config=enabled, cutover=CutoverEvidence(
            "synthetic-disabled-receipt", "synthetic-import-receipt", "fixture-runtime"))
        self.assertTrue(result.send_allowed)

    def test_manual_request_cannot_complete_production_slot(self):
        config = self.config(mode="manual_test")
        result = self.admit(config=config, manual_request_id="synthetic-test-1")
        self.assertIsNone(result.slot)
        self.assertTrue(result.send_allowed)
        self.assertTrue(result.delivery_key.startswith("manual-email:"))
        tomorrow = self.admit("2026-11-02T18:00:00+00:00", config=config,
                              manual_request_id="synthetic-test-1")
        self.assertEqual(result.delivery_key, tomorrow.delivery_key)
        self.assertEqual(self.admit(config=config, manual_request_id="synthetic-test-1",
                                   completed_keys=[result.delivery_key]).reason,
                         "DELIVERY_ALREADY_RECORDED")

    def test_dry_run_has_no_send_permission(self):
        result = self.admit()
        self.assertTrue(result.allowed)
        self.assertFalse(result.send_allowed)
        self.assertEqual(self.admit(completed_keys=[result.delivery_key]).reason,
                         "DELIVERY_ALREADY_RECORDED")

    def test_clock_and_owner_fail_closed(self):
        self.assertEqual(self.admit("2026-10-30T13:00:00").reason, "AWARE_CLOCK_REQUIRED")
        self.assertEqual(admit(self.config(), datetime.fromisoformat("2026-10-30T17:00:00+00:00"),
                               self.calendar, "another-runtime").reason, "SCHEDULER_OWNER_MISMATCH")


if __name__ == "__main__":
    unittest.main()
