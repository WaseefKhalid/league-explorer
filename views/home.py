"""Home: the league, headline numbers for the span, what's on the site, definitions, data notes."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics import data as d
from analytics import presets
from analytics.home import headline
from components import theme as ui
from components.render import span_label
from views.common import current_span

DEFINITIONS = [
    ("Phases", "PP = overs 1–6 · MO1 = overs 7–10 · MO2 = overs 11–16 · Death = overs 17–20."),
    ("Bowling types", "Right-arm pace, left-arm pace, off-spin, leg-spin (including googly bowlers), left-arm orthodox, "
                      "left-arm wrist-spin."),
    ("Strike rate (batting)", "Runs per 100 balls faced. No-balls count as faced; wides do not."),
    ("Average (batting)", "Runs ÷ dismissals. Run-outs are included; retired hurt is not out."),
    ("Economy and strike rate (bowling)", "Runs charged to the bowler (including wides and no-balls) per over, and "
                                          "legal balls per wicket. Byes, leg-byes and run-outs are not charged."),
    ("Impact", "Runs added (batting) or saved (bowling) compared with an average player in the same season, phase and "
               "match situation. See the Impact page."),
    ("Award type (Player of the Match)", "Batting-led, bowling-led, all-round or other, from the winner's match "
                                         "figures. See the Player of the Match page."),
    ("Decided match", "A result without DLS or a tie. Used for chasing, toss and par-score percentages."),
    ("Completed 1st innings", "19+ overs batted or all out, no DLS. Used for average first-innings scores."),
    ("Season", "The year the season ends in: {short} 1 = {first} … {short} {n} = {last}."),
]


def _date(ts) -> str:
    t = pd.Timestamp(ts)
    return f"{t.day} {t.strftime('%B %Y')}"


def _lede() -> str:
    """'All 11 seasons, ball by ball, with … Data to the 2026 final (3 May 2026). …' from the league's data."""
    seasons = d.seasons()
    n = len(seasons)
    with_ = ["batting hand", "bowling type"] if d.has("has_hand_type") else []
    with_ += ["phases", "impact"]
    count = f"All {n} seasons" if n > 1 else "One season"
    m = d.matches()
    dates = pd.to_datetime(m["Date"], errors="coerce")
    to = ""
    if dates.notna().any():
        last = m.loc[dates.idxmax()]
        when = _date(dates.max())
        to = (f" Data to the {int(last['Season'])} final ({when})." if str(last.get("Stage", "")) == "Final"
              else f" {len(m):,} matches, data to {when}.")
    return (f"{count}, ball by ball, with {', '.join(with_[:-1])} and {with_[-1]}.{to} Pick any run of seasons in "
            "the sidebar and every page recalculates.")


def _mvp_lede() -> str:
    from analytics import mvp_data as mvp
    try:
        g = dict(mvp.load("glance").values.tolist())
        n_imp, n_pl = int(g["Impact performances"]), int(g["Players"])
    except (FileNotFoundError, KeyError, ValueError, TypeError):
        try:
            n_imp, n_pl = len(mvp.load("highlights")), len(mvp.load("scoreboard"))
        except FileNotFoundError:
            n_imp = n_pl = None
    how_many = f"{n_imp:,} match-shaping performances from {n_pl:,} players" if n_imp is not None else \
        "every match-shaping performance"
    return (f"Who actually decides matches: {how_many} (fifties, hundreds, quick-fire 30s, 3-wicket hauls and "
            "economy spells), plus every knockout and every close finish.")


def _notes() -> list[str]:
    """The league's own data notes (the PSL's), else notes written from its data."""
    own = presets.preset("data_notes")
    if own:
        return own
    m = d.matches()
    dates = pd.to_datetime(m["Date"], errors="coerce")
    ties = int(m["Result"].astype(str).str.startswith("Tie").sum()) if "Result" in m else 0
    span = f", {_date(dates.min())} to {_date(dates.max())}" if dates.notna().any() else ""
    notes = [f"Source: Cricsheet ball-by-ball data ({len(m):,} {d.short()} matches{span}). Super overs are excluded "
             "from player and team stats" + (f" ({ties} tied game{'s' if ties != 1 else ''})." if ties else ".")]
    if d.has("has_hand_type"):
        notes.append("Batting hand and bowling style come from ESPNcricinfo profiles (via the open-source "
                     "cricketdata project) matched on Cricsheet player IDs; players without a profile are "
                     "\"Unknown\".")
    else:
        notes.append("Batting hand and bowling type aren't known for this league, so analyses built on them are "
                     "left out.")
    missing = [lab for f, lab in (("has_origin", "overseas / local"), ("has_host", "the host country"),
                                  ("has_home", "home / away"), ("has_fielding", "fielding"))
               if not d.has(f)]
    if missing:
        notes.append("Also not in this league's data: " + ", ".join(missing) + ". Those analyses are left out.")
    notes += ["Player identities follow Cricsheet IDs.",
              "Impact uses an expected-runs model built from this data (DLS and no-result games excluded)."]
    return notes


