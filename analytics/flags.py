"""
What each meta.json flag switches off when a league's data lacks it.

One table for the whole site. components/render.blocks_for() runs apply()
on every page's Blocks (whole analyses, table columns and KPI tiles listed
under a flag the league doesn't have are dropped), and the explorer pages
drop the filters in FILTERS. Analytics modules don't need to know.

  has_hand_type  batting hand and bowling type (and pace / spin, which comes from the type)
  has_origin     overseas / local (and country, which it is worked out from)
  has_host       the country each match was played in
  has_home       home / away / neutral for each team
  has_fielding   catches, stumpings and run-outs by fielder
"""
from __future__ import annotations

import fnmatch

from analytics import data as d
from analytics.blocks import Block

HAND_TYPE, ORIGIN, HOST, HOME, FIELDING = d.FLAGS
_TYPE_SPLITS = ["SR v pace", "SR v spin", "Balls/dis v pace", "Balls/dis v spin", "SR v RA pace", "SR v LA pace",
                "SR v off-spin", "SR v leg-spin", "SR v LA orthodox", "SR v LA wrist-spin"]

# Whole analyses (Block keys)
BLOCKS: dict[str, set[str]] = {
    HAND_TYPE: {
        "ki_11", "ki_12", "ki_13", "ki_14", "ki_16",         # Key Insights: hand v type, left-arm pace,
                                                             # types at the death, left-right pairs, dismissals
        "team_05", "team_06",                                # Teams: batting v bowling types
        "ph_03", "ph_04", "ph_05", "ph_06",                  # Phases: types by phase, hand v type
        "bx_04", "bx_05",                                    # Batter Explorer: by bowler type, by hand
        "wx_04", "wx_05",                                    # Bowler Explorer: by hand, by bowler type
        "tx_05", "tx_06",                                    # Team Explorer: v bowling types, v batter hand
        "vx_05",                                             # Venue Explorer: bowler types at the ground
    },
    ORIGIN: {"ki_15", "potm_04"},                            # overseas share; POTM overseas v local
    HOST: set(),
    HOME: {"ki_07"},                                         # home advantage
    FIELDING: set(),
}

# Table columns, by Block key. A trailing * matches any column starting with the rest.
COLUMNS: dict[str, dict[str, list[str]]] = {
    HAND_TYPE: {
        "bat_all": ["Hand"] + _TYPE_SPLITS,
        "bbs_top150": ["Hand"],
        "bowl_all": ["Type", "Style", "Econ v RHB", "SR v RHB", "Econ v LHB", "SR v LHB"],
        "bws_top150": ["Type"],
        "mu_all": ["Hand", "Bowler type"],
        "pl_all": ["Bat Hand", "Bowling Style", "Bowling Type", "Hand Source", "Style Source", "Still Missing"],
        "ph_01": ["* Spin %"],                               # spin share of each phase
        "ph_02": ["Spin share"],
        "ven_01": ["Pace econ", "Spin econ", "Pace balls / wkt", "Spin balls / wkt", "Spin share"],
    },
    ORIGIN: {
        "bat_all": ["Country"],
        "bowl_all": ["Country"],
        "pl_all": ["Country", "Overseas/Local"],
        "potm_02": ["Overseas winners"],
    },
    HOST: {
        "sea_01": ["In *", "Abroad"],                        # matches played outside the home country
        "ven_01": ["Host"],
    },
    HOME: {},
    FIELDING: {
        "pl_all": ["Catches"],
    },
}

# KPI tiles, by Block key and label
KPIS: dict[str, dict[str, list[str]]] = {
    ORIGIN: {"potm_kpis": ["WON BY OVERSEAS PLAYERS"]},
}

# Explorer filters (keyword names used by the analytics modules)
FILTERS: dict[str, set[str]] = {
    HAND_TYPE: {"bowler_type", "pace_spin", "batter_hand", "bat_hand"},
    HOST: {"host"},
}


def missing(league: d.League | None = None) -> list[str]:
    lg = league or d.current()
    return [f for f in d.FLAGS if not lg.has(f)]


def hidden_filters(league: d.League | None = None) -> set[str]:
    out: set[str] = set()
    for f in missing(league):
        out |= FILTERS.get(f, set())
    return out


def hidden_blocks(league: d.League | None = None) -> set[str]:
    out: set[str] = set()
    for f in missing(league):
        out |= BLOCKS.get(f, set())
    return out


def _match(cols, patterns) -> list:
    return [c for c in cols if any(fnmatch.fnmatchcase(str(c), p) for p in patterns)]


def _drop_columns(b: Block, patterns: list[str]) -> None:
    if b.df is None:
        return
    gone = _match(b.df.columns, patterns)
    if not gone:
        return
    b.df = b.df.drop(columns=gone)
    if b.labels is not None:
        b.labels = b.labels.drop(columns=[c for c in gone if c in b.labels.columns])
    if b.cell_tints is not None:
        b.cell_tints = b.cell_tints.drop(columns=[c for c in gone if c in b.cell_tints.columns])
    for c in gone:
        b.rules.pop(c, None)
        b.fmt.pop(c, None)
        b.center.pop(c, None)
    b.good_high = [c for c in b.good_high if c not in gone]
    b.good_low = [c for c in b.good_low if c not in gone]
    b.bars = [c for c in b.bars if c not in gone]
    b.muted_cols = [c for c in (b.muted_cols or []) if c not in gone]
    if b.chart:
        y = b.chart.get("y")
        ys = list(y) if isinstance(y, (list, tuple)) else [y]
        keep = [c for c in ys if c not in gone]
        if b.chart.get("x") in gone or not keep:
            b.chart = None
        elif len(keep) != len(ys):
            b.chart = dict(b.chart, y=keep if isinstance(y, (list, tuple)) else keep[0])


def apply(blocks: list[Block], league: d.League | None = None) -> list[Block]:
    """Drop what the league's data can't support. A league with every flag gets its Blocks back untouched."""
    gone = missing(league)
    if not gone:
        return blocks
    skip = hidden_blocks(league)
    out = []
    for b in blocks:
        if b.key in skip:
            continue
        cols = [p for f in gone for p in COLUMNS.get(f, {}).get(b.key, [])]
        if cols:
            _drop_columns(b, cols)
        tiles = {lab for f in gone for lab in KPIS.get(f, {}).get(b.key, [])}
        if tiles and b.kpis:
            b.kpis = [k for k in b.kpis if k[0] not in tiles]
        out.append(b)
    return out
