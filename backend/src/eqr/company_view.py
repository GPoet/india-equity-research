"""What a company page shows, shared by the live API and the static site export."""

from __future__ import annotations

from typing import Any

from eqr.fundamentals import Fundamentals, owners_profit


def series(f: Fundamentals) -> dict[str, list[dict[str, Any]]]:
    top = "total_income" if f.is_bank else "revenue"
    years = [
        {
            "fy_end": y.fy_end,
            "source": y.income_source,
            "revenue": y.income.get(top),
            "ebitda": y.income.get("ebitda"),
            "profit": owners_profit(y.income),
            "eps": y.income.get("eps_basic"),
            "cfo": y.income.get("cfo"),
            "capex": y.income.get("capex_ppe"),
            "equity": y.balance.get("equity_owners"),
            "debt": y.balance.get("total_debt"),
            "nii": y.income.get("nii"),
        }
        for y in reversed(f.years)
    ]
    quarters = [
        {
            "period_end": q.period_end,
            "revenue": q.income.get(top),
            "profit": owners_profit(q.income),
            "ebitda": q.income.get("ebitda"),
            "nii": q.income.get("nii"),
        }
        for q in reversed(f.quarters[:12])
    ]
    return {"years": years, "quarters": quarters}
