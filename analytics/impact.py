"""
Impact sheet — who really moves matches: batting, bowling, wicket-taking,
run-scoring and the last over.

Mirrors the workbook's 'Impact' sheet, which ranks per-player span sums
from the hidden 'Calc' sheet (one row per player in 'Players' order, so the
ROW()/1E9 tie-break = position in `players()` + 2) and the final-over
columns of 'Match Data'.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

SIGNED = "{:+,.1f}"

# Player Seasons columns summed per player over the span (Calc U:BC)
_SUM_COLS = {
    "Balls": "Balls", "Runs": "Runs",
    "Bat Run Impact": "W", "Bat Out Impact": "X",
    "Bowl Balls": "Z", "Bowl Runs": "AA", "Wkts": "AB",
    "Bowl Run Impact": "AC", "Bowl Wkt Impact": "AD",
    "Wicket Value": "AF",
    "B O20": "AI", "R O20": "AJ", "BB O20": "AL", "BR O20": "AM",
    "Top-order Wkts": "AS", "Set-batter Wkts": "AT",
    "Runs in Wins": "AU", "50+ in Wins": "AV",
    "Chase Runs": "AW", "Chase Balls": "AX",
    "6s O20": "AY", "Outs O20": "AZ", "BW O20": "BA",
}


# ── helpers ──────────────────────────────────────────────────────────────────
def _span(span):
    return int(min(span)), int(max(span))


def _xl_round(x: float, nd: int = 0) -> float:
    """Excel-style rounding (half away from zero)."""
    m = 10 ** nd
    return math.copysign(math.floor(abs(x) * m + 0.5 + 1e-9), x) / m


def _calc(span) -> pd.DataFrame:
    """Calc!A:BC for the span: one row per player (Players order), with the
    Excel row number in `_row` for the ROW()/1E9 tie-breaks."""
    lo, hi = _span(span)
    ps = d.player_seasons()
    ps = ps[(ps["Season"] >= lo) & (ps["Season"] <= hi)]
    sums = ps.groupby("Player", sort=False)[list(_SUM_COLS)].sum()
    names = d.players()["Player"]
    out = sums.reindex(names.values).fillna(0)
    ints = [c for c in _SUM_COLS if pd.api.types.is_integer_dtype(ps[c])]
    out[ints] = out[ints].astype(int)
    out.columns = [_SUM_COLS[c] for c in out.columns]
    out = out.rename(columns={"Balls": "U", "Runs": "V"})
    out.index.name = "Player"
    out = out.reset_index()
    out["_row"] = np.arange(len(out)) + 2
    return out


def _top(c: pd.DataFrame, value: pd.Series, qualifies: pd.Series, n: int,
         largest: bool = True) -> pd.DataFrame:
    """LARGE/SMALL over (value + ROW()/1E9) restricted to qualifying rows."""
    key = value.round(7) + c["_row"] / 1e9
    q = c[qualifies.values].assign(_key=key[qualifies.values])
    return q.sort_values("_key", ascending=not largest).head(n).reset_index(drop=True)


def _ranked(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df[cols].reset_index(drop=True) if len(df) else pd.DataFrame(columns=cols)
    df.insert(0, "#", np.arange(1, len(df) + 1))
    return df


def _overs(balls: pd.Series) -> pd.Series:
    """INT(b/6)&"."&MOD(b,6) — cricket overs notation as a number."""
    b = balls.astype(int)
    return (b // 6) + (b % 6) / 10.0


def _final_over(span) -> pd.DataFrame:
    """Match Data rows for tight final-over chases in the span
    (md_fochase=1, md_foneed<=15)."""
    lo, hi = _span(span)
    m = d.matches()
    f = m[(m["Final-over Chase"] == 1) & (m["Need off 20th"] <= 15)
          & (m["Season"] >= lo) & (m["Season"] <= hi)]
    return f


# ── sections ─────────────────────────────────────────────────────────────────
def _intro() -> Block:
    return Block(
        key="imp_intro", title="How impact works", kind="text",
        text=(
            f"Impact measures runs added or saved compared with an average {d.short()} player in the "
            "same situation. A model of expected runs (from every completed first innings, by "
            "balls left and wickets lost, scaled to each season's scoring) values every ball: a "
            "dot ball at 120/2 after 15 overs costs the batting side more than a dot in over 1.\n\n"
            "Batting impact = scoring above par for the balls faced (centred on the league average "
            "for that season and phase) + the cost of getting out compared with an average batter. "
            "Bowling impact = runs saved compared with par (economy) + the value of wickets taken. "
            "A score of +50 means roughly 50 runs better than an average player would have managed.\n\n"
            "DLS and no-result matches are left out of impact. Every table below follows the "
            "Seasons box at the top."
        ),
    )


def _kpis(c: pd.DataFrame, span) -> Block:
    def top_text(val: pd.Series, qual: pd.Series) -> str:
        if not qual.any():
            return "—"
        key = val.where(qual, -1e9).round(7) + c["_row"] / 1e9
        i = int(key.values.argmax())
        v = _xl_round(float(key.iloc[i]))
        return f"{c['Player'].iloc[i]}  {'+' if v >= 0 else '-'}{abs(v):.0f}"

    bat = top_text(c["W"] + c["X"], c["U"] > 0)
    bowl = top_text(c["AC"] + c["AD"], c["Z"] > 0)
    f = _final_over(span)
    n = len(f)
    defended = (f["Final-over Defended"] == 1).sum() / n if n else float("nan")
    avg_need = f["Need off 20th"].mean() if n else float("nan")
    return Block(
        key="imp_kpis", title="At a glance", kind="kpis",
        kpis=[
            ("TOP BATTING IMPACT", bat, None),
            ("TOP BOWLING IMPACT", bowl, None),
            ("TIGHT FINAL-OVER CHASES", f"{n:,.0f}", None),
            ("DEFENDED BY THE BOWLER", "—" if n == 0 else f"{defended:.1%}", None),
            ("AVG RUNS NEEDED OFF 20TH", "—" if n == 0 else f"{_xl_round(avg_need, 1):.1f}", None),
        ],
    )


def _bat_impact(c: pd.DataFrame) -> Block:
    t = _top(c, c["W"] + c["X"], c["U"] > 0, 25)
    t = t.assign(
        Player=t["Player"], Balls=t["U"], Runs=t["V"], SR=100 * t["V"] / t["U"],
        **{"Scoring impact": t["W"], "Dismissal impact": t["X"],
           "Total impact": t["W"] + t["X"],
           "Impact / 100 balls": (100 * (t["W"] + t["X"]) / t["U"]).where(t["U"] >= 120)},
    )
    cols = ["Player", "Balls", "Runs", "SR", "Scoring impact", "Dismissal impact",
            "Total impact", "Impact / 100 balls"]
    return Block(
        key="imp_01", title="Batting impact — top 25", df=_ranked(t, cols),
        note="runs added v an average batter (scoring + dismissals)",
        fmt={"#": "{:.0f}", "Balls": "{:,.0f}", "Runs": "{:,.0f}", "SR": "{:,.1f}",
             "Scoring impact": SIGNED, "Dismissal impact": SIGNED,
             "Total impact": SIGNED, "Impact / 100 balls": SIGNED},
        bars=["Total impact"],
        good_high=["SR", "Scoring impact", "Dismissal impact", "Impact / 100 balls"],
        center={"Scoring impact": 0.0, "Dismissal impact": 0.0},
    )


def _bowl_impact(c: pd.DataFrame) -> Block:
    t = _top(c, c["AC"] + c["AD"], c["Z"] > 0, 25)
    t = t.assign(
        Overs=_overs(t["Z"]), Wkts=t["AB"], Econ=6 * t["AA"] / t["Z"],
        **{"Economy impact": t["AC"], "Wicket impact": t["AD"],
           "Total impact": t["AC"] + t["AD"],
           "Impact / 4 overs": (24 * (t["AC"] + t["AD"]) / t["Z"]).where(t["Z"] >= 120)},
    )
    cols = ["Player", "Overs", "Wkts", "Econ", "Economy impact", "Wicket impact",
            "Total impact", "Impact / 4 overs"]
    return Block(
        key="imp_02", title="Bowling impact — top 25", df=_ranked(t, cols),
        note="runs saved v an average bowler (economy + wickets)",
        fmt={"#": "{:.0f}", "Overs": "{:.1f}", "Wkts": "{:,.0f}", "Econ": "{:,.2f}",
             "Economy impact": SIGNED, "Wicket impact": SIGNED,
             "Total impact": SIGNED, "Impact / 4 overs": SIGNED},
        bars=["Total impact"],
        good_high=["Economy impact", "Wicket impact", "Impact / 4 overs"],
        good_low=["Econ"],
        center={"Economy impact": 0.0, "Wicket impact": 0.0},
    )


def _wicket_impact(c: pd.DataFrame) -> Block:
    t = _top(c, c["AF"], c["AB"] > 0, 15)
    t = t.assign(
        Wkts=t["AB"],
        **{"Top-order wkts (1–3)": t["AS"], "Set-batter wkts (20+ balls)": t["AT"],
           "Wicket value (runs)": t["AF"], "Value per wicket": t["AF"] / t["AB"],
           "Balls per wkt": t["Z"] / t["AB"]},
    )
    cols = ["Player", "Wkts", "Top-order wkts (1–3)", "Set-batter wkts (20+ balls)",
            "Wicket value (runs)", "Value per wicket", "Balls per wkt"]
    return Block(
        key="imp_03", title="Wicket-taking impact — top 15", df=_ranked(t, cols),
        note="runs taken off the opposition's expected total by the bowler's wickets",
        fmt={"#": "{:.0f}", "Wkts": "{:,.0f}", "Top-order wkts (1–3)": "{:,.0f}",
             "Set-batter wkts (20+ balls)": "{:,.0f}", "Wicket value (runs)": "{:,.1f}",
             "Value per wicket": "{:,.1f}", "Balls per wkt": "{:,.1f}"},
        good_high=["Value per wicket"], good_low=["Balls per wkt"],
    )


def _run_impact(c: pd.DataFrame) -> Block:
    t = _top(c, c["W"], c["U"] > 0, 15)
    t = t.assign(
        Runs=t["V"], SR=100 * t["V"] / t["U"],
        **{"Scoring impact": t["W"], "Runs in wins": t["AU"],
           "% runs in wins": (t["AU"] / t["V"].where(t["V"] > 0)),
           "50+ in wins": t["AV"], "Chase runs": t["AW"],
           "Chase SR": (100 * t["AW"] / t["AX"].where(t["AX"] > 0))},
    )
    cols = ["Player", "Runs", "SR", "Scoring impact", "Runs in wins", "% runs in wins",
            "50+ in wins", "Chase runs", "Chase SR"]
    return Block(
        key="imp_04", title="Run-scoring impact — top 15", df=_ranked(t, cols),
        note="scoring above par for the balls faced (before the cost of dismissals)",
        fmt={"#": "{:.0f}", "Runs": "{:,.0f}", "SR": "{:,.1f}", "Scoring impact": SIGNED,
             "Runs in wins": "{:,.0f}", "% runs in wins": "{:.1%}", "50+ in wins": "{:,.0f}",
             "Chase runs": "{:,.0f}", "Chase SR": "{:,.1f}"},
        good_high=["SR", "Chase SR"],
    )


def _o20_bat(c: pd.DataFrame) -> Block:
    t = _top(c, 100 * c["AJ"] / c["AI"].where(c["AI"] > 0), c["AI"] >= 15, 12)
    t = t.assign(
        Balls=t["AI"], Runs=t["AJ"],
        **{"Strike rate": 100 * t["AJ"] / t["AI"], "Sixes": t["AY"], "Dismissals": t["AZ"]},
    )
    cols = ["Player", "Balls", "Runs", "Strike rate", "Sixes", "Dismissals"]
    return Block(
        key="imp_05", title="Last over (20th) — best hitters", df=_ranked(t, cols),
        note="15+ balls faced in the 20th over, ranked by strike rate",
        fmt={"#": "{:.0f}", "Balls": "{:,.0f}", "Runs": "{:,.0f}", "Strike rate": "{:,.1f}",
             "Sixes": "{:,.0f}", "Dismissals": "{:,.0f}"},
        good_high=["Strike rate"],
    )


def _o20_bowl(c: pd.DataFrame) -> Block:
    t = _top(c, 6 * c["AM"] / c["AL"].where(c["AL"] > 0), c["AL"] >= 30, 12, largest=False)
    t = t.assign(Balls=t["AL"], Runs=t["AM"], Economy=6 * t["AM"] / t["AL"], Wickets=t["BA"])
    cols = ["Player", "Balls", "Runs", "Economy", "Wickets"]
    return Block(
        key="imp_06", title="Last over (20th) — best bowlers", df=_ranked(t, cols),
        note="30+ balls bowled in the 20th over, ranked by economy",
        fmt={"#": "{:.0f}", "Balls": "{:,.0f}", "Runs": "{:,.0f}", "Economy": "{:,.2f}",
             "Wickets": "{:,.0f}"},
        good_low=["Economy"],
    )


def _defences(span) -> Block:
    cols = ["Bowler of the 20th", "Attempts", "Defended", "Success %", "Avg runs to defend"]
    m = d.matches()
    bowlers = sorted(m["Final-over Bowler"].dropna().astype(str).unique())  # Calc!BI2:BI92
    f = _final_over(span)
    g = f.groupby("Final-over Bowler").agg(
        Attempts=("Match ID", "size"),
        Defended=("Final-over Defended", lambda s: int((s == 1).sum())),
        Need=("Need off 20th", "mean"),
    )
    c = pd.DataFrame({"Bowler of the 20th": bowlers})
    c = c.join(g, on="Bowler of the 20th")
    c[["Attempts", "Defended"]] = c[["Attempts", "Defended"]].fillna(0).astype(int)
    c["_key"] = c["Attempts"] + c["Defended"] / 100 + (np.arange(len(c)) + 2) / 1e9
    t = c[c["Attempts"] > 0].sort_values("_key", ascending=False).head(12)
    t = t.assign(**{"Success %": t["Defended"] / t["Attempts"],
                    "Avg runs to defend": t["Need"]})
    return Block(
        key="imp_07", title="Final-over defences — who holds their nerve",
        df=_ranked(t, cols),
        note="chases needing 15 or fewer off the 20th with wickets in hand",
        fmt={"#": "{:.0f}", "Attempts": "{:,.0f}", "Defended": "{:,.0f}",
             "Success %": "{:.1%}", "Avg runs to defend": "{:,.1f}"},
        rules={"Success %": {"good": (">=", 0.65), "bad": ("<=", 0.4)}},
    )


def _howto() -> Block:
    return Block(
        key="imp_howto", title="How to read", kind="text",
        text=(
            "Tables are ranked live for the span you pick; lists stop early when fewer players "
            "qualify. Thresholds: per-100-ball and per-4-over rates need 120+ balls.\n\n"
            "Top-order wickets = batters in positions 1–3; set-batter wickets = batters who had "
            "faced 20+ balls. Wicket value is not centred (it is the raw runs removed).\n\n"
            "Final-over defences: chases still alive at the start of the 20th over (not yet won, "
            "wickets in hand) needing 15 or fewer; the bowler is whoever bowled the first ball of "
            "the over."
        ),
    )


def build(span: tuple[int, int]) -> list[Block]:
    c = _calc(span)
    return [
        _intro(),
        _kpis(c, span),
        _bat_impact(c),
        _bowl_impact(c),
        _wicket_impact(c),
        _run_impact(c),
        _o20_bat(c),
        _o20_bowl(c),
        _defences(span),
        _howto(),
    ]
