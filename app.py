"""
League Explorer · The 18th Yard — the analytics site for any T20 league.

Each league is a folder in data/leagues/ (parquet tables + meta.json): the PSL
from the PSL Analytics Workbook, any other league built from its Cricsheet zip
by engine/ (admin page "Add a league"). Every page is generated from
analytics/* (pure pandas; the PSL checked cell-for-cell against the workbook)
and rendered by components/*. The League picker and the season span at the
top of the sidebar drive every page.
"""
import streamlit as st

st.set_page_config(
    page_title="League Explorer · The 18th Yard",
    page_icon="🏏",
    layout="wide",
    initial_sidebar_state="auto",
)

from analytics import data as d  # noqa: E402
from components import auth, leagues  # noqa: E402
from components import theme as ui  # noqa: E402
from views import registry  # noqa: E402

st.session_state._chart_counter = 0
ui.inject_css()
# Public visitors: view and PNG only (no CSV on tables). Admin: everything.
if css := auth.public_css():
    st.markdown(css, unsafe_allow_html=True)

# ── League: one picker for the whole site (also sets it for this run's thread) ──
league = leagues.resolve()

# ── Season span: one control for the whole site, over the league's seasons ──
SEASONS = list(d.seasons())
FULL = (SEASONS[0], SEASONS[-1])
st.session_state.setdefault("span_gen", 0)


def _reset_span():
    st.session_state.span_gen += 1      # a fresh slider starts at the full span


with st.sidebar:
    st.markdown(
        f'<div class="wz-brand">{ui.ball_svg(24)}{ui.wordmark()}</div>',
        unsafe_allow_html=True)
    st.write("")
    leagues.picker()
    if len(SEASONS) > 1:
        lo, hi = st.select_slider(
            "Seasons", options=SEASONS, value=FULL, key=f"span_w{st.session_state.span_gen}_{league.key}",
            help="Pick any run of seasons, or the same season twice for one year. Every page recalculates.")
        st.session_state.span = (min(lo, hi), max(lo, hi))
        st.button("All seasons", on_click=_reset_span, icon=":material/restart_alt:", width="stretch",
                  disabled=st.session_state.span == FULL)
        st.caption("Every page follows this span.")
    else:
        st.session_state.span = FULL
        st.caption(f"Seasons: {SEASONS[0]} (the only season in the data so far).")
    st.divider()
    st.markdown(ui.contact_links(), unsafe_allow_html=True)
    st.write("")
    auth.panel()

page = st.navigation(registry.sections(admin=auth.is_admin()), position="top", expanded=True)
page.run()
ui.footer()
