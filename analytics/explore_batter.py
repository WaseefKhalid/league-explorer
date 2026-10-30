"""
Batter Explorer — any batter (or All) under any filter combination.

Mirrors the workbook sheet "Batter Explorer":
  §01 Filters / How to read                              -> note on bx_02
  §02 Summary (ball-level tiles)                          -> bx_02  (kpis)
      Summary · innings level † (Batting Innings sheet)   -> bx_02b (kpis)
      Summary · impact (+ SR v league, same filters)      -> bx_02c (kpis)
  §03 By phase              (ignores the phase filter)    -> bx_03
  §04 By bowler type        (ignores type + pace/spin)    -> bx_04
  §05 By batter hand        (ignores the hand filter)     -> bx_05
  §06 By stage of innings   (batter's own balls so far)   -> bx_06
  §07 By season             (ignores the season range)    -> bx_07
  §08 By opposition         (ignores the opposition)      -> bx_08
  §09 By venue              (ignores the venue filter)    -> bx_09

`span` replaces the Season from / Season to dropdowns (C7/C8). Every other
dropdown (C6, C9:C17) is a keyword filter; "All" = no filter.

Workbook semantics reproduced exactly:
* "All" is the SUMIFS wildcard "*" (matches any non-blank text).
* Innings "All" = innings 1..2 (super overs never count).
* Dismissals are COUNTIFS on Player Out (so a non-striker run-out counts,
  and the other filters — hand, ball no., phase … — apply to that ball).
* Breakdown tables always list every row of their dimension (0 balls -> "—").
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd

import analytics.data as d
from analytics.blocks import Block

# ── filters ──────────────────────────────────────────────────────────────────
FILTERS = ["batter", "venue", "phase", "bowler_type", "pace_spin", "opposition",
           "innings", "match_type", "host", "batter_hand"]

# Values selected in the saved workbook ('Batter Explorer'!C6, C9:C17;
# C7/C8 = 2016/2026 is the span).
DEFAULTS = {
    "batter": "Babar Azam",
    "venue": "All",
    "phase": "All",
    "bowler_type": "All",
    "pace_spin": "All",
    "opposition": "All",
    "innings": "All",
    "match_type": "All",
    "host": "All",
    "batter_hand": "All",
}

_LIST_COL = {  # data-validation list behind each dropdown (Lists sheet header)
    "batter": "Batters+All", "venue": "Venues+All", "phase": "Phases+All",
    "bowler_type": "Types+All", "pace_spin": "PaceSpin+All", "opposition": "Teams+All",
    "innings": "Innings", "match_type": "MatchType+All", "host": "Host+All",
    "batter_hand": "Hands+All",
}

# Ball Data column behind each text filter (batter handled separately: bd_batter / bd_out)
_BALL_COL = {
    "venue": "Venue", "phase": "Phase", "bowler_type": "Bowler Type",
    "pace_spin": "Pace/Spin", "opposition": "Bowling Team", "match_type": "Match Type",
    "host": "Host", "batter_hand": "Bat Hand",
}
# Batting Innings column behind the filters the † figures use
_INNS_COL = {
    "venue": "Venue", "opposition": "Opposition", "match_type": "Match Type",
    "host": "Host", "batter_hand": "Bat Hand",
}

DASH = "—"

HOW_TO_READ = (
    "Pick a batter (or All for every batter), then narrow down with any mix of filters. "
    "Every number on the right recalculates instantly.\n"
    "Strike rate = runs per 100 balls faced (no-balls count as faced, wides do not).\n"
    "Average = runs ÷ dismissals. Dismissals include run-outs; retired hurt is not out.\n"
    "Dot % / Boundary % = share of balls faced that were dots / fours + sixes.\n"
    "Breakdown tables ignore their own filter (e.g. \"by phase\" shows all four phases) "
    "but respect every other filter.\n"
    "Impact = runs added compared with an average batter facing the same balls in the same "
    "match situation (scoring + cost of dismissals). See the Impact sheet.\n"
    "\"—\" means no balls match the filters."
)
INNINGS_NOTE = ("† Innings-level figures use season, venue, opposition, innings, match type, "
                "host and batter-hand filters (not phase or bowler filters).")
IMPACT_NOTE = ("Impact = runs added compared with an average batter facing the same balls in "
               "the same match situation (scoring + cost of dismissals). See the Impact sheet.")

STAGES = [("Balls 1–10", 1, 10), ("Balls 11–20", 11, 20),
          ("Balls 21–30", 21, 30), ("Balls 31+", 31, 999)]

COLS = ["Balls", "Runs", "Strike rate", "Dismissals", "Average", "Dot %", "Boundary %", "4s", "6s"]
FMT = {"Balls": "{:,.0f}", "Runs": "{:,.0f}", "Strike rate": "{:,.1f}", "Dismissals": "{:,.0f}",
       "Average": "{:,.2f}", "Dot %": "{:.1%}", "Boundary %": "{:.1%}", "4s": "{:,.0f}",
       "6s": "{:,.0f}"}


# ── helpers ──────────────────────────────────────────────────────────────────
def _list(col: str) -> list:
    s = d.lists()[col].dropna().tolist()
    return [int(x) if isinstance(x, float) and x.is_integer() else x for x in s]


def filter_options(span=None) -> dict[str, list]:
    """Choices per filter, exactly the workbook's dropdown lists ("All" first)."""
    return {k: _list(c) for k, c in _LIST_COL.items()}


