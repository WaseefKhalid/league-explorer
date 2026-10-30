"""
"Players" sheet: every player in the league — fixed profile columns plus an
"In the selected span" block (matches, runs, wickets, POTM, batting impact,
bowling impact, catches) summed from Player Seasons for the span.
"""
from __future__ import annotations

import pandas as pd

from analytics import data as d
from analytics import presets
from analytics.blocks import Block

PROFILE = ["Player", "Full Name", "Country", "Overseas/Local", "Role (Cricinfo)", "Bat Hand",
           "Bowling Style", "Bowling Type", "Teams", "Seasons (career)"]
SPAN = ["Matches", "Runs", "Wickets", "POTM", "Batting impact", "Bowling impact", "Catches"]
SOURCE = ["Hand Source", "Style Source", "Still Missing"]
COLUMNS = PROFILE + SPAN + SOURCE
# Workbook group headers (row 12)
GROUPS = {"PROFILE": PROFILE, "IN THE SELECTED SPAN": SPAN, "DATA SOURCE": SOURCE}

FMT = {"Matches": "{:,.0f}", "Runs": "{:,.0f}", "Wickets": "{:,.0f}", "POTM": "{:,.0f}",
       "Batting impact": "{:+,.1f}", "Bowling impact": "{:+,.1f}", "Catches": "{:,.0f}"}

INTRO = [
    'Profile columns are fixed; the "In the selected span" block follows the Seasons box at the top.',
    "Sources: ESPNcricinfo profiles (via the open-source cricketdata project) matched on Cricsheet "
    'IDs; "You" = supplied by you; "Web check" = corrected from public profiles.',
]


def _intro() -> list[str]:
    """Generic lines (the sources line only when the league has hand / style data) + the league's own."""
    lines = INTRO[:1] + (INTRO[1:2] if d.has("has_hand_type") else [])
    return lines + presets.preset("players_notes", [])

_SUM = ["Mat", "Runs", "Wkts", "POTM", "Balls", "Bat Run Impact", "Bat Out Impact",
        "Bowl Balls", "Bowl Run Impact", "Bowl Wkt Impact", "Catches"]


def table(span: tuple[int, int]) -> pd.DataFrame:
    prof = d.players()
    ps = d.in_span(d.player_seasons(), span)
    g = ps.groupby("Player", sort=False)[_SUM].sum()
    g = g.reindex(prof["Player"]).fillna(0.0)

    df = prof[PROFILE].copy().fillna("")
    df["Matches"] = g["Mat"].to_numpy(dtype=float)
    df["Runs"] = g["Runs"].to_numpy(dtype=float)
    df["Wickets"] = g["Wkts"].to_numpy(dtype=float)
    df["POTM"] = g["POTM"].to_numpy(dtype=float)
    bat = (g["Bat Run Impact"] + g["Bat Out Impact"]).where(g["Balls"] > 0)
    bowl = (g["Bowl Run Impact"] + g["Bowl Wkt Impact"]).where(g["Bowl Balls"] > 0)
    df["Batting impact"] = bat.to_numpy(dtype=float)
    df["Bowling impact"] = bowl.to_numpy(dtype=float)
    df["Catches"] = g["Catches"].to_numpy(dtype=float)
    for c in SOURCE:
        df[c] = prof[c].fillna("").to_numpy()
    return df[COLUMNS].reset_index(drop=True)


def build(span: tuple[int, int]) -> list[Block]:
    df = table(span)
    intro = Block(key="pl_intro", title="How to read", kind="text",
                  text="\n".join(f"- {t}" for t in _intro()))
    main = Block(
        key="pl_all",
        title="Players",
        note=f"All {len(df)} players · profile plus matches, runs, wickets, awards and impact in your span",
        df=df,
        fmt=dict(FMT),
        rules={c: {"good": (">=", 10), "bad": ("<=", -10)} for c in ["Batting impact", "Bowling impact"]},
        # players with no match in the span are shown greyed
        muted_rows=df.index[df["Matches"] == 0].tolist(),
        height=640,
    )
    return [intro, main]
