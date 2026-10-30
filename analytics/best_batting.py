"""
"Best Batting Seasons" sheet: the 150 highest run-scoring individual
player-seasons inside the span.

Workbook logic: Calc!BF ranks each Player Seasons row in the span with
Runs > 0 by  Runs + (Runs/Balls)/1000 + ROW()/1E9  (runs, then strike rate,
then the later Player Seasons row), and the sheet lists LARGE(1..150).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

TOP_N = 150

COLUMNS = ["Rank", "Season", "Player", "Team", "Hand", "Inns", "Runs", "Balls", "Avg", "SR",
           "HS", "50s", "100s", "4s", "6s", "Bdry %", "Dot %", "Impact (runs ±)"]
# Workbook group headers (row 11)
GROUPS = {"SEASON": COLUMNS[0:5], "BATTING": COLUMNS[5:17], "IMPACT": COLUMNS[17:18]}

FMT = {
    "Rank": "{:,.0f}", "Season": "{:.0f}", "Inns": "{:,.0f}", "Runs": "{:,.0f}",
    "Balls": "{:,.0f}", "Avg": "{:,.1f}", "SR": "{:,.1f}", "HS": "{:,.0f}",
    "50s": "{:,.0f}", "100s": "{:,.0f}", "4s": "{:,.0f}", "6s": "{:,.0f}",
    "Bdry %": "{:.1%}", "Dot %": "{:.1%}", "Impact (runs ±)": "{:+,.1f}",
}

SUBTITLE = "The 150 highest run-scoring individual seasons inside your span"
HOW_TO_READ = [
    "Pick a span with the Seasons box: the list re-ranks every batter-season inside it by "
    "runs (ties broken by strike rate).",
    "Set both boxes to one year for that season's top-150 run list; use the Batting sheet "
    "for whole-span totals.",
]


def _div(a, b, scale=1.0):
    b = b.astype(float)
    return (a * scale) / b.where(b != 0)


def table(span: tuple[int, int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    ps = d.player_seasons()
    lo, hi = min(span), max(span)
    sel = (ps["Season"] >= lo) & (ps["Season"] <= hi) & (ps["Runs"] > 0)
    s = ps.loc[sel].copy()

    # Calc!BF key: Runs + Runs/Balls/1000 + ROW()/1E9 (Calc row = position + 2)
    pos = np.flatnonzero(sel.to_numpy())
    runs = s["Runs"].to_numpy(dtype=float)
    balls = s["Balls"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        key = runs + runs / balls / 1000 + (pos + 2) / 1e9
    s["_key"] = key
    s = s.sort_values("_key", ascending=False, kind="mergesort").head(TOP_N)

    out = pd.DataFrame(index=s.index)
    out["Rank"] = np.arange(1, len(s) + 1, dtype=float)
    out["Season"] = s["Season"].astype(int)
    out["Player"] = s["Player"]
    out["Team"] = s["Team"]
    out["Hand"] = s["Hand"]
    out["Inns"] = s["Inns"].astype(float)
    out["Runs"] = s["Runs"].astype(float)
    out["Balls"] = s["Balls"].astype(float)
    out["Avg"] = _div(s["Runs"], s["Inns"] - s["NO"])
    out["SR"] = _div(s["Runs"], s["Balls"], 100)
    hs_key = s["HS Key"].astype(float)
    hs_int = np.floor(hs_key)
    out["HS"] = hs_int
    for c in ["50s", "100s", "4s", "6s"]:
        out[c] = s[c].astype(float)
    out["Bdry %"] = _div(s["4s"] + s["6s"], s["Balls"])
    out["Dot %"] = _div(s["Bat Dots"], s["Balls"])
    out["Impact (runs ±)"] = (s["Bat Run Impact"] + s["Bat Out Impact"]).astype(float)

    df = out[COLUMNS].reset_index(drop=True)
    labels = pd.DataFrame(None, index=df.index, columns=COLUMNS, dtype=object)
    if len(df):
        txt = hs_int.astype(int).astype(str) + np.where((hs_key - hs_int) > 0.05, "*", "")
        labels["HS"] = txt.to_numpy()
    return df, labels


def build(span: tuple[int, int]) -> list[Block]:
    df, labels = table(span)
    ps = d.in_span(d.player_seasons(), span)
    balls = ps["Balls"].sum()
    center = {"SR": float(100 * ps["Runs"].sum() / balls)} if balls else {}
    return [Block(
        key="bbs_top150",
        title="Best Batting Seasons",
        note=SUBTITLE + ". " + " ".join(HOW_TO_READ),
        df=df,
        labels=labels,
        fmt=dict(FMT),
        rules={"Impact (runs ±)": {"good": (">=", 10), "bad": ("<=", -10)}},
        bars=["Runs"],
        good_high=["SR"],
        center=center,
        height=640,
    )]
