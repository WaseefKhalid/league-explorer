"""
Which league this visitor is looking at.

The leagues on offer are every folder in data/leagues/ with a meta.json, plus
any league the admin built in this session (kept in st.session_state as
DataFrames, never written to disk; it replaces a folder with the same slug for
this session only). The choice lives in st.session_state and in the URL as
?league=<slug>, so it follows the visitor from page to page and a link opens
the same league.

app.py calls resolve() at the top of every run, which also makes the league
current for this run's thread (analytics.data.set_current).
"""
from __future__ import annotations

import streamlit as st

from analytics import data as d

CHOICE = "wz_league"            # the selected slug
BUILT = "wz_built_leagues"      # slug -> League built in this session (admin)
_WIDGET = "wz_league_w"
_PARAM = "league"


def built() -> dict[str, d.League]:
    return st.session_state.setdefault(BUILT, {})


def available() -> dict[str, d.League]:
    out = dict(d.disk_leagues())
    out.update(built())
    return out


def resolve() -> d.League:
    """The visitor's league for this run (session, else ?league=, else the PSL), made current."""
    leagues = available()
    if not leagues:
        st.error("No league data found. Each league needs a folder in data/leagues/ with a meta.json.")
        st.stop()
    slug = st.session_state.get(CHOICE)
    if slug not in leagues:
        asked = st.query_params.get(_PARAM)
        slug = asked if asked in leagues else (d.DEFAULT_SLUG if d.DEFAULT_SLUG in leagues else next(iter(leagues)))
        st.session_state[CHOICE] = slug
    lg = leagues[slug]
    d.set_current(lg)
    if st.query_params.get(_PARAM) != slug:
        st.query_params[_PARAM] = slug
    return lg


def choose(slug: str) -> None:
    """Switch league (use as a callback). The season span starts again at the new league's full span."""
    st.session_state[CHOICE] = slug
    st.session_state["span_gen"] = st.session_state.get("span_gen", 0) + 1


def _picked() -> None:
    choose(st.session_state[_WIDGET])


def label(lg: d.League) -> str:
    return lg.name + (" · this session" if lg.in_memory else "")


def picker() -> None:
    """The League box at the top of the sidebar."""
    leagues = available()
    slugs = sorted(leagues, key=lambda s: (leagues[s].name.lower(), s))
    st.session_state[_WIDGET] = st.session_state[CHOICE]
    st.selectbox("League", slugs, key=_WIDGET, format_func=lambda s: label(leagues[s]), on_change=_picked,
                 help="Every page shows the league picked here.")


def add(tables: dict, meta: dict) -> d.League:
    """Keep a freshly built league in this session and switch to it."""
    lg = d.memory_league(tables, meta)
    built()[lg.slug] = lg
    choose(lg.slug)
    return lg


def discard(slug: str) -> None:
    built().pop(slug, None)
    if st.session_state.get(CHOICE) == slug:
        st.session_state.pop(CHOICE, None)
        st.session_state["span_gen"] = st.session_state.get("span_gen", 0) + 1
