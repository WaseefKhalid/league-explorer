"""
"Bowling" sheet — every bowler in the span: totals, phase economy and
wickets, workload by phase, v RHB / LHB, impact.

Workbook logic (rows 15–313, one row per bowler, SUMIFS over that bowler's
Player Seasons rows inside the span):
* Rows: every player who has bowled a ball (299 for 2016–2026). The site
  shows the bowlers with 1+ ball in the span (the workbook keeps the other
  rows as blanks/zeros).
* Order: wickets desc, then economy asc; exact ties keep player_id order
  (the order the workbook was generated in).
* Phase economy / economy v hand need 30+ balls; SR v hand needs 30+ balls
  and 1+ wicket; Impact / 4 overs needs 120+ balls.
* Tints: CF rules compare with league figures for the same span (row 7).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

TITLE = "Bowling"
SUBTITLE = "All {n:,} {short} bowlers · pick a season span, then sort or filter any column"
HOW_TO_READ = [
    "Every number follows the Seasons box at the top. Economy = runs charged to the bowler "
    "(incl. wides & no-balls) per over; SR = balls per wicket.",
    "Phase economy shows when 30+ balls were bowled in that phase within the span. "
    "Share of balls by phase shows how the bowler is used.",
    "Tints compare with the league for the same span (career tints need 240+ balls): "
    "green = cheaper / more penetrative, pink = dearer.",
    "Impact = runs saved compared with an average bowler in the same phase, season and "
    "match situation (economy + value of wickets).",
]

PH = ["PP", "MO1", "MO2", "Death"]

# Workbook header -> site column (grouped headers made unambiguous)
COLUMNS = (
    ["Player", "Rank (wkts)", "Type", "Style", "Country", "Teams",
     "Mat", "Inns", "Overs", "Balls", "Runs", "Wkts", "Avg", "Econ", "SR",
     "Dot %", "Bdry %", "Best", "3w", "4w+", "Maidens", "Wides", "NB"]
    + [f"{p} Econ" for p in PH]
    + [f"{p} wkts" for p in PH]
    + [f"{p} % balls" for p in PH]
    + ["Econ v RHB", "SR v RHB", "Econ v LHB", "SR v LHB",
       "Impact (runs ±)", "Impact / 4 overs"]
)

FMT = {
    "Rank (wkts)": "{:,.0f}", "Mat": "{:,.0f}", "Inns": "{:,.0f}", "Overs": "{:.1f}",
    "Balls": "{:,.0f}", "Runs": "{:,.0f}", "Wkts": "{:,.0f}",
    "Avg": "{:,.2f}", "Econ": "{:,.2f}", "SR": "{:,.1f}",
    "Dot %": "{:.1%}", "Bdry %": "{:.1%}",
    "3w": "{:,.0f}", "4w+": "{:,.0f}", "Maidens": "{:,.0f}", "Wides": "{:,.0f}", "NB": "{:,.0f}",
    **{f"{p} Econ": "{:,.2f}" for p in PH},
    **{f"{p} wkts": "{:,.0f}" for p in PH},
    **{f"{p} % balls": "{:.1%}" for p in PH},
    "Econ v RHB": "{:,.2f}", "SR v RHB": "{:,.1f}", "Econ v LHB": "{:,.2f}", "SR v LHB": "{:,.1f}",
    "Impact (runs ±)": "{:+,.1f}", "Impact / 4 overs": "{:+,.1f}",
}

_SUM_COLS = (
    ["Mat", "Bowl Inns", "Bowl Balls", "Bowl Runs", "Wkts", "Bowl Dots", "4s Conc", "6s Conc",
     "3w", "4w+", "Maidens", "Wides", "No-balls",
     "BB PP", "BB MO1", "BB MO2", "BB Death", "BR PP", "BR MO1", "BR MO2", "BR Death",
     "BW PP", "BW MO1", "BW MO2", "BW Death",
     "BB v RHB", "BB v LHB", "BR v RHB", "BR v LHB", "BW v RHB", "BW v LHB",
     "Bowl Run Impact", "Bowl Wkt Impact"]
)


def _div(a, b, scale=1.0, mask=None):
    """scale*a/b where b>0 (and mask), else NaN."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = b > 0 if mask is None else (b > 0) & np.asarray(mask, dtype=bool)
    out = np.full(len(a), np.nan)
    np.divide(scale * a, b, out=out, where=ok)
    return out


