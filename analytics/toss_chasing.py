"""
"Toss & Chasing" sheet of the PSL Analytics Workbook.

§01 Toss and chasing by season
§02 Toss and chasing by venue — selected span
§03 Par score guide — bat-first win % by first-innings total
§04 Chase calculator — after 15 overs
§05 Chase calculator — after 10 overs
§06 Powerplay wickets lost v result
§07 League v playoffs — chasing success

build(span) -> list[Block]; keys "toss_…".
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

import analytics.data as d
from analytics.blocks import Block

SUMMARY_COLS = ["Matches", "Decided*", "Toss winner bowled %", "Toss winner won %",
                "Bat-first wins", "Chase wins", "Chase win %"]
SUMMARY_FMT = {"Matches": "{:,.0f}", "Decided*": "{:,.0f}", "Toss winner bowled %": "{:.1%}",
               "Toss winner won %": "{:.1%}", "Bat-first wins": "{:,.0f}", "Chase wins": "{:,.0f}",
               "Chase win %": "{:.1%}"}
SUMMARY_RULE = {"good": (">=", 0.60), "bad": ("<=", 0.45)}
GRID_RULE = {"good": (">=", 0.60), "bad": ("<=", 0.40)}

PAR_BINS = [("Under 160", 0, 159), ("160–179", 160, 179), ("180–199", 180, 199),
            ("200–219", 200, 219), ("220+", 220, 999)]
WKT_BINS = [("0–2 down", 0, 2), ("3–4 down", 3, 4), ("5–6 down", 5, 6), ("7+ down", 7, 10),
            ("All wickets", 0, 10)]
NEED15 = [("≤30 runs", 0, 30), ("31–40 runs", 31, 40), ("41–50 runs", 41, 50),
          ("51–60 runs", 51, 60), ("61–70 runs", 61, 70), ("71+ runs", 71, 999)]
NEED10 = [("≤70 runs", 0, 70), ("71–85 runs", 71, 85), ("86–100 runs", 86, 100),
          ("101–115 runs", 101, 115), ("116–130 runs", 116, 130), ("131+ runs", 131, 999)]
PP_BINS = [("0 down after 6 overs", 0, 0), ("1 down", 1, 1), ("2 down", 2, 2), ("3 down", 3, 3),
           ("4+ down", 4, np.inf)]


# ── helpers ──────────────────────────────────────────────────────────────────
def _div(a, b, scale=1.0):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a * scale / b
    return np.where(np.isfinite(out), out, np.nan)


def _pct0(x: float) -> str:
    """Excel's '0%' display (round half up on the 15-digit value)."""
    v = Decimal(format(float(x), ".15g")) * 100
    return f"{int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP))}%"


@d.per_league()
def venues() -> tuple[str, ...]:
    v = d.lists()["Venues+All"].dropna().tolist()
    return tuple(x for x in v if x != "All")


def _between(s: pd.Series, lo, hi) -> pd.Series:
    return (s >= lo) & (s <= hi)


# ── §01 / §02 summary rows ───────────────────────────────────────────────────
def _summary_sums(m: pd.DataFrame, by: str | None) -> pd.DataFrame:
    dec = m["Decided (no DLS)"] == 1
    parts = pd.DataFrame({
        "n": np.ones(len(m)),
        "dec": dec.astype(float),
        "field": (m["Toss Decision"] == "Field").astype(float),
        "tw1": (m["Toss Winner Won"] == 1).astype(float),
        "tw0": (m["Toss Winner Won"] == 0).astype(float),
        "bfw": (dec & (m["Bat First Won"] == 1)).astype(float),
        "chw": (dec & (m["Bat First Won"] == 0)).astype(float),
    }, index=m.index)
    if by is None:
        return parts.sum().to_frame().T
    return parts.groupby(m[by]).sum()


def _summary_ratios(S: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Matches": S["n"].to_numpy(),
        "Decided*": S["dec"].to_numpy(),
        "Toss winner bowled %": _div(S["field"], S["n"]),
        "Toss winner won %": _div(S["tw1"], S["tw1"] + S["tw0"]),
        "Bat-first wins": S["bfw"].to_numpy(),
        "Chase wins": S["chw"].to_numpy(),
        "Chase win %": _div(S["chw"], S["dec"]),
    })


