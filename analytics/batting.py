"""
"Batting" sheet: every batter in the selected span — totals, strike rate
by phase, pace v spin, bowling type and innings stage, plus batting impact.

Workbook logic (rows 15–441, helper league figures in BI7:BV7):
* one row per batter (Inns > 0 in the span; the saved workbook lists the 427
  career batters, i.e. Inns > 0 over 2016–2026);
* default order = Runs desc, then strike rate desc (no balls faced last),
  then the Cricsheet player id — exactly the workbook's saved row order;
* split columns need 30+ balls in that split; Impact / 100 balls needs 60+;
* tints: Avg / SR vs the league for the span (only with 200+ balls),
  split SRs ±10% vs the league split SR, impact ±10 runs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

# Sums needed from Player Seasons (workbook column headers)
_SUM = ["Mat", "Inns", "NO", "Runs", "Balls", "100s", "50s", "4s", "6s", "Bat Dots",
        "R PP", "B PP", "R MO1", "B MO1", "R MO2", "B MO2", "R Death", "B Death",
        "R v Pace", "B v Pace", "R v Spin", "B v Spin", "Outs v Pace", "Outs v Spin",
        "R v RAP", "B v RAP", "R v LAP", "B v LAP", "R v OS", "B v OS",
        "R v LS", "B v LS", "R v LAO", "B v LAO", "R v LWS", "B v LWS",
        "R b1-10", "B b1-10", "R b21+", "B b21+",
        "Bat Run Impact", "Bat Out Impact"]

# Split strike-rate columns: output name -> (runs col, balls col)
SPLITS = {
    "PP SR": ("R PP", "B PP"),
    "MO1 SR": ("R MO1", "B MO1"),
    "MO2 SR": ("R MO2", "B MO2"),
    "Death SR": ("R Death", "B Death"),
    "SR v pace": ("R v Pace", "B v Pace"),
    "SR v spin": ("R v Spin", "B v Spin"),
    "SR v RA pace": ("R v RAP", "B v RAP"),
    "SR v LA pace": ("R v LAP", "B v LAP"),
    "SR v off-spin": ("R v OS", "B v OS"),
    "SR v leg-spin": ("R v LS", "B v LS"),
    "SR v LA orthodox": ("R v LAO", "B v LAO"),
    "SR v LA wrist-spin": ("R v LWS", "B v LWS"),
    "SR balls 1–10": ("R b1-10", "B b1-10"),
    "SR balls 21+": ("R b21+", "B b21+"),
}
# Split columns tinted ±10% vs the league split SR (CF on V:AA, AD:AI)
_TINTED_SPLITS = ["PP SR", "MO1 SR", "MO2 SR", "Death SR", "SR v pace", "SR v spin",
                  "SR v RA pace", "SR v LA pace", "SR v off-spin", "SR v leg-spin",
                  "SR v LA orthodox", "SR v LA wrist-spin"]

# Output columns in workbook order (B..AM). Group headers in the workbook:
# PLAYER (Player..Teams) · IN THE SELECTED SPAN (Mat..% runs in 4s/6s) ·
# STRIKE RATE BY PHASE · PACE v SPIN · STRIKE RATE v BOWLING TYPE ·
# INNINGS STAGE (SR) · IMPACT
COLUMNS = ["Player", "Rank (runs)", "Hand", "Country", "Teams",
           "Mat", "Inns", "NO", "Runs", "Balls", "Avg", "SR", "HS", "100s", "50s",
           "4s", "6s", "Bdry %", "Dot %", "% runs in 4s/6s",
           "PP SR", "MO1 SR", "MO2 SR", "Death SR",
           "SR v pace", "SR v spin", "Balls/dis v pace", "Balls/dis v spin",
           "SR v RA pace", "SR v LA pace", "SR v off-spin", "SR v leg-spin",
           "SR v LA orthodox", "SR v LA wrist-spin",
           "SR balls 1–10", "SR balls 21+",
           "Impact (runs ±)", "Impact / 100 balls"]

# Workbook header for each output column (for validation / reference)
WB_HEADERS = dict(zip(COLUMNS, [
    "Player", "Rank (runs)", "Hand", "Country", "Teams", "Mat", "Inns", "NO", "Runs",
    "Balls", "Avg", "SR", "HS", "100s", "50s", "4s", "6s", "Bdry %", "Dot %",
    "% runs in 4s/6s", "PP", "MO1", "MO2", "Death", "SR v pace", "SR v spin",
    "Balls/dis v pace", "Balls/dis v spin", "RA pace", "LA pace", "Off-spin",
    "Leg-spin", "LA orthodox", "LA wrist-spin", "Balls 1–10", "Balls 21+",
    "Impact (runs ±)", "Impact / 100 balls"]))

GROUPS = {
    "PLAYER": COLUMNS[0:5],
    "IN THE SELECTED SPAN": COLUMNS[5:20],
    "STRIKE RATE BY PHASE": COLUMNS[20:24],
    "PACE v SPIN": COLUMNS[24:28],
    "STRIKE RATE v BOWLING TYPE": COLUMNS[28:34],
    "INNINGS STAGE (SR)": COLUMNS[34:36],
    "IMPACT": COLUMNS[36:38],
}

FMT = {c: "{:,.1f}" for c in COLUMNS[20:36]}
FMT.update({
    "Rank (runs)": "{:,.0f}", "Mat": "{:,.0f}", "Inns": "{:,.0f}", "NO": "{:,.0f}",
    "Runs": "{:,.0f}", "Balls": "{:,.0f}", "Avg": "{:,.1f}", "SR": "{:,.1f}",
    "HS": "{:,.0f}", "100s": "{:,.0f}", "50s": "{:,.0f}", "4s": "{:,.0f}", "6s": "{:,.0f}",
    "Bdry %": "{:.1%}", "Dot %": "{:.1%}", "% runs in 4s/6s": "{:.1%}",
    "Impact (runs ±)": "{:+,.1f}", "Impact / 100 balls": "{:+,.1f}",
})

INTRO = [
    "Every number follows the Seasons box at the top ({lo} to {hi} = whole {short} career; "
    "set both boxes to one year for a single season).",
    "Split columns ({splits}) show only when the "
    "batter faced 30+ balls in that split within the span.",
    "Tints compare with the league for the same span: green = 10%+ above (career SR ±7%, "
    "average ±25%, 200+ balls), pink = below.",
    "Impact = runs added compared with an average batter facing the same balls in the "
    "same match situation, including the cost of getting out.",
]

MIN_SPLIT_BALLS = 30
MIN_IMPACT100_BALLS = 60
MIN_TINT_BALLS = 200


def _div(a, b, scale=1.0):
    """a/b*scale with NaN where b == 0 (vectorised)."""
    b = b.astype(float)
    return (a * scale) / b.where(b != 0)


def _hs(span_ps: pd.DataFrame) -> pd.DataFrame:
    """Max HS key per player in the span -> (int value, display text)."""
    key = span_ps.groupby("Player", sort=False)["HS Key"].max()
    hs_int = np.floor(key)
    star = (key - hs_int) > 0.05
    txt = hs_int.astype("Int64").astype(str) + np.where(star, "*", "")
    return pd.DataFrame({"HS": hs_int, "HS text": txt.where(key.notna())})


def league(span: tuple[int, int]) -> dict[str, float]:
    """The workbook's league figures for the span (Batting!BI7:BV7);
    IFERROR(...,0) -> 0 when there is no data."""
    ps = d.in_span(d.player_seasons(), span)
    s = ps[_SUM].sum()

    def r(a, b, k=1.0):
        return float(k * s[a] / s[b]) if s[b] else 0.0

    out = {"SR": r("Runs", "Balls", 100),
           "Avg": float(s["Runs"] / (s["Inns"] - s["NO"])) if (s["Inns"] - s["NO"]) else 0.0}
    for col, (rc, bc) in SPLITS.items():
        out[col] = r(rc, bc, 100)
    out["Balls/dis v pace"] = r("B v Pace", "Outs v Pace")
    out["Balls/dis v spin"] = r("B v Spin", "Outs v Spin")
    return out


def table(span: tuple[int, int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(df, labels) for the batter table in the selected span."""
    ps = d.in_span(d.player_seasons(), span)
    g = ps.groupby("Player", sort=False)[_SUM].sum()
    g = g[g["Inns"] > 0]
    if g.empty:
        df = pd.DataFrame({c: pd.Series(dtype=object if c in ("Player", "Hand", "Country", "Teams") else float)
                           for c in COLUMNS})
        return df, df.astype(object)

    g = g.join(_hs(ps[ps["Player"].isin(g.index)]))
    prof = d.players().set_index("Player")[["Bat Hand", "Country", "Teams"]]
    pid = ps.drop_duplicates("Player").set_index("Player")["player_id"]
    g = g.join(prof).join(pid)

    out = pd.DataFrame(index=g.index)
    out["Player"] = g.index
    # The Batting sheet shows an unknown batting hand as "—"
    out["Hand"] = g["Bat Hand"].fillna("").replace({"Unknown": "—"})
    # The Batting sheet leaves Country blank where the source had none ("Pakistan*")
    ctry = g["Country"].fillna("")
    out["Country"] = ctry.where(~ctry.str.endswith("*"), "")
    out["Teams"] = g["Teams"].fillna("")
    for c in ["Mat", "Inns", "NO", "Runs", "Balls"]:
        out[c] = g[c].astype(float)
    out["Avg"] = _div(g["Runs"], g["Inns"] - g["NO"])
    out["SR"] = _div(g["Runs"], g["Balls"], 100)
    out["HS"] = g["HS"]
    for c in ["100s", "50s", "4s", "6s"]:
        out[c] = g[c].astype(float)
    out["Bdry %"] = _div(g["4s"] + g["6s"], g["Balls"])
    out["Dot %"] = _div(g["Bat Dots"], g["Balls"])
    out["% runs in 4s/6s"] = _div(4 * g["4s"] + 6 * g["6s"], g["Runs"])
    for col, (rc, bc) in SPLITS.items():
        out[col] = _div(g[rc], g[bc], 100).where(g[bc] >= MIN_SPLIT_BALLS)
    for kind, bc, oc in [("pace", "B v Pace", "Outs v Pace"), ("spin", "B v Spin", "Outs v Spin")]:
        out[f"Balls/dis v {kind}"] = _div(g[bc], g[oc]).where((g[bc] >= MIN_SPLIT_BALLS) & (g[oc] > 0))
    imp = (g["Bat Run Impact"] + g["Bat Out Impact"]).where(g["Balls"] > 0)
    out["Impact (runs ±)"] = imp
    out["Impact / 100 balls"] = _div(imp, g["Balls"], 100).where(g["Balls"] >= MIN_IMPACT100_BALLS)

    # Workbook order: runs desc, strike rate desc (no balls last), player id
    sr_key = out["SR"].fillna(-1.0)
    out = out.assign(_sr=sr_key, _pid=g["player_id"]).sort_values(
        ["Runs", "_sr", "_pid"], ascending=[False, False, True], kind="mergesort")
    # RANK(J, J:J) for runs > 0 (ties share the higher rank)
    out["Rank (runs)"] = out["Runs"].rank(method="min", ascending=False).where(out["Runs"] > 0)
    hs_txt = g.loc[out.index, "HS text"]

    df = out[COLUMNS].reset_index(drop=True)
    labels = pd.DataFrame(None, index=df.index, columns=COLUMNS, dtype=object)
    labels["HS"] = hs_txt.to_numpy()
    return df, labels


