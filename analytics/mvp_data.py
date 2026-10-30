"""
Shared data and helpers for the MVP pages (Impact Performances): the
league's mvp/ tables (tools/build_mvp.py for the PSL workbook, engine/mvp.py
for any league built from a Cricsheet zip).

Lists with a date (every impact performance, every knockout and close-finish
match) follow the site's season span. Player totals are all-season figures
and say so on the page.
"""
from __future__ import annotations

import pandas as pd

from analytics import data as d

ALL_TEAMS, ALL_PLAYERS, ALL_ROLES = "All teams", "All players", "All roles"

# Category order and labels exactly as the workbook's Impact Highlights sheet
CATEGORIES = ["3+ wickets", "Economy spells", "Hundreds", "Fifties", "Quick-fire 30+"]
CATEGORY_LABELS = {
    "3+ wickets": "Bowling — 3+ wickets",
    "Economy spells": "Bowling — economy spells",
    "Hundreds": "Batting — hundreds",
    "Fifties": "Batting — fifties",
    "Quick-fire 30+": "Batting — quick-fire 30+ (SR 150+)",
}


def load(name: str) -> pd.DataFrame:
    """The current league's mvp/<name> table (cached by analytics.data)."""
    return d.load(f"mvp/{name}")


def full() -> tuple[int, int]:
    """The league's whole span: what the all-season tables describe."""
    return d.full_span()


def in_span(df: pd.DataFrame, span, col: str = "Season") -> pd.DataFrame:
    lo, hi = min(span), max(span)
    return df[(df[col] >= lo) & (df[col] <= hi)]


def is_full(span) -> bool:
    return (min(span), max(span)) == full()


def all_seasons_note(text: str = "") -> str:
    lo, hi = full()
    years = f"{lo}–{hi}" if hi > lo else f"{lo}"
    lead = f"All seasons, {years}: these are career figures and don't change with the season span."
    return f"{lead} {text}".strip()


def teams_in(series: pd.Series) -> list[str]:
    """Unique team names from a 'Team A, Team B' column, sorted."""
    names = set()
    for v in series.dropna():
        names.update(t.strip() for t in str(v).split(","))
    return sorted(n for n in names if n)


def has_team(series: pd.Series, team: str) -> pd.Series:
    return series.fillna("").map(lambda v: team in [t.strip() for t in str(v).split(",")])


def quartile_rule(s: pd.Series, qualified: pd.Series, higher_is_better: bool = True) -> dict:
    """Green for the best quarter and red for the worst quarter of qualified
    players; everyone else and small samples stay untinted."""
    q = pd.to_numeric(s[qualified], errors="coerce").quantile([.25, .75])
    lo, hi = float(q.loc[.25]), float(q.loc[.75])
    good, bad = ((">=", hi), ("<=", lo)) if higher_is_better else (("<=", lo), (">=", hi))
    return {"good": good, "bad": bad, "where": qualified, "mid": False}


def mark(df: pd.DataFrame, cells: dict[str, pd.Series]) -> pd.DataFrame:
    """A cell_tints frame: {column: Series of 'good' / 'bad' / ''}."""
    out = pd.DataFrame("", index=df.index, columns=df.columns, dtype=object)
    for col, s in cells.items():
        if col in out.columns:
            out[col] = s.reindex(df.index).fillna("").astype(str)
    return out


def won_lost(result: pd.Series) -> pd.Series:
    return result.map({"Won": "good", "Lost": "bad"}).fillna("")
