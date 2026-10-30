"""
Matchup Explorer — batter v bowler head-to-head and team v team head-to-head.

Mirrors the workbook sheet "Matchup Explorer":
  §02 Head-to-head summary (batter v bowler)      -> mx_02 (kpis)
  §03 By season (ignores the season range)        -> mx_03
  §04 By phase (ignores the phase filter)         -> mx_04
  §06 Team head-to-head summary                   -> mx_06 (kpis)
  §07 Team head-to-head by season                 -> mx_07

`span` replaces both Season from/to boxes (C8/C9 and C37/C38).
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd

import analytics.data as d
from analytics.blocks import Block

FILTERS = ["batter", "bowler", "phase", "venue", "match_type",
           "team_a", "team_b", "team_venue", "team_match_type"]

# Values selected in the saved workbook ('Matchup Explorer'!C6:C12, C35:C40)
DEFAULTS = {
    "batter": "Babar Azam",
    "bowler": "Shaheen Shah Afridi",
    "phase": "All",
    "venue": "All",
    "match_type": "All",
    "team_a": "Lahore Qalandars",
    "team_b": "Karachi Kings",
    "team_venue": "All",
    "team_match_type": "All",
}

DASH = "—"

HOW_TO_READ = (
    "Choose any batter and bowler. Dismissals count only wickets credited to the bowler "
    "(run-outs excluded).\n"
    "Verdict compares the pair with the batter's own career: Bowler on top = 2+ dismissals at "
    "1.5x his usual rate without being hit harder, or SR 15+ below career while still getting "
    "him out. Batter on top = SR 15+ above career without falling more often, or 24+ balls "
    "unbeaten at career SR or better. Needs 6+ balls.\n"
    "For a sortable list of every pair with 12+ balls, see the Matchups sheet."
)

BVB_COLS = ["Balls", "Runs", "Strike rate", "Dismissals", "Dot %", "4s", "6s"]
BVB_FMT = {"Balls": "{:,.0f}", "Runs": "{:,.0f}", "Strike rate": "{:,.1f}",
           "Dismissals": "{:,.0f}", "Dot %": "{:.1%}", "4s": "{:,.0f}", "6s": "{:,.0f}"}
TT_COLS = ["Season", "Matches", "A wins", "B wins", "No result", "A win %"]


# ── helpers ──────────────────────────────────────────────────────────────────
def _isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def xl_fmt(v, numfmt: str) -> str:
    """Format a value the way Excel shows it for the given number format
    (round half away from zero on the 15-significant-digit value)."""
    if _isnan(v):
        return DASH
    if isinstance(v, str):
        return v
    pct = numfmt.endswith("%")
    core = numfmt.rstrip("%")
    places = len(core.split(".")[1]) if "." in core else 0
    x = float(v) * (100 if pct else 1)
    q = Decimal(f"{x:.15g}").quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if q == 0:
        q = abs(q)
    s = f"{q:,.{places}f}" if core.startswith("#,##") else f"{q:.{places}f}"
    return s + ("%" if pct else "")


def _span(span):
    return int(min(span)), int(max(span))


def _all(v) -> bool:
    return v is None or v == "All"


def _list(col: str) -> list:
    s = d.lists()[col].dropna().tolist()
    return [int(x) if isinstance(x, float) and x.is_integer() else x for x in s]


def filter_options(span=None) -> dict[str, list]:
    venues = _list("Venues+All")
    mtypes = _list("MatchType+All")
    teams = _list("Teams")
    return {
        "batter": _list("Batters"),
        "bowler": _list("Bowlers"),
        "phase": _list("Phases+All"),
        "venue": venues,
        "match_type": mtypes,
        "team_a": teams,
        "team_b": teams,
        "team_venue": venues,
        "team_match_type": mtypes,
    }


@d.per_league()
def defaults() -> dict:
    """DEFAULTS where this league has those players and teams; otherwise the
    batter–bowler pair that met most often and the most-played fixture."""
    opts = filter_options()
    out = dict(DEFAULTS)
    if out["batter"] not in opts["batter"] or out["bowler"] not in opts["bowler"]:
        ps = d.pair_seasons().groupby(["Batter", "Bowler"])["Balls"].sum()
        ps = ps[ps.index.get_level_values(0).isin(opts["batter"]) & ps.index.get_level_values(1).isin(opts["bowler"])]
        if len(ps):
            out["batter"], out["bowler"] = ps.idxmax()
    if out["team_a"] not in opts["team_a"] or out["team_b"] not in opts["team_b"]:
        tm = d.team_matches()
        tm = tm[tm["Team"].isin(opts["team_a"]) & tm["Opposition"].isin(opts["team_b"])]
        g = tm.groupby(["Team", "Opposition"]).size()
        if len(g):
            out["team_a"], out["team_b"] = g.idxmax()
    return out


# ── batter v bowler ─────────────────────────────────────────────────────────
def _pair_rows(batter, bowler, venue, match_type) -> pd.DataFrame:
    """Ball rows for this bowler where the batter is on strike or is the man out,
    with the venue / match-type filters applied (no season or phase filter)."""
    b = d.ball()
    m = (b["Bowler"] == bowler) & ((b["Batter"] == batter) | (b["Player Out"] == batter))
    if not _all(venue):
        m &= b["Venue"] == venue
    if not _all(match_type):
        m &= b["Match Type"] == match_type
    sub = b.loc[m, ["Season", "Phase", "Batter", "Player Out", "Ball Faced", "Bat Runs",
                    "Bat Dot", "Four", "Six", "Bowler Wkt"]].copy()
    sub["_bat"] = (sub["Batter"] == batter).astype(np.int64)
    sub["_dis"] = ((sub["Player Out"] == batter) & (sub["Bowler Wkt"] == 1)).astype(np.int64)
    for c in ["Ball Faced", "Bat Runs", "Bat Dot", "Four", "Six"]:
        sub[c] = sub[c] * sub["_bat"]
    return sub


def _bvb_table(sub: pd.DataFrame, key: str, order: list) -> pd.DataFrame:
    g = sub.groupby(key)[["Ball Faced", "Bat Runs", "_dis", "Bat Dot", "Four", "Six"]].sum()
    g = g.reindex(order, fill_value=0)
    balls = g["Ball Faced"].astype(float)
    out = pd.DataFrame({
        key: order,
        "Balls": g["Ball Faced"].to_numpy(),
        "Runs": g["Bat Runs"].to_numpy(),
        "Strike rate": (100 * g["Bat Runs"] / balls.where(balls > 0)).to_numpy(),
        "Dismissals": g["_dis"].to_numpy(),
        "Dot %": (g["Bat Dot"] / balls.where(balls > 0)).to_numpy(),
        "4s": g["Four"].to_numpy(),
        "6s": g["Six"].to_numpy(),
    })
    return out.reset_index(drop=True)


def _career(batter):
    b = d.ball()
    bat = b["Batter"] == batter
    faced = b.loc[bat, "Ball Faced"].sum()
    runs = b.loc[bat, "Bat Runs"].sum()
    outs = int(((b["Player Out"] == batter) & (b["Bowler Wkt"] == 1)).sum())
    sr = 100 * runs / faced if faced else 0.0          # AA13 (IFERROR -> 0)
    bpd = faced / outs if outs else 9999.0            # AA14 (IFERROR -> 9999)
    return sr, bpd


def verdict(balls, sr, dis, career_sr, career_bpd) -> str:
    """'Matchup Explorer'!M10."""
    if balls < 6:
        return "Too few balls"
    bpd = 9999.0 if dis == 0 else balls / dis   # AA15
    if (dis >= 2 and bpd < 0.67 * career_bpd and sr <= career_sr + 15) or \
       (sr < career_sr - 15 and dis >= 1 and bpd <= career_bpd):
        return "Bowler on top"
    if (sr > career_sr + 15 and bpd >= career_bpd) or \
       (dis == 0 and balls >= 24 and sr >= career_sr):
        return "Batter on top"
    return "Even"


def _bvb_blocks(span, batter, bowler, phase, venue, match_type) -> list[Block]:
    lo, hi = _span(span)
    seasons = list(d.seasons())
    sub = _pair_rows(batter, bowler, venue, match_type)

    # §02 summary: span + phase filter
    s = sub[(sub["Season"] >= lo) & (sub["Season"] <= hi)]
    if not _all(phase):
        s = s[s["Phase"] == phase]
    balls = int(s["Ball Faced"].sum())
    runs = int(s["Bat Runs"].sum())
    dis = int(s["_dis"].sum())
    dots = int(s["Bat Dot"].sum())
    fours = int(s["Four"].sum())
    sixes = int(s["Six"].sum())
    sr = 100 * runs / balls if balls > 0 else float("nan")
    bpd = balls / dis if dis > 0 else float("nan")
    dotp = dots / balls if balls > 0 else float("nan")
    avg = runs / dis if dis > 0 else float("nan")
    c_sr, c_bpd = _career(batter)
    v = verdict(balls, sr if balls > 0 else 0.0, dis, c_sr, c_bpd)

    kpis = [
        ("BALLS", xl_fmt(balls, "#,##0"), None),
        ("RUNS", xl_fmt(runs, "#,##0"), None),
        ("STRIKE RATE", xl_fmt(sr, "0.0"), None),
        ("DISMISSALS (BOWLER)", xl_fmt(dis, "0"), None),
        ("BALLS PER DISMISSAL", xl_fmt(bpd, "0.0"), None),
        ("DOT BALL %", xl_fmt(dotp, "0.0%"), None),
        ("FOURS", xl_fmt(fours, "0"), None),
        ("SIXES", xl_fmt(sixes, "0"), None),
        ("AVERAGE", xl_fmt(avg, "0.00"), None),
        ("VERDICT", v, f"career SR {xl_fmt(c_sr, '0.0')} · {xl_fmt(c_bpd, '0.0')} balls/dismissal"
         if c_bpd != 9999.0 else f"career SR {xl_fmt(c_sr, '0.0')}"),
    ]
    blocks = [Block(key="mx_02", title="Head-to-head summary", kind="kpis", kpis=kpis,
                    note=HOW_TO_READ)]

    # §03 by season: ignores the season range (phase / venue / match type apply)
    s3 = sub if _all(phase) else sub[sub["Phase"] == phase]
    t3 = _bvb_table(s3, "Season", seasons)
    blocks.append(Block(
        key="mx_03", title="By season", df=t3, note="ignores the season range",
        fmt={"Season": "{:.0f}", **BVB_FMT},
        muted_rows=[i for i, x in enumerate(seasons) if x < lo or x > hi],
    ))

    # §04 by phase: span applies, ignores the phase filter
    s4 = sub[(sub["Season"] >= lo) & (sub["Season"] <= hi)]
    t4 = _bvb_table(s4, "Phase", list(d.PHASES))
    blocks.append(Block(key="mx_04", title="By phase", df=t4, note="ignores the phase filter",
                        fmt=dict(BVB_FMT)))
    return blocks


# ── team v team ─────────────────────────────────────────────────────────────
def _tt_blocks(span, team_a, team_b, venue, match_type) -> list[Block]:
    lo, hi = _span(span)
    seasons = list(d.seasons())
    tm = d.team_matches()
    base = pd.Series(True, index=tm.index)
    if not _all(venue):
        base &= tm["Venue"] == venue
    if not _all(match_type):
        base &= tm["Match Type"] == match_type
    a_all = tm[base & (tm["Team"] == team_a) & (tm["Opposition"] == team_b)]
    b_all = tm[base & (tm["Team"] == team_b) & (tm["Opposition"] == team_a)]
    a = a_all[(a_all["Season"] >= lo) & (a_all["Season"] <= hi)]
    bb = b_all[(b_all["Season"] >= lo) & (b_all["Season"] <= hi)]

    n = len(a)
    aw = int((a["Result"] == "Won").sum())
    bw = int((a["Result"] == "Lost").sum())
    nr = int((a["Result"] == "No result").sum())
    winp = aw / (aw + bw) if (aw + bw) > 0 else float("nan")
    a1 = a.loc[a["Full 1st Inns"] == 1, "Runs Scored"].dropna()
    b1 = bb.loc[bb["Full 1st Inns"] == 1, "Runs Scored"].dropna()
    a_avg = a1.mean() if len(a1) else float("nan")
    b_avg = b1.mean() if len(b1) else float("nan")
    # MAXIFS ignores blanks and returns 0 when nothing numeric matches
    a_hi = (float(a["Runs Scored"].max()) if a["Runs Scored"].notna().any() else 0.0) if n > 0 else float("nan")
    b_hi = (float(bb["Runs Scored"].max()) if bb["Runs Scored"].notna().any() else 0.0) if n > 0 else float("nan")
    a_chase = int(((a["Result"] == "Won") & (a["Batting Order"] == "Chasing")).sum())

    kpis = [
        ("MATCHES", xl_fmt(n, "0"), None),
        ("TEAM A WINS", xl_fmt(aw, "0"), team_a),
        ("TEAM B WINS", xl_fmt(bw, "0"), team_b),
        ("NO RESULT", xl_fmt(nr, "0"), None),
        ("TEAM A WIN %", xl_fmt(winp, "0.0%"), team_a),
        ("A AVG 1ST-INNS SCORE", xl_fmt(a_avg, "0"), team_a),
        ("B AVG 1ST-INNS SCORE", xl_fmt(b_avg, "0"), team_b),
        ("A HIGHEST TOTAL", xl_fmt(a_hi, "0"), team_a),
        ("B HIGHEST TOTAL", xl_fmt(b_hi, "0"), team_b),
        ("A WINS CHASING", xl_fmt(a_chase, "0"), team_a),
    ]
    blocks = [Block(key="mx_06", title="Team head-to-head summary", kind="kpis", kpis=kpis,
                    note=f"{team_a} (A) v {team_b} (B)")]

    # §07 by season: ignores the season range
    res = a_all.assign(_w=(a_all["Result"] == "Won").astype(int),
                       _l=(a_all["Result"] == "Lost").astype(int),
                       _n=(a_all["Result"] == "No result").astype(int),
                       _m=1)
    g = res.groupby("Season")[["_m", "_w", "_l", "_n"]].sum().reindex(seasons, fill_value=0)
    dec = (g["_w"] + g["_l"]).astype(float)
    t7 = pd.DataFrame({
        "Season": seasons,
        "Matches": g["_m"].to_numpy(),
        "A wins": g["_w"].to_numpy(),
        "B wins": g["_l"].to_numpy(),
        "No result": g["_n"].to_numpy(),
        "A win %": (g["_w"] / dec.where(dec > 0)).to_numpy(),
    })
    blocks.append(Block(
        key="mx_07", title="Team head-to-head by season", df=t7,
        note="ignores the season range",
        fmt={"Season": "{:.0f}", "Matches": "{:,.0f}", "A wins": "{:,.0f}", "B wins": "{:,.0f}",
             "No result": "{:,.0f}", "A win %": "{:.1%}"},
        good_high=["A win %"], center={"A win %": 0.5},
        muted_rows=[i for i, x in enumerate(seasons) if x < lo or x > hi],
    ))
    return blocks


def build(span=None, **filters) -> list[Block]:
    span = span or d.full_span()
    f = {**DEFAULTS, **{k: v for k, v in filters.items() if v is not None}}
    return (_bvb_blocks(span, f["batter"], f["bowler"], f["phase"], f["venue"], f["match_type"])
            + _tt_blocks(span, f["team_a"], f["team_b"], f["team_venue"], f["team_match_type"]))
