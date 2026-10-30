#!/usr/bin/env python3
import copy
import decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

import niulai_state as state


def alert(number=1, **changes):
    value = {"id": str(uuid.UUID(int=number)), "ticker": "SNPS", "direction": "below",
             "threshold": "395.850000000000000001", "enabled": True,
             "note": "中文价格线", "createdAt": "2026-10-18T00:00:00Z", "updatedAt": "2026-10-18T00:00:00Z"}
    value.update(changes)
    return value


class OrchestrationConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'config_revision': 9, 'alert_authority': 'niulai_saved_json_sqlite',
            'price_monitor': {'studio_dependency': False, 'engine': 'scripts/price_watch.py', 'buffer_fraction': '.005'},
            '_meta': {'user_timezone': 'Asia/Shanghai', 'session_timezone': 'America/New_York'},
            'schedules': [{'role': 'daily_triggered_research', 'enabled': True, 'automation_id': 'test-only'}],
            'research': {'daily_triggered_review': {
                'enabled': True, 'batch_size': 3, 'max_concurrency': 3,
                'read_original_documents': True, 'incremental_evidence_required': True,
                'allow_no_new_edge': True, 'automatic_trading': False, 'automatic_alert_edits': False,
                'orchestration_policy_version': '2026-10-20-native-ticker-1',
                'orchestration': {'engine': 'native_subagents', 'orchestrator': 'single_parent',
                                  'unit': 'ticker', 'max_active_ticker_pipelines': 3,
                                  'independent_review': True, 'shared_db_writer': 'orchestrator_only',
                                  'per_ticker_checkpoints': True}}}}

    def test_valid_native_orchestration(self):
        self.assertTrue(state.validate_config(self.config)['valid'])

    def test_old_policy_remains_valid(self):
        self.config['config_revision'] = 8
        policy = self.config['research']['daily_triggered_review']
        del policy['orchestration_policy_version']; del policy['orchestration']
        self.assertTrue(state.validate_config(self.config)['valid'])

    def test_versioned_policy_requires_orchestration(self):
        del self.config['research']['daily_triggered_review']['orchestration']
        with self.assertRaises(state.StateError): state.validate_config(self.config)

    def test_concurrency_is_bounded_and_not_boolean(self):
        policy = self.config['research']['daily_triggered_review']
        for value in (0, 4, 9, True, '3', 1.5):
            with self.subTest(value=value):
                policy['orchestration']['max_active_ticker_pipelines'] = value
                with self.assertRaises(state.StateError): state.validate_config(self.config)

    def test_each_execution_boundary_is_required(self):
        policy = self.config['research']['daily_triggered_review']
        original = copy.deepcopy(policy['orchestration'])
        for key in original:
            with self.subTest(key=key):
                policy['orchestration'] = copy.deepcopy(original)
                del policy['orchestration'][key]
                with self.assertRaises(state.StateError): state.validate_config(self.config)

    def test_no_child_writer_or_non_independent_review(self):
        policy = self.config['research']['daily_triggered_review']
        for key, value in [('shared_db_writer', 'any_agent'), ('independent_review', False), ('unit', 'industry'), ('engine', 'custom_executor')]:
            with self.subTest(key=key):
                altered = copy.deepcopy(self.config)
                altered['research']['daily_triggered_review']['orchestration'][key] = value
                with self.assertRaises(state.StateError): state.validate_config(altered)

    def test_unknown_version_rejected(self):
        self.config['research']['daily_triggered_review']['orchestration_policy_version'] = 'future-unreviewed'
        with self.assertRaises(state.StateError): state.validate_config(self.config)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_77_alerts_preserve_71_enabled_and_private_owner_removed(self):
        rows = [alert(i + 1, enabled=i < 71, ownerId="private") for i in range(77)]
        summary = state.import_alerts(self.root, {"alerts": rows})
        self.assertEqual((summary["alerts"], summary["enabled_alerts"]), (77, 71))
        first = (self.root / "alerts.json").read_bytes()
        state.import_alerts(self.root, {"alerts": rows})
        self.assertEqual(first, (self.root / "alerts.json").read_bytes())
        self.assertNotIn(b"ownerId", first)
        self.assertEqual(json.loads(first)["alerts"][0]["threshold"], "395.850000000000000001")
        with sqlite3.connect(self.root / "alerts.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM import_events").fetchone()[0], 1)

    def test_nonfinite_zero_negative_thresholds_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", "0", "-0.1", True, float("nan")):
            with self.subTest(value=value), self.assertRaises(state.StateError):
                state.normalize_alerts({"alerts": [alert(threshold=value)]})
        self.assertEqual(decimal.Decimal(state.normalize_alerts([alert(threshold=decimal.Decimal("0.000000000000000001"))])[0]["threshold"]), decimal.Decimal("1E-18"))

    def test_duplicates_directions_and_index_templates(self):
        for rows in ([alert(), alert()], [alert(direction="maybe")], [alert(ticker="^GSPC")]):
            with self.assertRaises(state.StateError):
                state.normalize_alerts(rows)
        self.assertFalse(state.normalize_alerts([alert(ticker="^GSPC", enabled=False)])[0]["enabled"])

    def test_research_many_to_many_idempotence_and_stale_version(self):
        inventory = {"securities": [{"id": "s1", "symbol": "SNPS"}, {"id": "s2", "symbol": "CDNS"}],
                     "artifacts": [{"library_file_id": "libfile_report", "version_id": "12", "name": "报告.pdf"}],
                     "research_sections": [{"id": "section1", "artifact_id": "libfile_report", "status": "historical"}],
                     "security_artifact_relations": [{"security_id": key, "artifact_id": "libfile_report", "section_id": "section1", "relationship": "research"} for key in ("s1", "s2")]}
        state.import_research(self.root, inventory)
        before = (self.root / "research.json").read_bytes()
        state.import_research(self.root, inventory)
        self.assertEqual(before, (self.root / "research.json").read_bytes())
        with sqlite3.connect(self.root / "research.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM security_artifact_relations").fetchone()[0], 2)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], state.SCHEMA_VERSION)
        stale = copy.deepcopy(inventory)
        stale["artifacts"][0]["version_id"] = "11"
        with self.assertRaisesRegex(state.StateError, "Stale"):
            state.import_research(self.root, stale)
        self.assertEqual(before, (self.root / "research.json").read_bytes())
        changed = copy.deepcopy(inventory)
        changed["artifacts"][0]["name"] = "other.pdf"
        with self.assertRaisesRegex(state.StateError, "collision"):
            state.import_research(self.root, changed)

    def test_unknown_version_is_not_invented(self):
        inventory = {"artifacts": [{"library_file_id": "libfile_initial", "version_id": None, "name": "initial.pdf"}]}
        state.import_research(self.root, inventory)
        state.import_research(self.root, inventory)
        self.assertIsNone(json.loads((self.root / "research.json").read_text())["artifacts"][0]["version_id"])

    def test_plan_is_pure_omission_not_delete_and_stale_concurrent_edit(self):
        observed = {"alerts": [alert(1), alert(2)]}
        desired = {"_meta": {"observed_fingerprint": state.fingerprint(state.normalize_alerts(observed))}, "alerts": [alert(1, threshold="390")]}
        before = copy.deepcopy(desired)
        plan = state.plan_alert_sync(desired, observed)
        self.assertEqual(desired, before)
        self.assertEqual([row["operation"] for row in plan["operations"]], ["update"])
        self.assertEqual(plan["omitted_observed_rows"], 1)
        later = {"alerts": [alert(1, threshold="380"), alert(2)]}
        with self.assertRaisesRegex(state.StateError, "Stale"):
            state.plan_alert_sync(desired, later)
        desired["alerts"] = [{"id": alert(2)["id"], "operation": "delete"}]
        self.assertEqual(state.plan_alert_sync(desired, observed)["operations"][0]["operation"], "delete")

    def test_fk_failure_rolls_back_entire_import(self):
        inventory = {"securities": [{"symbol": "SNPS"}], "artifacts": [{"library_file_id": "libfile_bad", "version": 1, "filename": "bad.pdf", "security_symbols": ["UNKNOWN"]}]}
        with self.assertRaises(sqlite3.IntegrityError):
            state.import_research(self.root, inventory)
        with sqlite3.connect(self.root / "research.sqlite") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM securities").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
