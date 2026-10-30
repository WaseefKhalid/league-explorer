"""
Admin · Add a league: a Cricsheet CSV2 zip in, the whole site for that league out.

The build runs engine.build_league() in this session; the league appears in
the sidebar picker at once (for this visitor only). "Download data bundle"
gives the files to commit to GitHub, after which it is on the site for
everyone. Building a newer zip with the same short name refreshes a league.
"""
from __future__ import annotations

import functools
import inspect
import io
import json
import re
import time
import traceback
import zipfile

import pandas as pd
import streamlit as st

from analytics import data as d
from components import auth, leagues
from components import theme as ui

# What every league folder holds (the PSL's files are the template)
CORE_TABLES = ["ball", "matches", "team_matches", "bat_inns", "bowl_inns", "partnerships", "pair_seasons",
               "player_seasons", "players", "lists"]
MVP_TABLES = ["scoreboard", "definitions", "glance", "highlights", "highlights_note", "ko_matches", "ko_cards",
              "ko_players", "close_matches", "close_players", "close_players_wb_tints", "close_teams",
              "close_glance", "close_definitions", "close_note"]
FLAG_LABELS = {"has_hand_type": "Batting hand & bowling type", "has_origin": "Overseas / local",
               "has_host": "Host country", "has_home": "Home / away", "has_fielding": "Fielding"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_ERROR = "wz_add_league_error"


def _missing(lg: d.League) -> list[str]:
    have = set(lg.tables or {})
    return [t for t in CORE_TABLES if t not in have] + [f"mvp/{t}" for t in MVP_TABLES if f"mvp/{t}" not in have]


def bundle_bytes(lg: d.League) -> bytes:
    """data/leagues/<slug>/<table>.parquet, …/mvp/<name>.parquet and …/meta.json, zipped.
    Runs when the button is clicked (it only reads the League it was given)."""
    root = f"data/leagues/{lg.slug}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, df in sorted((lg.tables or {}).items()):
            part = io.BytesIO()
            df.to_parquet(part, index=False)
            z.writestr(f"{root}/{name}.parquet", part.getvalue())
        z.writestr(f"{root}/meta.json", json.dumps(lg.meta, indent=2, ensure_ascii=False, default=str) + "\n")
    return buf.getvalue()


def _build(data: bytes, name: str, short: str, home: str, bar=None) -> None:
    """Run the engine; on success keep the league in this session and switch to it."""
    st.session_state.pop(_ERROR, None)
    try:
        from engine import build_league     # lazy: the public site never needs the engine
    except Exception as e:                  # noqa: BLE001 — any import problem means "not available"
        st.session_state[_ERROR] = ("The league builder (engine/) couldn't be loaded, so nothing was built.",
                                    f"{type(e).__name__}: {e}")
        return
    try:
        t0 = time.time()
        kw = {}
        if bar is not None and "progress" in inspect.signature(build_league).parameters:
            kw["progress"] = lambda f, text: bar.progress(min(max(float(f), 0.0), 1.0), text=str(text))
        tables, meta = build_league(data, name=name, short=short,
                                    overrides={"home_country": home} if home else {}, **kw)
        meta = dict(meta)
        meta.setdefault("name", name)
        meta.setdefault("short", short)
        slug = str(meta.get("slug") or short).lower()
        if not _SLUG.match(slug):
            raise ValueError(f"The engine returned an unusable slug: {slug!r}")
        meta["slug"] = slug
        lg = leagues.add(tables, meta)
        st.session_state["wz_add_league_done"] = (lg.slug, time.time() - t0)
    except Exception as e:                  # noqa: BLE001 — show the admin what went wrong
        st.session_state[_ERROR] = (f"The build failed: {type(e).__name__}: {e}", traceback.format_exc())


def _flag_chips(lg: d.League) -> str:
    out = []
    for f, lab in FLAG_LABELS.items():
        mark = "✓" if lg.has(f) else "—"
        out.append(f"{mark} {lab}")
    return " · ".join(out)


def _summary(lg: d.League) -> str:
    seasons = lg.meta.get("seasons") or []
    span = f"{min(seasons)}–{max(seasons)}" if seasons else "—"
    n = lg.meta.get("matches")
    return (f"{n:,} matches · seasons {span} · built {lg.meta.get('built', '—')}" if isinstance(n, int)
            else f"seasons {span} · built {lg.meta.get('built', '—')}")


def page():
    if not auth.is_admin():      # never served to the public, even by direct link
        st.stop()
    ui.top_bar()
    st.markdown('<div class="wz-title"><h1>Add a league</h1></div>', unsafe_allow_html=True)
    st.markdown('<p class="wz-dek">Turn any Cricsheet T20 league into the whole site: upload its ball-by-ball '
                'zip, name it, build. It opens here straight away; download the data bundle and commit it to '
                'put it on the site for everyone.</p>', unsafe_allow_html=True)

    with st.form("wz_add_league", border=True):
        up = st.file_uploader("Cricsheet zip (CSV2 format)", type=["zip"],
                              help="cricsheet.org → Downloads → pick the league → \"CSV2\" "
                                   "(for example ilt20_male_csv2.zip).")
        c1, c2, c3 = st.columns([2.2, 1, 1.6])
        with c1:
            name = st.text_input("League name", placeholder="International League T20")
        with c2:
            short = st.text_input("Short name", placeholder="ILT20", max_chars=12,
                                  help="Shown on every page (\"ILT20 2023–2026\") and used for the folder name.")
        with c3:
            home = st.text_input("Home country (optional)", placeholder="United Arab Emirates",
                                 help="Where the league is based: used for home / away, overseas / local and "
                                      "matches played abroad.")
        go = st.form_submit_button("Build", type="primary", icon=":material/construction:")
    if go:
        name, short, home = name.strip(), short.strip(), home.strip()
        missing = [w for w, ok in (("the zip", up is not None), ("a league name", name), ("a short name", short))
                   if not ok]
        if missing:
            st.warning("Still needed: " + ", ".join(missing) + ". The grey text in a box is only an example; "
                       "type your own.", icon=":material/info:")
        else:
            bar = st.progress(0.0, text=f"Building {name} from {up.name}… (large leagues take a minute)")
            _build(up.getvalue(), name, short, home, bar)
            bar.empty()
            if _ERROR not in st.session_state:
                st.rerun()          # so the sidebar picker lists (and shows) the new league

    if err := st.session_state.get(_ERROR):
        st.error(err[0], icon=":material/error:")
        with st.expander("Details"):
            st.code(err[1], language=None)
    if done := st.session_state.pop("wz_add_league_done", None):
        lg = leagues.built().get(done[0])
        if lg is not None:
            st.success(f"Built {lg.name} in {done[1]:.0f} s. It's selected in the sidebar now (for you only, "
                       "until you commit the bundle).", icon=":material/check_circle:")

    built = leagues.built()
    on_disk = d.disk_leagues()
    if built:
        st.subheader("Built in this session", anchor=False)
        for slug, lg in built.items():
            with st.container(border=True, key=f"built_{slug}"):
                st.markdown(f"**{ui._e(lg.name)}** ({ui._e(lg.short)}) · folder `{slug}`")
                st.caption(f"{_summary(lg)}  \n{_flag_chips(lg)}")
                if err := lg.meta.get("mvp_error"):
                    st.warning(f"The MVP step failed ({err}), so the MVP pages are left out for this league. "
                               "Everything else was built.", icon=":material/warning:")
                elif miss := _missing(lg):
                    st.warning("The build has no " + ", ".join(miss) + ". Pages that use them won't work for this "
                               "league until the engine produces them.", icon=":material/warning:")
                if slug in on_disk:
                    st.caption(f":material/sync: Committing this bundle replaces the {on_disk[slug].name} folder "
                               f"already on the site (a refresh).")
                b1, b2, b3 = st.columns([1.6, 1.2, 1], vertical_alignment="center")
                with b1:
                    st.download_button("Download data bundle", data=functools.partial(bundle_bytes, lg),
                                       file_name=f"{slug}-league-data.zip", mime="application/zip",
                                       on_click="ignore", icon=":material/download:", type="primary",
                                       key=f"bundle_{slug}", width="stretch")
                with b2:
                    st.button("Show this league", key=f"open_{slug}", on_click=leagues.choose, args=(slug,),
                              icon=":material/visibility:", width="stretch",
                              disabled=st.session_state.get(leagues.CHOICE) == slug)
                with b3:
                    st.button("Discard", key=f"drop_{slug}", on_click=leagues.discard, args=(slug,),
                              icon=":material/delete:", width="stretch")
        folder = next(iter(built)) if len(built) == 1 else "<folder>"
        st.markdown(
            "**Put it on the site for everyone**\n"
            f"1. Download the data bundle and unzip it. You get `data/leagues/{folder}/` with the tables, an `mvp` "
            "folder and `meta.json`.\n"
            "2. On GitHub, open the site's repository, go to `data/leagues/`, choose **Add file → Upload files** "
            f"and drag the `{folder}` folder in.\n"
            "3. Commit. When the app restarts, the league is in everyone's League picker.")

    st.subheader("Refresh a league", anchor=False)
    st.caption("New season or corrections? Download the newest zip from Cricsheet and build it here with the same "
               "short name. The bundle has the same folder name, so committing it overwrites the old files.")
    if on_disk:
        rows = [{"Folder": s, "League": lg.name, "Short": lg.short,
                 "Seasons": (f"{min(lg.meta['seasons'])}–{max(lg.meta['seasons'])}" if lg.meta.get("seasons")
                             else "—"),
                 "Matches": lg.meta.get("matches"), "Built": lg.meta.get("built"),
                 **{lab: lg.has(f) for f, lab in FLAG_LABELS.items()}}
                for s, lg in on_disk.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Matches": st.column_config.NumberColumn(format="%d")})
