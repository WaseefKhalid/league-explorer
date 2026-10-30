"""Every page on the site, grouped the way the top navigation shows them."""
from __future__ import annotations

import threading

import streamlit as st

from analytics import data as d
from analytics import flags
from views.common import explorer_page, span_page

PAGE_INFO = {
    # url: (section, title, module, kind, lede, icon) — the lede here is the PSL wording;
    # ledes() rewrites it for the current league (counts, and what its data supports).
    # ── MVP: the Impact Performances workbook, the site's headline feature ──
    "mvp-scoreboard": ("MVP", "MVP Scoreboard", "mvp_scoreboard", "explorer",
                       "Who delivers when it counts: every player's fifties, hundreds, quick-fire 30s, 3-wicket "
                       "hauls and economy spells, with knockout and close-finish appearances.",
                       ":material/workspace_premium:"),
    "impact-highlights": ("MVP", "Impact Highlights", "mvp_highlights", "explorer",
                          "Every one of the 1,905 impact performances, ranked within its category, with the leaders "
                          "in each.", ":material/auto_awesome:"),
    "knockout-matches": ("MVP", "Knockout Matches", "mvp_knockouts", "explorer",
                         "All 44 play-offs: every scorecard with the impact performances marked, and every player's "
                         "knockout record.", ":material/trophy:"),
    "close-finishes": ("MVP", "Close Finishes", "mvp_close", "explorer",
                       "How teams and players perform when the match is tight, against how they do in all matches.",
                       ":material/hourglass_bottom:"),
    "key-insights": ("Insights", "Key Insights", "key_insights", "span",
                     "Eighteen findings from 83,749 balls: what really wins games, the chase calculator, par scores, "
                     "toss traps, matchup edges and hidden specialists.", ":material/lightbulb:"),
    "impact": ("Insights", "Impact", "impact", "span",
               "Who really moves matches: runs added or saved against an average player, wicket-taking value, "
               "run-scoring impact, last-over specialists and final-over defences.", ":material/bolt:"),
    "player-of-the-match": ("Insights", "Player of the Match", "potm", "span",
                            "Most awards and award rate, awards by team, what kind of performance wins it, overseas v "
                            "local, losing-side awards and every final.", ":material/emoji_events:"),
    "batter-explorer": ("Explorers", "Batter Explorer", "explore_batter", "explorer",
                        "Any batter, or all batters, by venue, phase, bowler type, pace or spin, opposition, innings, "
                        "match type, host and batter hand — with impact.", ":material/sports_cricket:"),
    "bowler-explorer": ("Explorers", "Bowler Explorer", "explore_bowler", "explorer",
                        "Any bowler, or all bowlers of a type, by venue, phase, batter hand, opposition, innings, "
                        "match type and host — with impact.", ":material/sports_baseball:"),
    "matchup-explorer": ("Explorers", "Matchup Explorer", "explore_matchup", "explorer",
                         "Batter v bowler head-to-head by season and phase, and team v team head-to-head.",
                         ":material/swords:"),
    "team-explorer": ("Explorers", "Team Explorer", "explore_team", "explorer",
                      "Record, toss, bat-first and chasing, phase profile, batting v bowler types, bowling v batter "
                      "hand and season finishes for any team.", ":material/groups:"),
    "venue-explorer": ("Explorers", "Venue & Toss Explorer", "explore_venue", "explorer",
                       "Par scores, toss value, chasing, phase scoring, bowler types and team records at any ground.",
                       ":material/stadium:"),
    "seasons": ("League", "Season by Season", "seasons", "span",
                "Champions, scoring trends, chasing and toss by season, plus a Selected span row that adds up your "
                "seasons.", ":material/calendar_month:"),
    "teams": ("League", "Teams", "teams", "span",
              "Records, season finishes, head-to-heads and team profiles.", ":material/shield:"),
    "toss-and-chasing": ("League", "Toss & Chasing", "toss_chasing", "span",
                         "Does the toss matter, what wins batting first, and when is a chase safe.",
                         ":material/swap_vert:"),
    "venues": ("League", "Venues", "venues", "span",
               "How each ground plays: scoring, chasing, toss and pace v spin.", ":material/location_on:"),
    "phases": ("League", "Phases", "phases", "span",
               "PP (overs 1–6), MO1 (7–10), MO2 (11–16) and Death (17–20): trends, the over-by-over curve, bowling "
               "types by phase and batter hand v bowling type.", ":material/timeline:"),
    "batting": ("Players", "Batting", "batting", "span",
                "Every batter: totals, phase, pace or spin, bowling-type and innings-stage strike rates, and impact.",
                ":material/sports_cricket:"),
    "best-batting-seasons": ("Players", "Best Batting Seasons", "best_batting", "span",
                             "The 150 highest run-scoring individual seasons inside your span.", ":material/star:"),
    "bowling": ("Players", "Bowling", "bowling", "span",
                "Every bowler: totals, phase economy and wickets, workload by phase, v RHB and LHB, and impact.",
                ":material/sports_baseball:"),
    "best-bowling-seasons": ("Players", "Best Bowling Seasons", "best_bowling", "span",
                             "The 150 highest wicket-taking individual seasons inside your span.", ":material/star:"),
    "matchups": ("Players", "Matchups", "matchups", "explorer",
                 "Every batter–bowler pair that has met for 12+ balls: head-to-head and who is on top.",
                 ":material/compare_arrows:"),
    "players": ("Players", "Player List", "players_list", "span",
                "All 459 players: hand, bowling style and type, country, and matches, runs, wickets, awards and "
                "impact in your span.", ":material/badge:"),
}

