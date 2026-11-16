from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import json
import math
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tuning.probabilistic_manifold.cli as support_cli
import tuning.probabilistic_manifold.core as core
from tuning.probabilistic_manifold.core import (
    DataContractError,
    FeaturePanelRow,
    PriceSeries,
    build_feature_panel,
    canonical_json_bytes,
    classify_geometry,
    dependence_adjusted_ess,
    feature_correlations,
    fit_robust_scaler,
    is_stale,
    load_config,
    load_price_series,
    nearest_neighbors,
    nonoverlap_episode_count,
    open_root_anchor,
    resolve_output_path,
    resolve_source_path,
    select_support_training_rows,
    source_manifest,
    write_canonical_json,
)
from tuning.probabilistic_manifold.outcomes import calculate_mature_outcomes, load_outcome_config

HERE = Path(__file__).resolve().parents[1]
CONFIG_PATH = HERE / "config.v1.json"
OUTCOME_CONFIG_PATH = HERE / "outcomes-config.v1.json"


def series(symbol: str, n: int = 520, start: dt.date = dt.date(2020, 1, 1), shock: dict[int, float] | None = None) -> PriceSeries:
    shock = shock or {}
    dates = tuple(start + dt.timedelta(days=i) for i in range(n))
    prices, value = [], 100.0
    for i in range(n):
        value *= shock.get(i, 1.001 + 0.0003 * math.sin(i / 7))
        prices.append(value)
    return PriceSeries(symbol, dates, tuple(prices), f"{symbol}.json", hashlib.sha256(symbol.encode()).hexdigest(), n)


def panel_config() -> dict:
    return {"eras": [{"name": "all", "start": "1900-01-01", "end": "2099-12-31"}]}


def row(day: int, x: float | None, y: float | None = None) -> FeaturePanelRow:
    features = {"x": x}
    if y is not None:
        features["y"] = y
    return FeaturePanelRow(dt.date(2020, 1, 1) + dt.timedelta(days=day), 1.0, "era", features)


class PanelAndOutcomeIsolationTests(unittest.TestCase):
    def test_features_are_past_only_when_future_prices_change(self):
        base = {"TQQQ": series("TQQQ"), "QQQ": series("QQQ")}
        changed = dict(base)
        tqqq = series("TQQQ")
        prices = list(tqqq.adjusted_market_prices)
        prices[301:] = [value * 9 for value in prices[301:]]
        changed["TQQQ"] = PriceSeries(tqqq.symbol, tqqq.dates, tuple(prices), tqqq.path, tqqq.sha256, tqqq.byte_count)
        self.assertEqual(build_feature_panel(base, panel_config())[300].features, build_feature_panel(changed, panel_config())[300].features)

    def test_outcome_config_is_closed_and_separate(self):
        loaded = load_outcome_config(OUTCOME_CONFIG_PATH)
        self.assertEqual(loaded["primary_sessions"], 126)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.json"
            bad = dict(loaded); bad["extra"] = 1; path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(DataContractError, "keys mismatch"):
                load_outcome_config(path)

    def test_outcomes_are_isolated_and_only_emitted_after_maturity(self):
        data = {"TQQQ": series("TQQQ"), "QQQ": series("QQQ")}
        outcomes = calculate_mature_outcomes(data, 126, -0.30)
        self.assertEqual(len(outcomes), 394)
        self.assertEqual(outcomes[-1].end_date, data["TQQQ"].dates[-1].isoformat())
        self.assertEqual(outcomes[-1].origin_date, data["TQQQ"].dates[-127].isoformat())

    def test_outcome_chronology_and_material_loss(self):
        data = {"TQQQ": series("TQQQ", shock={200: 0.5}), "QQQ": series("QQQ")}
        target = calculate_mature_outcomes(data, 126, -0.30)[100]
        self.assertTrue(target.material_loss)
        self.assertLessEqual(target.max_drawdown, -0.30)

    def test_support_core_and_cli_do_not_import_outcomes(self):
        self.assertNotIn(".outcomes", inspect.getsource(core))
        self.assertNotIn(".outcomes", inspect.getsource(support_cli))
        self.assertNotIn("calculate_mature_outcomes", inspect.getsource(core))

    def test_required_missing_date_fails_without_forward_fill(self):
        tqqq, qqq = series("TQQQ"), series("QQQ")
        qqq = PriceSeries(qqq.symbol, qqq.dates[:20] + qqq.dates[21:], qqq.adjusted_market_prices[:20] + qqq.adjusted_market_prices[21:], qqq.path, qqq.sha256, qqq.byte_count)
        with self.assertRaisesRegex(DataContractError, "no forward fill"):
            build_feature_panel({"TQQQ": tqqq, "QQQ": qqq}, panel_config())

    def test_optional_missing_rows_remain_missing(self):
        optional = series("SPY", n=100, start=dt.date(2021, 1, 1))
        panel = build_feature_panel({"TQQQ": series("TQQQ"), "QQQ": series("QQQ"), "SPY": optional}, panel_config())
        self.assertIsNone(panel[300].features["spy_return_21"])


