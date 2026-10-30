"""Shared page scaffolding: header, season span, span pages and explorer pages."""
from __future__ import annotations

import importlib

import streamlit as st

from analytics import data as d
from analytics import flags
from components import theme as ui
from components.render import blocks_for, render_blocks, span_label


def current_span() -> tuple[int, int]:
    """The sidebar's season span, kept inside the current league's seasons."""
    s = d.seasons()
    span = st.session_state.get("span")
    if not span:
        return (s[0], s[-1])
    lo, hi = int(min(span)), int(max(span))
    if lo > s[-1] or hi < s[0]:
        return (s[0], s[-1])
    return (max(lo, s[0]), min(hi, s[-1]))


def page_header(title: str, lede: str | None, span) -> None:
    ui.top_bar()
    chip = f'<span class="wz-chip-span">{span_label(span)}</span>'
    st.markdown(f'<div class="wz-title"><h1>{ui._e(title)}</h1>{chip}</div>', unsafe_allow_html=True)
    if lede:
        st.markdown(f'<p class="wz-dek">{lede}</p>', unsafe_allow_html=True)


def span_page(module: str, title: str, lede: str):
    def _page():
        span = current_span()
        page_header(title, lede, span)
        with st.spinner("Working it out…"):
            blocks = blocks_for(module, span)
        render_blocks(blocks, span)
    _page.__name__ = f"page_{module}"
    return _page


def _options(module: str, span) -> dict:
    """The explorer's filter choices for the current league (filters its data lacks are dropped)."""
    lg = d.current()
    opts = _cached_options(module, tuple(span), lg.key, lg)
    hidden = flags.hidden_filters(lg)
    return {k: v for k, v in opts.items() if k not in hidden}


@st.cache_data(show_spinner=False)
def _cached_options(module: str, span, league_key: str, _league: d.League) -> dict:
    mod = importlib.import_module(f"analytics.{module}")
    with d.using(_league):
        return mod.filter_options(span)


def _label(name: str) -> str:
    special = {"pace_spin": "Pace / spin", "match_type": "Match type", "bat_hand": "Batter hand",
               "batter_hand": "Batter hand", "bowler_type": "Bowler type", "bowl_type": "Bowler type",
               "team_a": "Team", "team_b": "Opponent", "opposition": "Opposition", "host": "Host country",
               "innings": "Innings"}
    return special.get(name, name.replace("_", " ").capitalize())


def explorer_page(module: str, title: str, lede: str, groups: list[list[str]] | None = None):
    """groups: optional rows of filter names, e.g. [["batter"], ["venue", "phase", ...]]."""
    def _page():
        span = current_span()
        page_header(title, lede, span)
        mod = importlib.import_module(f"analytics.{module}")
        opts = _options(module, span)
        defaults = getattr(mod, "DEFAULTS", {})
        names = [n for n in getattr(mod, "FILTERS", list(opts)) if n in opts]
        rows = groups or [names[:1], names[1:]]
        chosen = {}
        with st.container(border=True):
            for row in rows:
                row = [n for n in row if n in opts]
                if not row:
                    continue
                if len(row) == 1:
                    slots = [st.columns([2, 3])[0]]
                else:
                    slots = []
                    with st.container(key=f"flt_{module}_{len(chosen)}"):
                        for start in range(0, len(row), 4):
                            slots += st.columns(4)[:len(row[start:start + 4])]
                for col, name in zip(slots, row):
                    choices = list(opts[name])
                    key = f"{module}__{name}"
                    default = defaults.get(name, choices[0] if choices else None)
                    if key in st.session_state and st.session_state[key] not in choices:
                        del st.session_state[key]
                    idx = choices.index(default) if default in choices else 0
                    with col:
                        chosen[name] = st.selectbox(_label(name), choices, index=idx, key=key)
        filters = tuple(sorted(chosen.items()))
        with st.spinner("Working it out…"):
            blocks = blocks_for(module, span, filters)
        render_blocks(blocks, span, toc=len(blocks) > 4)
    _page.__name__ = f"page_{module}"
    return _page
