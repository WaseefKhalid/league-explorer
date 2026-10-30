"""MVP · Knockout Matches — every play-off: the matches, each match's
scorecard with impact performances marked, and every player's knockout record."""
from __future__ import annotations

import re

import pandas as pd

from analytics import mvp_data as m
from analytics.blocks import Block

FILTERS = ["match", "player"]


def _matches(span=None) -> pd.DataFrame:
    k = m.load("ko_matches")
    k = m.in_span(k, span) if span is not None else k
    return k.sort_values("Date", ascending=False)


def _label(row) -> str:
    return f"{row['Stage']} — {row['Match']}"


def filter_options(span=None) -> dict[str, list]:
    k = _matches(span)
    players = m.load("ko_players")["Player"].tolist()
    return {"match": [_label(r) for _, r in k.iterrows()] or ["No knockout matches in this span"],
            "player": [m.ALL_PLAYERS] + sorted(players, key=str.lower)}


DEFAULTS = {"player": m.ALL_PLAYERS}     # match: the latest one in the span


def _card_key(row) -> str:
    """The match-by-match banner for a match row, e.g.
    '19 Feb 2016 · 2016 Qualifier 1 · Quetta Gladiators v Peshawar Zalmi · …'."""
    t = pd.Timestamp(row["Date"])
    return f"{t.strftime('%d %b %Y')} · {row['Stage'].replace(' · ', ' ')} · {row['Match']}"


def _balls(runs_balls) -> float:
    mm = re.search(r"\((\d+)\)", str(runs_balls or ""))
    return float(mm.group(1)) if mm else 0.0


def build(span=None, match: str | None = None, player: str = m.ALL_PLAYERS) -> list[Block]:
    span = span or m.full()
    blocks: list[Block] = []
    k = _matches(span)
    cards = m.in_span(m.load("ko_cards"), span)
    finals = k[k["Stage only"] == "Final"]

    blocks.append(Block(key="ko_glance", title="At a glance", kind="kpis", kpis=[
        ("Knockout matches", f"{len(k):,}", None),
        ("Finals", f"{len(finals):,}", None),
        # (at the full span: the workbook's 250, which counts two pairs of same-named players separately)
        ("Players", f"{len(m.load('ko_players')) if m.is_full(span) else cards['Player'].nunique():,}",
         "batted or bowled"),
        ("Impact performances", f"{int(cards['Impact'].notna().sum()):,}", "in knockouts"),
    ]))

    shown = k.sort_values("Date")[["Stage", "Match", "Date", "Score · 1st", "Score · 2nd", "Result", "Venue",
                                   "Player of the Match"]].reset_index(drop=True)
    blocks.append(Block(
        key="ko_matches", title=f"The matches · {len(shown)}", df=shown,
        bold_rows=shown.index[shown["Stage"].str.endswith("Final")].tolist(),
        note="Every play-off in your season span: qualifiers, eliminators and finals (in bold). Match = batting "
             "first v second.", height=720 if len(shown) > 15 else None))

    # One match's scorecard
    if len(k):
        labels = {_label(r): r for _, r in k.iterrows()}
        row = labels.get(match) if match in labels else k.iloc[0]
        key = _card_key(row)
        card = cards[cards["Match"].str.startswith(key)]
        cols = ["Player", "Team", "Opposition", "Runs", "Balls", "SR", "4s / 6s", "Overs", "Runs conc.", "Wickets",
                "Economy", "Team result", "Impact"]
        card = card[cols].reset_index(drop=True)
        impact = card["Impact"].notna()
        blocks.append(Block(
            key="ko_card", title=f"Match by match · {row['Stage']}",
            finding=f"{row['Match']}: {row['Result']}. Player of the Match: {row['Player of the Match']}.",
            df=card,
            cell_tints=m.mark(card, {"Player": impact.map({True: "good", False: ""}),
                                     "Impact": impact.map({True: "good", False: ""})}),
            fmt={"Balls": "{:.0f}", "SR": "{:.1f}", "Overs": "{:g}", "Runs conc.": "{:.0f}", "Wickets": "{:.0f}",
                 "Economy": "{:.2f}"},
            note="Green = an impact performance (criteria on the MVP Scoreboard "
                 "page). DNB = did not bat; — = did not bowl."))

    # One player's knockout innings, match by match
    if player != m.ALL_PLAYERS:
        log = cards[cards["Player"] == player].sort_values("Date")
        if len(log):
            log = log.assign(Match=log["Match"].str.rsplit(" · ", n=1).str[0])
            cols = ["Match", "Team", "Runs", "Balls", "SR", "Overs", "Runs conc.", "Wickets", "Economy",
                    "Team result", "Impact"]
            log = log[cols].reset_index(drop=True)
            imp = log["Impact"].notna()
            blocks.append(Block(
                key="ko_player", title=f"{player} · every knockout match", df=log,
                cell_tints=m.mark(log, {"Impact": imp.map({True: "good", False: ""}),
                                        "Team result": m.won_lost(log["Team result"])}),
                fmt={"Balls": "{:.0f}", "SR": "{:.1f}", "Overs": "{:g}", "Runs conc.": "{:.0f}",
                     "Wickets": "{:.0f}", "Economy": "{:.2f}"},
                note="In your season span. Green impact = an impact performance; result green = won, red = lost."))

    p = m.load("ko_players").copy()
    full = p.copy()
    if player != m.ALL_PLAYERS:
        p = p[p["Player"] == player]
    p = p.reset_index(drop=True)
    balls_q = full["Runs (balls)"].map(_balls) >= 30
    overs_q = full["Overs"].fillna(0) >= 10
    sr_rule = m.quartile_rule(full["Strike rate"], balls_q)
    ec_rule = m.quartile_rule(full["Economy"], overs_q, higher_is_better=False)
    keep = full.index[full["Player"].isin(p["Player"])]
    sr_rule["where"] = balls_q.loc[keep].reset_index(drop=True)
    ec_rule["where"] = overs_q.loc[keep].reset_index(drop=True)
    blocks.append(Block(
        key="ko_players", title=f"Player summary · all knockout matches · {len(p)} player{'s' if len(p) != 1 else ''}",
        df=p, rules={"Strike rate": sr_rule, "Economy": ec_rule}, bars=["Impact innings"],
        fmt={"Strike rate": "{:.1f}", "Economy": "{:.2f}", "Overs": "{:g}", "Runs conceded": "{:,.0f}",
             "Matches": "{:.0f}", "Fifties": "{:.0f}", "Wickets": "{:.0f}", "Impact innings": "{:.0f}"},
        note=m.all_seasons_note('Sorted by knockout matches played. "In the finals" shows each final the player '
                                "batted or bowled in. Green = best quarter, red = worst quarter (strike rate: 30+ "
                                "balls faced; economy: 10+ overs)."),
        height=720 if len(p) > 15 else None))
    return blocks
