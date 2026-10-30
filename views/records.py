"""Records page — analyses kept from the original site (not in the workbook)."""
from __future__ import annotations

import streamlit as st

from analytics import records
from components.render import blocks_for, render_blocks
from views.common import current_span, page_header


def page():
    span = current_span()
    page_header("Records", "Highest and lowest totals, best innings and bowling figures, the biggest partnerships "
                           "and batting by position. Pick a batter to see their partners and positions.", span)
    opts = records.filter_options(span)["player"]
    key = "records__player"
    if key in st.session_state and st.session_state[key] not in opts:
        del st.session_state[key]
    with st.container(border=True):
        c, _ = st.columns([2, 3])
        with c:
            player = st.selectbox("Batter (for partners and positions)", opts, key=key)
    blocks = blocks_for("records", span, (("player", player),))
    render_blocks(blocks, span)
