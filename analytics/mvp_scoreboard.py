"""MVP · Scoreboard — the workbook's Summary sheet: what counts, the numbers at
a glance, and every player's impact innings."""
from __future__ import annotations

import pandas as pd

import analytics.data as d
from analytics import mvp_data as m
from analytics.blocks import Block

FILTERS = ["team", "role", "player"]
DEFAULTS = {"team": m.ALL_TEAMS, "role": m.ALL_ROLES, "player": m.ALL_PLAYERS}
ROLES = ["Batter", "Bowler", "All-rounder"]


def filter_options(span=None) -> dict[str, list]:
    b = m.load("scoreboard")
    roles = [r for r in ROLES if r in set(b["Role"])]
    return {"team": [m.ALL_TEAMS] + m.teams_in(b["Team(s)"]),
            "role": [m.ALL_ROLES] + roles,
            "player": [m.ALL_PLAYERS] + sorted(b["Player"].tolist(), key=str.lower)}


def _glance(span) -> list[tuple[str, str, str | None]]:
    """The workbook's 'At a glance' numbers, counted for the season span."""
    if m.is_full(span):
        g = dict(m.load("glance").values.tolist())
        order = ["Matches in the data", "Players", "Knockout matches", "Close finishes",
                 "Impact performances", "Hundreds", "Fifties", "3+ wicket hauls"]
        return [(k, f"{int(g[k]):,}", None) for k in order]
    h = m.in_span(m.load("highlights"), span)
    n = h["Category"].value_counts()
    return [
        ("Matches in the data", f"{len(d.in_span(d.matches(), span)):,}", None),
        ("Players", f"{int(dict(m.load('glance').values.tolist())['Players']):,}", "all seasons"),
        ("Knockout matches", f"{len(m.in_span(m.load('ko_matches'), span)):,}", None),
        ("Close finishes", f"{len(m.in_span(m.load('close_matches'), span)):,}", None),
        ("Impact performances", f"{len(h):,}", None),
        ("Hundreds", f"{int(n.get('Hundreds', 0)):,}", None),
        ("Fifties", f"{int(n.get('Fifties', 0)):,}", None),
        ("3+ wicket hauls", f"{int(n.get('3+ wickets', 0)):,}", None),
    ]


def build(span=None, team: str = m.ALL_TEAMS, role: str = m.ALL_ROLES,
          player: str = m.ALL_PLAYERS) -> list[Block]:
    span = span or m.full()
    blocks: list[Block] = []

    defs = m.load("definitions").copy()
    blocks.append(Block(
        key="sb_def", title="What counts as an impact performance", df=defs,
        note="An innings or spell counts once per category it meets. Knockout matches and close finishes are "
             "tracked for every player too."))

    blocks.append(Block(key="sb_glance", title="At a glance", kind="kpis", kpis=_glance(span),
                        note=None if m.is_full(span) else
                        "Counted for your season span (players: all seasons)."))

    board = m.load("scoreboard").copy()
    full = board.copy()
    if team != m.ALL_TEAMS:
        board = board[m.has_team(board["Team(s)"], team)]
    if role != m.ALL_ROLES:
        board = board[board["Role"] == role]
    if player != m.ALL_PLAYERS:
        board = board[board["Player"] == player]

    top = board[board["Impact innings"] > 0].head(15)[["Player", "Impact innings"]].reset_index(drop=True)
    if len(top) > 1:
        lead = board.iloc[0]
        who = "" if team == m.ALL_TEAMS and role == m.ALL_ROLES else " here"
        blocks.append(Block(
            key="sb_top", title="Most impact innings", df=top, kind="chart",
            finding=f"{lead['Player']} has the most impact innings{who}: {int(lead['Impact innings'])} in "
                    f"{int(lead['Matches'])} matches.",
            note=m.all_seasons_note(),
            chart={"type": "hbar", "x": "Player", "y": "Impact innings", "color": "amber"}))

    # Quality tints: best / worst quarter among players with a real sample
    bat_q = full["Batting inns"].fillna(0) >= 10
    bowl_q = full["Bowling inns"].fillna(0) >= 10
    rules = {
        "Average": m.quartile_rule(full["Average"], bat_q),
        "Strike rate": m.quartile_rule(full["Strike rate"], bat_q),
        "Economy": m.quartile_rule(full["Economy"], bowl_q, higher_is_better=False),
    }
    for r in rules.values():
        r["where"] = r["where"].reindex(board.index)
    n = len(board)
    blocks.append(Block(
        key="sb_board", title=f"Player scoreboard · {n} player{'s' if n != 1 else ''}",
        df=board.reset_index(drop=True),
        rules={k: {**v, "where": v["where"].reset_index(drop=True)} for k, v in rules.items()},
        bars=["Impact innings"],
        fmt={"Runs": "{:,.0f}", "Average": "{:.2f}", "Strike rate": "{:.1f}", "Economy": "{:.2f}",
             **{c: "{:,.0f}" for c in ("Matches", "Batting inns", "Fifties", "Hundreds", "Quick-fire 30+",
                                         "Bowling inns", "Wickets", "3+ wkt hauls", "Economy spells",
                                         "Impact innings", "Player of the Match", "Knockout matches",
                                         "Close finishes")}},
        note=m.all_seasons_note("Sorted by impact innings. Green = best quarter, red = worst quarter of players with "
                                "10+ batting innings (average, strike rate) or 10+ bowling innings (economy). "
                                "Average = runs ÷ dismissals; economy = runs per over."),
        height=720 if n > 15 else None))
    return blocks