class GeometryTests(unittest.TestCase):
    def test_training_split_uses_horizon_without_accessing_outcomes(self):
        rows = [row(i, float(i)) for i in range(300)]
        selected = select_support_training_rows(rows, 299, ["x"], 126)
        self.assertEqual(len(selected), 174)
        self.assertEqual(selected[-1].date, rows[173].date)

    def test_scaler_is_isolated_from_query(self):
        training = [row(i, float(i), float(i * 2)) for i in range(1, 8)]
        first = fit_robust_scaler(training, ["x", "y"])
        query = row(99, 1e9, -1e9)
        self.assertEqual(first, fit_robust_scaler(training, ["x", "y"]))
        self.assertNotIn(query.features["x"], first.medians.values())

    def test_neighbor_recomputation_uses_raw_query(self):
        training = [row(1, 0, 0), row(2, 10, 10), row(3, 20, 20), row(4, 30, 30)]
        scaler = fit_robust_scaler(training, ["x", "y"])
        self.assertEqual(nearest_neighbors(training, row(9, 1, 1), scaler, ["x", "y"], 1)[0]["date"], training[0].date.isoformat())
        self.assertEqual(nearest_neighbors(training, row(9, 29, 29), scaler, ["x", "y"], 1)[0]["date"], training[-1].date.isoformat())

    def test_zero_mad_forces_abstention_error(self):
        with self.assertRaisesRegex(DataContractError, "MAD is zero"):
            fit_robust_scaler([row(i, 1.0, float(i)) for i in range(5)], ["x", "y"])

    def test_status_vocabulary_and_invalid_threshold_abstention(self):
        self.assertEqual(classify_geometry(1.0, 2.0, 3.0), "inside")
        self.assertEqual(classify_geometry(2.5, 2.0, 3.0), "edge")
        self.assertEqual(classify_geometry(4.0, 2.0, 3.0), "outside")
        self.assertEqual(classify_geometry(1.0, 3.0, 2.0), "inconclusive")

    def test_stale_rule_is_calendar_based(self):
        origin = dt.date(2026, 11, 5)
        self.assertFalse(is_stale(dt.date(2026, 11, 9), origin, 7))
        self.assertTrue(is_stale(dt.date(2026, 11, 13), origin, 7))

    def test_nonoverlap_and_ess_penalize_clusters(self):
        dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(500)]
        clustered = [dates[i] for i in (100, 101, 102, 103)]
        separated = [dates[i] for i in (0, 130, 260, 390)]
        self.assertEqual(nonoverlap_episode_count(clustered, dates, 126), 1)
        self.assertEqual(nonoverlap_episode_count(separated, dates, 126), 4)
        self.assertLess(dependence_adjusted_ess(clustered, dates, 126), dependence_adjusted_ess(separated, dates, 126))

    def test_feature_correlations_expose_collinearity(self):
        rows = [row(i, float(i), float(i * 2)) for i in range(10)]
        result = feature_correlations(rows, ["x", "y"])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["pearson_correlation"], 1.0)
        self.assertEqual(result[0]["rows"], 10)


