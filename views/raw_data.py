"""Raw data: every table behind the site, filterable and downloadable."""
from __future__ import annotations

import functools

import pandas as pd
import streamlit as st

from analytics import data as d
from components import auth
from views.common import current_span, page_header

TABLES = [
    ("Matches", "matches", "One row per match: toss, scores, result, margin, player of the match and award details.",
     ["Team 1", "Team 2"], ["Player of Match"]),
    ("Team innings", "team_matches", "One row per team per match: result, batting order, runs by phase, sixes, home or "
     "away.", ["Team", "Opposition"], []),
    ("Batting innings", "bat_inns", "One row per batter per innings.", ["Team", "Opposition"], ["Batter"]),
    ("Bowling innings", "bowl_inns", "One row per bowler per innings.", ["Team", "Opposition"], ["Bowler"]),
    ("Player seasons", "player_seasons", "One row per player per season, with every measure the season-span pages "
     "add up.", [], ["Player"]),
    ("Pair seasons", "pair_seasons", "One row per batter–bowler pair per season.", [], ["Batter", "Bowler"]),
    ("Balls", "ball", "Every delivery with phase, hand, bowler type, outcome and impact.",
     ["Batting Team", "Bowling Team"], ["Batter", "Bowler"]),
]
MAX_SHOW = 20000


@st.cache_data(show_spinner=False, max_entries=64)
def _filtered(name: str, span, team: str, who: str, league_key: str, _league: d.League) -> pd.DataFrame:
    # league_key is the cache key; _league is passed explicitly because the CSV
    # download runs this later, possibly outside the page's script thread.
    info = next(t for t in TABLES if t[1] == name)
    df = d.load(name, _league)
    if "Season" in df.columns:
        df = d.in_span(df, span)
    if team != "All teams" and info[3]:
        mask = False
        for c in info[3]:
            mask = mask | (df[c] == team)
        df = df[mask]
    if who.strip() and info[4]:
        q = who.strip().lower()
        mask = False
        for c in info[4]:
            mask = mask | df[c].astype(str).str.lower().str.contains(q, regex=False)
        df = df[mask]
    return df.reset_index(drop=True)


def _csv(name, span, team, who, league: d.League) -> bytes:
    return _filtered(name, span, team, who, league.key, league).to_csv(index=False).encode("utf-8")


def page():
    if not auth.is_admin():      # never served to the public, even by direct link
        st.stop()
    span = current_span()
    lg = d.current()
    page_header("Raw Data", "Every table behind the site. Filter by team or name, then download the rows as CSV.",
                span)
    teams = ["All teams"] + sorted(d.team_matches()["Team"].dropna().unique().tolist())
    tabs = st.tabs([t[0] for t in TABLES])
    for tab, (label, name, blurb, team_cols, name_cols) in zip(tabs, TABLES):
        with tab:
            st.caption(blurb)
            c1, c2, c3 = st.columns([1.3, 1.6, 1], vertical_alignment="bottom")
            with c1:
                team = st.selectbox("Team", teams, key=f"raw_team_{name}", disabled=not team_cols)
            with c2:
                who = st.text_input("Player name contains", key=f"raw_who_{name}", disabled=not name_cols,
                                    placeholder="e.g. Babar")
            df = _filtered(name, span, team, who, lg.key, lg)
            with c3:
                st.download_button("CSV", data=functools.partial(_csv, name, span, team, who, lg),
                                   file_name=f"the-18th-yard-{lg.slug}-{name}-{min(span)}-{max(span)}.csv",
                                   mime="text/csv",
                                   key=f"raw_csv_{name}", on_click="ignore", icon=":material/download:",
                                   width="stretch")
            shown = df if len(df) <= MAX_SHOW else df.head(MAX_SHOW)
            st.caption(f"{len(df):,} rows" + (f" (showing the first {MAX_SHOW:,}; the CSV has them all)"
                                               if len(df) > MAX_SHOW else ""))
            cfg = {c: st.column_config.DateColumn(c, format="D MMM YYYY") for c in df.columns
                   if pd.api.types.is_datetime64_any_dtype(df[c])}
            for c in ("Season", "Match ID"):
                if c in df.columns:
                    cfg[c] = st.column_config.NumberColumn(c, format="%d")
            st.dataframe(shown, width="stretch", hide_index=True, height=520, column_config=cfg, placeholder="—")
