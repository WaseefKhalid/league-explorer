"""MVP · Impact Highlights — every impact performance, ranked within its
category, with the category leaders. Follows the season span."""
from __future__ import annotations

import pandas as pd

from analytics import mvp_data as m
from analytics.blocks import Block

FILTERS = ["category", "stage", "team", "player", "close"]
ALL_CATS, ALL_STAGES, ALL_MATCHES = "All categories", "All matches", "All matches"
STAGES = [ALL_STAGES, "League", "Knockouts", "Finals"]
CLOSE = [ALL_MATCHES, "Close finishes only"]
DEFAULTS = {"category": ALL_CATS, "stage": ALL_STAGES, "team": m.ALL_TEAMS, "player": m.ALL_PLAYERS,
            "close": ALL_MATCHES}


def filter_options(span=None) -> dict[str, list]:
    h = m.load("highlights")
    if span is not None:
        h = m.in_span(h, span)
    return {"category": [ALL_CATS] + m.CATEGORIES,
            "stage": STAGES,
            "team": [m.ALL_TEAMS] + sorted(h["Team"].dropna().unique().tolist()),
            "player": [m.ALL_PLAYERS] + sorted(h["Player"].dropna().unique().tolist(), key=str.lower),
            "close": CLOSE}


def _ranked(span) -> pd.DataFrame:
    """The span's performances, re-ranked within each category in the
    workbook's order (at the full span the ranks are the workbook's)."""
    h = m.in_span(m.load("highlights"), span).copy()
    h["_cat"] = h["Category"].map({c: i for i, c in enumerate(m.CATEGORIES)})
    h = h.sort_values(["_cat", "Rank"], kind="stable")
    h["Rank"] = h.groupby("Category").cumcount() + 1
    return h.drop(columns="_cat")


def _leaders(g: pd.DataFrame, n: int = 3) -> str:
    """'Name 19 · Name 18 · Name 13'; ties go to whoever got there first."""
    if g.empty:
        return "—"
    agg = g.groupby("Player").agg(count=("Rank", "size"), first=("Date", "min"))
    agg = agg.sort_values(["count", "first"], ascending=[False, True], kind="stable").head(n)
    return " · ".join(f"{p} {int(r['count'])}" for p, r in agg.iterrows())


def build(span=None, category: str = ALL_CATS, stage: str = ALL_STAGES, team: str = m.ALL_TEAMS,
          player: str = m.ALL_PLAYERS, close: str = ALL_MATCHES) -> list[Block]:
    span = span or m.full()
    h = _ranked(span)
    blocks: list[Block] = []

    glance = pd.DataFrame({
        "Category": [m.CATEGORY_LABELS[c] for c in m.CATEGORIES],
        "Performances": [int((h["Category"] == c).sum()) for c in m.CATEGORIES],
        "Most in this category": [_leaders(h[h["Category"] == c]) for c in m.CATEGORIES],
    })
    note = m.load("highlights_note").iloc[0, 0]
    blocks.append(Block(key="hl_glance", title="At a glance · most in each category", df=glance, bars=["Performances"],
                        fmt={"Performances": "{:,.0f}"}, note=note))

    per = (h.assign(Season=h["Season"].astype(str))
             .pivot_table(index="Season", columns="Category", values="Rank", aggfunc="size", fill_value=0)
             .reindex(columns=m.CATEGORIES, fill_value=0).reset_index())
    if len(per) > 1:
        blocks.append(Block(key="hl_seasons", title="Impact performances by season", df=per, kind="chart",
                            note="Each bar adds up the five categories for one season.",
                            chart={"type": "stacked", "x": "Season", "y": m.CATEGORIES,
                                   "colors": ["red", "violet", "amber", "sky", "green"]}))

    lst = h
    if category != ALL_CATS:
        lst = lst[lst["Category"] == category]
    if stage == "League":
        lst = lst[lst["Match stage"] == "League"]
    elif stage == "Knockouts":
        lst = lst[lst["Match stage"] != "League"]
    elif stage == "Finals":
        lst = lst[lst["Match stage"] == "Final"]
    if team != m.ALL_TEAMS:
        lst = lst[lst["Team"] == team]
    if player != m.ALL_PLAYERS:
        lst = lst[lst["Player"] == player]
    if close != ALL_MATCHES:
        lst = lst[lst["Close finish"]]
    lst = lst.reset_index(drop=True)
    lst["Close finish"] = lst["Close finish"].map({True: "Close", False: None})
    cols = ["Category", "Rank", "Player", "Team", "Figures", "Detail", "Opposition", "Venue", "Date", "Season",
            "Match stage", "Team result", "Close finish"]
    lst = lst[cols]
    n = len(lst)
    blocks.append(Block(
        key="hl_list", title=f"All impact performances · {n:,}", df=lst,
        cell_tints=m.mark(lst, {"Team result": m.won_lost(lst["Team result"])}),
        fmt={"Rank": "{:.0f}", "Season": "{:.0f}"},
        note="Ranked within each category for your season span (best figures first). Green = the player's team "
             "won, red = lost. Use the filters above to show one player, team, category or stage.",
        height=720 if n > 15 else None))
    return blocks
