"""Read-only descriptive support geometry with hardened local I/O.

This module deliberately does not import or calculate future outcomes. It reports
historical training-cloud geometry, never a probability, forecast, or action.
"""
from __future__ import annotations

import datetime as dt
import errno
import hashlib
import json
import math
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Mapping, Sequence

ALLOWED_STATUS = {"inside", "edge", "outside", "inconclusive"}
KNOWN_SOURCES = {"TQQQ", "QQQ", "SPY", "TLT", "HYG"}
KNOWN_DISTANCE_FEATURES = {
    "tqqq_return_21", "tqqq_return_63", "tqqq_return_126",
    "tqqq_distance_from_126_high", "tqqq_realized_vol_21",
    "tqqq_downside_semivariance_63", "qqq_return_21", "qqq_return_63",
    "qqq_return_126", "tqqq_vs_3x_qqq_gap_21",
}
KNOWN_PROXY_FEATURES = {"spy_return_21", "tlt_return_21", "hyg_return_21"}
EXPECTED_PRICE_FIELD = "chart.result[0].indicators.adjclose[0].adjclose"
FIXED_INSIDE_QUANTILE = 0.95
FIXED_EDGE_QUANTILE = 0.99
FIXED_MATURITY_SESSIONS = 126


class DataContractError(ValueError):
    """A source, configuration, or output violates the local contract."""


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    dates: tuple[dt.date, ...]
    adjusted_market_prices: tuple[float, ...]
    path: str
    sha256: str
    byte_count: int

    def by_date(self) -> dict[dt.date, float]:
        return dict(zip(self.dates, self.adjusted_market_prices))


@dataclass(frozen=True)
class FeaturePanelRow:
    date: dt.date
    adjusted_market_price: float
    era: str
    features: Mapping[str, float | None]


@dataclass(frozen=True)
class RobustScaler:
    medians: Mapping[str, float]
    mads: Mapping[str, float]
    scales: Mapping[str, float]

    def transform(self, values: Mapping[str, float]) -> tuple[float, ...]:
        return tuple((values[name] - self.medians[name]) / self.scales[name] for name in self.medians)