# Filter rows for explorer pages that don't use the default (first filter alone, then the rest)
GROUPS = {
    "mvp_scoreboard": [["team", "role", "player"]],
    "mvp_highlights": [["category", "stage", "close"], ["team", "player"]],
    "mvp_close": [["team", "player"]],
    "matchups": [["batter", "bowler", "edge"]],
}

_NUMBER_WORDS = {n: w for n, w in enumerate(
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen "
    "Seventeen Eighteen".split())}
_KI_KEYS = [f"ki_{i:02d}" for i in range(1, 19)]


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _count(fn) -> int | None:
    try:
        return len(fn())
    except (FileNotFoundError, KeyError):
        return None


@d.per_league()
def ledes() -> dict[str, str]:
    """Each page's one-line description for the current league: its own counts, and
    no mention of analyses its data can't support."""
    from analytics import mvp_data as m

    ht, origin, host = d.has("has_hand_type"), d.has("has_origin"), d.has("has_host")
    out = {url: info[4] for url, info in PAGE_INFO.items()}

    n_imp = _count(lambda: m.load("highlights"))
    out["impact-highlights"] = (f"Every one of the {n_imp:,} impact performances, ranked within its category, with "
                                f"the leaders in each." if n_imp else
                                "Every impact performance, ranked within its category, with the leaders in each.")
    n_ko = _count(lambda: m.load("ko_matches"))
    who = f"All {n_ko} play-offs" if n_ko and n_ko > 1 else ("The play-off" if n_ko == 1 else "Every play-off")
    out["knockout-matches"] = (f"{who}: every scorecard with the impact performances marked, and every player's "
                               "knockout record.")

    n_ki = len([k for k in _KI_KEYS if k not in flags.hidden_blocks()])
    topics = ["what really wins games", "the chase calculator", "par scores", "toss traps"] + \
        (["matchup edges"] if ht else []) + ["hidden specialists"]
    out["key-insights"] = (f"{_NUMBER_WORDS.get(n_ki, str(n_ki))} findings from {len(d.ball()):,} balls: "
                           f"{_and(topics)}.")
    out["player-of-the-match"] = ("Most awards and award rate, awards by team, what kind of performance wins it, "
                                  + ("overseas v local, " if origin else "") + "losing-side awards and every final.")

    by = ["venue", "phase"] + (["bowler type", "pace or spin"] if ht else []) + \
        ["opposition", "innings", "match type"] + (["host"] if host else []) + (["batter hand"] if ht else [])
    out["batter-explorer"] = f"Any batter, or all batters, by {_and(by)} — with impact."
    by = ["venue", "phase"] + (["batter hand"] if ht else []) + ["opposition", "innings", "match type"] + \
        (["host"] if host else [])
    out["bowler-explorer"] = (f"Any bowler, or all bowlers{' of a type' if ht else ''}, by {_and(by)} — with "
                              "impact.")
    parts = ["Record", "toss", "bat-first and chasing", "phase profile"] + \
        (["batting v bowler types", "bowling v batter hand"] if ht else []) + ["season finishes"]
    out["team-explorer"] = f"{_and(parts)} for any team."
    parts = ["Par scores", "toss value", "chasing", "phase scoring"] + (["bowler types"] if ht else []) + \
        ["team records"]
    out["venue-explorer"] = f"{_and(parts)} at any ground."
    out["venues"] = "How each ground plays: " + _and(["scoring", "chasing", "toss"] + (["pace v spin"] if ht else [])) + "."
    out["phases"] = ("PP (overs 1–6), MO1 (7–10), MO2 (11–16) and Death (17–20): " +
                     _and(["trends", "the over-by-over curve"] +
                          (["bowling types by phase", "batter hand v bowling type"] if ht else [])) + ".")
    out["batting"] = ("Every batter: totals, " +
                      ("phase, pace or spin, bowling-type and innings-stage" if ht else "phase and innings-stage") +
                      " strike rates, and impact.")
    out["bowling"] = ("Every bowler: totals, phase economy and wickets, workload by phase, " +
                      ("v RHB and LHB, " if ht else "") + "and impact.")
    profile = (["hand", "bowling style and type"] if ht else []) + (["country"] if origin else [])
    n_pl = len(d.players())
    out["players"] = (f"All {n_pl:,} players: " + (", ".join(profile) + ", and " if profile else "") +
                      "matches, runs, wickets, awards and impact in your span.")
    return out


