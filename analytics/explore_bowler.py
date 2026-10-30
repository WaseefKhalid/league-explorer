"""
Bowler Explorer — any bowler (or All, e.g. every leg-spinner) under any filter combination.

Mirrors the workbook sheet "Bowler Explorer":
  §01 Filters / How to read                              -> note on wx_02
  §02 Summary (ball-level tiles)                          -> wx_02  (kpis)
      Summary · innings level † (Bowling Innings sheet)   -> wx_02b (kpis)
      Summary · impact (+ econ v league, same filters)    -> wx_02c (kpis)
  §03 By phase           (ignores the phase filter)       -> wx_03
  §04 By batter hand     (ignores the hand filter)        -> wx_04
  §05 By bowler type     (ignores type + pace/spin)       -> wx_05
  §06 By season          (ignores the season range)       -> wx_06
  §07 By opposition      (ignores the opposition)         -> wx_07
  §08 By venue           (ignores the venue filter)       -> wx_08

`span` replaces the Season from / Season to dropdowns (C7/C8). Every other
dropdown (C6, C9:C17) is a keyword filter; "All" = no filter.

Workbook semantics reproduced exactly:
* "All" is the SUMIFS wildcard "*" (matches any non-blank text).
* Innings "All" = innings 1..2 (super overs never count).
* Opposition = the batting team on that ball.
* Overs are shown as cricket notation (INT(balls/6) & "." & MOD(balls,6));
  in `df` they are the number 347.4 etc. with fmt "{:.1f}".
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
FILTERS = ["bowler", "venue", "phase", "batter_hand", "opposition", "innings",
           "match_type", "host", "bowler_type", "pace_spin"]

# Values selected in the saved workbook ('Bowler Explorer'!C6, C9:C17;
# C7/C8 = 2016/2026 is the span).
DEFAULTS = {
    "bowler": "Shaheen Shah Afridi",
    "venue": "All",
    "phase": "All",
    "batter_hand": "All",
    "opposition": "All",
    "innings": "All",
    "match_type": "All",
    "host": "All",
    "bowler_type": "All",
    "pace_spin": "All",
}

_LIST_COL = {  # data-validation list behind each dropdown (Lists sheet header)
    "bowler": "Bowlers+All", "venue": "Venues+All", "phase": "Phases+All",
    "batter_hand": "Hands+All", "opposition": "Teams+All", "innings": "Innings",
    "match_type": "MatchType+All", "host": "Host+All", "bowler_type": "Types+All",
    "pace_spin": "PaceSpin+All",
}

# Ball Data column behind each text filter
_BALL_COL = {
    "venue": "Venue", "phase": "Phase", "batter_hand": "Bat Hand",
    "opposition": "Batting Team", "match_type": "Match Type", "host": "Host",
    "bowler_type": "Bowler Type", "pace_spin": "Pace/Spin",
}
# Bowling Innings column behind the filters the † figures use
_INNS_COL = {
    "venue": "Venue", "opposition": "Opposition", "match_type": "Match Type",
    "host": "Host", "bowler_type": "Bowler Type",
}

DASH = "—"

HOW_TO_READ = (
    "Pick a bowler (or All, then use Bowler type for e.g. every leg-spinner), and filter by "
    "season range, venue, phase, batter hand, opposition, innings, match type or host.\n"
    "Economy = runs conceded per over (byes, leg-byes and penalties are not charged to the "
    "bowler).\n"
    "Average = runs per wicket; Strike rate = balls per wicket. Run-outs are not bowler "
    "wickets.\n"
    "Dot % = legal balls with no runs charged to the bowler. Boundary % = 4s + 6s conceded "
    "per legal ball.\n"
    "Breakdown tables ignore their own filter but respect every other filter. "
    "\"—\" = no balls match.\n"
    "Impact = runs saved compared with an average bowler in the same phase, season and match "
    "situation (economy + value of wickets). Econ v league: negative = cheaper than the league "
    "with the same filters."
)
INNINGS_NOTE = ("† Innings-level figures use season, venue, opposition, innings, match type, "
                "host and bowler-type filters (not phase, hand or pace/spin).")
IMPACT_NOTE = ("Impact = runs saved compared with an average bowler in the same phase, season "
               "and match situation (economy + value of wickets). Econ v league: negative = "
               "cheaper than the league with the same filters.")

COLS = ["Overs", "Legal balls", "Runs", "Wickets", "Economy", "Average", "Strike rate",
        "Dot %", "Boundary %"]
FMT = {"Overs": "{:.1f}", "Legal balls": "{:,.0f}", "Runs": "{:,.0f}", "Wickets": "{:,.0f}",
       "Economy": "{:,.2f}", "Average": "{:,.2f}", "Strike rate": "{:,.1f}",
       "Dot %": "{:.1%}", "Boundary %": "{:.1%}"}


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


def overs_text(balls) -> str:
    """INT(balls/6) & "." & MOD(balls,6)"""
    b = int(round(float(balls)))
    return f"{b // 6}.{b % 6}"


def _overs_num(balls):
    b = np.rint(np.asarray(balls, dtype=float)).astype(np.int64)
    return b // 6 + (b % 6) / 10.0


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
    for c in ["Bowler", *_BALL_COL.values()]:
        codes, uniq = pd.factorize(b[c])          # blank -> -1
        A[c] = (codes, {u: i for i, u in enumerate(uniq)})
    for c in ["Season", "Innings"]:
        A[c] = b[c].to_numpy(np.int64)
    for c in ["Legal Ball", "Bowler Runs", "Bowler Wkt", "Bowl Dot", "Four", "Six",
              "Wides", "No-balls", "Bowl Run Impact", "Bowl Wkt Impact"]:
        A[c] = np.nan_to_num(b[c].to_numpy(np.float64))     # SUMIFS skips blanks
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
    bowl = _eq(A, "Bowler", f["bowler"])
    return A, m, bowl


def _all_but(A, m, *skip) -> np.ndarray:
    r = np.ones(A["n"], bool)
    for k, v in m.items():
        if k not in skip:
            r &= v
    return r


def _stat_frame(legal, runs, wkts, dots, fours, sixes) -> pd.DataFrame:
    legal, runs, wkts = (np.rint(x).astype(np.int64) for x in (legal, runs, wkts))
    return pd.DataFrame({
        "Overs": _overs_num(legal), "Legal balls": legal, "Runs": runs, "Wickets": wkts,
        "Economy": _div(runs, legal, 6.0), "Average": _div(runs, wkts),
        "Strike rate": _div(legal, wkts), "Dot %": _div(dots, legal),
        "Boundary %": _div(np.asarray(fours) + np.asarray(sixes), legal),
    })


def _breakdown(A, base, key, codes, label_col, labels) -> pd.DataFrame:
    """One row per label (codes = position of each label in key's coding)."""
    n = int(max(key.max(initial=0), max(codes, default=0))) + 1
    mb = base & (key >= 0)
    kb = key[mb]

    def s(col):
        return np.bincount(kb, weights=A[col][mb], minlength=n)[codes]

    df = _stat_frame(s("Legal Ball"), s("Bowler Runs"), s("Bowler Wkt"), s("Bowl Dot"),
                     s("Four"), s("Six"))
    df.insert(0, label_col, labels)
    return df.reset_index(drop=True)


def _text_breakdown(A, base, col, label_col, labels):
    codes_arr, idx = A[col]
    spare = len(idx)                       # labels absent from the data -> all-zero row
    codes = [idx.get(x, spare) for x in labels]
    return _breakdown(A, base, codes_arr, codes, label_col, labels)


# ── build ────────────────────────────────────────────────────────────────────
def build(span: tuple[int, int] | None = None, **filters) -> list[Block]:
    span = span or d.full_span()
    f = _resolve(filters)
    A, m, bowl = _masks(span, f)
    lo, hi = min(span), max(span)

    # ── §02 Summary (ball level) ────────────────────────────────────────────
    base = _all_but(A, m)
    mb = base & bowl

    def tot(col):
        return float(A[col][mb].sum())

    wkts, legal, runs = tot("Bowler Wkt"), tot("Legal Ball"), tot("Bowler Runs")
    econ = _div(runs, legal, 6.0)
    kpis = [
        ("WICKETS", xl_fmt(wkts, "0"), None),
        ("OVERS", overs_text(legal), None),
        ("ECONOMY", xl_fmt(econ, "0.00"), None),
        ("AVERAGE", xl_fmt(_div(runs, wkts), "0.00"), None),
        ("STRIKE RATE", xl_fmt(_div(legal, wkts), "0.0"), None),
        ("DOT BALL %", xl_fmt(_div(tot("Bowl Dot"), legal), "0.0%"), None),
        ("BOUNDARY %", xl_fmt(_div(tot("Four") + tot("Six"), legal), "0.0%"), None),
        ("WIDES · NO-BALLS", f"{int(tot('Wides'))} · {int(tot('No-balls'))}", None),
        ("LEGAL BALLS", xl_fmt(legal, "#,##0"), None),
        ("RUNS CONCEDED", xl_fmt(runs, "#,##0"), None),
    ]
    blocks = [Block(key="wx_02", title="Summary", kind="kpis", kpis=kpis, note=HOW_TO_READ)]

    # ── † innings-level figures (Bowling Innings) ───────────────────────────
    bo = d.bowl_inns()
    ilo, ihi = _inn_range(f["innings"])
    mi = (bo["Season"] >= lo) & (bo["Season"] <= hi) & \
         (bo["Innings"] >= ilo) & (bo["Innings"] <= ihi)
    mi &= bo["Bowler"].notna() if f["bowler"] == "All" else (bo["Bowler"] == f["bowler"])
    for k, c in _INNS_COL.items():
        mi &= bo[c].notna() if f[k] == "All" else (bo[c] == f[k])
    inns = bo.loc[mi, ["Wickets", "Maidens"]]
    n_inns = len(inns)
    best = float(inns["Wickets"].max()) if n_inns else float("nan")
    blocks.append(Block(
        key="wx_02b", title="Summary · innings level †", kind="kpis", note=INNINGS_NOTE,
        kpis=[
            ("INNINGS †", xl_fmt(n_inns, "0"), None),
            ("3-WICKET HAULS †", xl_fmt(int((inns["Wickets"] == 3).sum()), "0"), None),
            ("4+ WICKET HAULS †", xl_fmt(int((inns["Wickets"] >= 4).sum()), "0"), None),
            ("MAIDENS †", xl_fmt(int(inns["Maidens"].sum()), "0"), None),
            ("BEST WICKETS †", xl_fmt(best, "0"), None),
        ]))

    # ── impact ───────────────────────────────────────────────────────────────
    econ_imp, wkt_imp = tot("Bowl Run Impact"), tot("Bowl Wkt Impact")
    impact = econ_imp + wkt_imp
    lg = base & (A["Bowler"][0] >= 0)
    lg_econ = _div(A["Bowler Runs"][lg].sum(), A["Legal Ball"][lg].sum(), 6.0)
    sg = "+0.0;-0.0;0.0"
    blocks.append(Block(
        key="wx_02c", title="Summary · impact", kind="kpis", note=IMPACT_NOTE,
        kpis=[
            ("BOWLING IMPACT (RUNS ±)", xl_fmt(impact, sg), None),
            ("IMPACT PER 4 OVERS", xl_fmt(_div(impact, legal, 24.0), sg), None),
            ("ECONOMY IMPACT", xl_fmt(econ_imp, sg), None),
            ("WICKET IMPACT", xl_fmt(wkt_imp, sg), None),
            ("ECON v LEAGUE · SAME FILTERS", xl_fmt(econ - lg_econ, "+0.00;-0.00;0.00"), None),
        ]))

    def table(key, title, note, df, **kw):
        return Block(key=key, title=title, note=note, df=df, fmt=dict(FMT, **kw.pop("fmt", {})),
                     good_low=["Economy", "Average", "Strike rate", "Boundary %"],
                     good_high=["Dot %"], **kw)

    # §03 By phase
    df = _text_breakdown(A, _all_but(A, m, "phase") & bowl, "Phase", "Phase", list(d.PHASES))
    blocks.append(table("wx_03", "By phase", "PP 1–6 · MO1 7–10 · MO2 11–16 · Death 17–20", df))

    # §04 By batter hand
    df = _text_breakdown(A, _all_but(A, m, "batter_hand") & bowl, "Bat Hand", "Batter hand",
                         list(d.HANDS))
    blocks.append(table("wx_04", "By batter hand", "ignores the batter-hand filter", df))

    # §05 By bowler type (ignores bowler type and pace/spin)
    df = _text_breakdown(A, _all_but(A, m, "bowler_type", "pace_spin") & bowl, "Bowler Type",
                         "Bowler type", list(d.BOWL_TYPES))
    blocks.append(table("wx_05", "By bowler type",
                        "ignores bowler-type and pace/spin filters · try it with Bowler = All", df))

    # §06 By season (ignores the season range; seasons outside the span greyed)
    seasons = A["seasons"]
    df = _breakdown(A, _all_but(A, m, "season") & bowl, A["season_code"],
                    list(range(len(seasons))), "Season", seasons)
    muted = [i for i, s in enumerate(seasons) if s < lo or s > hi]
    blocks.append(table(
        "wx_06", "By season", "ignores the season range", df, fmt={"Season": "{:.0f}"},
        muted_rows=muted,
        chart={"type": "line", "x": "Season", "y": "Economy",
               "title": "Economy by season", "color": "sky"}))

    # §07 By opposition (batting team)
    df = _text_breakdown(A, _all_but(A, m, "opposition") & bowl, "Batting Team", "Opposition",
                         _list("Teams"))
    blocks.append(table("wx_07", "By opposition", "ignores the opposition filter", df))

    # §08 By venue
    df = _text_breakdown(A, _all_but(A, m, "venue") & bowl, "Venue", "Venue",
                         _list("Venues+All")[1:])
    blocks.append(table("wx_08", "By venue", "ignores the venue filter", df))
    return blocks