class ClosedConfigTests(unittest.TestCase):
    def base(self) -> dict:
        return json.loads(CONFIG_PATH.read_text())

    def write_and_load(self, value: dict) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "config.json"
            path.write_text(json.dumps(value))
            return load_config(path)

    def assert_bad(self, value: dict, pattern: str = "") -> None:
        with self.assertRaisesRegex(DataContractError, pattern or ".+"):
            self.write_and_load(value)

    def test_checked_in_config_passes_closed_schema(self):
        self.assertEqual(load_config(CONFIG_PATH)["schema_version"], "probabilistic-manifold-config-v1")

    def test_unknown_or_missing_keys_are_rejected(self):
        value = self.base(); value["unexpected"] = 1; self.assert_bad(value, "keys mismatch")
        value = self.base(); del value["analysis_as_of"]; self.assert_bad(value, "keys mismatch")
        value = self.base(); value["knn"]["extra"] = 1; self.assert_bad(value, "keys mismatch")

    def test_absolute_parent_and_non_normalized_source_paths_are_rejected(self):
        for attack in ("/etc/passwd", "../escape.json", "mentor/../escape.json", "mentor//file.json", "C:\\escape.json"):
            value = self.base(); value["sources"]["TQQQ"]["path"] = attack
            self.assert_bad(value, "path")

    def test_price_field_quantiles_and_maturity_are_frozen_exactly(self):
        value = self.base(); value["price_basis"]["field"] = "chart.result[0].indicators.quote[0].close"; self.assert_bad(value, "parsed adjusted-close path")
        value = self.base(); value["knn"]["inside_quantile"] = 0.949; self.assert_bad(value, "frozen")
        value = self.base(); value["knn"]["edge_quantile"] = 0.991; self.assert_bad(value, "frozen")
        value = self.base(); value["training_cloud_maturity_sessions"] = 125; self.assert_bad(value, "equal 126")

    def test_tqqq_and_qqq_must_be_required_true(self):
        for symbol in ("TQQQ", "QQQ"):
            value = self.base(); value["sources"][symbol]["required"] = False
            self.assert_bad(value, "required true")

    def test_source_hash_bytes_date_symbol_and_types_are_closed(self):
        mutations = []
        value = self.base(); value["sources"]["TQQQ"]["sha256"] = "A" * 64; mutations.append(value)
        value = self.base(); value["sources"]["TQQQ"]["bytes"] = True; mutations.append(value)
        value = self.base(); value["sources"]["TQQQ"]["expected_start"] = "02/11/2010"; mutations.append(value)
        value = self.base(); value["sources"]["TQQQ"]["expected_end"] = "2000-01-01"; mutations.append(value)
        value = self.base(); value["sources"]["TQQQ"]["symbol"] = "QQQ"; mutations.append(value)
        value = self.base(); value["sources"]["TQQQ"]["required"] = 1; mutations.append(value)
        for value in mutations:
            self.assert_bad(value)

    def test_feature_lists_are_unique_and_known(self):
        value = self.base(); value["distance_features"].append(value["distance_features"][0]); self.assert_bad(value, "unique")
        value = self.base(); value["distance_features"][0] = "future_return"; self.assert_bad(value, "unknown")
        value = self.base(); value["informational_proxy_features"][0] = "unknown"; self.assert_bad(value, "unknown")

    def test_knn_horizon_threshold_and_staleness_constraints(self):
        mutations = []
        value = self.base(); value["knn"]["k"] = 0; mutations.append(value)
        value = self.base(); value["knn"]["k"] = 300; mutations.append(value)
        value = self.base(); value["knn"]["calibration_stride"] = 0; mutations.append(value)
        value = self.base(); value["knn"]["maximum_staleness_calendar_days"] = -1; mutations.append(value)
        value = self.base(); value["knn"]["inside_quantile"] = 0.999; mutations.append(value)
        value = self.base(); value["training_cloud_maturity_sessions"] = 0; mutations.append(value)
        for value in mutations:
            self.assert_bad(value)

    def test_era_overlap_order_duplicate_and_integration_mutations_fail(self):
        value = self.base(); value["eras"][1]["start"] = value["eras"][0]["end"]; self.assert_bad(value, "non-overlapping")
        value = self.base(); value["eras"][1]["name"] = value["eras"][0]["name"]; self.assert_bad(value, "unique")
        value = self.base(); value["integration"]["probability_feature_compatible"] = True; self.assert_bad(value, "must be false")
        value = self.base(); value["integration"]["policy_scope"] = "predictive"; self.assert_bad(value, "unsupported")


