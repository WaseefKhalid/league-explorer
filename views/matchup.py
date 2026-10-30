"""Matchup Explorer: two tools on one page — batter v bowler, and team v team."""
from __future__ import annotations

import streamlit as st

from analytics import explore_matchup as mx
from components.render import blocks_for, render_blocks
from views.common import _label, _options, current_span, page_header

PAIR = ["batter", "bowler", "phase", "venue", "match_type"]
TEAM = ["team_a", "team_b", "team_venue", "team_match_type"]
LABELS = {"team_a": "Team", "team_b": "Opponent", "team_venue": "Venue", "team_match_type": "Match type"}


def _panel(names, opts, prefix):
    defaults = mx.defaults()
    chosen = {}
    with st.container(border=True, key=f"flt_matchup_{prefix}"):
        for start in range(0, len(names), 4):
            row = names[start:start + 4]
            for col, name in zip(st.columns(4), row):
                choices = list(opts[name])
                key = f"explore_matchup__{name}"
                if key in st.session_state and st.session_state[key] not in choices:
                    del st.session_state[key]
                default = defaults.get(name, choices[0] if choices else None)
                idx = choices.index(default) if default in choices else 0
                with col:
                    chosen[name] = st.selectbox(LABELS.get(name, _label(name)), choices, index=idx, key=key)
    return chosen


def page():
    span = current_span()
    page_header("Matchup Explorer", "Batter v bowler head-to-head by season and phase, and team v team "
                                    "head-to-head.", span)
    opts = _options("explore_matchup", span)
    tab_pair, tab_team = st.tabs(["Batter v bowler", "Team v team"])
    with tab_pair:
        pair = _panel([n for n in PAIR if n in opts], opts, "pair")
    with tab_team:
        team = _panel([n for n in TEAM if n in opts], opts, "team")
    filters = tuple(sorted({**pair, **team}.items()))
    blocks = blocks_for("explore_matchup", span, filters)
    team_keys = {"mx_05", "mx_06", "mx_07", "mx_08"}
    with tab_pair:
        render_blocks([b for b in blocks if b.key not in team_keys], span, toc=False)
    with tab_team:
        render_blocks([b for b in blocks if b.key in team_keys], span, toc=False)
