"""MVP · Close Finishes — how every team and player performs when the match
is tight, against how they do in all matches."""
from __future__ import annotations

import pandas as pd

import analytics.data as d
from analytics import mvp_data as m
from analytics.blocks import Block

FILTERS = ["team", "player"]
DEFAULTS = {"team": m.ALL_TEAMS, "player": m.ALL_PLAYERS}


def filter_options(span=None) -> dict[str, list]:
    p = m.load("close_players")
    return {"team": [m.ALL_TEAMS] + m.teams_in(m.load("close_teams")["Team"]),
            "player": [m.ALL_PLAYERS] + sorted(set(p["Player"]), key=str.lower)}


def _glance(span) -> list[tuple[str, str, str | None]]:
    if m.is_full(span):
        return [(lab, str(val), None) for lab, val in m.load("close_glance").values.tolist()]
    cm = m.in_span(m.load("close_matches"), span)
    games = d.in_span(d.matches(), span)
    completed = int((games["Result"].str.lower() != "no result").sum())
    share = f"{len(cm) / completed:.0%}" if completed else "—"
    return [(f"{d.short()} matches in the data", f"{len(games):,}", None),
            ("Close finishes", f"{len(cm):,}", None),
            ("Share of completed matches", share, None),
            ("Ties / super overs", f"{int(cm['Result'].str.startswith('Tied').sum()):,}", None),
            ("Close knockout matches", f"{int((cm['Stage'] != 'League').sum()):,}", None)]


def build(span=None, team: str = m.ALL_TEAMS, player: str = m.ALL_PLAYERS) -> list[Block]:
    span = span or m.full()
    blocks: list[Block] = []
    notes = m.load("close_note")["note"].tolist()

    blocks.append(Block(key="cl_def", title="What counts as a close finish", df=m.load("close_definitions"),
                        note=notes[0]))
    blocks.append(Block(key="cl_glance", title="At a glance", kind="kpis", kpis=_glance(span),
                        note=None if m.is_full(span) else "Counted for your season span."))

    t = m.load("close_teams").copy()
    # compared at the precision shown (whole per cent), so 47% v 47% stays plain
    close_pct, all_pct = (t["Win %"] * 100).round(), (t["All matches · win %"] * 100).round()
    better, worse = close_pct > all_pct, close_pct < all_pct
    tints = better.map({True: "good", False: ""}).where(~worse, "bad")
    blocks.append(Block(
        key="cl_teams", title="Team record in close finishes", df=t,
        cell_tints=m.mark(t, {"Win %": tints}),
        bold_rows=t.index[t["Team"] == team].tolist(),
        fmt={"Win %": "{:.0%}", "All matches · win %": "{:.0%}"},
        note=m.all_seasons_note("Green = a better win rate in close finishes than in all matches, red = worse."),
        chart={"type": "grouped", "x": "Team", "y": ["Win %", "All matches · win %"],
               "data": t.assign(**{"Win %": t["Win %"] * 100, "All matches · win %": t["All matches · win %"] * 100}),
               "title": "Win % in close finishes v all matches", "colors": ["amber", "sky"],
               "labels": {"Win %": "Close finishes", "All matches · win %": "All matches"}}))

    p = m.load("close_players").copy()
    wb = m.load("close_players_wb_tints")
    keep = pd.Series(True, index=p.index)
    if team != m.ALL_TEAMS:
        keep &= m.has_team(p["Team(s)"], team)
    if player != m.ALL_PLAYERS:
        keep &= p["Player"] == player
    p, wb = p[keep].reset_index(drop=True), wb[keep].reset_index(drop=True)
    n = len(p)
    blocks.append(Block(
        key="cl_players", title=f"Player summary · close finishes against all matches · {n} player{'s' if n != 1 else ''}",
        df=p, cell_tints=m.mark(p, {"Strike rate": wb["Strike rate"], "Economy": wb["Economy"]}),
        fmt={"Runs": "{:,.0f}", "Balls": "{:,.0f}", "Strike rate": "{:.1f}", "SR · all matches": "{:.1f}",
             "Average": "{:.2f}", "Wickets": "{:.0f}", "Overs": "{:g}", "Economy": "{:.2f}",
             "Econ. · all matches": "{:.2f}", "Death-over SR (bat)": "{:.1f}", "Death-over econ.": "{:.2f}",
             "Dot % (bowl)": "{:.0%}", "Close matches": "{:.0f}"},
        note=m.all_seasons_note(notes[1]),
        height=720 if n > 15 else None))

    cm = m.in_span(m.load("close_matches"), span)
    if team != m.ALL_TEAMS:
        cm = cm[cm["Match"].str.contains(team, regex=False)]
    if player != m.ALL_PLAYERS:
        cm = cm[cm["Key performers"].fillna("").str.contains(player, regex=False)]
    cm = cm.drop(columns="Season").reset_index(drop=True)
    blocks.append(Block(
        key="cl_matches", title=f"The close finishes · {len(cm)} match{'es' if len(cm) != 1 else ''}", df=cm,
        bold_rows=cm.index[cm["Stage"] != "League"].tolist(),
        note=notes[2] + " Knockout matches in bold. Follows your season span" +
             (" and the team / player filters." if team != m.ALL_TEAMS or player != m.ALL_PLAYERS else "."),
        height=720 if len(cm) > 15 else None))
    return blocks
