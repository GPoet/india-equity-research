"""A company's sector picture: how its sector is doing, which related sectors are strong,
and the strongest sectors in the market right now."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from eqr.sectors.analysis import excess_correlations, pe_vs_history, sector_scores
from eqr.sectors.catalog import BENCHMARK, LINKS, SECTORS

MIN_COMOVEMENT = 0.30
TOP_N = 5


@dataclass(frozen=True)
class SectorStat:
    key: str
    label: str
    stance: str
    rank: int  # 1 = strongest
    of: int
    rs_3m: float | None
    rs_6m: float | None
    vs_200dma: float | None
    pe: float | None
    pe_premium: float | None  # vs its own median over the window


@dataclass(frozen=True)
class RelatedSector:
    stat: SectorStat
    why: str
    correlation: float | None  # weekly, market move removed
    basis: str  # "economic link" | "co-movement"


@dataclass(frozen=True)
class SectorPicture:
    as_of: str
    sector: SectorStat | None
    related: tuple[RelatedSector, ...]
    strongest: tuple[SectorStat, ...]
    weakest: tuple[SectorStat, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


def _f(x: object) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)  # type: ignore[arg-type]


def build_stats(closes: pd.DataFrame, pe: pd.DataFrame) -> dict[str, SectorStat]:
    by_index = {s.index: s for s in SECTORS.values()}
    cols = [c for c in closes.columns if c in by_index or c == BENCHMARK]
    scores = sector_scores(closes[cols], BENCHMARK).drop(index=BENCHMARK, errors="ignore")
    ranked = scores[scores["stance"] != "insufficient history"]
    vals = pe_vs_history(pe[[c for c in cols if c in pe.columns]])
    stats = {}
    for idx_name, row in scores.iterrows():
        sec = by_index[idx_name]
        rank = list(ranked.index).index(idx_name) + 1 if idx_name in ranked.index else 0
        v = vals.loc[idx_name] if idx_name in vals.index else None
        stats[sec.key] = SectorStat(
            key=sec.key,
            label=sec.label,
            stance=row["stance"],
            rank=rank,
            of=len(ranked),
            rs_3m=_f(row["rs_3m"]),
            rs_6m=_f(row["rs_6m"]),
            vs_200dma=_f(row["vs_200dma"]),
            pe=_f(v["pe"]) if v is not None else None,
            pe_premium=_f(v["pe_premium"]) if v is not None else None,
        )
    return stats


def sector_picture(sector_key: str | None, closes: pd.DataFrame, pe: pd.DataFrame) -> SectorPicture:
    stats = build_stats(closes, pe)
    ranked = sorted((s for s in stats.values() if s.rank), key=lambda s: s.rank)
    notes: list[str] = []
    related: list[RelatedSector] = []
    own = stats.get(sector_key) if sector_key else None
    if sector_key and own is None:
        notes.append(f"Sector '{sector_key}' has no index history")
    if own is not None:
        by_index = {s.index: s.key for s in SECTORS.values()}
        corr = excess_correlations(
            closes[[c for c in closes.columns if c in by_index or c == BENCHMARK]], BENCHMARK
        )
        own_index = SECTORS[sector_key].index  # type: ignore[index]

        def c(other: str) -> float | None:
            oi = SECTORS[other].index
            if own_index in corr.index and oi in corr.columns:
                return _f(corr.loc[own_index, oi])
            return None

        linked = set()
        for other, why in LINKS.get(sector_key, []):  # type: ignore[arg-type]
            if other in stats:
                related.append(RelatedSector(stats[other], why, c(other), "economic link"))
                linked.add(other)
        if own_index in corr.index:
            co = (
                corr.loc[own_index]
                .drop(labels=[own_index], errors="ignore")
                .dropna()
                .sort_values(ascending=False)
            )
            for oi, value in co.items():
                key = by_index.get(oi)
                if key and key not in linked and key in stats and value >= MIN_COMOVEMENT:
                    related.append(
                        RelatedSector(
                            stats[key],
                            "moves with it beyond the market",
                            float(value),
                            "co-movement",
                        )
                    )
                if sum(r.basis == "co-movement" for r in related) == 3:
                    break
    return SectorPicture(
        as_of=str(closes.index[-1].date()),
        sector=own,
        related=tuple(related),
        strongest=tuple(ranked[:TOP_N]),
        weakest=tuple(ranked[-TOP_N:][::-1]),
        notes=tuple(notes),
    )
