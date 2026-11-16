"""Focused provider-free tests for Nasdaq Composite identity/availability packets."""
from copy import deepcopy
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from investment.research.index_identity import (
    MAX_INPUT_BYTES,
    IndexIdentityError,
    compile_packet,
    encode_packet,
    load_packet,
    validate_packet,
    write_packet_atomic,
    canonical_json_bytes,
    write_new_bytes_atomic,
    write_new_json_atomic,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
DATE = "2026-10-30"
RETRIEVED = "2026-10-31T12:00:00Z"


def source(authority, publisher, url, sha=SHA_A, published=DATE):
    return {
        "authority": authority,
        "publisher": publisher,
        "url": url,
        "published_date": published,
        "retrieved_at": RETRIEVED,
        "sha256": sha,
    }


def unavailable(reason="gated"):
    return {
        "status": "unverifiable",
        "value": None,
        "effective_date": None,
        "source": None,
        "reason": reason,
    }


def exact(value, bound_source):
    return {
        "status": "exact",
        "value": value,
        "effective_date": DATE,
        "source": bound_source,
        "reason": None,
    }


def gated_packet():
    return {
        "schema_version": 1,
        "kind": "nasdaq_composite_identity_availability",
        "identity": {
            "official_name": "Nasdaq Composite",
            "official_symbol": "COMP",
            "basis": "price_index",
            "source": source("official", "Nasdaq", "https://indexes.nasdaq.com/comp"),
        },
        "aliases": [
            {
                "symbol": "^IXIC",
                "kind": "vendor_alias",
                "provider": "Example Market Data Vendor",
                "basis": "price_index",
                "source": source("vendor", "Example Market Data Vendor",
                                 "https://example.com/index/ixic", SHA_B),
            },
            {
                "symbol": "NASDAQCOM",
                "kind": "price_series_alias",
                "provider": "FRED",
                "basis": "price_index",
                "source": source("fred", "Federal Reserve Bank of St. Louis",
                                 "https://fred.stlouisfed.org/series/NASDAQCOM", SHA_C),
            },
        ],
        "availability": {
            "current_level": unavailable(),
            "history": unavailable(),
            "component_count": unavailable(),
            "membership": unavailable(),
            "weights": unavailable(),
            "valuation": unavailable(),
        },
        "proxies": [
            {
                "kind": "oneq_etf",
                "symbol": "ONEQ",
                "basis": "etf_total_return",
                "effective_date": DATE,
                "source": source("proxy", "Example Fund Sponsor",
                                 "https://example.com/funds/oneq", SHA_B),
            },
            {
                "kind": "nasdaq_listed_market_cap_reconstruction",
                "symbol": None,
                "basis": "market_cap_reconstruction",
                "effective_date": DATE,
                "source": source("proxy", "Example Reconstruction Publisher",
                                 "https://example.com/reconstruction", SHA_C),
            },
        ],
    }


def exact_packet():
    packet = gated_packet()
    official = source("official", "Nasdaq", "https://indexes.nasdaq.com/comp-components")
    packet["availability"] = {
        "current_level": exact({
            "level": "18999.50",
            "basis": "price_index",
        }, {**official, "url": "https://indexes.nasdaq.com/comp-level"}),
        "history": exact({
            "basis": "price_index",
            "start_date": "2026-10-01",
            "end_date": DATE,
            "observation_count": 22,
            "artifact_sha256": SHA_C,
            "series_id": "COMP",
            "provenance": "official_nasdaq_comp",
        }, {**official, "url": "https://indexes.nasdaq.com/comp-history", "sha256": SHA_B}),
        "component_count": exact(2, official),
        "membership": exact(["AAPL", "MSFT"], {**official, "sha256": SHA_B}),
        "weights": exact([
            {"symbol": "AAPL", "weight": "0.6"},
            {"symbol": "MSFT", "weight": "0.4"},
        ], {**official, "sha256": SHA_C}),
        "valuation": exact({
            "metric": "forward_price_to_earnings",
            "value": "25.4",
            "unit": "ratio",
            "estimate_effective_date": DATE,
        }, source("estimate", "FactSet",
                  "https://insight.factset.com/estimates/comp", SHA_B)),
    }
    return packet


class IndexIdentityTests(unittest.TestCase):
    def assert_code(self, code, packet):
        with self.assertRaisesRegex(IndexIdentityError, f"^{code}$"):
            validate_packet(packet)

    def test_valid_gated_ixic_packet_keeps_aliases_and_exact_fields_null(self):
        compiled = compile_packet(json.dumps(gated_packet()))
        self.assertEqual(compiled["identity"]["official_symbol"], "COMP")
        self.assertEqual(compiled["aliases"][0]["symbol"], "^IXIC")
        self.assertEqual(compiled["aliases"][1]["symbol"], "NASDAQCOM")
        self.assertTrue(all(row["status"] == "unverifiable" and row["value"] is None
                            for row in compiled["availability"].values()))
        self.assertEqual(compiled["availability"]["history"]["reason"], "gated")
        self.assertEqual(encode_packet(compiled), encode_packet(compiled))

    def test_valid_exact_packet_reconciles_level_history_membership_weights_and_valuation(self):
        compiled = validate_packet(exact_packet())
        self.assertEqual(compiled["availability"]["current_level"]["value"]["level"], "18999.50")
        self.assertEqual(compiled["availability"]["history"]["value"]["series_id"], "COMP")
        self.assertEqual(compiled["availability"]["component_count"]["value"], 2)
        self.assertEqual(compiled["availability"]["valuation"]["value"]["value"], "25.4")

    def test_fred_nasdaqcom_history_is_explicit_price_series_not_official_symbol(self):
        packet = exact_packet()
        packet["availability"]["history"] = exact({
            "basis": "price_index",
            "start_date": "2026-10-01",
            "end_date": DATE,
            "observation_count": 22,
            "artifact_sha256": SHA_A,
            "series_id": "NASDAQCOM",
            "provenance": "fred_nasdaqcom_price_series",
        }, source("fred", "Federal Reserve Bank of St. Louis",
                  "https://fred.stlouisfed.org/series/NASDAQCOM", SHA_C))
        compiled = validate_packet(packet)
        self.assertEqual(compiled["identity"]["official_symbol"], "COMP")
        self.assertEqual(compiled["availability"]["history"]["value"]["series_id"], "NASDAQCOM")

    def test_official_symbol_confusion_is_rejected(self):
        for symbol in ("^IXIC", "NASDAQCOM", "ONEQ"):
            packet = gated_packet()
            packet["identity"]["official_symbol"] = symbol
            with self.subTest(symbol=symbol):
                self.assert_code("INDEX_OFFICIAL_IDENTITY_CONFUSION", packet)

    def test_level_and_history_reject_wrong_basis_source_and_date(self):
        cases = []
        wrong_level_basis = exact_packet()
        wrong_level_basis["availability"]["current_level"]["value"]["basis"] = "total_return"
        cases.append(("INDEX_BASIS_CONFUSION", wrong_level_basis))
        wrong_history_basis = exact_packet()
        wrong_history_basis["availability"]["history"]["value"]["basis"] = "total_return"
        cases.append(("INDEX_BASIS_CONFUSION", wrong_history_basis))
        wrong_date = exact_packet()
        wrong_date["availability"]["history"]["value"]["end_date"] = "2026-10-29"
        cases.append(("INDEX_DATE_INCONSISTENT", wrong_date))
        wrong_source_date = exact_packet()
        wrong_source_date["availability"]["history"]["source"]["published_date"] = "2026-10-29"
        cases.append(("INDEX_HISTORY_SOURCE_DATE_REQUIRED", wrong_source_date))
        for code, packet in cases:
            with self.subTest(code=code):
                self.assert_code(code, packet)

    def test_proxy_or_vendor_history_cannot_masquerade_as_exact_comp_history(self):
        for authority, publisher, url in (
            ("proxy", "Example Fund Sponsor", "https://example.com/funds/oneq"),
            ("vendor", "Example Market Data Vendor", "https://example.com/index/ixic"),
        ):
            packet = exact_packet()
            packet["availability"]["history"]["source"] = source(
                authority, publisher, url, SHA_C)
            with self.subTest(authority=authority):
                self.assert_code("INDEX_HISTORY_SOURCE_INVALID", packet)

    def test_membership_and_weights_sources_bind_effective_date(self):
        for name, code in (
            ("membership", "INDEX_MEMBERSHIP_SOURCE_DATE_REQUIRED"),
            ("weights", "INDEX_WEIGHTS_SOURCE_DATE_REQUIRED"),
        ):
            packet = exact_packet()
            packet["availability"][name]["source"]["published_date"] = "2026-10-29"
            with self.subTest(name=name):
                self.assert_code(code, packet)

    def test_valuation_sources_are_explicitly_allowed(self):
        packet = exact_packet()
        packet["availability"]["valuation"]["source"] = source(
            "official", "Example Official", "https://example.com/comp", SHA_B)
        self.assert_code("INDEX_VALUATION_SOURCE_INVALID", packet)
        packet = exact_packet()
        packet["availability"]["valuation"]["source"] = source(
            "estimate", "Unknown Estimates", "https://example.com/comp", SHA_B)
        self.assert_code("INDEX_VALUATION_ESTIMATE_SOURCE_INVALID", packet)
        packet = exact_packet()
        packet["availability"]["valuation"]["source"] = source(
            "official", "Nasdaq", "https://indexes.nasdaq.com/comp-valuation", SHA_B)
        self.assertEqual(validate_packet(packet)["availability"]["valuation"]["status"], "exact")

    def test_alias_set_and_fred_identity_are_strict(self):
        packet = gated_packet()
        packet["aliases"].pop()
        self.assert_code("INDEX_ALIAS_SET_REQUIRED", packet)
        for publisher, url in (
            ("Not FRED", "https://fred.stlouisfed.org/series/NASDAQCOM"),
            ("Federal Reserve Bank of St. Louis", "https://example.com/NASDAQCOM"),
        ):
            packet = gated_packet()
            packet["aliases"][1]["source"] = source("fred", publisher, url, SHA_C)
            with self.subTest(publisher=publisher, url=url):
                self.assert_code("INDEX_FRED_ALIAS_CONFUSION", packet)

    def test_oneq_basis_and_source_date_are_unambiguous(self):
        packet = gated_packet()
        packet["proxies"][0]["basis"] = "price_index"
        self.assert_code("INDEX_PROXY_SCHEMA", packet)
        packet = gated_packet()
        packet["proxies"][0]["source"]["published_date"] = "2026-10-29"
        self.assert_code("INDEX_PROXY_SOURCE_DATE_REQUIRED", packet)
        for basis in ("etf_market_price_return", "etf_total_return"):
            packet = gated_packet()
            packet["proxies"][0]["basis"] = basis
            with self.subTest(basis=basis):
                self.assertEqual(validate_packet(packet)["proxies"][0]["basis"], basis)

    def test_proxy_cannot_populate_exact_comp_fields(self):
        packet = exact_packet()
        packet["availability"]["membership"]["source"] = source(
            "proxy", "Example Fund Sponsor", "https://example.com/funds/oneq")
        self.assert_code("INDEX_EXACT_REQUIRES_OFFICIAL_SOURCE", packet)
        packet = exact_packet()
        packet["availability"]["membership"]["value"][0] = "ONEQ"
        self.assert_code("INDEX_PROXY_OR_ALIAS_AS_EXACT", packet)

    def test_valuation_without_exact_weights_is_rejected(self):
        packet = exact_packet()
        packet["availability"]["weights"] = unavailable("unavailable")
        self.assert_code("INDEX_VALUATION_REQUIRES_MEMBERSHIP_AND_WEIGHTS", packet)

    def test_bad_weight_sum_is_rejected(self):
        packet = exact_packet()
        packet["availability"]["weights"]["value"][1]["weight"] = "0.39"
        self.assert_code("INDEX_WEIGHT_RECONCILIATION_FAILED", packet)

    def test_missing_source_date_or_hash_is_rejected(self):
        mutations = (
            lambda packet: packet["availability"]["component_count"].pop("source"),
            lambda packet: packet["availability"]["component_count"]["source"].pop("published_date"),
            lambda packet: packet["availability"]["component_count"]["source"].pop("sha256"),
        )
        for mutate in mutations:
            packet = exact_packet()
            mutate(packet)
            with self.subTest(packet=packet):
                with self.assertRaises(IndexIdentityError):
                    validate_packet(packet)

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        raw = json.dumps(gated_packet())
        duplicate = raw.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1)
        with self.assertRaisesRegex(IndexIdentityError, "^INDEX_JSON_DUPLICATE_KEY$"):
            load_packet(duplicate)
        nonfinite = raw.replace('"schema_version": 1', '"schema_version": NaN', 1)
        with self.assertRaisesRegex(IndexIdentityError, "^INDEX_JSON_NONFINITE$"):
            load_packet(nonfinite)
        packet = gated_packet()
        packet["schema_version"] = math.inf
        self.assert_code("INDEX_SCHEMA_VERSION_UNSUPPORTED", packet)

    def test_unhashable_enums_unicode_depth_and_embedded_paths_are_stable(self):
        packet = gated_packet()
        packet["identity"]["source"]["authority"] = ["official"]
        self.assert_code("INDEX_IDENTITY_SOURCE_INVALID", packet)
        packet = gated_packet()
        packet["availability"]["history"]["status"] = ["exact"]
        self.assert_code("INDEX_AVAILABILITY_STATUS", packet)
        packet = gated_packet()
        packet["identity"]["source"]["publisher"] = "bad\ud800publisher"
        self.assert_code("INDEX_TEXT_UNICODE_INVALID", packet)
        packet = gated_packet()
        packet["identity"]["source"]["publisher"] = "prefix=/Users/alice/source.json"
        self.assert_code("INDEX_SECRET_OR_PRIVATE_DATA", packet)
        packet = gated_packet()
        deep = []
        cursor = deep
        for _ in range(30):
            child = []
            cursor.append(child)
            cursor = child
        packet["proxies"] = deep
        self.assert_code("INDEX_STRUCTURE_TOO_DEEP", packet)
        raw = json.dumps(gated_packet()).replace('"Nasdaq"', '"bad\\ud800publisher"', 1)
        with self.assertRaisesRegex(IndexIdentityError, "^INDEX_TEXT_UNICODE_INVALID$"):
            load_packet(raw)

    def test_private_paths_secrets_dates_and_unsupported_claims_are_rejected(self):
        cases = []
        private = gated_packet()
        private["identity"]["source"]["publisher"] = "/Users/alice/private/source.json"
        cases.append(("INDEX_SECRET_OR_PRIVATE_DATA", private))
        secret = gated_packet()
        secret["aliases"][0]["provider"] = "api_key=synthetic-secret-value"
        cases.append(("INDEX_SECRET_OR_PRIVATE_DATA", secret))
        dated = exact_packet()
        dated["availability"]["weights"]["effective_date"] = "2026-10-29"
        cases.append(("INDEX_DATE_INCONSISTENT", dated))
        unsupported = exact_packet()
        unsupported["availability"]["valuation"]["value"]["metric"] = "market_cap"
        cases.append(("INDEX_UNSUPPORTED_VALUATION_CLAIM", unsupported))
        for code, packet in cases:
            with self.subTest(code=code):
                self.assert_code(code, packet)

    def test_atomic_writer_reconciles_pre_effect_failure_and_preserves_prior_output(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            output.write_bytes(b"old-valid-output\n")
            with mock.patch("investment.research.index_identity.os.replace",
                            side_effect=OSError("synthetic private diagnostic")):
                with self.assertRaisesRegex(IndexIdentityError, "^INDEX_OUTPUT_FAILED$"):
                    write_packet_atomic(exact_packet(), output)
            self.assertEqual(output.read_bytes(), b"old-valid-output\n")
            self.assertEqual([item for item in parent.iterdir() if item != output], [])

    def test_cli_reconciles_pre_effect_replace_failure_and_preserves_prior_output(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_path = parent / "input.json"
            output_path = parent / "output.json"
            input_path.write_text(json.dumps(exact_packet()))
            prior = encode_packet(exact_packet())
            output_path.write_bytes(prior)
            script = r'''
import os, sys
from investment.research import index_identity as target
def failing_replace(*args, **kwargs):
    raise OSError("synthetic pre-effect failure /private/path")
target.os.replace = failing_replace
raise SystemExit(target.main(["compile", sys.argv[1], "--output", sys.argv[2]]))
'''
            result = subprocess.run(
                [sys.executable, "-c", script, str(input_path), str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stderr)["code"], "INDEX_OUTPUT_FAILED")
            self.assertEqual(output_path.read_bytes(), prior)
            self.assertEqual(sorted(item.name for item in parent.iterdir()),
                             ["input.json", "output.json"])

    def test_absent_destination_concurrent_create_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            real_link = os.link

            def create_then_link(source_path, output_path, *, src_dir_fd=None,
                                 dst_dir_fd=None, follow_symlinks=True):
                descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                     | os.O_NOFOLLOW, 0o600, dir_fd=dst_dir_fd)
                try:
                    os.write(descriptor, b"concurrent-output\n")
                finally:
                    os.close(descriptor)
                return real_link(source_path, output_path, src_dir_fd=src_dir_fd,
                                 dst_dir_fd=dst_dir_fd,
                                 follow_symlinks=follow_symlinks)

            with mock.patch("investment.research.index_identity.os.link",
                            side_effect=create_then_link):
                with self.assertRaisesRegex(IndexIdentityError, "^INDEX_OUTPUT_FAILED$"):
                    write_packet_atomic(exact_packet(), output)
            self.assertEqual(output.read_bytes(), b"concurrent-output\n")
            self.assertEqual(list(parent.iterdir()), [output])

    def test_destination_swap_inside_replace_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            backup = parent / "prior-backup.json"
            output.write_bytes(b"prior-output\n")
            real_replace = os.replace

            def swap_then_replace(source_path, output_path, *, src_dir_fd=None,
                                  dst_dir_fd=None):
                os.rename(output_path, backup.name, src_dir_fd=dst_dir_fd,
                          dst_dir_fd=dst_dir_fd)
                descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                     | os.O_NOFOLLOW, 0o600, dir_fd=dst_dir_fd)
                try:
                    os.write(descriptor, b"concurrent-output\n")
                finally:
                    os.close(descriptor)
                real_replace(source_path, output_path, src_dir_fd=src_dir_fd,
                             dst_dir_fd=dst_dir_fd)

            with mock.patch("investment.research.index_identity.os.replace",
                            side_effect=swap_then_replace):
                with self.assertRaisesRegex(
                        IndexIdentityError, "^INDEX_OUTPUT_OUTCOME_UNKNOWN$"):
                    write_packet_atomic(exact_packet(), output)
            self.assertEqual(backup.read_bytes(), b"prior-output\n")
            self.assertEqual(compile_packet(output.read_bytes()), validate_packet(exact_packet()))
            self.assertEqual(sorted(item.name for item in parent.iterdir()),
                             ["packet.json", "prior-backup.json"])

    def test_parent_lock_contention_is_pre_effect_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            output.write_bytes(b"prior-output\n")
            descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(IndexIdentityError, "^INDEX_OUTPUT_FAILED$"):
                    write_packet_atomic(exact_packet(), output)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            self.assertEqual(output.read_bytes(), b"prior-output\n")
            self.assertEqual(list(parent.iterdir()), [output])

    def test_replace_effect_then_raise_reconciles_to_durability_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            output.write_bytes(b"previous\n")
            real_replace = os.replace

            def replace_then_raise(source_path, output_path, *, src_dir_fd=None,
                                   dst_dir_fd=None):
                real_replace(source_path, output_path, src_dir_fd=src_dir_fd,
                             dst_dir_fd=dst_dir_fd)
                raise OSError("synthetic unknown effect /Users/private")

            with mock.patch("investment.research.index_identity.os.replace",
                            side_effect=replace_then_raise):
                with self.assertRaisesRegex(
                        IndexIdentityError, "^INDEX_OUTPUT_DURABILITY_UNVERIFIED$"):
                    write_packet_atomic(exact_packet(), output)
            self.assertEqual(compile_packet(output.read_bytes()), validate_packet(exact_packet()))
            self.assertEqual([item for item in parent.iterdir() if item != output], [])

    def test_parent_fsync_failure_is_sanitized_and_leaves_complete_valid_output(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            calls = 0
            real_fsync = os.fsync

            def fail_parent_fsync(descriptor):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic parent durability failure /private/path")
                return real_fsync(descriptor)

            with mock.patch("investment.research.index_identity.os.fsync",
                            side_effect=fail_parent_fsync):
                with self.assertRaisesRegex(
                        IndexIdentityError, "^INDEX_OUTPUT_DURABILITY_UNVERIFIED$"):
                    write_packet_atomic(exact_packet(), output)
            self.assertEqual(compile_packet(output.read_bytes()), validate_packet(exact_packet()))
            self.assertEqual([item for item in parent.iterdir() if item != output], [])

    def test_output_parent_chmod_before_replace_preserves_prior_output(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            output.write_bytes(b"prior-output\n")
            original_mode = parent.stat().st_mode & 0o777
            real_fsync = os.fsync
            calls = 0

            def chmod_after_temp_fsync(descriptor):
                nonlocal calls
                calls += 1
                real_fsync(descriptor)
                if calls == 1:
                    os.chmod(parent, 0o777)

            try:
                with mock.patch("investment.research.index_identity.os.fsync",
                                side_effect=chmod_after_temp_fsync):
                    with self.assertRaisesRegex(IndexIdentityError, "^INDEX_OUTPUT_FAILED$"):
                        write_packet_atomic(exact_packet(), output)
            finally:
                os.chmod(parent, original_mode)
            self.assertEqual(output.read_bytes(), b"prior-output\n")
            self.assertEqual(list(parent.iterdir()), [output])

    def test_output_parent_chmod_after_directory_fsync_is_outcome_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            output.write_bytes(b"prior-output\n")
            original_mode = parent.stat().st_mode & 0o777
            real_fsync = os.fsync
            calls = 0

            def chmod_after_directory_fsync(descriptor):
                nonlocal calls
                calls += 1
                real_fsync(descriptor)
                if calls == 2:
                    os.chmod(parent, 0o777)

            try:
                with mock.patch("investment.research.index_identity.os.fsync",
                                side_effect=chmod_after_directory_fsync):
                    with self.assertRaisesRegex(
                            IndexIdentityError, "^INDEX_OUTPUT_OUTCOME_UNKNOWN$"):
                        write_packet_atomic(exact_packet(), output)
            finally:
                os.chmod(parent, original_mode)
            self.assertEqual(compile_packet(output.read_bytes()), validate_packet(exact_packet()))
            self.assertEqual(list(parent.iterdir()), [output])

    def test_output_parent_chmod_during_readback_is_outcome_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            output = parent / "packet.json"
            output.write_bytes(b"prior-output\n")
            original_mode = parent.stat().st_mode & 0o777
            real_read = os.read
            fired = False

            def chmod_during_readback(descriptor, count):
                nonlocal fired
                data = real_read(descriptor, count)
                if not fired:
                    fired = True
                    os.chmod(parent, 0o777)
                return data

            try:
                with mock.patch("investment.research.index_identity.os.read",
                                side_effect=chmod_during_readback):
                    with self.assertRaisesRegex(
                            IndexIdentityError, "^INDEX_OUTPUT_OUTCOME_UNKNOWN$"):
                        write_packet_atomic(exact_packet(), output)
            finally:
                os.chmod(parent, original_mode)
            self.assertEqual(compile_packet(output.read_bytes()), validate_packet(exact_packet()))
            self.assertEqual(list(parent.iterdir()), [output])

    def test_cli_bounded_read_rejects_oversize_without_output(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_path = parent / "oversize.json"
            output_path = parent / "output.json"
            input_path.write_bytes(b" " * (MAX_INPUT_BYTES + 4096))
            result = subprocess.run(
                [sys.executable, "-m", "investment.research.index_identity", "compile",
                 str(input_path), "--output", str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=20,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stderr)["code"], "INDEX_JSON_TOO_LARGE")
            self.assertFalse(output_path.exists())

    def test_cli_fifo_is_rejected_without_blocking(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            fifo = parent / "input.fifo"
            output = parent / "output.json"
            os.mkfifo(fifo, 0o600)
            result = subprocess.run(
                [sys.executable, "-m", "investment.research.index_identity", "compile",
                 str(fifo), "--output", str(output)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stderr)["code"], "INDEX_INPUT_INVALID")
            self.assertFalse(output.exists())

    def test_cli_rejects_hardlinked_and_mutating_input(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            source = parent / "source.json"
            linked = parent / "linked.json"
            source.write_text(json.dumps(exact_packet()))
            os.link(source, linked)
            linked_result = subprocess.run(
                [sys.executable, "-m", "investment.research.index_identity", "compile",
                 str(linked), "--output", str(parent / "linked-output.json")],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(linked_result.returncode, 1, linked_result.stderr)
            self.assertEqual(json.loads(linked_result.stderr)["code"], "INDEX_INPUT_INVALID")
            linked.unlink()
            script = r'''
import os, sys
from investment.research import index_identity as target
real_read = target.os.read
fired = False
def mutating_read(descriptor, count):
    global fired
    data = real_read(descriptor, count)
    if not fired:
        fired = True
        info = os.stat(sys.argv[1])
        with open(sys.argv[1], "r+b") as handle:
            raw = handle.read()
            offset = raw.index(b" ")
            handle.seek(offset)
            handle.write(b"\\t")
        os.utime(sys.argv[1], ns=(info.st_atime_ns, info.st_mtime_ns))
    return data
target.os.read = mutating_read
raise SystemExit(target.main(["compile", sys.argv[1], "--output", sys.argv[2]]))
'''
            changed_result = subprocess.run(
                [sys.executable, "-c", script, str(source),
                 str(parent / "changed-output.json")],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(changed_result.returncode, 1, changed_result.stderr)
            self.assertEqual(json.loads(changed_result.stderr)["code"],
                             "INDEX_INPUT_INVALID")
            self.assertFalse((parent / "linked-output.json").exists())
            self.assertFalse((parent / "changed-output.json").exists())

    def test_cli_rejects_symlink_leaf_ancestor_and_output_without_following(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            real_parent = parent / "real"
            real_parent.mkdir(mode=0o700)
            source_path = real_parent / "input.json"
            source_path.write_text(json.dumps(exact_packet()))
            leaf_link = parent / "leaf.json"
            leaf_link.symlink_to(source_path)
            ancestor_link = parent / "linked-parent"
            ancestor_link.symlink_to(real_parent, target_is_directory=True)
            protected = parent / "protected.json"
            protected.write_bytes(b"protected\n")
            output_link = parent / "output.json"
            output_link.symlink_to(protected)
            cases = (
                (leaf_link, parent / "leaf-output.json", "INDEX_INPUT_INVALID"),
                (ancestor_link / "input.json", parent / "ancestor-output.json",
                 "INDEX_INPUT_INVALID"),
                (source_path, output_link, "INDEX_OUTPUT_INVALID"),
            )
            for input_path, output_path, code in cases:
                result = subprocess.run(
                    [sys.executable, "-m", "investment.research.index_identity", "compile",
                     str(input_path), "--output", str(output_path)],
                    cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    text=True, capture_output=True, timeout=10,
                )
                with self.subTest(code=code, input=input_path, output=output_path):
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(json.loads(result.stderr)["code"], code)
            self.assertEqual(protected.read_bytes(), b"protected\n")
            self.assertFalse((parent / "leaf-output.json").exists())
            self.assertFalse((parent / "ancestor-output.json").exists())

    def test_cli_rejects_renamed_input_ancestor_during_read(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_parent = parent / "input-parent"
            moved_parent = parent / "moved-parent"
            input_parent.mkdir(mode=0o700)
            input_path = input_parent / "input.json"
            input_path.write_text(json.dumps(exact_packet()))
            output_path = parent / "output.json"
            script = r'''
import os, sys
from investment.research import index_identity as target
real_read = target.os.read
fired = False
def attacking_read(descriptor, count):
    global fired
    data = real_read(descriptor, count)
    if not fired:
        fired = True
        os.rename(sys.argv[1], sys.argv[2])
        os.symlink(sys.argv[2], sys.argv[1], target_is_directory=True)
    return data
target.os.read = attacking_read
raise SystemExit(target.main(["compile", sys.argv[3], "--output", sys.argv[4]]))
'''
            result = subprocess.run(
                [sys.executable, "-c", script, str(input_parent), str(moved_parent),
                 str(input_path), str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stderr)["code"], "INDEX_INPUT_INVALID")
            self.assertFalse(output_path.exists())
            self.assertEqual(compile_packet((moved_parent / "input.json").read_bytes()),
                             validate_packet(exact_packet()))

    def test_cli_output_parent_replacement_is_pre_effect_failure(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_path = parent / "input.json"
            input_path.write_text(json.dumps(exact_packet()))
            output_parent = parent / "publish"
            moved_parent = parent / "publish-moved"
            output_parent.mkdir(mode=0o700)
            output_path = output_parent / "packet.json"
            output_path.write_bytes(b"prior-output\n")
            script = r'''
import os, sys
from investment.research import index_identity as target
real_fsync = target.os.fsync
fired = False
def attacking_fsync(descriptor):
    global fired
    real_fsync(descriptor)
    if not fired:
        fired = True
        os.rename(sys.argv[1], sys.argv[2])
        os.mkdir(sys.argv[1], 0o700)
target.os.fsync = attacking_fsync
raise SystemExit(target.main(["compile", sys.argv[3], "--output", sys.argv[4]]))
'''
            result = subprocess.run(
                [sys.executable, "-c", script, str(output_parent), str(moved_parent),
                 str(input_path), str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stderr)["code"], "INDEX_OUTPUT_FAILED")
            self.assertFalse(output_path.exists())
            self.assertEqual((moved_parent / "packet.json").read_bytes(), b"prior-output\n")
            self.assertEqual(list(output_parent.iterdir()), [])
            self.assertEqual(list(moved_parent.iterdir()), [moved_parent / "packet.json"])

    def test_cli_post_rename_directory_fsync_is_durability_unknown(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_path = parent / "input.json"
            output_path = parent / "output.json"
            input_path.write_text(json.dumps(exact_packet()))
            script = r'''
import os, sys
from investment.research import index_identity as target
real_fsync = target.os.fsync
calls = 0
def failing_fsync(descriptor):
    global calls
    calls += 1
    if calls == 2:
        raise OSError("synthetic post-rename durability failure /private/path")
    return real_fsync(descriptor)
target.os.fsync = failing_fsync
raise SystemExit(target.main(["compile", sys.argv[1], "--output", sys.argv[2]]))
'''
            result = subprocess.run(
                [sys.executable, "-c", script, str(input_path), str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stderr)["code"],
                             "INDEX_OUTPUT_DURABILITY_UNVERIFIED")
            self.assertEqual(compile_packet(output_path.read_bytes()), validate_packet(exact_packet()))
            self.assertEqual(sorted(item.name for item in parent.iterdir()),
                             ["input.json", "output.json"])

    def test_cli_real_shaped_compile_round_trip(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_path = parent / "input.json"
            output_path = parent / "output.json"
            input_path.write_text(json.dumps(exact_packet()))
            result = subprocess.run(
                [sys.executable, "-m", "investment.research.index_identity", "compile",
                 str(input_path), "--output", str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(compile_packet(output_path.read_bytes()), validate_packet(exact_packet()))

    def test_cli_validation_failure_is_sanitized_and_does_not_partially_replace(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            input_path = parent / "input.json"
            output_path = parent / "output.json"
            output_path.write_bytes(b"previous\n")
            packet = gated_packet()
            packet["identity"]["official_symbol"] = "^IXIC"
            input_path.write_text(json.dumps(packet))
            result = subprocess.run(
                [sys.executable, "-m", "investment.research.index_identity", "compile",
                 str(input_path), "--output", str(output_path)],
                cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, timeout=20,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(json.loads(result.stderr), {
                "status": "invalid", "code": "INDEX_OFFICIAL_IDENTITY_CONFUSION"
            })
            self.assertNotIn(str(parent), result.stderr)
            self.assertEqual(output_path.read_bytes(), b"previous\n")



    def test_generic_new_artifact_writer_is_deterministic_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as td:
            root = Path(td)
            root.chmod(0o700)
            target = root / "artifact.json"
            value = {"z": 1, "a": [True, None]}
            expected = b'{"a":[true,null],"z":1}\n'
            self.assertEqual(expected, canonical_json_bytes(value))
            receipt = write_new_json_atomic(value, target)
            self.assertEqual(expected, target.read_bytes())
            self.assertEqual(len(expected), receipt["bytes"])
            with self.assertRaisesRegex(IndexIdentityError, "^INDEX_OUTPUT_EXISTS$"):
                write_new_json_atomic(value, target)
            self.assertEqual(expected, target.read_bytes())

    def test_generic_new_artifact_writer_rejects_symlink_leaf(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as td:
            root = Path(td)
            root.chmod(0o700)
            victim = root / "victim"
            victim.write_bytes(b"old")
            link = root / "artifact"
            link.symlink_to(victim)
            with self.assertRaisesRegex(IndexIdentityError, "^INDEX_OUTPUT_EXISTS$"):
                write_new_bytes_atomic(b"new", link)
            self.assertEqual(b"old", victim.read_bytes())

if __name__ == "__main__":
    unittest.main()
