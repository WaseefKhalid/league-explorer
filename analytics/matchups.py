"""
"Matchups" sheet — every batter v bowler pair that met for 12+ balls in the
span: head-to-head numbers, the batter's own span record, and who is on top.

Workbook logic (rows 13–1916, one row per pair, SUMIFS over that pair's
Pair Seasons rows / the batter's Player Seasons rows inside the span):
* Rows: pairs with 12+ balls (1,904 for 2016–2026). The workbook keeps that
  fixed list and blanks "Edge" below 12 balls; the site lists the pairs with
  12+ balls in the selected span.
* Order: balls desc. Ties come out of the generator's default (unstable)
  sort on pairs keyed by (batter player_id, bowler player_id); reproduced
  exactly with the same heapsort-based descending argsort.
* Edge (sheet's how-to-read row 9, column P formula):
    Bowler on top = (2+ outs AND balls/dis < 0.67 x batter's span balls/dis
                     AND SR <= batter SR + 15)
                 OR (SR < batter SR − 15 AND 1+ out AND balls/dis <= batter's)
    Batter on top = (SR > batter SR + 15 AND balls/dis >= batter's)
                 OR (0 outs AND 24+ balls AND SR >= batter SR)
    otherwise Even.  (balls/dis with 0 outs, or a missing batter rate, = 9999)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

MIN_BALLS = 12
TITLE = "Matchups — batter v bowler"
SUBTITLE = "{n:,} pairs that have met for 12+ balls · pick a span, then filter Batter or Bowler"
HOW_TO_READ = [
    "Every number follows the Seasons box at the top. Dismissals count only wickets credited to the bowler.",
    "Edge (shown when the pair met for 12+ balls in the span) compares the pair with the batter's own "
    "span record: Bowler on top = 2+ dismissals at 1.5x his usual rate without being hit harder, or SR "
    "15+ below his norm while still dismissing him; Batter on top = SR 15+ above his norm without "
    "falling more often, or 24+ balls unbeaten at his normal SR or better.",
]

COLUMNS = ["Batter", "Hand", "Bowler", "Bowler type", "Balls", "Runs", "Outs", "SR",
           "Batter SR (span)", "Dot %", "4s", "6s", "Balls / dis", "Batter balls / dis (span)", "Edge"]

FMT = {
    "Balls": "{:,.0f}", "Runs": "{:,.0f}", "Outs": "{:,.0f}", "SR": "{:,.1f}",
    "Batter SR (span)": "{:,.1f}", "Dot %": "{:.1%}", "4s": "{:,.0f}", "6s": "{:,.0f}",
    "Balls / dis": "{:,.1f}", "Batter balls / dis (span)": "{:,.1f}", "Edge": "{:+.0f}",
}

# Edge: number in df (for tinting), text in labels
EDGE_VALUE = {"Batter on top": 1.0, "Even": 0.0, "Bowler on top": -1.0}
_TEXT = {"Batter", "Hand", "Bowler", "Bowler type"}


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object if c in _TEXT else float) for c in COLUMNS})


def _desc_order(values: np.ndarray) -> np.ndarray:
    """Positions sorting `values` descending exactly like the generator's
    DataFrame.sort_values(ascending=False) with numpy's heapsort-equivalent
    default: reverse, argsort, reverse."""
    n = len(values)
    ridx = np.arange(n)[::-1]
    return ridx[np.argsort(values[::-1], kind="heapsort")][::-1]


def _edge(F, H, I, J, O) -> np.ndarray:
    bpd = np.where(H > 0, F / np.where(H > 0, H, 1), 9999.0)
    Oe = np.where(np.isfinite(O), O, 9999.0)
    bowler = ((H >= 2) & (bpd < 0.67 * Oe) & (I <= J + 15)) | ((I < J - 15) & (H >= 1) & (bpd <= Oe))
    batter = ((I > J + 15) & (bpd >= Oe)) | ((H == 0) & (F >= 24) & (I >= J))
    edge = np.where(bowler, "Bowler on top", np.where(batter, "Batter on top", "Even")).astype(object)
    edge[F < MIN_BALLS] = None
    return edge


def table(span) -> tuple[pd.DataFrame, pd.Series]:
    """(df, edge_text) for the span."""
    pr = d.in_span(d.pair_seasons(), span)
    g = pr.groupby(["Batter", "Bowler"], sort=False)[["Balls", "Runs", "Outs", "Dots", "Fours", "Sixes"]].sum()
    g = g[g["Balls"] >= MIN_BALLS]
    if g.empty:
        return _empty(), pd.Series(dtype=object)
    g = g.reset_index()

    ps_all = d.player_seasons()
    pid = ps_all.groupby("Player")["player_id"].first()
    btype = ps_all.groupby("Player")["Bowl Type"].first()
    hand = d.players().drop_duplicates("Player").set_index("Player")["Bat Hand"]

    # generator order: pairs keyed by (batter id, bowler id), then balls desc
    g["_b"] = g["Batter"].map(pid).fillna(g["Batter"])
    g["_w"] = g["Bowler"].map(pid).fillna(g["Bowler"])
    g = g.sort_values(["_b", "_w"], kind="mergesort").reset_index(drop=True)
    g = g.iloc[_desc_order(g["Balls"].to_numpy())].reset_index(drop=True)

    # batter's own span record (Player Seasons)
    ps = d.in_span(ps_all, span)
    bat = ps.groupby("Player")[["Runs", "Balls", "Outs to Bowlers"]].sum()
    bR = g["Batter"].map(bat["Runs"]).fillna(0).to_numpy(float)
    bB = g["Batter"].map(bat["Balls"]).fillna(0).to_numpy(float)
    bO = g["Batter"].map(bat["Outs to Bowlers"]).fillna(0).to_numpy(float)

    F = g["Balls"].to_numpy(float)
    G = g["Runs"].to_numpy(float)
    H = g["Outs"].to_numpy(float)

    def div(a, b, k=1.0):
        out = np.full(len(a), np.nan)
        np.divide(k * a, b, out=out, where=b > 0)
        return out

    I = div(G, F, 100)
    J = div(bR, bB, 100)
    O = div(bB, bO)
    edge = _edge(F, H, I, J, O)

    df = pd.DataFrame({
        "Batter": g["Batter"].to_numpy(object),
        "Hand": g["Batter"].map(hand).to_numpy(object),
        "Bowler": g["Bowler"].to_numpy(object),
        "Bowler type": g["Bowler"].map(btype).to_numpy(object),
        "Balls": F,
        "Runs": G,
        "Outs": H,
        "SR": I,
        "Batter SR (span)": J,
        "Dot %": div(g["Dots"].to_numpy(float), F),
        "4s": g["Fours"].to_numpy(float),
        "6s": g["Sixes"].to_numpy(float),
        "Balls / dis": div(F, H),
        "Batter balls / dis (span)": O,
        "Edge": pd.Series(edge).map(EDGE_VALUE).to_numpy(float),
    })
    return df[COLUMNS], pd.Series(edge, index=df.index, dtype=object)


def build(span: tuple[int, int]) -> list[Block]:
    span = (min(span), max(span))
    df, edge = table(span)
    labels = pd.DataFrame(None, index=df.index, columns=df.columns, dtype=object)
    labels["Edge"] = edge
    intro = Block(
        key="mu_intro",
        title="How to read",
        kind="text",
        text="\n".join(f"- {t}" for t in HOW_TO_READ),
    )
    main = Block(
        key="mu_all",
        title=TITLE,
        df=df,
        note=SUBTITLE.format(n=len(df)),
        # CF: "Batter…" green, "Bowler…" pink, "Even" yellow (Edge: +1 / 0 / −1)
        rules={"Edge": {"good": (">=", 0.5), "bad": ("<=", -0.5)}},
        labels=labels,
        fmt=FMT,
        height=640,
    )
    return [intro, main]