def build(span: tuple[int, int]) -> list[Block]:
    df, labels = table(span)
    lg = league(span)
    n = len(df)

    rules: dict[str, dict] = {}
    # Avg and SR: league-relative, only for batters with 200+ balls
    # (NaN threshold = rule does not apply to that row, as in the workbook)
    enough = df["Balls"] >= MIN_TINT_BALLS
    for col, hi, lo in [("Avg", 1.25, 0.75), ("SR", 1.07, 0.93)]:
        rules[col] = {"good": (">=", pd.Series(lg[col] * hi, index=df.index).where(enough)),
                      "bad": ("<=", pd.Series(lg[col] * lo, index=df.index).where(enough))}
    for col in _TINTED_SPLITS:
        rules[col] = {"good": (">=", lg[col] * 1.1), "bad": ("<=", lg[col] * 0.9)}
    for col in ["Impact (runs ±)", "Impact / 100 balls"]:
        rules[col] = {"good": (">=", 10), "bad": ("<=", -10)}

    good_high = ["SR balls 1–10", "SR balls 21+", "Balls/dis v pace", "Balls/dis v spin"]
    center = {c: lg[c] for c in good_high if lg.get(c)}

    lo, hi = d.full_span()
    splits = "phase, pace/spin, bowling type, innings stage" if d.has("has_hand_type") else "phase, innings stage"
    intro = Block(
        key="bat_intro", title="How to read", kind="text",
        text="\n".join(f"- {t}" for t in INTRO).format(lo=lo, hi=hi, short=d.short(), splits=splits),
    )
    table_block = Block(
        key="bat_all", title="Batting",
        note=f"All {n} {d.short()} batters · pick a season span, then sort or filter any column",
        df=df, labels=labels, fmt=dict(FMT), rules=rules,
        good_high=good_high, center=center, height=640,
    )
    return [intro, table_block]
