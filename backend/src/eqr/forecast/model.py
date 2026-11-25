"""1-2 month forecast: expected return vs the Nifty from a small ridge regression, and a range
whose width comes from the stock's own volatility (plus results-day jumps), scaled so the 80%
band held ~80% of outcomes in the fitting years. The fitted model is judged on later years it
never saw; it only gives a lean when that held-out test showed skill."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

FEATURES = ("mom_12_1", "rev_1m", "surprise", "value")
HORIZONS = {"1m": 21, "2m": 42}  # trading days
Z80, Z50 = NormalDist().inv_cdf(0.90), NormalDist().inv_cdf(0.75)
RIDGE = 0.02  # shrinkage per observation, on standardised inputs
MODEL_PATH = Path(__file__).resolve().parents[3] / "config" / "forecast_model.json"
_N = NormalDist()


@dataclass(frozen=True)
class HorizonModel:
    days: int
    intercept: float
    coefs: dict[str, float]  # per standardised input
    means: dict[str, float]
    stds: dict[str, float]
    vol_scale: float  # multiplies the raw volatility so the 80% band is calibrated
    lean_up: float  # predicted excess at the top fifth of the fitting sample
    lean_down: float  # ... and the bottom fifth

    def predict_excess(self, x: dict[str, float | None]) -> float:
        out = self.intercept
        for k in FEATURES:
            v = x.get(k)
            if v is None or self.stds[k] == 0:
                continue  # unknown input counts as average
            out += self.coefs[k] * (v - self.means[k]) / self.stds[k]
        return out


@dataclass(frozen=True)
class ForecastModel:
    horizons: dict[str, HorizonModel]
    fitted_on: str
    tested_on: str
    test: dict[str, dict[str, Any]] = field(default_factory=dict)
    has_edge: dict[str, bool] = field(default_factory=dict)

    def save(self, path: Path = MODEL_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, default=str))

    @staticmethod
    def load(path: Path = MODEL_PATH) -> ForecastModel | None:
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        hs = {k: HorizonModel(**v) for k, v in raw["horizons"].items()}
        return ForecastModel(
            hs, raw["fitted_on"], raw["tested_on"], raw.get("test", {}), raw.get("has_edge", {})
        )


def _sigma_excess(row: dict[str, Any], days: int) -> float:
    var = row["vol_excess_daily"] ** 2 * days + (row.get("jump_var") or 0.0) * row.get(
        f"event_{days}", 0
    )
    return math.sqrt(var)


def fit_horizon(rows: list[dict[str, Any]], name: str) -> HorizonModel:
    days = HORIZONS[name]
    data = [r for r in rows if r.get(f"y_{name}") is not None]
    if len(data) < 50:
        raise ValueError(f"Only {len(data)} observations for {name}; need 50")
    df = pd.DataFrame(data)
    means = {k: float(df[k].mean(skipna=True)) if df[k].notna().any() else 0.0 for k in FEATURES}
    stds = {k: float(df[k].std(skipna=True)) if df[k].notna().sum() > 1 else 0.0 for k in FEATURES}
    X = np.column_stack(
        [
            ((df[k] - means[k]) / stds[k]).fillna(0.0).to_numpy() if stds[k] else np.zeros(len(df))
            for k in FEATURES
        ]
    )
    y = df[f"y_{name}"].to_numpy(dtype=float)
    y_mean = float(y.mean())
    lam = RIDGE * len(df)
    beta = np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ (y - y_mean))
    hm = HorizonModel(
        days, y_mean, dict(zip(FEATURES, map(float, beta), strict=True)), means, stds, 1.0, 0.0, 0.0
    )
    preds = np.array([hm.predict_excess(r) for r in data])
    raw = np.array([_sigma_excess(r, days) for r in data])
    ok = raw > 0
    scale = float(np.quantile(np.abs(y[ok] - preds[ok]) / raw[ok], 0.80) / Z80)
    return HorizonModel(
        days,
        y_mean,
        hm.coefs,
        means,
        stds,
        scale,
        float(np.quantile(preds, 0.80)),
        float(np.quantile(preds, 0.20)),
    )


def evaluate(hm: HorizonModel, rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Held-out skill: rank correlation per date (averaged, with a t-stat across dates), top
    fifth minus bottom fifth realised excess, band coverage, and the base rate."""
    data = [r for r in rows if r.get(f"y_{name}") is not None]
    if not data:
        return {"n": 0}
    df = pd.DataFrame(data)
    df["pred"] = [hm.predict_excess(r) for r in data]
    df["sig"] = [hm.vol_scale * _sigma_excess(r, hm.days) for r in data]
    y = df[f"y_{name}"]
    ics, spreads = [], []
    for _, g in df.groupby("day"):
        if len(g) < 10:
            continue
        ics.append(g["pred"].rank().corr(g[f"y_{name}"].rank()))
        k = max(len(g) // 5, 1)
        s = g.sort_values("pred")
        spreads.append(s[f"y_{name}"].iloc[-k:].mean() - s[f"y_{name}"].iloc[:k].mean())
    resid = (y - df["pred"]).abs()
    ic_mean = float(np.mean(ics)) if ics else None
    ic_t = (
        float(np.mean(ics) / (np.std(ics, ddof=1) / math.sqrt(len(ics))))
        if len(ics) > 2 and np.std(ics) > 0
        else None
    )
    return {
        "n": len(df),
        "dates": len(ics),
        "rank_ic": ic_mean,
        "rank_ic_t": ic_t,
        "top_minus_bottom": float(np.mean(spreads)) if spreads else None,
        "direction_right": float(((df["pred"] > 0) == (y > 0)).mean()),
        "base_rate_beat_nifty": float((y > 0).mean()),
        "coverage_80": float((resid <= Z80 * df["sig"]).mean()),
        "coverage_50": float((resid <= Z50 * df["sig"]).mean()),
        "note": "6- and 8-week windows from monthly dates overlap; the t-stat is optimistic for 2 months",
    }


def shows_edge(t: dict[str, Any]) -> bool:
    """Held-out rank correlation positive and not noise (t >= 2), top fifth beat bottom fifth,
    and the 80% band held 70-90% of outcomes."""
    return bool(
        t.get("rank_ic") is not None
        and t["rank_ic"] > 0
        and (t.get("rank_ic_t") or 0) >= 2
        and (t.get("top_minus_bottom") or 0) > 0
        and 0.70 <= t.get("coverage_80", 0) <= 0.90
    )


@dataclass(frozen=True)
class HorizonForecast:
    horizon: str
    days: int
    median: float
    band50: tuple[float, float]
    band80: tuple[float, float]
    p_up: float
    p_beat_nifty: float
    expected_excess: float
    results_in_window: bool
    lean: str


def forecast(
    model: ForecastModel,
    x: dict[str, Any],
    price: float,
    beta: float,
    market_return_year: float,
) -> list[HorizonForecast]:
    """x carries the inputs plus vol_daily, vol_excess_daily, jump_var, event_21/event_42."""
    out = []
    for name, hm in model.horizons.items():
        ex = hm.predict_excess(x)
        mkt = beta * math.log1p(market_return_year) * hm.days / 252
        event = x.get(f"event_{hm.days}", 0)
        jump = (x.get("jump_var") or 0.0) * event
        sig_total = hm.vol_scale * math.sqrt(x["vol_daily"] ** 2 * hm.days + jump)
        sig_ex = hm.vol_scale * _sigma_excess(x, hm.days)
        mu = ex + mkt
        if not model.has_edge.get(name):
            lean = "no measured edge"
        elif ex >= hm.lean_up:
            lean = "lean buy"
        elif ex <= hm.lean_down:
            lean = "lean avoid"
        else:
            lean = "no clear lean"
        out.append(
            HorizonForecast(
                horizon=name,
                days=hm.days,
                median=price * math.exp(mu),
                band50=(
                    price * math.exp(mu - Z50 * sig_total),
                    price * math.exp(mu + Z50 * sig_total),
                ),
                band80=(
                    price * math.exp(mu - Z80 * sig_total),
                    price * math.exp(mu + Z80 * sig_total),
                ),
                p_up=_N.cdf(mu / sig_total) if sig_total > 0 else float(mu > 0),
                p_beat_nifty=_N.cdf(ex / sig_ex) if sig_ex > 0 else float(ex > 0),
                expected_excess=ex,
                results_in_window=bool(event),
                lean=lean,
            )
        )
    return out
