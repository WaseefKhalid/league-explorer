"""MVP · Knockout Matches: each picker sits right above what it changes."""
from __future__ import annotations

import streamlit as st

from analytics import mvp_data as m
from analytics import mvp_knockouts as ko
from components.render import blocks_for, render_blocks
from views.common import current_span, page_header

MATCH_KEY, PLAYER_KEY = "mvp_knockouts__match", "mvp_knockouts__player"


def _valid(key: str, options: list) -> str:
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]
    return st.session_state.get(key, options[0])


def _gap():
    st.markdown('<div class="wz-gap"></div>', unsafe_allow_html=True)


def page(title: str, lede: str):
    def _page():
        span = current_span()
        page_header(title, lede, span)
        opts = ko.filter_options(span)
        match = _valid(MATCH_KEY, opts["match"])
        player = _valid(PLAYER_KEY, opts["player"])
        blocks = {b.key: b for b in blocks_for("mvp_knockouts", span, (("match", match), ("player", player)))}

        render_blocks([blocks[k] for k in ("ko_glance", "ko_matches") if k in blocks], span, toc=False)
        if "ko_card" in blocks:
            _gap()
            with st.container(border=True):
                c, _ = st.columns([2, 3])
                with c:
                    st.selectbox("Pick a knockout match", opts["match"], key=MATCH_KEY)
            render_blocks([blocks["ko_card"]], span, toc=False)
        _gap()
        with st.container(border=True):
            c, _ = st.columns([2, 3])
            with c:
                st.selectbox("Pick a player (or all players)", opts["player"], key=PLAYER_KEY)
        render_blocks([blocks[k] for k in ("ko_player", "ko_players") if k in blocks], span, toc=False)
    _page.__name__ = "page_mvp_knockouts"
    return _page