def _isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def xl_fmt(v, numfmt: str) -> str:
    """Show a value the way Excel does for `numfmt` ('0', '#,##0', '0.0', '0.00',
    '0.0%', '+0.0;-0.0;0.0' …): round half away from zero; NaN -> "—"."""
    if _isnan(v):
        return DASH
    if isinstance(v, str):
        return v
    signed = numfmt.startswith("+")
    core = numfmt.split(";")[0].lstrip("+")
    pct = core.endswith("%")
    core = core.rstrip("%")
    places = len(core.split(".")[1]) if "." in core else 0
    x = float(v) * (100 if pct else 1)
    q = Decimal(f"{x:.15g}").quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    q = abs(q)
    s = f"{q:,.{places}f}" if core.startswith("#,##") else f"{q:.{places}f}"
    if signed:
        sign = "+" if x > 0 else ("-" if x < 0 else "")
    else:
        sign = "-" if (x < 0 and q != 0) else ""
    return sign + s + ("%" if pct else "")


def _div(a, b, scale=1.0):
    """Element-wise a/b*scale with NaN where b == 0 (numpy arrays or scalars)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(b > 0, scale * a / np.where(b > 0, b, 1.0), np.nan)
    return r if r.ndim else float(r)


@d.per_league()
def _arrays():
    """Factorised Ball Data columns (built once; never mutates the shared frame)."""
    b = d.ball()
    A = {"n": len(b)}
    for c in ["Batter", "Player Out", *_BALL_COL.values()]:
        codes, uniq = pd.factorize(b[c])          # blank -> -1
        A[c] = (codes, {u: i for i, u in enumerate(uniq)})
    for c in ["Season", "Innings", "Batter Ball No"]:
        A[c] = b[c].to_numpy(np.int64)
    for c in ["Ball Faced", "Bat Runs", "Bat Dot", "Four", "Six",
              "Bat Run Impact", "Exp Out Cost", "Out Impact"]:
        A[c] = np.nan_to_num(b[c].to_numpy(np.float64))     # SUMIFS skips blanks
    stage = np.full(len(b), -1, np.int64)
    bn = A["Batter Ball No"]
    for i, (_, lo, hi) in enumerate(STAGES):
        stage[(bn >= lo) & (bn <= hi)] = i
    A["stage"] = stage
    seasons = list(d.seasons())
    A["season_code"] = np.searchsorted(np.array(seasons), A["Season"])
    A["seasons"] = seasons
    return A


def _eq(A, col, sel) -> np.ndarray:
    """SUMIFS criterion: "All" -> '*' (any non-blank text), else exact match."""
    codes, idx = A[col]
    if sel is None or sel == "All":
        return codes >= 0
    i = idx.get(sel)
    return codes == i if i is not None else np.zeros(A["n"], bool)


def _inn_range(sel) -> tuple[int, int]:
    lo = 2 if sel == "2nd innings" else 1
    hi = 1 if sel == "1st innings" else 2
    return lo, hi


def _resolve(filters: dict) -> dict:
    f = dict(DEFAULTS)
    f.update({k: v for k, v in filters.items() if k in DEFAULTS and v is not None})
    return f


def _masks(span, f):
    A = _arrays()
    lo, hi = min(span), max(span)
    ilo, ihi = _inn_range(f["innings"])
    m = {
        "season": (A["Season"] >= lo) & (A["Season"] <= hi),
        "innings": (A["Innings"] >= ilo) & (A["Innings"] <= ihi),
    }
    for k, c in _BALL_COL.items():
        m[k] = _eq(A, c, f[k])
    bat = _eq(A, "Batter", f["batter"])
    out = _eq(A, "Player Out", f["batter"])
    return A, m, bat, out


def _all_but(A, m, *skip) -> np.ndarray:
    r = np.ones(A["n"], bool)
    for k, v in m.items():
        if k not in skip:
            r &= v
    return r


def _stat_frame(balls, runs, outs, dots, fours, sixes) -> pd.DataFrame:
    balls, runs, outs, fours, sixes = (np.rint(x).astype(np.int64)
                                       for x in (balls, runs, outs, fours, sixes))
    return pd.DataFrame({
        "Balls": balls, "Runs": runs, "Strike rate": _div(runs, balls, 100.0),
        "Dismissals": outs, "Average": _div(runs, outs), "Dot %": _div(dots, balls),
        "Boundary %": _div(fours + sixes, balls), "4s": fours, "6s": sixes,
    })


def _breakdown(A, base, bat, out, key, codes, label_col, labels) -> pd.DataFrame:
    """One row per label (codes = position of each label in key's coding)."""
    n = int(max(key.max(initial=0), max(codes, default=0))) + 1
    mb = base & bat & (key >= 0)
    mo = base & out & (key >= 0)
    kb, ko = key[mb], key[mo]

    def s(col):
        return np.bincount(kb, weights=A[col][mb], minlength=n)[codes]

    outs = np.bincount(ko, minlength=n)[codes].astype(float)
    df = _stat_frame(s("Ball Faced"), s("Bat Runs"), outs, s("Bat Dot"), s("Four"), s("Six"))
    df.insert(0, label_col, labels)
    return df.reset_index(drop=True)


def _text_breakdown(A, base, bat, out, col, label_col, labels):
    codes_arr, idx = A[col]
    codes = [idx.get(x, -1) for x in labels]
    # labels missing from the data get an all-zero row via a spare code
    spare = len(idx)
    codes = [c if c >= 0 else spare for c in codes]
    return _breakdown(A, base, bat, out, codes_arr, codes, label_col, labels)


# ── build ────────────────────────────────────────────────────────────────────
def build(span: tuple[int, int] | None = None, **filters) -> list[Block]:
    span = span or d.full_span()
    f = _resolve(filters)
    A, m, bat, out = _masks(span, f)
    lo, hi = min(span), max(span)

    # ── §02 Summary (ball level) ────────────────────────────────────────────
    base = _all_but(A, m)
    mb, mo = base & bat, base & out
    runs = A["Bat Runs"][mb].sum()
    balls = A["Ball Faced"][mb].sum()
    outs = float(mo.sum())
    fours, sixes = A["Four"][mb].sum(), A["Six"][mb].sum()
    dots = A["Bat Dot"][mb].sum()
    sr = _div(runs, balls, 100.0)
    kpis = [
        ("RUNS", xl_fmt(runs, "#,##0"), None),
        ("BALLS FACED", xl_fmt(balls, "#,##0"), None),
        ("STRIKE RATE", xl_fmt(sr, "0.0"), None),
        ("AVERAGE", xl_fmt(_div(runs, outs), "0.00"), None),
        ("DISMISSALS", xl_fmt(outs, "0"), None),
        ("FOURS", xl_fmt(fours, "0"), None),
        ("SIXES", xl_fmt(sixes, "0"), None),
        ("DOT BALL %", xl_fmt(_div(dots, balls), "0.0%"), None),
        ("BOUNDARY %", xl_fmt(_div(fours + sixes, balls), "0.0%"), None),
        ("BALLS PER DISMISSAL", xl_fmt(_div(balls, outs), "0.0"), None),
    ]
    blocks = [Block(key="bx_02", title="Summary", kind="kpis", kpis=kpis, note=HOW_TO_READ)]

    # ── † innings-level figures (Batting Innings) ───────────────────────────
    bi = d.bat_inns()
    ilo, ihi = _inn_range(f["innings"])
    mi = (bi["Season"] >= lo) & (bi["Season"] <= hi) & \
         (bi["Innings"] >= ilo) & (bi["Innings"] <= ihi)
    mi &= bi["Batter"].notna() if f["batter"] == "All" else (bi["Batter"] == f["batter"])
    for k, c in _INNS_COL.items():
        mi &= bi[c].notna() if f[k] == "All" else (bi[c] == f[k])
    inns = bi.loc[mi, ["Runs", "Out"]]
    n_inns = len(inns)
    hs = float(inns["Runs"].max()) if n_inns else float("nan")
    blocks.append(Block(
        key="bx_02b", title="Summary · innings level †", kind="kpis", note=INNINGS_NOTE,
        kpis=[
            ("INNINGS †", xl_fmt(n_inns, "0"), None),
            ("NOT OUTS †", xl_fmt(int((inns["Out"] == 0).sum()), "0"), None),
            ("FIFTIES †", xl_fmt(int(((inns["Runs"] >= 50) & (inns["Runs"] < 100)).sum()), "0"), None),
            ("HUNDREDS †", xl_fmt(int((inns["Runs"] >= 100).sum()), "0"), None),
            ("HIGH SCORE †", xl_fmt(hs, "0"), None),
        ]))

    # ── impact ───────────────────────────────────────────────────────────────
    scoring = A["Bat Run Impact"][mb].sum()
    dismissal = A["Out Impact"][mo].sum() - A["Exp Out Cost"][mb].sum()
    impact = scoring + dismissal
    lg_runs = A["Bat Runs"][base & (A["Batter"][0] >= 0)].sum()
    lg_balls = A["Ball Faced"][base & (A["Batter"][0] >= 0)].sum()
    sr_v_lg = sr - _div(lg_runs, lg_balls, 100.0)        # NaN if either side is "—"
    sg = "+0.0;-0.0;0.0"
    blocks.append(Block(
        key="bx_02c", title="Summary · impact", kind="kpis", note=IMPACT_NOTE,
        kpis=[
            ("BATTING IMPACT (RUNS ±)", xl_fmt(impact, sg), None),
            ("IMPACT PER 100 BALLS", xl_fmt(_div(impact, balls, 100.0), sg), None),
            ("SCORING IMPACT", xl_fmt(scoring, sg), None),
            ("DISMISSAL IMPACT", xl_fmt(dismissal, sg), None),
            ("SR v LEAGUE · SAME FILTERS", xl_fmt(sr_v_lg, sg), None),
        ]))

    def table(key, title, note, df, **kw):
        return Block(key=key, title=title, note=note, df=df, fmt=dict(FMT, **kw.pop("fmt", {})),
                     good_high=["Strike rate", "Average", "Boundary %"], good_low=["Dot %"], **kw)

    # §03 By phase
    df = _text_breakdown(A, _all_but(A, m, "phase"), bat, out, "Phase", "Phase", list(d.PHASES))
    blocks.append(table("bx_03", "By phase", "PP 1–6 · MO1 7–10 · MO2 11–16 · Death 17–20", df))

    # §04 By bowler type (ignores bowler type and pace/spin)
    df = _text_breakdown(A, _all_but(A, m, "bowler_type", "pace_spin"), bat, out,
                         "Bowler Type", "Bowler type", list(d.BOWL_TYPES))
    blocks.append(table("bx_04", "By bowler type", "ignores bowler-type and pace/spin filters", df))

    # §05 By batter hand
    df = _text_breakdown(A, _all_but(A, m, "batter_hand"), bat, out, "Bat Hand",
                         "Batter hand", list(d.HANDS))
    blocks.append(table("bx_05", "By batter hand",
                        "ignores the batter-hand filter · try it with Batter = All", df))

    # §06 By stage of innings (batter's own ball number)
    df = _breakdown(A, base, bat, out, A["stage"], list(range(len(STAGES))),
                    "Balls faced", [s[0] for s in STAGES])
    blocks.append(table("bx_06", "By stage of innings", "the batter's own balls faced so far", df))

    # §07 By season (ignores the season range; seasons outside the span greyed)
    seasons = A["seasons"]
    df = _breakdown(A, _all_but(A, m, "season"), bat, out, A["season_code"],
                    list(range(len(seasons))), "Season", seasons)
    muted = [i for i, s in enumerate(seasons) if s < lo or s > hi]
    blocks.append(table(
        "bx_07", "By season", "ignores the season range", df, fmt={"Season": "{:.0f}"},
        muted_rows=muted,
        chart={"type": "line", "x": "Season", "y": "Strike rate",
               "title": "Strike rate by season", "color": "amber"}))

    # §08 By opposition (bowling team)
    df = _text_breakdown(A, _all_but(A, m, "opposition"), bat, out, "Bowling Team",
                         "Opposition", _list("Teams"))
    blocks.append(table("bx_08", "By opposition", "ignores the opposition filter", df))

    # §09 By venue
    df = _text_breakdown(A, _all_but(A, m, "venue"), bat, out, "Venue", "Venue",
                         _list("Venues+All")[1:])
    blocks.append(table("bx_09", "By venue", "ignores the venue filter", df))
    return blocks
