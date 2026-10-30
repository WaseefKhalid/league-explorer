"""
Editorial choices for leagues we know well, keyed by league slug.

Everything here is optional. A league without an entry (any league built
from a Cricsheet zip) gets defaults worked out from its own data. The PSL
entry keeps the PSL pages exactly as they were validated against the PSL
Analytics Workbook: the grounds and teams its Key Insights compare, its
season notes and the data notes on Home. A refreshed PSL (same slug) keeps
them too.
"""
from __future__ import annotations

from analytics import data as d

PRESETS: dict[str, dict] = {
    "psl": {
        "home_country": "Pakistan",
        # Key Insights · par scores: extra columns (header, venue)
        "par_venues": [("National Stadium", "National Stadium"), ("Gaddafi Stadium", "Gaddafi Stadium"),
                       ("Rawalpindi", "Rawalpindi Cricket Stadium")],
        # Key Insights · the toss: grounds, in the order shown
        "toss_venues": ["Dubai International Cricket Stadium", "Sharjah Cricket Stadium", "National Stadium",
                        "Gaddafi Stadium", "Sheikh Zayed Stadium", "Rawalpindi Cricket Stadium",
                        "Multan Cricket Stadium"],
        # Key Insights · home advantage: (team, home ground label)
        "home_teams": [("Multan Sultans", "Multan"), ("Lahore Qalandars", "Gaddafi, Lahore"),
                       ("Islamabad United", "Rawalpindi"), ("Karachi Kings", "National, Karachi")],
        # Key Insights · left-arm pace: the stars taken out of the third row, and how the row names them
        "left_arm_stars": (["Shaheen Shah Afridi", "Mohammad Amir", "Wahab Riaz"], "Shaheen, Amir & Wahab"),
        # Season by Season · how to read (extra lines)
        "season_notes": [
            "2020 playoffs were played in November 2020; 2021 was split between Karachi and Abu Dhabi.",
            "Seven league fixtures were washed out without a ball and are not in the data "
            "(2016 KK–PZ, 2018 KK–MS, 2020 IU–PZ & MS–QG, 2024 IU–QG & LQ–PZ, 2026 IU–PZ).",
        ],
        # Player List · how to read (extra lines)
        "players_notes": [
            "* Country missing in the source; these are Pakistani domestic players and are treated as local.",
        ],
        # Home · data notes
        "data_notes": [
            "Source: Cricsheet ball-by-ball data (357 PSL matches, 2016 to 3 May 2026). Super overs are excluded "
            "from player and team stats (4 tied games).",
            "Batting hand and bowling style come from ESPNcricinfo profiles via the open-source cricketdata "
            "project, matched on Cricsheet player IDs, plus 27 hand-supplied entries and 2 web-checked "
            "corrections (Sufiyan Muqeem, Saim Ayub). 17 fringe players remain \"Unknown\" (0.3% of balls).",
            "Seven league fixtures were washed out without a ball and are not in the data: 2016 KK–PZ, 2018 "
            "KK–MS, 2020 IU–PZ and MS–QG, 2024 IU–QG and LQ–PZ, 2026 IU–PZ (inferred). Points tables built from "
            "this data must add 1 point each.",
            "Player identities follow Cricsheet IDs (renamed players merged; two Khurram Shahzads and two "
            "Mohammad Imrans kept separate; the two Tayyab Abbas IDs merged).",
            "Impact uses an expected-runs model built from this data (DLS and no-result games excluded).",
        ],
    },
}


def preset(key: str, default=None):
    """The current league's preset `key`, or `default`."""
    return PRESETS.get(d.current().slug, {}).get(key, default)


@d.per_league()
def home_country() -> str:
    """meta.json's home_country, else the preset, else the country that hosted most matches."""
    hc = d.meta().get("home_country") or preset("home_country")
    if hc:
        return str(hc)
    host = d.matches()["Host"].dropna().astype(str)
    host = host[host != "Unknown"]
    return str(host.value_counts().index[0]) if len(host) else ""
