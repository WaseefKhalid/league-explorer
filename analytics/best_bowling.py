"""
"Best Bowling Seasons" sheet — the 150 best individual wicket-taking seasons
inside the span.

Workbook logic: Calc!BG ranks every Player Seasons row in the span with 1+
wicket by the key  Wkts + (30 − economy)/1000 + ROW()/1e9  (wickets, ties
broken by economy, then by the later Player Seasons row) and the sheet lists
LARGE(key, 1..150). Each row then reads that bowler-season straight from
Player Seasons.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

TOP_N = 150
TITLE = "Best Bowling Seasons"
SUBTITLE = "The 150 highest wicket-taking individual seasons inside your span"
HOW_TO_READ = (
    "Pick a span with the Seasons box: every bowler-season inside it is re-ranked by wickets "
    "(ties broken by economy). Set both boxes to one year for that season's wicket list; "
    "use the Bowling sheet for whole-span totals."
)

COLUMNS = ["Rank", "Season", "Player", "Team", "Type", "Inns", "Overs", "Balls", "Runs", "Wkts",
           "Avg", "Econ", "SR", "Dot %", "Best", "4w+", "Impact (runs ±)"]

FMT = {
    "Rank": "{:,.0f}", "Season": "{:.0f}", "Inns": "{:,.0f}", "Overs": "{:.1f}",
    "Balls": "{:,.0f}", "Runs": "{:,.0f}", "Wkts": "{:,.0f}",
    "Avg": "{:,.2f}", "Econ": "{:,.2f}", "SR": "{:,.1f}", "Dot %": "{:.1%}",
    "4w+": "{:,.0f}", "Impact (runs ±)": "{:+,.1f}",
}

_TEXT = {"Player", "Team", "Type", "Best"}


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object if c in _TEXT else float) for c in COLUMNS})


def table(span) -> pd.DataFrame:
    lo, hi = min(span), max(span)
    ps = d.player_seasons()
    season = ps["Season"].to_numpy()
    wk = ps["Wkts"].to_numpy(float)
    sel = (season >= lo) & (season <= hi) & (wk > 0)
    if not sel.any():
        return _empty()
    rows = np.flatnonzero(sel)
    sub = ps.iloc[rows]
    balls = sub["Bowl Balls"].to_numpy(float)
    runs = sub["Bowl Runs"].to_numpy(float)
    w = sub["Wkts"].to_numpy(float)
    # Calc!BG: BM + (30 - 6*BL/BK)/1000 + ROW()/1E9 (Calc row = Player Seasons row = index + 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        key = w + (30 - 6 * runs / balls) / 1000 + (rows + 2) / 1e9
    key = np.where(np.isfinite(key), key, -1)
    order = np.argsort(-key, kind="mergesort")
    order = order[key[order] > 0][:TOP_N]
    s = sub.iloc[order]

    I = s["Bowl Balls"].to_numpy(float)
    J = s["Bowl Runs"].to_numpy(float)
    K = s["Wkts"].to_numpy(float)
    bk = s["Best Key"].fillna(0).to_numpy(float)
    bw = np.floor((bk + 999) / 1000)
    br = 1000 * bw - bk

    def div(a, b, k=1.0):
        out = np.full(len(a), np.nan)
        np.divide(k * a, b, out=out, where=b > 0)
        return out

    out = pd.DataFrame({
        "Rank": np.arange(1, len(s) + 1, dtype=float),
        "Season": s["Season"].to_numpy(float),
        "Player": s["Player"].to_numpy(object),
        "Team": s["Team"].to_numpy(object),
        "Type": s["Bowl Type"].to_numpy(object),
        "Inns": s["Bowl Inns"].to_numpy(float),
        "Overs": np.floor(I / 6) + np.mod(I, 6) / 10,
        "Balls": I,
        "Runs": J,
        "Wkts": K,
        "Avg": div(J, K),
        "Econ": div(J, I, 6),
        "SR": div(I, K),
        "Dot %": div(s["Bowl Dots"].to_numpy(float), I),
        "Best": [f"{int(a)}/{int(b)}" for a, b in zip(bw, br)],
        "4w+": s["4w+"].to_numpy(float),
        "Impact (runs ±)": s["Bowl Run Impact"].to_numpy(float) + s["Bowl Wkt Impact"].to_numpy(float),
    })
    return out[COLUMNS]


def build(span: tuple[int, int]) -> list[Block]:
    span = (min(span), max(span))
    df = table(span)
    return [Block(
        key="bws_top150",
        title=TITLE,
        df=df,
        note=f"{SUBTITLE}. {HOW_TO_READ}",
        rules={"Impact (runs ±)": {"good": (">=", 10), "bad": ("<=", -10)}},
        bars=["Wkts"],
        good_low=["Avg", "Econ", "SR"],
        good_high=["Dot %"],
        fmt=FMT,
        height=640,
    )]