_run = threading.local()   # this run's pages (for st.page_link on Home), per visitor


def current_pages() -> dict[str, st.Page]:
    return getattr(_run, "pages", {})


def pages(admin: bool = False) -> dict[str, st.Page]:
    from views import add_league, home, raw_data, records
    text = ledes()
    out = {"home": st.Page(home.page, title="Home", icon=":material/home:", url_path="home", default=True)}
    mvp_ok = d.current().has_mvp
    for url, (section, title, module, kind, _lede, icon) in PAGE_INFO.items():
        if section == "MVP" and not mvp_ok:      # this league's build has no MVP tables
            continue
        lede = text[url]
        if url == "matchup-explorer":
            from views.matchup import page as fn
        elif url == "knockout-matches":
            from views import mvp_knockouts
            fn = mvp_knockouts.page(title, lede)
        else:
            fn = span_page(module, title, lede) if kind == "span" else \
                explorer_page(module, title, lede, GROUPS.get(module))
        out[url] = st.Page(fn, title=title, icon=icon, url_path=url)
    out["records"] = st.Page(records.page, title="Records", icon=":material/military_tech:", url_path="records")
    if admin:   # the raw tables, their CSVs and the league builder are for the admin only
        out["raw-data"] = st.Page(raw_data.page, title="Raw Data", icon=":material/table_view:",
                                  url_path="raw-data")
        out["add-league"] = st.Page(add_league.page, title="Add a league", icon=":material/add_circle:",
                                    url_path="add-league")
    _run.pages = out
    return out


def sections(admin: bool = False) -> dict[str, list[st.Page]]:
    p = pages(admin)
    groups: dict[str, list] = {"": [p["home"]], "Insights": [], "Explorers": [], "League": [], "Players": []}
    mvp: list = []
    for url, (section, *_rest) in PAGE_INFO.items():
        if url in p:
            (mvp if section == "MVP" else groups[section]).append(p[url])
    groups["More"] = [p["records"]] + [p[k] for k in ("raw-data", "add-league") if k in p]
    if mvp:
        groups["MVP"] = mvp      # last in the menu
    return groups