def league(span) -> dict[str, float]:
    """Row 7 helper cells BI7:BO7 — league figures for the span (IFERROR → 0)."""
    ps = d.in_span(d.player_seasons(), span)
    s = ps[["Bowl Runs", "Bowl Balls", "Wkts", "BR PP", "BB PP", "BR MO1", "BB MO1",
            "BR MO2", "BB MO2", "BR Death", "BB Death"]].sum()

    def f(a, b, k=1.0):
        return float(k * a / b) if b else 0.0

    return {
        "econ": f(s["Bowl Runs"], s["Bowl Balls"], 6),   # BI7
        "avg": f(s["Bowl Runs"], s["Wkts"]),             # BJ7
        "sr": f(s["Bowl Balls"], s["Wkts"]),             # BK7
        "PP": f(s["BR PP"], s["BB PP"], 6),              # BL7
        "MO1": f(s["BR MO1"], s["BB MO1"], 6),           # BM7
        "MO2": f(s["BR MO2"], s["BB MO2"], 6),           # BN7
        "Death": f(s["BR Death"], s["BB Death"], 6),     # BO7
    }


def table(span) -> pd.DataFrame:
    ps_all = d.player_seasons()
    ps = d.in_span(ps_all, span)
    g = ps.groupby("Player", sort=False)[_SUM_COLS].sum()
    g = g[g["Bowl Balls"] > 0]
    if g.empty:
        return pd.DataFrame({c: pd.Series(dtype=object if c in ("Player", "Type", "Style", "Country", "Teams", "Best") else float)
                             for c in COLUMNS})

    pid = ps_all.groupby("Player")["player_id"].first()
    btype = ps_all.groupby("Player")["Bowl Type"].first()
    best_key = ps.groupby("Player")["Best Key"].max()
    pl = d.players().drop_duplicates("Player").set_index("Player")

    g = g.copy()
    names = g.index.to_series()
    K = g["Bowl Balls"].to_numpy(float)
    L = g["Bowl Runs"].to_numpy(float)
    M = g["Wkts"].to_numpy(float)

    out = pd.DataFrame(index=g.index)
    out["Player"] = names.values
    out["Rank (wkts)"] = np.nan  # filled after sorting below
    out["Type"] = names.map(btype).values
    out["Style"] = names.map(pl["Bowling Style"]).values
    country = names.map(pl["Country"])
    out["Country"] = country.where(~country.fillna("").str.endswith("*")).values  # "Pakistan*" shows blank in the workbook
    out["Teams"] = names.map(pl["Teams"]).values
    out["Mat"] = g["Mat"].values
    out["Inns"] = g["Bowl Inns"].values
    out["Overs"] = np.where(K > 0, np.floor(K / 6) + np.mod(K, 6) / 10, np.nan)
    out["Balls"] = K
    out["Runs"] = L
    out["Wkts"] = M
    out["Avg"] = _div(L, M)
    out["Econ"] = _div(L, K, 6)
    out["SR"] = _div(K, M)
    out["Dot %"] = _div(g["Bowl Dots"], K)
    out["Bdry %"] = _div(g["4s Conc"].to_numpy(float) + g["6s Conc"].to_numpy(float), K)
    bk = names.map(best_key).fillna(0).to_numpy(float)          # MAXIFS → 0 when nothing
    bw = np.floor((bk + 999) / 1000)
    br = 1000 * bw - bk
    best = pd.Series([f"{int(w)}/{int(r)}" for w, r in zip(bw, br)], index=g.index)
    out["Best"] = best.where(g["Bowl Inns"].to_numpy() > 0)
    out["3w"] = g["3w"].values
    out["4w+"] = g["4w+"].values
    out["Maidens"] = g["Maidens"].values
    out["Wides"] = g["Wides"].values
    out["NB"] = g["No-balls"].values
    for p in PH:
        bb = g[f"BB {p}"].to_numpy(float)
        out[f"{p} Econ"] = _div(g[f"BR {p}"], bb, 6, mask=bb >= 30)
    for p in PH:
        out[f"{p} wkts"] = g[f"BW {p}"].values
    for p in PH:
        out[f"{p} % balls"] = _div(g[f"BB {p}"], K)
    for h in ("RHB", "LHB"):
        bb = g[f"BB v {h}"].to_numpy(float)
        bwh = g[f"BW v {h}"].to_numpy(float)
        out[f"Econ v {h}"] = _div(g[f"BR v {h}"], bb, 6, mask=bb >= 30)
        out[f"SR v {h}"] = _div(bb, bwh, mask=bb >= 30)
    imp = g["Bowl Run Impact"].to_numpy(float) + g["Bowl Wkt Impact"].to_numpy(float)
    out["Impact (runs ±)"] = np.where(K > 0, imp, np.nan)
    out["Impact / 4 overs"] = _div(24 * imp, K, mask=K >= 120)

    # Order: base = player_id order, then stable sort by wickets desc, economy asc
    out["_pid"] = names.map(pid).values
    out = out.sort_values("_pid", kind="mergesort")
    out = out.sort_values(["Wkts", "Econ"], ascending=[False, True], kind="mergesort")
    out = out.drop(columns="_pid").reset_index(drop=True)
    # RANK(M, M:M) — competition rank on wickets, blank for 0 wkts
    rank = out["Wkts"].rank(method="min", ascending=False)
    out["Rank (wkts)"] = rank.where(out["Wkts"] > 0)
    return out[COLUMNS]