def _exact_keys(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise DataContractError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise DataContractError(f"{label} keys mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    return value


def _string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value):
        raise DataContractError(f"{label} must be a nonempty string")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DataContractError(f"{label} must be an integer >= {minimum}")
    return value


def _number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise DataContractError(f"{label} must be a finite number")
    return float(value)


def _date(value: Any, label: str) -> dt.date:
    text = _string(value, label)
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise DataContractError(f"{label} must be ISO date YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise DataContractError(f"{label} must be canonical ISO date")
    return parsed


def validate_relative_path(value: Any, label: str) -> str:
    text = _string(value, label)
    if "\\" in text or ":" in text:
        raise DataContractError(f"{label} must use a relative POSIX path")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise DataContractError(f"{label} must not be absolute or contain dot segments")
    if str(path) != text:
        raise DataContractError(f"{label} must be normalized")
    return text


@dataclass
class RootAnchor:
    """Held descriptor plus an explicit local trusted-root contract."""
    fd: int
    path: Path
    device: int
    inode: int
    uid: int
    mode: int

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "RootAnchor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IFMT(value.st_mode)


def _validate_trusted_stat(value: os.stat_result, label: str, *, directory: bool, device: int | None = None) -> None:
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(value.st_mode):
        raise DataContractError(f"{label} has wrong file type or is a symlink")
    if value.st_uid not in {0, os.getuid()}:
        raise DataContractError(f"{label} is not owned by current uid or root")
    if stat.S_IMODE(value.st_mode) & 0o022:
        raise DataContractError(f"{label} is group/world writable")
    if device is not None and value.st_dev != device:
        raise DataContractError(f"{label} crosses filesystem device")


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _validate_system_ancestors(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            value = os.lstat(current)
        except OSError as exc:
            raise DataContractError(f"{label} ancestor is missing") from exc
        _validate_trusted_stat(value, f"{label} ancestor", directory=True)


def open_root_anchor(root: Path, label: str = "root") -> RootAnchor:
    """Bind a local trusted root; same-UID concurrent replacement is out of scope."""
    absolute = _absolute_without_resolving(root)
    _validate_system_ancestors(absolute, label)
    before = os.lstat(absolute)
    _validate_trusted_stat(before, label, directory=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(absolute, flags)
    except OSError as exc:
        raise DataContractError(f"{label} does not name an accessible trusted directory") from exc
    try:
        after = os.fstat(fd)
        if _identity(before) != _identity(after):
            raise DataContractError(f"{label} changed while anchoring")
        _validate_trusted_stat(after, label, directory=True)
        return RootAnchor(fd, absolute, after.st_dev, after.st_ino, after.st_uid, stat.S_IMODE(after.st_mode))
    except Exception:
        os.close(fd)
        raise


def _revalidate_anchor(anchor: RootAnchor, label: str) -> None:
    current = os.fstat(anchor.fd)
    if (current.st_dev, current.st_ino, current.st_uid, stat.S_IMODE(current.st_mode)) != (anchor.device, anchor.inode, anchor.uid, anchor.mode):
        raise DataContractError(f"{label} root descriptor changed")
    _validate_trusted_stat(current, label, directory=True)


def _trusted_candidate(anchor: RootAnchor, relative_path: str, label: str, *, require_file: bool) -> Path:
    relative = validate_relative_path(relative_path, label)
    _revalidate_anchor(anchor, label)
    parts = PurePosixPath(relative).parts
    current = anchor.path
    for part in parts[:-1]:
        current = current / part
        try:
            value = os.lstat(current)
        except OSError as exc:
            raise DataContractError(f"{label} ancestor is missing") from exc
        _validate_trusted_stat(value, f"{label} ancestor", directory=True, device=anchor.device)
    candidate = current / parts[-1]
    if require_file:
        try:
            value = os.lstat(candidate)
        except OSError as exc:
            raise DataContractError(f"{label} file is missing") from exc
        _validate_trusted_stat(value, label, directory=False, device=anchor.device)
    elif candidate.exists() or candidate.is_symlink():
        value = os.lstat(candidate)
        _validate_trusted_stat(value, label, directory=False, device=anchor.device)
    return candidate


def resolve_source_path(source_root: Path, relative_path: str) -> Path:
    with open_root_anchor(source_root, "source root") as anchor:
        return _trusted_candidate(anchor, relative_path, "source path", require_file=True)


def resolve_output_path(output_root: Path, relative_path: str | Path) -> Path:
    with open_root_anchor(output_root, "output root") as anchor:
        return _trusted_candidate(anchor, str(relative_path), "output path", require_file=False)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("write returned no progress")
        offset += written


def _stable_readback(path: Path, anchor: RootAnchor) -> bytes:
    before = os.lstat(path)
    _validate_trusted_stat(before, "output readback", directory=False, device=anchor.device)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if _identity(before) != _identity(opened):
            raise DataContractError("output changed while opening readback")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        immediate = os.lstat(path)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise DataContractError("output changed during stable readback")
        if _identity(after) != _identity(immediate):
            raise DataContractError("output path changed during stable readback")
        return b"".join(chunks)
    finally:
        os.close(fd)


def write_canonical_json(output_root: Path, relative_path: str | Path, value: Any, *, root_anchor: RootAnchor | None = None) -> str:
    """Durably publish beneath a validated local trusted root."""
    payload = canonical_json_bytes(value)
    owned_anchor = root_anchor is None
    anchor = root_anchor or open_root_anchor(output_root, "output root")
    destination: Path | None = None
    temporary: Path | None = None
    fd: int | None = None
    try:
        destination = _trusted_candidate(anchor, str(relative_path), "output path", require_file=False)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for _ in range(32):
            candidate = destination.parent / f".{destination.name}.tmp.{os.getpid()}.{secrets.token_hex(12)}"
            try:
                fd = os.open(candidate, flags, 0o600)
                temporary = candidate
                break
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
        if fd is None or temporary is None:
            raise DataContractError("could not allocate unique output temp file")
        temporary_stat = os.fstat(fd)
        _validate_trusted_stat(temporary_stat, "output temp", directory=False, device=anchor.device)
        if stat.S_IMODE(temporary_stat.st_mode) != 0o600:
            raise DataContractError("output temp mode is not 0600")
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = None
        immediate = os.lstat(temporary)
        if _identity(immediate) != _identity(temporary_stat):
            raise DataContractError("output temp changed before replace")
        _revalidate_anchor(anchor, "output")
        _trusted_candidate(anchor, str(relative_path), "output path", require_file=False)
        os.replace(temporary, destination)
        temporary = None
        directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        observed = _stable_readback(destination, anchor)
        if observed != payload:
            raise DataContractError("output stable readback mismatch")
        return hashlib.sha256(observed).hexdigest()
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        if owned_anchor:
            anchor.close()


def _read_stable_source(anchor: RootAnchor, relative_path: str) -> bytes:
    path = _trusted_candidate(anchor, relative_path, "source", require_file=True)
    before = os.lstat(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if _identity(before) != _identity(opened):
            raise DataContractError("source changed while opening")
        _validate_trusted_stat(opened, "source", directory=False, device=anchor.device)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        immediate = os.lstat(path)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise DataContractError("source changed during read")
        if _identity(after) != _identity(immediate):
            raise DataContractError("source path changed during read")
        _revalidate_anchor(anchor, "source")
        return b"".join(chunks)
    finally:
        os.close(fd)

def load_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataContractError("configuration is unreadable JSON") from exc
    config = dict(_exact_keys(raw, {
        "schema_version", "analysis_as_of", "expected_latest_completed_exchange_session",
        "price_basis", "training_cloud_maturity_sessions", "sources", "distance_features",
        "informational_proxy_features", "knn", "eras", "integration",
    }, "config"))
    if config["schema_version"] != "probabilistic-manifold-config-v1":
        raise DataContractError("unsupported config schema_version")
    analysis_as_of = _date(config["analysis_as_of"], "analysis_as_of")
    expected_session = _date(config["expected_latest_completed_exchange_session"], "expected_latest_completed_exchange_session")
    if expected_session > analysis_as_of:
        raise DataContractError("expected session cannot be after analysis_as_of")

    basis = _exact_keys(config["price_basis"], {"field", "label", "limitations"}, "price_basis")
    for key in basis:
        _string(basis[key], f"price_basis.{key}")
    if basis["field"] != EXPECTED_PRICE_FIELD:
        raise DataContractError("price_basis.field must match the parsed adjusted-close path")
    if basis["label"] != "adjusted_market_price":
        raise DataContractError("price basis label must be adjusted_market_price")

    maturity = _integer(config["training_cloud_maturity_sessions"], "training_cloud_maturity_sessions", minimum=1)
    if maturity != FIXED_MATURITY_SESSIONS:
        raise DataContractError("training_cloud_maturity_sessions must equal 126")

    sources = _exact_keys(config["sources"], KNOWN_SOURCES, "sources")
    for symbol, value in sources.items():
        spec = _exact_keys(value, {"symbol", "required", "path", "sha256", "bytes", "expected_start", "expected_end"}, f"sources.{symbol}")
        if spec["symbol"] != symbol:
            raise DataContractError(f"sources.{symbol}.symbol mismatch")
        if type(spec["required"]) is not bool:
            raise DataContractError(f"sources.{symbol}.required must be boolean")
        if symbol in {"TQQQ", "QQQ"} and spec["required"] is not True:
            raise DataContractError(f"{symbol} must be required true")
        validate_relative_path(spec["path"], f"sources.{symbol}.path")
        digest = _string(spec["sha256"], f"sources.{symbol}.sha256")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise DataContractError(f"sources.{symbol}.sha256 must be 64 lowercase hex characters")
        _integer(spec["bytes"], f"sources.{symbol}.bytes", minimum=1)
        start = _date(spec["expected_start"], f"sources.{symbol}.expected_start")
        end = _date(spec["expected_end"], f"sources.{symbol}.expected_end")
        if end < start:
            raise DataContractError(f"sources.{symbol} end precedes start")

    for key, known in (("distance_features", KNOWN_DISTANCE_FEATURES), ("informational_proxy_features", KNOWN_PROXY_FEATURES)):
        values = config[key]
        if type(values) is not list or not values or any(type(item) is not str for item in values):
            raise DataContractError(f"{key} must be a nonempty string list")
        if len(values) != len(set(values)):
            raise DataContractError(f"{key} must contain unique features")
        unknown = set(values) - known
        if unknown:
            raise DataContractError(f"{key} contains unknown features: {sorted(unknown)}")

    knn = _exact_keys(config["knn"], {
        "k", "calibration_stride", "inside_quantile", "edge_quantile",
        "minimum_training_rows", "minimum_nonoverlap_episodes",
        "minimum_dependence_adjusted_ess", "maximum_staleness_calendar_days",
    }, "knn")
    k = _integer(knn["k"], "knn.k", minimum=1)
    _integer(knn["calibration_stride"], "knn.calibration_stride", minimum=1)
    minimum_rows = _integer(knn["minimum_training_rows"], "knn.minimum_training_rows", minimum=1)
    if k > minimum_rows:
        raise DataContractError("knn.k cannot exceed minimum_training_rows")
    _integer(knn["minimum_nonoverlap_episodes"], "knn.minimum_nonoverlap_episodes", minimum=1)
    if _number(knn["minimum_dependence_adjusted_ess"], "knn.minimum_dependence_adjusted_ess") <= 0:
        raise DataContractError("minimum_dependence_adjusted_ess must be positive")
    _integer(knn["maximum_staleness_calendar_days"], "knn.maximum_staleness_calendar_days", minimum=0)
    inside = _number(knn["inside_quantile"], "knn.inside_quantile")
    edge = _number(knn["edge_quantile"], "knn.edge_quantile")
    if inside != FIXED_INSIDE_QUANTILE or edge != FIXED_EDGE_QUANTILE:
        raise DataContractError("training-cloud quantiles are frozen at 0.95 and 0.99")

    eras = config["eras"]
    if type(eras) is not list or not eras:
        raise DataContractError("eras must be a nonempty list")
    seen_names: set[str] = set()
    previous_end: dt.date | None = None
    for index, value in enumerate(eras):
        rule = _exact_keys(value, {"name", "start", "end"}, f"eras[{index}]")
        name = _string(rule["name"], f"eras[{index}].name")
        if name in seen_names:
            raise DataContractError("era names must be unique")
        seen_names.add(name)
        start = _date(rule["start"], f"eras[{index}].start")
        end = _date(rule["end"], f"eras[{index}].end")
        if end < start or (previous_end is not None and start <= previous_end):
            raise DataContractError("eras must be ordered and non-overlapping")
        previous_end = end

    integration = _exact_keys(config["integration"], {"policy_scope", "probability_feature_compatible"}, "integration")
    if integration["policy_scope"] != "descriptive_training_cloud_v1":
        raise DataContractError("unsupported integration.policy_scope")
    if integration["probability_feature_compatible"] is not False:
        raise DataContractError("probability_feature_compatible must be false for this slice")
    return config


def load_bound_price_series(source_root: Path, symbol: str, spec: Mapping[str, Any], *, root_anchor: RootAnchor | None = None) -> PriceSeries:
    """Load one immutable, identity-bound adjusted-price series.

    The caller owns the symbol allowlist. This generic loader validates the bound
    path/hash/size/symbol/date contract and performs no provider access.
    """
    if type(symbol) is not str or not symbol or spec.get("symbol") != symbol:
        raise DataContractError("source symbol contract mismatch")
    owned_anchor = root_anchor is None
    anchor = root_anchor or open_root_anchor(source_root, "source root")
    try:
        payload = _read_stable_source(anchor, spec["path"])
    finally:
        if owned_anchor:
            anchor.close()
    observed_hash = hashlib.sha256(payload).hexdigest()
    if observed_hash != spec["sha256"]:
        raise DataContractError(f"sha256 mismatch for {symbol}")
    if len(payload) != spec["bytes"]:
        raise DataContractError(f"byte-count mismatch for {symbol}")
    try:
        result = json.loads(payload)["chart"]["result"][0]
        observed_symbol = result["meta"]["symbol"]
        timestamps = result["timestamp"]
        prices = result["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise DataContractError(f"invalid chart structure for {symbol}") from exc
    if observed_symbol != symbol:
        raise DataContractError(f"symbol mismatch: expected {symbol}, got {observed_symbol}")
    if type(timestamps) is not list or type(prices) is not list or len(timestamps) != len(prices) or not timestamps:
        raise DataContractError(f"timestamp/price length mismatch for {symbol}")
    dates: list[dt.date] = []
    values: list[float] = []
    for timestamp, raw_price in zip(timestamps, prices):
        if type(timestamp) is not int or type(raw_price) not in (int, float):
            raise DataContractError(f"invalid row types for {symbol}")
        date = dt.datetime.fromtimestamp(timestamp, dt.UTC).date()
        price = float(raw_price)
        if not math.isfinite(price) or price <= 0:
            raise DataContractError(f"invalid adjusted price for {symbol} on {date}")
        dates.append(date)
        values.append(price)
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise DataContractError(f"dates are not strictly increasing for {symbol}")
    if dates[0].isoformat() != spec["expected_start"] or dates[-1].isoformat() != spec["expected_end"]:
        raise DataContractError(f"date-range mismatch for {symbol}")
    return PriceSeries(symbol, tuple(dates), tuple(values), spec["path"], observed_hash, len(payload))


def load_price_series(source_root: Path, symbol: str, spec: Mapping[str, Any], *, root_anchor: RootAnchor | None = None) -> PriceSeries:
    """Backward-compatible TQQQ support wrapper around the generic bound loader."""
    if symbol not in KNOWN_SOURCES:
        raise DataContractError("source symbol contract mismatch")
    return load_bound_price_series(source_root, symbol, spec, root_anchor=root_anchor)


def source_manifest(series: Mapping[str, PriceSeries], config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "probabilistic-manifold-source-manifest-v1",
        "price_basis": config["price_basis"],
        "sources": [
            {"symbol": symbol, "path": item.path, "sha256": item.sha256,
             "bytes": item.byte_count, "rows": len(item.dates),
             "date_start": item.dates[0].isoformat(), "date_end": item.dates[-1].isoformat(),
             "required": bool(config["sources"][symbol]["required"])}
            for symbol, item in sorted(series.items())
        ],
    }


def _return(prices: Sequence[float], index: int, sessions: int) -> float | None:
    return None if index < sessions else prices[index] / prices[index - sessions] - 1.0


def _log_returns(prices: Sequence[float], index: int, sessions: int) -> list[float] | None:
    if index < sessions:
        return None
    return [math.log(prices[j] / prices[j - 1]) for j in range(index - sessions + 1, index + 1)]


def _realized_vol(prices: Sequence[float], index: int, sessions: int) -> float | None:
    values = _log_returns(prices, index, sessions)
    if values is None:
        return None
    center = sum(values) / len(values)
    return math.sqrt(252.0 * sum((value - center) ** 2 for value in values) / len(values))


def _downside_semivariance(prices: Sequence[float], index: int, sessions: int) -> float | None:
    values = _log_returns(prices, index, sessions)
    return None if values is None else 252.0 * sum(min(value, 0.0) ** 2 for value in values) / len(values)


def _era(date: dt.date, rules: Sequence[Mapping[str, str]]) -> str:
    matches = [rule["name"] for rule in rules if dt.date.fromisoformat(rule["start"]) <= date <= dt.date.fromisoformat(rule["end"])]
    if len(matches) != 1:
        raise DataContractError(f"date {date} matches {len(matches)} era rules")
    return matches[0]


def build_feature_panel(series: Mapping[str, PriceSeries], config: Mapping[str, Any]) -> list[FeaturePanelRow]:
    primary = series["TQQQ"]
    qqq_map = series["QQQ"].by_date()
    if any(date not in qqq_map for date in primary.dates):
        raise DataContractError("QQQ is missing TQQQ dates; no forward fill allowed")
    qqq_prices = [qqq_map[date] for date in primary.dates]
    optional_aligned = {symbol: [item.by_date().get(date) for date in primary.dates]
                        for symbol, item in series.items() if symbol not in {"TQQQ", "QQQ"}}
    rows: list[FeaturePanelRow] = []
    for i, date in enumerate(primary.dates):
        t21, q21 = _return(primary.adjusted_market_prices, i, 21), _return(qqq_prices, i, 21)
        features: dict[str, float | None] = {
            "tqqq_return_21": t21,
            "tqqq_return_63": _return(primary.adjusted_market_prices, i, 63),
            "tqqq_return_126": _return(primary.adjusted_market_prices, i, 126),
            "tqqq_distance_from_126_high": None if i < 125 else primary.adjusted_market_prices[i] / max(primary.adjusted_market_prices[i-125:i+1]) - 1.0,
            "tqqq_realized_vol_21": _realized_vol(primary.adjusted_market_prices, i, 21),
            "tqqq_downside_semivariance_63": _downside_semivariance(primary.adjusted_market_prices, i, 63),
            "qqq_return_21": q21,
            "qqq_return_63": _return(qqq_prices, i, 63),
            "qqq_return_126": _return(qqq_prices, i, 126),
            "tqqq_vs_3x_qqq_gap_21": None if t21 is None or q21 is None else t21 - ((1.0 + q21) ** 3 - 1.0),
        }
        for symbol in ("SPY", "TLT", "HYG"):
            aligned = optional_aligned.get(symbol)
            value = None
            if aligned is not None and i >= 21 and aligned[i] is not None and aligned[i-21] is not None:
                value = aligned[i] / aligned[i-21] - 1.0
            features[f"{symbol.lower()}_return_21"] = value
        rows.append(FeaturePanelRow(date, primary.adjusted_market_prices[i], _era(date, config["eras"]), features))
    return rows


def select_support_training_rows(panel: Sequence[FeaturePanelRow], origin_index: int, feature_names: Sequence[str], maturity_horizon: int) -> list[FeaturePanelRow]:
    return [row for index, row in enumerate(panel[:origin_index])
            if index + maturity_horizon <= origin_index
            and all(row.features.get(name) is not None for name in feature_names)]


def fit_robust_scaler(rows: Sequence[FeaturePanelRow], feature_names: Sequence[str]) -> RobustScaler:
    centers: dict[str, float] = {}
    mads: dict[str, float] = {}
    scales: dict[str, float] = {}
    for name in feature_names:
        values = [float(row.features[name]) for row in rows if row.features.get(name) is not None]
        if len(values) != len(rows) or not values:
            raise DataContractError(f"training feature {name} contains missing values")
        center = median(values)
        mad = median(abs(value - center) for value in values)
        scale = 1.4826 * mad
        if not math.isfinite(scale) or scale <= 1e-12:
            raise DataContractError(f"training MAD is zero for {name}")
        centers[name], mads[name], scales[name] = center, mad, scale
    return RobustScaler(centers, mads, scales)


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((left-right) ** 2 for left, right in zip(a, b)))


def nearest_neighbors(training: Sequence[FeaturePanelRow], query: FeaturePanelRow, scaler: RobustScaler, feature_names: Sequence[str], k: int) -> list[dict[str, Any]]:
    query_raw = {name: float(query.features[name]) for name in feature_names}
    query_scaled = scaler.transform(query_raw)
    neighbors = []
    for row in training:
        raw = {name: float(row.features[name]) for name in feature_names}
        neighbors.append({"date": row.date.isoformat(), "era": row.era,
                          "distance": _distance(query_scaled, scaler.transform(raw)),
                          "raw_euclidean_distance": _distance(tuple(query_raw[name] for name in feature_names), tuple(raw[name] for name in feature_names))})
    neighbors.sort(key=lambda item: (item["distance"], item["date"]))
    return neighbors[:k]


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise DataContractError("empty quantile input")
    position = (len(ordered)-1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] if lower == upper else ordered[lower] + (ordered[upper]-ordered[lower]) * (position-lower)


def classify_geometry(k_distance: float, inside_threshold: float, edge_threshold: float) -> str:
    if not (0 <= inside_threshold < edge_threshold) or not math.isfinite(k_distance):
        return "inconclusive"
    return "inside" if k_distance <= inside_threshold else "edge" if k_distance <= edge_threshold else "outside"


def is_stale(as_of: dt.date, origin: dt.date, maximum_calendar_days: int) -> bool:
    return (as_of-origin).days > maximum_calendar_days


def calibration_k_distances(training: Sequence[FeaturePanelRow], scaler: RobustScaler, feature_names: Sequence[str], k: int, stride: int) -> list[float]:
    scaled = [scaler.transform({name: float(row.features[name]) for name in feature_names}) for row in training]
    results = []
    for index in range(0, len(training), stride):
        distances = sorted(_distance(scaled[index], other) for j, other in enumerate(scaled) if j != index)
        if len(distances) >= k:
            results.append(distances[k-1])
    return results


def nonoverlap_episode_count(neighbor_dates: Sequence[dt.date], panel_dates: Sequence[dt.date], horizon: int) -> int:
    date_index = {date: i for i, date in enumerate(panel_dates)}
    positions = sorted(date_index[date] for date in neighbor_dates)
    count, last_end = 0, -1
    for position in positions:
        if position > last_end:
            count += 1
            last_end = position + horizon
    return count


def dependence_adjusted_ess(neighbor_dates: Sequence[dt.date], panel_dates: Sequence[dt.date], horizon: int) -> float:
    date_index = {date: i for i, date in enumerate(panel_dates)}
    positions = [date_index[date] for date in neighbor_dates]
    n = len(positions)
    if not n:
        return 0.0
    dependence = sum(max(0, horizon-abs(left-right))/horizon for left in positions for right in positions)
    return n*n/dependence if dependence else float(n)


def _feature_diagnostics(rows: Sequence[FeaturePanelRow], feature_names: Sequence[str]) -> dict[str, Any]:
    result = {}
    for name in feature_names:
        values = [float(row.features[name]) for row in rows if row.features.get(name) is not None]
        result[name] = {"non_missing": len(values), "missing": len(rows)-len(values),
                        "minimum": min(values) if values else None, "maximum": max(values) if values else None}
    return result


def feature_correlations(rows: Sequence[FeaturePanelRow], feature_names: Sequence[str]) -> list[dict[str, Any]]:
    """Return all training-cloud Pearson pairs as descriptive collinearity diagnostics."""
    result: list[dict[str, Any]] = []
    for left_index, left in enumerate(feature_names):
        for right in feature_names[left_index+1:]:
            pairs = [(float(row.features[left]), float(row.features[right])) for row in rows
                     if row.features.get(left) is not None and row.features.get(right) is not None]
            if len(pairs) < 2:
                correlation = None
            else:
                left_mean = sum(item[0] for item in pairs)/len(pairs)
                right_mean = sum(item[1] for item in pairs)/len(pairs)
                numerator = sum((a-left_mean)*(b-right_mean) for a, b in pairs)
                left_ss = sum((a-left_mean)**2 for a, _ in pairs)
                right_ss = sum((b-right_mean)**2 for _, b in pairs)
                correlation = None if left_ss <= 0 or right_ss <= 0 else numerator/math.sqrt(left_ss*right_ss)
            result.append({"left": left, "right": right, "rows": len(pairs), "pearson_correlation": correlation})
    result.sort(key=lambda item: (-(abs(item["pearson_correlation"]) if item["pearson_correlation"] is not None else -1), item["left"], item["right"]))
    return result


def run_support(config_path: Path, source_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_config(config_path)
    loaded: dict[str, PriceSeries] = {}
    source_warnings: list[str] = []
    with open_root_anchor(source_root, "source root") as source_anchor:
        for symbol, spec in config["sources"].items():
            try:
                loaded[symbol] = load_price_series(source_root, symbol, spec, root_anchor=source_anchor)
            except DataContractError as exc:
                if spec["required"]:
                    raise
                source_warnings.append(str(exc))
    manifest = source_manifest(loaded, config)
    panel = build_feature_panel(loaded, config)
    as_of = dt.date.fromisoformat(config["analysis_as_of"])
    eligible = [(i, row) for i, row in enumerate(panel) if row.date <= as_of]
    if not eligible:
        raise DataContractError("no panel row on or before analysis_as_of")
    origin_index, origin = eligible[-1]
    feature_names = list(config["distance_features"])
    geometry_reasons: list[str] = []
    staleness = (as_of-origin.date).days
    if is_stale(as_of, origin.date, config["knn"]["maximum_staleness_calendar_days"]):
        geometry_reasons.append("origin_is_stale")
    if any(origin.features.get(name) is None for name in feature_names):
        geometry_reasons.append("origin_missing_distance_feature")
    training = select_support_training_rows(panel, origin_index, feature_names, config["training_cloud_maturity_sessions"])
    if len(training) < config["knn"]["minimum_training_rows"]:
        geometry_reasons.append("insufficient_training_cloud_rows")

    geometry_status = "inconclusive"
    neighbors: list[dict[str, Any]] = []
    empirical_quantiles: dict[str, float] = {}
    nonoverlap_count, ess = 0, 0.0
    scaler_summary: dict[str, Any] = {}
    if not geometry_reasons:
        scaler = fit_robust_scaler(training, feature_names)
        scaler_summary = {name: {"median": scaler.medians[name], "mad": scaler.mads[name], "scale_1_4826_mad": scaler.scales[name]} for name in feature_names}
        k = config["knn"]["k"]
        neighbors = nearest_neighbors(training, origin, scaler, feature_names, k)
        empirical = calibration_k_distances(training, scaler, feature_names, k, config["knn"]["calibration_stride"])
        empirical_quantiles = {
            "q95_k_distance": _quantile(empirical, config["knn"]["inside_quantile"]),
            "q99_k_distance": _quantile(empirical, config["knn"]["edge_quantile"]),
        }
        geometry_status = classify_geometry(neighbors[-1]["distance"], empirical_quantiles["q95_k_distance"], empirical_quantiles["q99_k_distance"])
        neighbor_dates = [dt.date.fromisoformat(item["date"]) for item in neighbors]
        horizon = config["training_cloud_maturity_sessions"]
        nonoverlap_count = nonoverlap_episode_count(neighbor_dates, [row.date for row in panel], horizon)
        ess = dependence_adjusted_ess(neighbor_dates, [row.date for row in panel], horizon)
        if nonoverlap_count < config["knn"]["minimum_nonoverlap_episodes"]:
            geometry_reasons.append("too_few_nonoverlapping_neighbor_episodes")
        if ess < config["knn"]["minimum_dependence_adjusted_ess"]:
            geometry_reasons.append("dependence_adjusted_ess_below_minimum")
        if geometry_reasons:
            geometry_status = "inconclusive"

    expected = dt.date.fromisoformat(config["expected_latest_completed_exchange_session"])
    required_ends = {symbol: loaded[symbol].dates[-1] for symbol in ("TQQQ", "QQQ")}
    missing_latest = sorted(symbol for symbol, end in required_ends.items() if end < expected)
    integration_reasons: list[str] = []
    if missing_latest:
        integration_reasons.append("expected_latest_completed_exchange_session_missing")
    if config["integration"]["probability_feature_compatible"] is False:
        integration_reasons.append("probability_feature_compatible_false")
    current_status = "inconclusive" if integration_reasons else geometry_status
    era_counts: dict[str, int] = {}
    for item in neighbors:
        era_counts[item["era"]] = era_counts.get(item["era"], 0) + 1
    all_features = feature_names + list(config["informational_proxy_features"])
    packet = {
        "schema_version": "probabilistic-manifold-support-packet-v2",
        "status": current_status,
        "status_reasons": integration_reasons,
        "origin_id": f"origin_{origin.date.isoformat()}",
        "policy_scope": config["integration"]["policy_scope"],
        "probability_feature_compatible": False,
        "claim_scope": "descriptive historical training-cloud geometry only; no outcome access, probability, forecast, expected return, or action",
        "analysis_as_of": as_of.isoformat(),
        "expected_latest_completed_exchange_session": expected.isoformat(),
        "source_freshness": {"passed": not missing_latest, "missing_symbols": missing_latest,
                             "observed_required_end_dates": {symbol: date.isoformat() for symbol, date in sorted(required_ends.items())}},
        "origin": {"date": origin.date.isoformat(), "calendar_staleness_days": staleness,
                   "era": origin.era, "adjusted_market_price": origin.adjusted_market_price,
                   "features": dict(origin.features)},
        "basis": config["price_basis"],
        "support_geometry": {
            "status": geometry_status,
            "status_reasons": geometry_reasons,
            "scope": "in_sample_descriptive_training_cloud",
            "training": {"rows": len(training), "date_start": training[0].date.isoformat() if training else None,
                         "date_end": training[-1].date.isoformat() if training else None,
                         "selection": "feature-complete rows at least primary_sessions before origin; no outcomes accessed",
                         "scaler_fit_scope": "training-cloud rows only; origin excluded", "robust_scaler": scaler_summary,
                         "pairwise_feature_correlations": feature_correlations(training, feature_names)},
            "knn": {"k": config["knn"]["k"],
                    "metric": "Euclidean distance in original feature coordinates after training-only median/MAD scaling; no embedding",
                    "neighbors": neighbors,
                    "in_sample_empirical_training_cloud_quantiles": empirical_quantiles,
                    "nonoverlap_episode_count_126": nonoverlap_count,
                    "dependence_adjusted_ess_overlap_kernel": ess,
                    "neighbor_era_counts": era_counts},
        },
        "panel": {"rows": len(panel), "date_start": panel[0].date.isoformat(), "date_end": panel[-1].date.isoformat(),
                  "feature_diagnostics": _feature_diagnostics(panel, all_features)},
        "source_warnings": source_warnings,
        "outcomes_accessed": False,
        "protected_outcomes_accessed": False,
    }
    if current_status not in ALLOWED_STATUS or geometry_status not in ALLOWED_STATUS:
        raise AssertionError("invalid status")
    return packet, manifest
