"""
Team Explorer — record, toss, batting order, phase profile and matchups for any team.

Mirrors the workbook sheet "Team Explorer":
  §02 Record                          -> tx_02 (kpis)
  §03 Batting by phase                -> tx_03
  §04 Bowling by phase                -> tx_04
  §05 Team batting v bowling types    -> tx_05
  §06 Team bowling v batter hand      -> tx_06
  §07 Season by season                -> tx_07 (ignores the season range)

`span` replaces Season from/to (C7/C8).
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

import analytics.data as d
from analytics.blocks import Block

FILTERS = ["team", "venue", "opposition", "match_type", "host", "toss", "batting_order"]

# Values selected in the saved workbook ('Team Explorer'!C6, C9:C14)
DEFAULTS = {
    "team": "Lahore Qalandars",
    "venue": "All",
    "opposition": "All",
    "match_type": "All",
    "host": "All",
    "toss": "All",
    "batting_order": "All",
}

DASH = "—"

HOW_TO_READ = (
    "Results come from one row per team per match (Team Match Data). A super-over win counts as a win.\n"
    "Win % = wins ÷ (matches − no results). Average 1st-innings score uses completed first innings "
    "only (19+ overs or all out, no DLS).\n"
    "Phase tables use the ball-by-ball data and ignore the Toss filter; \"Batting order\" maps to "
    "1st / 2nd innings.\n"
    "Team batting v bowling types: how the selected team scores against each kind of bowler."
)

INT = "{:,.0f}"


# ── helpers ──────────────────────────────────────────────────────────────────
def _isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def xl_fmt(v, numfmt: str) -> str:
    """Format a value the way Excel shows it for the given number format."""
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


def _all(v) -> bool:
    return v is None or v == "All"


def _list(col: str) -> list:
    s = d.lists()[col].dropna().tolist()
    return [int(x) if isinstance(x, float) and x.is_integer() else x for x in s]


def _div(a, b, scale=1.0):
    b = b.astype(float)
    return (scale * a / b.where(b > 0)).to_numpy()


def filter_options(span=None) -> dict[str, list]:
    return {
        "team": _list("Teams"),
        "venue": _list("Venues+All"),
        "opposition": _list("Teams+All"),
        "match_type": _list("MatchType+All"),
        "host": _list("Host+All"),
        "toss": _list("Toss"),
        "batting_order": _list("Order"),
    }


def _finish_map() -> dict:
    l = d.lists()
    k = l["FinishKey"].dropna()
    return dict(zip(k, l.loc[k.index, "FinishLabel"]))


# ── sections ────────────────────────────────────────────────────────────────
def _tm_rows(f) -> pd.DataFrame:
    """Team Match Data rows for the team with every filter except the season range."""
    tm = d.team_matches()
    m = tm["Team"] == f["team"]
    if not _all(f["venue"]):
        m &= tm["Venue"] == f["venue"]
    if not _all(f["opposition"]):
        m &= tm["Opposition"] == f["opposition"]
    if not _all(f["match_type"]):
        m &= tm["Match Type"] == f["match_type"]
    if not _all(f["host"]):
        m &= tm["Host"] == f["host"]
    if not _all(f["toss"]):
        m &= tm["Toss"] == {"Won toss": "Won", "Lost toss": "Lost"}.get(f["toss"], f["toss"])
    if not _all(f["batting_order"]):
        m &= tm["Batting Order"] == f["batting_order"]
    return tm[m]


def _record(t: pd.DataFrame) -> list[tuple]:
    n = len(t)
    res = t["Result"]
    won = int((res == "Won").sum())
    lost = int((res == "Lost").sum())
    nr = int((res == "No result").sum())
    winp = won / (n - nr) if (n - nr) > 0 else float("nan")
    tosses = int((t["Toss"] == "Won").sum())
    bf = t["Batting Order"] == "Bat first"
    ch = t["Batting Order"] == "Chasing"
    w_bf = int(((res == "Won") & bf).sum())
    w_ch = int(((res == "Won") & ch).sum())
    r1 = t.loc[t["Full 1st Inns"] == 1, "Runs Scored"].dropna()
    c1 = t.loc[t["Opp Full 1st Inns"] == 1, "Runs Conceded"].dropna()
    avg1 = r1.mean() if len(r1) else float("nan")
    conc1 = c1.mean() if len(c1) else float("nan")
    runs = t["Runs Scored"]
    hi = (float(runs.max()) if runs.notna().any() else 0.0) if n > 0 else float("nan")
    comp = t.loc[t["Completed Inns"] == 1, "Runs Scored"]
    lo = (float(comp.min()) if comp.notna().any() else 0.0) if len(comp) > 0 else float("nan")
    six = t["Sixes"].fillna(0).sum() / n if n > 0 else float("nan")
    d_bf = int(bf.sum()) - int((bf & (res == "No result")).sum())
    d_ch = int(ch.sum()) - int((ch & (res == "No result")).sum())
    bfp = w_bf / d_bf if d_bf != 0 else float("nan")
    chp = w_ch / d_ch if d_ch != 0 else float("nan")
    return [
        ("PLAYED", xl_fmt(n, "0"), None),
        ("WON", xl_fmt(won, "0"), None),
        ("LOST", xl_fmt(lost, "0"), None),
        ("NO RESULT", xl_fmt(nr, "0"), None),
        ("WIN %", xl_fmt(winp, "0.0%"), None),
        ("TOSSES WON", xl_fmt(tosses, "0"), None),
        ("WINS BATTING FIRST", xl_fmt(w_bf, "0"), None),
        ("WINS CHASING", xl_fmt(w_ch, "0"), None),
        ("AVG 1ST-INNS SCORE", xl_fmt(avg1, "0"), None),
        ("AVG CONCEDED (OPP 1ST INNS)", xl_fmt(conc1, "0"), None),
        ("HIGHEST TOTAL", xl_fmt(hi, "0"), None),
        ("LOWEST COMPLETED", xl_fmt(lo, "0"), None),
        ("SIXES PER MATCH", xl_fmt(six, "0.0"), None),
        ("BAT-FIRST WIN %", xl_fmt(bfp, "0.0%"), None),
        ("CHASING WIN %", xl_fmt(chp, "0.0%"), None),
    ]


def _ball_rows(f, lo, hi, batting: bool) -> pd.DataFrame:
    """Ball rows with the team batting (or bowling); toss filter ignored."""
    b = d.ball()
    team_col, opp_col = ("Batting Team", "Bowling Team") if batting else ("Bowling Team", "Batting Team")
    m = (b[team_col] == f["team"]) & (b["Season"] >= lo) & (b["Season"] <= hi)
    if not _all(f["venue"]):
        m &= b["Venue"] == f["venue"]
    if not _all(f["opposition"]):
        m &= b[opp_col] == f["opposition"]
    if not _all(f["match_type"]):
        m &= b["Match Type"] == f["match_type"]
    if not _all(f["host"]):
        m &= b["Host"] == f["host"]
    order = f["batting_order"]
    if batting:
        i_lo = 2 if order == "Chasing" else 1
        i_hi = 1 if order == "Bat first" else 2
    else:
        i_lo = 2 if order == "Bat first" else 1
        i_hi = 1 if order == "Chasing" else 2
    m &= (b["Innings"] >= i_lo) & (b["Innings"] <= i_hi)
    return b[m]


def _phase_table(rows: pd.DataFrame, batting: bool) -> pd.DataFrame:
    g = rows.groupby("Phase")[["Total Runs", "Legal Ball", "Wicket", "Four", "Six",
                               "Ball Faced", "Bowl Dot"]].sum().reindex(d.PHASES, fill_value=0)
    runs_h, rate_h = ("Runs", "Run rate") if batting else ("Runs conceded", "Economy")
    return pd.DataFrame({
        "Phase": list(d.PHASES),
        runs_h: g["Total Runs"].to_numpy(),
        "Legal balls": g["Legal Ball"].to_numpy(),
        rate_h: _div(g["Total Runs"], g["Legal Ball"], 6),
        "Wickets": g["Wicket"].to_numpy(),
        "Balls / wkt": _div(g["Legal Ball"], g["Wicket"]),
        "Boundary %": _div(g["Four"] + g["Six"], g["Ball Faced"]),
        "Dot %": _div(g["Bowl Dot"], g["Legal Ball"]),
    })


def _phase_fmt(rate_h, runs_h):
    return {runs_h: INT, "Legal balls": INT, rate_h: "{:,.2f}", "Wickets": INT,
            "Balls / wkt": "{:,.1f}", "Boundary %": "{:.1%}", "Dot %": "{:.1%}"}


def build(span=None, **filters) -> list[Block]:
    span = span or d.full_span()
    f = {**DEFAULTS, **{k: v for k, v in filters.items() if v is not None}}
    lo, hi = int(min(span)), int(max(span))
    seasons = list(d.seasons())
    blocks: list[Block] = []

    # §02 Record
    t_all = _tm_rows(f)
    t = t_all[(t_all["Season"] >= lo) & (t_all["Season"] <= hi)]
    blocks.append(Block(key="tx_02", title="Record", kind="kpis", kpis=_record(t),
                        note=HOW_TO_READ))

    bat = _ball_rows(f, lo, hi, batting=True)
    bowl = _ball_rows(f, lo, hi, batting=False)

    # §03 / §04 phase tables
    blocks.append(Block(key="tx_03", title="Batting by phase", df=_phase_table(bat, True),
                        note="runs scored by the team", fmt=_phase_fmt("Run rate", "Runs")))
    blocks.append(Block(key="tx_04", title="Bowling by phase", df=_phase_table(bowl, False),
                        note="runs conceded by the team",
                        fmt=_phase_fmt("Economy", "Runs conceded")))

    # §05 batting v bowler types
    g = bat.groupby("Bowler Type")[["Ball Faced", "Bat Runs", "Bowler Wkt", "Bat Dot", "Four",
                                    "Six"]].sum().reindex(d.BOWL_TYPES, fill_value=0)
    t5 = pd.DataFrame({
        "Bowler type": list(d.BOWL_TYPES),
        "Balls faced": g["Ball Faced"].to_numpy(),
        "Runs": g["Bat Runs"].to_numpy(),
        "Strike rate": _div(g["Bat Runs"], g["Ball Faced"], 100),
        "Wickets lost": g["Bowler Wkt"].to_numpy(),
        "Balls / wkt": _div(g["Ball Faced"], g["Bowler Wkt"]),
        "Dot %": _div(g["Bat Dot"], g["Ball Faced"]),
        "Boundary %": _div(g["Four"] + g["Six"], g["Ball Faced"]),
    })
    blocks.append(Block(
        key="tx_05", title="Team batting v bowling types", df=t5, note="wickets = bowler-credited",
        fmt={"Balls faced": INT, "Runs": INT, "Strike rate": "{:,.1f}", "Wickets lost": INT,
             "Balls / wkt": "{:,.1f}", "Dot %": "{:.1%}", "Boundary %": "{:.1%}"},
        good_high=["Strike rate", "Balls / wkt", "Boundary %"], good_low=["Dot %"],
    ))

    # §06 bowling v batter hand
    g = bowl.groupby("Bat Hand")[["Legal Ball", "Bowler Runs", "Bowler Wkt", "Bowl Dot", "Four",
                                  "Six"]].sum().reindex(d.HANDS, fill_value=0)
    t6 = pd.DataFrame({
        "Batter hand": list(d.HANDS),
        "Legal balls": g["Legal Ball"].to_numpy(),
        "Runs conceded": g["Bowler Runs"].to_numpy(),
        "Economy": _div(g["Bowler Runs"], g["Legal Ball"], 6),
        "Wickets": g["Bowler Wkt"].to_numpy(),
        "Balls / wkt": _div(g["Legal Ball"], g["Bowler Wkt"]),
        "Dot %": _div(g["Bowl Dot"], g["Legal Ball"]),
        "Boundary %": _div(g["Four"] + g["Six"], g["Legal Ball"]),
    })
    blocks.append(Block(
        key="tx_06", title="Team bowling v batter hand", df=t6,
        fmt={"Legal balls": INT, "Runs conceded": INT, "Economy": "{:,.2f}", "Wickets": INT,
             "Balls / wkt": "{:,.1f}", "Dot %": "{:.1%}", "Boundary %": "{:.1%}"},
    ))

    # §07 season by season (ignores the season range; finish = whole season)
    tt = t_all.assign(_m=1, _w=(t_all["Result"] == "Won").astype(int),
                      _l=(t_all["Result"] == "Lost").astype(int))
    g = tt.groupby("Season")[["_m", "_w", "_l"]].sum().reindex(seasons, fill_value=0)
    dec = (g["_w"] + g["_l"]).astype(float)
    fin = _finish_map()
    t7 = pd.DataFrame({
        "Season": seasons,
        "Played": g["_m"].to_numpy(),
        "Won": g["_w"].to_numpy(),
        "Lost": g["_l"].to_numpy(),
        "Win %": (g["_w"] / dec.where(dec > 0)).to_numpy(),
        "Finish": [fin.get(f"{f['team']}|{s}", DASH) for s in seasons],
    })
    blocks.append(Block(
        key="tx_07", title="Season by season", df=t7,
        note="ignores the season range; finish = whole season",
        fmt={"Season": "{:.0f}", "Played": INT, "Won": INT, "Lost": INT, "Win %": "{:.1%}"},
        good_high=["Win %"], center={"Win %": 0.5},
        muted_rows=[i for i, s in enumerate(seasons) if s < lo or s > hi],
        chart={"type": "bar", "x": "Season", "y": "Win %", "title": f"{f['team']} — win % by season",
               "color": "amber"},
    ))
    return blocks