def _rules(df: pd.DataFrame, lg: dict) -> dict:
    career = df["Balls"] >= 240      # "career tints need 240+ balls"
    r = {
        "Avg": {"good": ("<=", lg["avg"] * 0.8), "bad": (">=", lg["avg"] * 1.2), "where": career},
        "Econ": {"good": ("<=", lg["econ"] * (1 - 0.07)), "bad": (">=", lg["econ"] * 1.07), "where": career},
        "SR": {"good": ("<=", lg["sr"] * 0.8), "bad": (">=", lg["sr"] * 1.2), "where": career},
        "Econ v RHB": {"good": ("<=", lg["econ"] * 0.92), "bad": (">=", lg["econ"] * 1.08)},
        "Econ v LHB": {"good": ("<=", lg["econ"] * 0.92), "bad": (">=", lg["econ"] * 1.08)},
        "Impact (runs ±)": {"good": (">=", 10), "bad": ("<=", -10)},
        "Impact / 4 overs": {"good": (">=", 10), "bad": ("<=", -10)},
    }
    for p in PH:
        r[f"{p} Econ"] = {"good": ("<=", lg[p] * 0.92), "bad": (">=", lg[p] * 1.08)}
    return r


def build(span: tuple[int, int]) -> list[Block]:
    span = (min(span), max(span))
    df = table(span)
    lg = league(span)
    intro = Block(
        key="bowl_intro",
        title="How to read",
        kind="text",
        text="\n".join(f"- {t}" for t in HOW_TO_READ),
    )
    main = Block(
        key="bowl_all",
        title=TITLE,
        df=df,
        note=SUBTITLE.format(n=len(df), short=d.short()),
        rules=_rules(df, lg),
        good_low=["Bdry %", "SR v RHB", "SR v LHB"],
        good_high=["Dot %"],
        fmt=FMT,
        height=640,
    )
    return [intro, main]
