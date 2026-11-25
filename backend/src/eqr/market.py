"""Market-wide valuation inputs (rates, risk premium) from config/market_inputs.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "market_inputs.toml"


@dataclass(frozen=True)
class MarketInputs:
    as_of: date
    max_age_days: int
    gsec_10y: float  # decimals from here on (0.073 = 7.3%)
    sovereign_default_spread: float
    equity_risk_premium: float
    aaa_spread_over_gsec: float
    terminal_growth: float
    default_tax_rate: float
    margin_of_safety: float
    sources: dict[str, str]

    @property
    def risk_free_inr(self) -> float:
        """Damodaran: local-currency risk-free = government yield - sovereign default spread."""
        return self.gsec_10y - self.sovereign_default_spread

    @property
    def aaa_yield(self) -> float:
        return self.gsec_10y + self.aaa_spread_over_gsec

    def cost_of_equity(self, beta: float) -> float:
        return self.risk_free_inr + beta * self.equity_risk_premium

    def staleness_warning(self, today: date) -> str | None:
        age = (today - self.as_of).days
        if age > self.max_age_days:
            return f"Market inputs are {age} days old (as of {self.as_of}); update config/market_inputs.toml"
        return None


def load_market_inputs(path: Path = DEFAULT_PATH) -> MarketInputs:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    pct = lambda key: float(raw[key]) / 100  # noqa: E731
    inputs = MarketInputs(
        as_of=date.fromisoformat(raw["as_of"]),
        max_age_days=int(raw.get("max_age_days", 30)),
        gsec_10y=pct("gsec_10y"),
        sovereign_default_spread=pct("sovereign_default_spread"),
        equity_risk_premium=pct("equity_risk_premium"),
        aaa_spread_over_gsec=pct("aaa_spread_over_gsec"),
        terminal_growth=pct("terminal_growth"),
        default_tax_rate=pct("default_tax_rate"),
        margin_of_safety=pct("margin_of_safety"),
        sources={k: v for k, v in raw.items() if k.endswith("_source")},
    )
    if inputs.terminal_growth >= inputs.risk_free_inr:
        raise ValueError(
            f"terminal_growth {inputs.terminal_growth:.2%} must be below the rupee "
            f"risk-free rate {inputs.risk_free_inr:.2%}"
        )
    return inputs
