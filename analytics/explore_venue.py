"""
Venue & Toss Explorer — par scores, toss value, chasing, phase scoring and
bowler types at any ground.

Mirrors the workbook sheet "Venue Explorer" (titled "Venue & Toss Explorer"):
  §02 Ground summary                  -> vx_02 (kpis)
  §03 Par score guide                 -> vx_03
  §04 Scoring by phase                -> vx_04
  §05 Bowler types at this ground     -> vx_05
  §06 Season by season                -> vx_06 (ignores the season range)
  §07 Team records here               -> vx_07

`span` replaces Season from/to (C7/C8).
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

import analytics.data as d
from analytics.blocks import Block

FILTERS = ["venue", "match_type"]

# Values selected in the saved workbook ('Venue Explorer'!C6, C9)
DEFAULTS = {"venue": "Gaddafi Stadium", "match_type": "All"}

DASH = "—"

HOW_TO_READ = (
    "Choose a ground (or All) and a season range. Chase / toss figures use decided matches only "
    "(no ties, no DLS).\n"
    "Average 1st-innings score uses completed first innings (19+ overs or all out).\n"
    "Par guide: how often the side batting first won, by the first-innings total it posted.\n"
    "Toss value = how often the toss winner went on to win."
)

# 'Venue Explorer'!E14:E18 with the bounds in AA14:AB18
PAR_BINS = [("Under 160", 0, 159), ("160–179", 160, 179), ("180–199", 180, 199),
            ("200–219", 200, 219), ("220+", 220, 999)]

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
    return {"venue": _list("Venues+All"), "match_type": _list("MatchType+All")}


def _filt(df, venue, match_type):
    m = pd.Series(True, index=df.index)
    if not _all(venue):
        m &= df["Venue"] == venue
    if not _all(match_type):
        m &= df["Match Type"] == match_type
    return df[m]


def _maxifs(s: pd.Series) -> float:
    """MAXIFS: ignores blanks, 0 when nothing numeric matches."""
    return float(s.max()) if s.notna().any() else 0.0


# ── build ───────────────────────────────────────────────────────────────────
def build(span=None, **filters) -> list[Block]:
    span = span or d.full_span()
    f = {**DEFAULTS, **{k: v for k, v in filters.items() if v is not None}}
    venue, mtype = f["venue"], f["match_type"]
    lo, hi = int(min(span)), int(max(span))
    seasons = list(d.seasons())
    blocks: list[Block] = []

    md_all = _filt(d.matches(), venue, mtype)
    md = md_all[(md_all["Season"] >= lo) & (md_all["Season"] <= hi)]
    bd = _filt(d.ball(), venue, mtype)
    bd = bd[(bd["Season"] >= lo) & (bd["Season"] <= hi)]

    # §02 Ground summary
    n = len(md)
    dec = md["Decided (no DLS)"] == 1
    bfw = int((dec & (md["Bat First Won"] == 1)).sum())
    chw = int((dec & (md["Bat First Won"] == 0)).sum())
    chp = chw / (bfw + chw) if (bfw + chw) > 0 else float("nan")
    f1 = md.loc[md["Full 1st Inns"] == 1, "1st Inns Runs"].dropna()
    avg1 = f1.mean() if len(f1) else float("nan")
    field = (md["Toss Decision"] == "Field").sum() / n if n > 0 else float("nan")
    tw1, tw0 = int((md["Toss Winner Won"] == 1).sum()), int((md["Toss Winner Won"] == 0).sum())
    twp = tw1 / (tw1 + tw0) if (tw1 + tw0) > 0 else float("nan")
    hi_tot = max(_maxifs(md["1st Inns Runs"]), _maxifs(md["2nd Inns Runs"])) if n > 0 else float("nan")
    n200 = int((md["1st Inns Runs"] >= 200).sum() + (md["2nd Inns Runs"] >= 200).sum())
    six = bd["Six"].sum() / n if n > 0 else float("nan")
    kpis = [
        ("MATCHES", xl_fmt(n, "0"), None),
        ("WON BATTING FIRST", xl_fmt(bfw, "0"), None),
        ("WON CHASING", xl_fmt(chw, "0"), None),
        ("CHASE WIN %", xl_fmt(chp, "0.0%"), None),
        ("AVG 1ST-INNS SCORE", xl_fmt(avg1, "0"), None),
        ("TOSS WINNER BOWLED FIRST", xl_fmt(field, "0.0%"), None),
        ("TOSS WINNER WON", xl_fmt(twp, "0.0%"), None),
        ("HIGHEST TOTAL", xl_fmt(hi_tot, "0"), None),
        ("200+ TOTALS", xl_fmt(n200, "0"), None),
        ("SIXES PER MATCH", xl_fmt(six, "0.0"), None),
    ]
    blocks.append(Block(key="vx_02", title="Ground summary", kind="kpis", kpis=kpis,
                        note=HOW_TO_READ))

    # §03 Par score guide
    par = md[(md["Full 1st Inns"] == 1) & dec]
    inn1 = par["1st Inns Runs"]
    rows = []
    for lab, a, b in PAR_BINS:
        m = (inn1 >= a) & (inn1 <= b)
        k = int(m.sum())
        w = int((m & (par["Bat First Won"] == 1)).sum())
        rows.append((lab, k, w, w / k if k > 0 else float("nan")))
    t3 = pd.DataFrame(rows, columns=["1st-innings total", "Matches", "Bat-first wins", "Bat-first win %"])
    blocks.append(Block(
        key="vx_03", title="Par score guide", df=t3, note="bat-first win % by first-innings total",
        fmt={"Matches": INT, "Bat-first wins": INT, "Bat-first win %": "{:.1%}"},
        good_high=["Bat-first win %"], center={"Bat-first win %": 0.5},
    ))

    # §04 Scoring by phase
    g = bd.groupby("Phase")[["Total Runs", "Legal Ball", "Wicket", "Four", "Six", "Ball Faced",
                             "Bowl Dot"]].sum().reindex(d.PHASES, fill_value=0)
    t4 = pd.DataFrame({
        "Phase": list(d.PHASES),
        "Runs": g["Total Runs"].to_numpy(),
        "Legal balls": g["Legal Ball"].to_numpy(),
        "Run rate": _div(g["Total Runs"], g["Legal Ball"], 6),
        "Wickets": g["Wicket"].to_numpy(),
        "Balls / wkt": _div(g["Legal Ball"], g["Wicket"]),
        "Boundary %": _div(g["Four"] + g["Six"], g["Ball Faced"]),
        "Dot %": _div(g["Bowl Dot"], g["Legal Ball"]),
    })
    blocks.append(Block(
        key="vx_04", title="Scoring by phase", df=t4,
        fmt={"Runs": INT, "Legal balls": INT, "Run rate": "{:,.2f}", "Wickets": INT,
             "Balls / wkt": "{:,.1f}", "Boundary %": "{:.1%}", "Dot %": "{:.1%}"},
    ))

    # §05 Bowler types at this ground
    total_legal = bd["Legal Ball"].sum()
    g = bd.groupby("Bowler Type")[["Legal Ball", "Bowler Runs", "Bowler Wkt", "Bowl Dot"]].sum() \
          .reindex(d.BOWL_TYPES, fill_value=0)
    t5 = pd.DataFrame({
        "Bowler type": list(d.BOWL_TYPES),
        "Legal balls": g["Legal Ball"].to_numpy(),
        "Share of balls": (g["Legal Ball"] / total_legal).to_numpy() if total_legal > 0
        else [float("nan")] * len(d.BOWL_TYPES),
        "Runs": g["Bowler Runs"].to_numpy(),
        "Economy": _div(g["Bowler Runs"], g["Legal Ball"], 6),
        "Wickets": g["Bowler Wkt"].to_numpy(),
        "Balls / wkt": _div(g["Legal Ball"], g["Bowler Wkt"]),
        "Dot %": _div(g["Bowl Dot"], g["Legal Ball"]),
    })
    blocks.append(Block(
        key="vx_05", title="Bowler types at this ground", df=t5,
        fmt={"Legal balls": INT, "Share of balls": "{:.1%}", "Runs": INT, "Economy": "{:,.2f}",
             "Wickets": INT, "Balls / wkt": "{:,.1f}", "Dot %": "{:.1%}"},
        good_low=["Economy", "Balls / wkt"], good_high=["Dot %"],
    ))

    # §06 Season by season (ignores the season range)
    s = md_all.assign(
        _m=1,
        _f1=(md_all["Full 1st Inns"] == 1).astype(int),
        _r1=md_all["1st Inns Runs"].where(md_all["Full 1st Inns"] == 1, 0),
        _dec=(md_all["Decided (no DLS)"] == 1).astype(int),
        _ch=((md_all["Decided (no DLS)"] == 1) & (md_all["Bat First Won"] == 0)).astype(int),
        _fd=(md_all["Toss Decision"] == "Field").astype(int),
    )
    g = s.groupby("Season")[["_m", "_f1", "_r1", "_dec", "_ch", "_fd"]].sum() \
         .reindex(seasons, fill_value=0)
    t6 = pd.DataFrame({
        "Season": seasons,
        "Matches": g["_m"].to_numpy(),
        "Avg 1st-inns": _div(g["_r1"], g["_f1"]),
        "Chase win %": _div(g["_ch"], g["_dec"]),
        "Toss → bowl %": _div(g["_fd"], g["_m"]),
    })
    blocks.append(Block(
        key="vx_06", title="Season by season", df=t6, note="ignores the season range",
        fmt={"Season": "{:.0f}", "Matches": INT, "Avg 1st-inns": "{:,.0f}",
             "Chase win %": "{:.1%}", "Toss → bowl %": "{:.1%}"},
        muted_rows=[i for i, x in enumerate(seasons) if x < lo or x > hi],
        chart={"type": "line", "x": "Season", "y": "Avg 1st-inns",
               "title": "Average first-innings score by season", "color": "sky"},
    ))

    # §07 Team records here (static team list, workbook order)
    teams = _list("Teams")
    tm = _filt(d.team_matches(), venue, mtype)
    tm = tm[(tm["Season"] >= lo) & (tm["Season"] <= hi)]
    g = tm.assign(_m=1, _w=(tm["Result"] == "Won").astype(int), _l=(tm["Result"] == "Lost").astype(int)) \
          .groupby("Team")[["_m", "_w", "_l"]].sum().reindex(teams, fill_value=0)
    t7 = pd.DataFrame({
        "Team": teams,
        "Played": g["_m"].to_numpy(),
        "Won": g["_w"].to_numpy(),
        "Lost": g["_l"].to_numpy(),
        "Win %": _div(g["_w"], g["_w"] + g["_l"]),
    })
    blocks.append(Block(
        key="vx_07", title="Team records here", df=t7,
        fmt={"Played": INT, "Won": INT, "Lost": INT, "Win %": "{:.1%}"},
        good_high=["Win %"], center={"Win %": 0.5},
    ))
    return blocks