def _definitions() -> list[tuple[str, str]]:
    s = d.seasons()
    fill = dict(short=d.short(), first=s[0], last=s[-1], n=len(s))
    return [(t, m.format(**fill)) for t, m in DEFINITIONS
            if t != "Bowling types" or d.has("has_hand_type")]


def page():
    from views.registry import PAGE_INFO, current_pages, ledes

    span = current_span()
    pages, text = current_pages(), ledes()
    ui.top_bar()
    st.markdown(
        f'<div class="wz-title"><h1>{ui._e(d.current().name)}</h1>'
        f'<span class="wz-chip-span">{span_label(span)}</span></div>'
        f'<p class="wz-dek">{ui._e(_lede())}</p>',
        unsafe_allow_html=True)

    nums = headline(span)
    ui.scoreboard([(f"{v:,}", k) for k, v in nums], extra_class="wz-board-4")

    st.write("")
    sections: dict[str, list] = {}
    for url, (section, title, _m, kind, _lede_psl, icon) in PAGE_INFO.items():
        sections.setdefault(section, []).append((url, title, text[url], kind))

    mvp = sections.pop("MVP", [])       # shown last, after More
    blurbs = {
        "Insights": "The findings: what wins, who moves matches, who takes the award.",
        "Explorers": "Pick a player, team or ground and filter by anything.",
        "League": "How the league plays, season by season and ground by ground.",
        "Players": "Every batter, bowler and matchup, sortable.",
    }
    for section, items in sections.items():
        st.subheader(section, anchor=False)
        st.caption(blurbs.get(section, ""))
        cols = st.columns(3)
        for i, (url, title, lede, kind) in enumerate(items):
            with cols[i % 3]:
                with st.container(border=True, key=f"hc_{url}"):
                    page = pages.get(url)
                    if page is not None:
                        st.page_link(page, label=title, icon=page.icon)
                    st.caption(lede)
    st.subheader("More", anchor=False)
    more = [("records", "Highest and lowest totals, best innings and figures, biggest partnerships and batting by "
                        "position."),
            ("raw-data", "Every table behind the site, filterable and downloadable as CSV."),          # admin only
            ("add-league", "Build any Cricsheet T20 league into the site, or refresh one."),          # admin only
            ]
    cols = st.columns(3)
    for col, (url, blurb) in zip(cols, [m for m in more if m[0] in pages]):
        with col:
            with st.container(border=True):
                st.page_link(pages[url], label=pages[url].title, icon=pages[url].icon)
                st.caption(blurb)

    # Last: the MVP feature · Impact Performances (when this league's build has it)
    st.write("")
    mvp = [m for m in mvp if m[0] in pages]
    if mvp:
        with st.container(key="mvp_feature"):
            st.markdown(
                '<div class="wz-feature-head"><span class="wz-feature-tag">MVP</span><h2>Impact Performances</h2>'
                f'</div><p class="wz-feature-lede">{ui._e(_mvp_lede())}</p>', unsafe_allow_html=True)
            cols = st.columns(4)
            for i, (url, title, lede, kind) in enumerate(mvp):
                with cols[i % 4]:
                    with st.container(border=True, key=f"hc_{url}"):
                        st.page_link(pages[url], label=title, icon=pages[url].icon)
                        st.caption(lede)

    st.write("")
    with st.expander("Definitions", icon=":material/menu_book:"):
        st.markdown("\n".join(f"- **{t}.** {m}" for t, m in _definitions()))
    with st.expander("Data notes", icon=":material/info:"):
        st.markdown("\n".join(f"- {n}" for n in _notes()))