def by_season(span) -> tuple[pd.DataFrame, list, list]:
    lo, hi = span
    seasons = list(d.seasons())
    m = d.matches()
    S = _summary_sums(m, "Season").reindex(seasons, fill_value=0)
    span_s = S.loc[[s for s in seasons if lo <= s <= hi]].sum().to_frame().T
    all_s = S.sum().to_frame().T
    R = _summary_ratios(pd.concat([S, span_s, all_s], ignore_index=True))
    R.insert(0, "Season", [str(s) for s in seasons] + ["Selected span", "All seasons"])
    muted = [i for i, s in enumerate(seasons) if s < lo or s > hi]
    return R, muted, [len(seasons)]


def by_venue(span) -> pd.DataFrame:
    V = list(venues())
    m = d.in_span(d.matches(), span)
    S = _summary_sums(m, "Venue").reindex(V, fill_value=0)
    tot = _summary_sums(m, None)
    R = _summary_ratios(pd.concat([S, tot], ignore_index=True))
    R.insert(0, "Venue", V + ["All (selected span)"])
    return R


# ── §03 Par score guide ──────────────────────────────────────────────────────
def par_guide(span) -> tuple[pd.DataFrame, pd.DataFrame]:
    V = list(venues())
    m = d.in_span(d.matches(), span)
    m = m[(m["Full 1st Inns"] == 1) & (m["Decided (no DLS)"] == 1)]
    cols = ["All venues"] + V
    num = pd.DataFrame(np.nan, index=range(len(PAR_BINS)), columns=cols)
    lab = pd.DataFrame("", index=range(len(PAR_BINS)), columns=cols, dtype=object)
    inn1 = m["1st Inns Runs"]
    for i, (_, lo, hi) in enumerate(PAR_BINS):
        sel = m[_between(inn1, lo, hi)]
        n = sel["Venue"].value_counts().reindex(V, fill_value=0)
        w = sel.loc[sel["Bat First Won"] == 1, "Venue"].value_counts().reindex(V, fill_value=0)
        ns = [len(sel)] + n.tolist()
        ws = [int((sel["Bat First Won"] == 1).sum())] + w.tolist()
        for j, (nn, ww) in enumerate(zip(ns, ws)):
            if nn == 0:
                lab.iat[i, j] = "–"
            elif nn < 3:
                lab.iat[i, j] = f"{ww} of {nn}"
            else:
                num.iat[i, j] = ww / nn
                lab.iat[i, j] = _pct0(ww / nn)
    names = [b[0] for b in PAR_BINS]
    num.insert(0, "1st-innings total", names)
    lab.insert(0, "1st-innings total", names)
    return num, lab