class RootedIOTests(unittest.TestCase):
    def test_source_resolution_rejects_absolute_parent_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); root = base / "root"; outside = base / "outside"; root.mkdir(); outside.mkdir()
            (outside / "data.json").write_text("{}")
            (root / "link").symlink_to(outside, target_is_directory=True)
            for attack in ("/etc/passwd", "../outside/data.json", "link/data.json"):
                with self.assertRaises(DataContractError):
                    resolve_source_path(root, attack)

    def test_output_resolution_rejects_absolute_parent_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); root = base / "root"; outside = base / "outside"; root.mkdir(); outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            for attack in ("/tmp/out.json", "../out.json", "link/out.json"):
                with self.assertRaises(DataContractError):
                    resolve_output_path(root, attack)

    def test_trusted_root_rejects_symlink_and_writable_roots(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw); real = base / "real"; real.mkdir(); link = base / "link"; link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(DataContractError):
                open_root_anchor(link)
            real.chmod(0o777)
            try:
                with self.assertRaisesRegex(DataContractError, "group/world writable"):
                    open_root_anchor(real)
            finally:
                real.chmod(0o700)

    def test_trusted_root_rejects_unowned_root(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); real_lstat = core.os.lstat
            def fake_lstat(path):
                observed = real_lstat(path)
                if Path(path) == root:
                    values = list(observed)
                    values[4] = os.getuid() + 1000
                    return os.stat_result(values)
                return observed
            with mock.patch.object(core.os, "lstat", side_effect=fake_lstat):
                with self.assertRaisesRegex(DataContractError, "owned by current uid or root"):
                    open_root_anchor(root)

    def test_trusted_root_rejects_writable_existing_ancestor(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); child = root / "child"; child.mkdir(); source = child / "data.json"; source.write_text("{}")
            child.chmod(0o777)
            try:
                with self.assertRaisesRegex(DataContractError, "group/world writable"):
                    resolve_source_path(root, "child/data.json")
            finally:
                child.chmod(0o700)

    def test_atomic_writer_handles_partial_writes_mode_and_readback(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); real_write = os.write
            def partial(fd: int, data: bytes) -> int:
                return real_write(fd, data[:max(1, len(data)//3)])
            with mock.patch.object(core.os, "write", side_effect=partial):
                digest = write_canonical_json(root, "packet.json", {"b": 2, "a": 1})
            payload = (root / "packet.json").read_bytes()
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(stat.S_IMODE((root / "packet.json").stat().st_mode), 0o600)
            self.assertFalse(list(root.glob(".packet.json.tmp.*")))

    def test_atomic_writer_cleans_unique_temp_on_write_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with mock.patch.object(core.os, "write", side_effect=OSError("injected")):
                with self.assertRaises(OSError):
                    write_canonical_json(root, "packet.json", {"a": 1})
            self.assertFalse((root / "packet.json").exists())
            self.assertFalse(list(root.glob(".packet.json.tmp.*")))

    def test_atomic_writer_rejects_unstable_readback(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with mock.patch.object(core, "_stable_readback", return_value=b"mutated"):
                with self.assertRaisesRegex(DataContractError, "readback mismatch"):
                    write_canonical_json(root, "packet.json", {"a": 1})
            self.assertFalse(list(root.glob(".packet.json.tmp.*")))

    def test_hash_bound_loader_rejects_mutated_source(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = {"chart": {"result": [{"meta": {"symbol": "TQQQ"}, "timestamp": [1577836800], "indicators": {"adjclose": [{"adjclose": [1.0]}]}}]}}
            encoded = json.dumps(payload).encode(); path = root / "TQQQ.json"; path.write_bytes(encoded)
            spec = {"symbol": "TQQQ", "path": "TQQQ.json", "sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded), "expected_start": "2020-01-01", "expected_end": "2020-01-01"}
            load_price_series(root, "TQQQ", spec)
            path.write_bytes(encoded + b" ")
            with self.assertRaisesRegex(DataContractError, "sha256 mismatch"):
                load_price_series(root, "TQQQ", spec)


class DeterminismTests(unittest.TestCase):
    def test_canonical_hash_is_order_independent(self):
        self.assertEqual(canonical_json_bytes({"b": 2, "a": 1}), canonical_json_bytes({"a": 1, "b": 2}))

    def test_published_packets_bind_manifest_hash(self):
        artifacts = HERE / "artifacts"
        for manifest_name, packet_name in (("source-manifest.json", "support-packet.json"), ("source-manifest.v2.json", "support-packet.v2.json")):
            manifest = (artifacts / manifest_name).read_bytes()
            packet = json.loads((artifacts / packet_name).read_text())
            self.assertEqual(packet["source_manifest_sha256"], hashlib.sha256(manifest).hexdigest())

    def test_manifest_is_deterministic_and_sorted(self):
        cfg = load_config(CONFIG_PATH)
        sources = {"TQQQ": series("TQQQ", 10), "QQQ": series("QQQ", 10)}
        manifest = source_manifest(sources, cfg)
        self.assertEqual([item["symbol"] for item in manifest["sources"]], ["QQQ", "TQQQ"])
        self.assertEqual(canonical_json_bytes(manifest), canonical_json_bytes(manifest))


if __name__ == "__main__":
    unittest.main()
