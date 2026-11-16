"""Optional future-label calculation, isolated from the support CLI path."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .core import DataContractError, PriceSeries


@dataclass(frozen=True)
class MatureOutcome:
    origin_date: str
    horizon_sessions: int
    end_date: str
    return_value: float
    max_drawdown: float
    relative_qqq_return: float
    material_loss: bool


def load_outcome_config(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataContractError("outcome configuration is unreadable JSON") from exc
    expected = {"schema_version", "primary_sessions", "provisional_sessions", "material_loss_drawdown_threshold"}
    if type(value) is not dict or set(value) != expected:
        raise DataContractError("outcome configuration keys mismatch")
    if value["schema_version"] != "probabilistic-manifold-outcomes-config-v1":
        raise DataContractError("unsupported outcome configuration schema")
    primary, provisional, threshold = value["primary_sessions"], value["provisional_sessions"], value["material_loss_drawdown_threshold"]
    if type(primary) is not int or primary <= 0 or type(provisional) is not int or provisional <= primary:
        raise DataContractError("outcome horizons must be positive and provisional must exceed primary")
    if type(threshold) not in (int, float) or not -1.0 < float(threshold) < 0.0:
        raise DataContractError("material-loss threshold must be between -1 and 0")
    return value


def calculate_mature_outcomes(series: Mapping[str, PriceSeries], horizon: int, material_loss_threshold: float) -> list[MatureOutcome]:
    """Calculate labels only where the complete future horizon already exists."""
    if type(horizon) is not int or horizon <= 0:
        raise DataContractError("horizon must be a positive integer")
    tqqq = series["TQQQ"]
    qqq_map = series["QQQ"].by_date()
    if any(date not in qqq_map for date in tqqq.dates):
        raise DataContractError("QQQ is missing TQQQ dates; no forward fill allowed")
    qqq: Sequence[float] = [qqq_map[date] for date in tqqq.dates]
    results: list[MatureOutcome] = []
    for index in range(0, len(tqqq.dates)-horizon):
        end = index+horizon
        path = tqqq.adjusted_market_prices[index:end+1]
        peak, drawdown = path[0], 0.0
        for price in path:
            peak = max(peak, price)
            drawdown = min(drawdown, price/peak-1.0)
        t_return = tqqq.adjusted_market_prices[end]/tqqq.adjusted_market_prices[index]-1.0
        q_return = qqq[end]/qqq[index]-1.0
        results.append(MatureOutcome(tqqq.dates[index].isoformat(), horizon, tqqq.dates[end].isoformat(),
                                     t_return, drawdown, t_return-q_return, drawdown <= material_loss_threshold))
    return results