# ── §04 / §05 Chase calculators ──────────────────────────────────────────────
def chase_grid(span, at: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bins = NEED15 if at == 15 else NEED10
    m = d.in_span(d.matches(), span)
    m = m[m[f"Alive@{at}"] == 1]
    need, wk = m[f"Need@{at}"], m[f"Wkts@{at}"]
    won = m["Chase Won"] == 1
    cols = [w[0] for w in WKT_BINS]
    N = np.zeros((len(bins), len(WKT_BINS)))
    W = np.zeros_like(N)
    for i, (_, lo, hi) in enumerate(bins):
        rmask = _between(need, lo, hi)
        for j, (_, wlo, whi) in enumerate(WKT_BINS):
            mk = rmask & _between(wk, wlo, whi)
            N[i, j] = mk.sum()
            W[i, j] = (mk & won).sum()
    pct = _div(W, N)
    num = pd.DataFrame(pct, columns=cols)
    n_df = pd.DataFrame(N, columns=cols)
    lab = pd.DataFrame([[(f"{_pct0(p)} ({int(n)})" if n > 0 else f"– ({int(n)})")
                         for p, n in zip(pr, nr)] for pr, nr in zip(pct, N)], columns=cols, dtype=object)
    names = [b[0] for b in bins]
    for f in (num, lab, n_df):
        f.insert(0, "Runs needed", names)
    return num, lab, n_df


# ── §06 Powerplay wickets ────────────────────────────────────────────────────
def pp_wickets(span) -> pd.DataFrame:
    tm = d.in_span(d.team_matches(), span)
    tm = tm[tm["Decided"] == 1]
    ppw = tm["PP Wkts"]
    won = tm["Result"] == "Won"
    rows = []
    for name, lo, hi in PP_BINS:
        sel = _between(ppw, lo, hi)
        bf = sel & (tm["Batting Order"] == "Bat first")
        ch = sel & (tm["Batting Order"] == "Chasing")
        nb, nc = float(bf.sum()), float(ch.sum())
        rows.append({"PP wickets lost": name,
                     "Batting first win %": (bf & won).sum() / nb if nb else np.nan,
                     "Chasing win %": (ch & won).sum() / nc if nc else np.nan,
                     "Batting first (n)": nb, "Chasing (n)": nc})
    return pd.DataFrame(rows)


# ── §07 League v playoffs ────────────────────────────────────────────────────
def league_playoffs(span) -> pd.DataFrame:
    m = d.in_span(d.matches(), span)
    dec = m["Decided (no DLS)"] == 1
    rows = []
    for name, mt in (("League", "League"), ("Playoffs", "Playoff")):
        sel = dec & (m["Match Type"] == mt)
        n = float(sel.sum())
        rows.append({"Match type": name,
                     "Chase win %": (sel & (m["Bat First Won"] == 0)).sum() / n if n else np.nan,
                     "Decided matches": n})
    return pd.DataFrame(rows)


# ── build ────────────────────────────────────────────────────────────────────
def build(span: tuple[int, int]) -> list[Block]:
    lo, hi = min(span), max(span)
    span = (lo, hi)
    out: list[Block] = []

    s, muted, bold = by_season(span)
    out.append(Block(
        key="toss_01", title="Toss and chasing by season", df=s,
        note=("* Decided = a winner without DLS or a tie. Toss winner bowled % uses all matches. "
              "Seasons outside your span are greyed."),
        rules={"Toss winner won %": SUMMARY_RULE, "Chase win %": SUMMARY_RULE},
        fmt=dict(SUMMARY_FMT), muted_rows=muted, bold_rows=bold,
    ))

    v = by_venue(span)
    out.append(Block(
        key="toss_02", title="Toss and chasing by venue — selected span", df=v,
        note="* Decided = a winner without DLS or a tie. Toss winner bowled % uses all matches.",
        rules={"Toss winner won %": SUMMARY_RULE, "Chase win %": SUMMARY_RULE},
        fmt=dict(SUMMARY_FMT), bold_rows=[len(v) - 1],
    ))

    p_num, p_lab = par_guide(span)
    pcols = [c for c in p_num.columns if c != "1st-innings total"]
    out.append(Block(
        key="toss_03", title="Par score guide — bat-first win % by first-innings total",
        df=p_num, labels=p_lab, kind="matrix",
        note=("selected span · completed first innings, decided matches. Cells with fewer than 3 "
              'matches show the raw count (e.g. "1 of 2") instead of a percentage.'),
        rules={"*": GRID_RULE}, fmt={c: "{:.0%}" for c in pcols},
    ))

    for key, at, title in (("toss_04", 15, "Chase calculator — after 15 overs (runs still needed v wickets down)"),
                           ("toss_05", 10, "Chase calculator — after 10 overs")):
        c_num, c_lab, _ = chase_grid(span, at)
        wcols = [w[0] for w in WKT_BINS]
        out.append(Block(
            key=key, title=title, df=c_num, labels=c_lab, kind="matrix",
            note=("selected span · chasing side won % · (n) = chases. Every non-DLS 20-over chase still "
                  "alive at that point (not yet won, not all out); small cells (n under 10) are "
                  "indicative only."),
            rules={"*": GRID_RULE}, fmt={c: "{:.0%}" for c in wcols},
        ))

    pp = pp_wickets(span)
    out.append(Block(
        key="toss_06", title="Powerplay wickets lost v result", df=pp,
        note="selected span · decided matches · win % and (n)",
        rules={"Batting first win %": GRID_RULE, "Chasing win %": GRID_RULE},
        fmt={"Batting first win %": "{:.0%}", "Chasing win %": "{:.0%}",
             "Batting first (n)": "({:,.0f})", "Chasing (n)": "({:,.0f})"},
    ))

    out.append(Block(
        key="toss_07", title="League v playoffs — chasing success", df=league_playoffs(span),
        note="selected span", fmt={"Chase win %": "{:.1%}", "Decided matches": "{:,.0f}"},
    ))

    out.append(Block(
        key="toss_howto", title="How to read", kind="text",
        text=("- \\* Decided = a winner without DLS or a tie. Toss winner bowled % uses all matches. "
              "Every table follows the Seasons box at the top.\n"
              "- Chase calculators use every non-DLS 20-over chase still alive at that point (not yet "
              "won, not all out); small cells (n under 10) are indicative only.\n"
              "- Tints: green = 60%+ for the side named in the column, pink = 40% or less, amber in "
              "between."),
    ))
    return out
