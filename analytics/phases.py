"""
Phases sheet — PP (overs 1–6) · MO1 (7–10) · MO2 (11–16) · Death (17–20).

Mirrors the workbook's "Phases" sheet:
  §01 Phase trends by season (+ "Selected span" / "All seasons" rows)
  §02 Over by over — selected span v all seasons (+ line chart)
  §03 Economy by bowling type and phase
  §04 Balls per wicket by bowling type and phase
  §05 Share of each phase bowled by each type
  §06 Batter hand v bowling type
  How to read (footnotes)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analytics.data as d
from analytics.blocks import Block

PHASE_HEAD = {"PP": "PP Overs 1–6", "MO1": "MO1 Overs 7–10",
              "MO2": "MO2 Overs 11–16", "Death": "Death Overs 17–20"}
OVER_PHASE = {o: ("PP" if o <= 6 else "MO1" if o <= 10 else "MO2" if o <= 16 else "Death")
              for o in range(1, 21)}
ALL_TYPES = "All types"

_SUMS = ["Total Runs", "Bowler Runs", "Bat Runs", "Legal Ball", "Ball Faced", "Four",
         "Six", "Wicket", "Bowler Wkt", "Bowl Dot", "Bat Dot"]


@d.per_league()
def _cube() -> pd.DataFrame:
    """Ball Data summed by Season x Over x Phase x Bowler Type x Pace/Spin x
    Bat Hand. Span-independent and small (a few thousand rows), so every
    table below is a cheap groupby on it."""
    b = d.ball()
    return (b.groupby(["Season", "Over", "Phase", "Bowler Type", "Pace/Spin", "Bat Hand"],
                      observed=True, dropna=False)[_SUMS].sum().reset_index())


def _div(a, b, scale=1.0):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a * scale / b
    out[~np.isfinite(out)] = np.nan
    return out


def _sum_by(c: pd.DataFrame, keys, cols, index=None) -> pd.DataFrame:
    """groupby-sum that always returns every requested index row (zeros if absent)."""
    g = c.groupby(keys, observed=True)[cols].sum()
    if index is not None:
        g = g.reindex(index, fill_value=0)
    return g


# ── §01 Phase trends by season ───────────────────────────────────────────────
def _phase_stats(g: pd.DataFrame, spin: pd.Series) -> dict[str, np.ndarray]:
    """g: sums per row-key for one phase; spin: spin legal balls per row-key."""
    return {
        "Run rate": _div(g["Total Runs"], g["Legal Ball"], 6),
        "Balls/wkt": _div(g["Legal Ball"], g["Wicket"]),
        "Bdry %": _div(g["Four"] + g["Six"], g["Ball Faced"]),
        "Spin %": _div(spin, g["Legal Ball"]),
    }


def _trends(span):
    lo, hi = min(span), max(span)
    cube = _cube()
    seasons = list(d.seasons())
    cols = ["Total Runs", "Legal Ball", "Wicket", "Four", "Six", "Ball Faced"]

    by = cube.groupby(["Season", "Phase"], observed=True)[cols].sum()
    spin = cube[cube["Pace/Spin"] == "Spin"].groupby(["Season", "Phase"], observed=True)["Legal Ball"].sum()
    in_span = cube[(cube["Season"] >= lo) & (cube["Season"] <= hi)]
    by_span = in_span.groupby("Phase", observed=True)[cols].sum()
    spin_span = in_span[in_span["Pace/Spin"] == "Spin"].groupby("Phase", observed=True)["Legal Ball"].sum()
    by_all = cube.groupby("Phase", observed=True)[cols].sum()
    spin_all = cube[cube["Pace/Spin"] == "Spin"].groupby("Phase", observed=True)["Legal Ball"].sum()

    labels = seasons + ["Selected span", "All seasons"]
    df = pd.DataFrame({"Season": pd.Series(labels, dtype=object)})
    for p in d.PHASES:
        rows = pd.MultiIndex.from_product([seasons, [p]], names=["Season", "Phase"])
        g = by.reindex(rows, fill_value=0)
        s = spin.reindex(rows, fill_value=0)
        g_span = by_span.reindex([p], fill_value=0)
        g_all = by_all.reindex([p], fill_value=0)
        stacked = pd.concat([g.reset_index(drop=True), g_span.reset_index(drop=True),
                             g_all.reset_index(drop=True)], ignore_index=True)
        spins = np.concatenate([s.to_numpy(dtype=float),
                                [float(spin_span.get(p, 0))], [float(spin_all.get(p, 0))]])
        for name, vals in _phase_stats(stacked, spins).items():
            df[f"{p} {name}"] = vals
    return df, seasons


# ── §02 Over by over ─────────────────────────────────────────────────────────
def _overs(span):
    lo, hi = min(span), max(span)
    cube = _cube()
    overs = list(range(1, 21))
    cols = ["Total Runs", "Legal Ball", "Wicket", "Four", "Six", "Ball Faced", "Bowl Dot"]
    c = cube[(cube["Season"] >= lo) & (cube["Season"] <= hi)]
    g = _sum_by(c, "Over", cols, overs)
    spin = c[c["Pace/Spin"] == "Spin"].groupby("Over")["Legal Ball"].sum().reindex(overs, fill_value=0)
    g_all = _sum_by(cube, "Over", ["Total Runs", "Legal Ball"], overs)
    return pd.DataFrame({
        "Over": overs,
        "Phase": [OVER_PHASE[o] for o in overs],
        "Runs / over": _div(g["Total Runs"], g["Legal Ball"], 6),
        "Wkts / over": _div(g["Wicket"], g["Legal Ball"], 6),
        "Boundary %": _div(g["Four"] + g["Six"], g["Ball Faced"]),
        "Dot %": _div(g["Bowl Dot"], g["Legal Ball"]),
        "Spin share": _div(spin, g["Legal Ball"]),
        "RPO — all seasons": _div(g_all["Total Runs"], g_all["Legal Ball"], 6),
    })


# ── §03–§05 Bowling type x phase ─────────────────────────────────────────────
def _type_phase(span):
    lo, hi = min(span), max(span)
    cube = _cube()
    c = cube[(cube["Season"] >= lo) & (cube["Season"] <= hi) & (cube["Bowler Type"] != "Unknown")]
    cols = ["Bowler Runs", "Legal Ball", "Bowler Wkt"]
    idx = pd.MultiIndex.from_product([d.BOWL_TYPES, d.PHASES], names=["Bowler Type", "Phase"])
    g = c.groupby(["Bowler Type", "Phase"], observed=True)[cols].sum().reindex(idx, fill_value=0)
    tot = c.groupby("Phase", observed=True)[cols].sum().reindex(d.PHASES, fill_value=0)

    econ = pd.DataFrame({"Bowling type": d.BOWL_TYPES + [ALL_TYPES]})
    bpw = pd.DataFrame({"Bowling type": d.BOWL_TYPES + [ALL_TYPES]})
    share = pd.DataFrame({"Bowling type": list(d.BOWL_TYPES)})
    for p in d.PHASES:
        gp = g.xs(p, level="Phase").reindex(d.BOWL_TYPES)
        runs = np.append(gp["Bowler Runs"].to_numpy(dtype=float), tot.loc[p, "Bowler Runs"])
        legal = np.append(gp["Legal Ball"].to_numpy(dtype=float), tot.loc[p, "Legal Ball"])
        wk = np.append(gp["Bowler Wkt"].to_numpy(dtype=float), tot.loc[p, "Bowler Wkt"])
        econ[PHASE_HEAD[p]] = _div(runs, legal, 6)
        bpw[PHASE_HEAD[p]] = _div(legal, wk)
        share[PHASE_HEAD[p]] = _div(gp["Legal Ball"], np.full(len(d.BOWL_TYPES), tot.loc[p, "Legal Ball"]))
    return econ, bpw, share


def _vs_all_rule(df: pd.DataFrame, cols: list[str]) -> dict:
    """Workbook CF: green if <= All-types row x 0.95, pink if >= x 1.05 (lower
    is better for the bowler). The All-types row itself is not tinted in the
    workbook, so its thresholds are NaN."""
    is_all = df["Bowling type"] == ALL_TYPES
    rules = {}
    for col in cols:
        ref = df.loc[is_all, col]
        ref = float(ref.iloc[0]) if len(ref) else np.nan
        good = pd.Series(ref * 0.95, index=df.index).where(~is_all)
        bad = pd.Series(ref * 1.05, index=df.index).where(~is_all)
        rules[col] = {"good": ("<=", good), "bad": (">=", bad)}
    return rules


# ── §06 Batter hand v bowling type ───────────────────────────────────────────
def _hand_type(span):
    lo, hi = min(span), max(span)
    cube = _cube()
    c = cube[(cube["Season"] >= lo) & (cube["Season"] <= hi)]
    cols = ["Ball Faced", "Bat Runs", "Bowler Wkt", "Bat Dot", "Four", "Six"]
    idx = pd.MultiIndex.from_product([d.HANDS, d.BOWL_TYPES], names=["Bat Hand", "Bowler Type"])
    g = c.groupby(["Bat Hand", "Bowler Type"], observed=True)[cols].sum().reindex(idx, fill_value=0)
    known = c[(c["Bowler Type"] != "Unknown") & (c["Bat Hand"] != "Unknown")]
    avg_sr = float(_div([known["Bat Runs"].sum()], [known["Ball Faced"].sum()], 100)[0])
    df = pd.DataFrame({
        "Batter hand": [h for h, _ in idx],
        "Bowling type": [t for _, t in idx],
        "Balls": g["Ball Faced"].to_numpy(dtype=int),
        "Strike rate": _div(g["Bat Runs"], g["Ball Faced"], 100),
        "Balls / wkt": _div(g["Ball Faced"], g["Bowler Wkt"]),
        "Dot %": _div(g["Bat Dot"], g["Ball Faced"]),
        "Boundary %": _div(g["Four"] + g["Six"], g["Ball Faced"]),
    })
    return df, avg_sr


# ── build ────────────────────────────────────────────────────────────────────
def build(span: tuple[int, int]) -> list[Block]:
    lo, hi = min(span), max(span)
    blocks: list[Block] = []

    # §01
    tr, seasons = _trends(span)
    is_season = tr.index[: len(seasons)]
    muted = [i for i, s in zip(is_season, seasons) if s < lo or s > hi]
    bold = tr.index[tr["Season"].isin(["Selected span", "All seasons"])].tolist()
    tr_fmt = {}
    for p in d.PHASES:
        tr_fmt[f"{p} Run rate"] = "{:,.2f}"
        tr_fmt[f"{p} Balls/wkt"] = "{:,.1f}"
        tr_fmt[f"{p} Bdry %"] = "{:.1%}"
        tr_fmt[f"{p} Spin %"] = "{:.1%}"
    # Workbook: green colour scale (min → 50th pct → max) on each phase's run
    # rate over the season rows → good_high centred on that median.
    rr_cols = [f"{p} Run rate" for p in d.PHASES]
    center = {}
    for col in rr_cols:
        vals = tr.loc[is_season, col].to_numpy(dtype=float)
        if np.isfinite(vals).any():
            center[col] = float(np.nanmedian(vals))
    blocks.append(Block(
        key="ph_01",
        title="Phase trends by season",
        df=tr,
        note='seasons outside your span are greyed · "Selected span" adds them up',
        good_high=rr_cols,
        center=center,
        fmt=tr_fmt,
        muted_rows=muted,
        bold_rows=bold,
    ))

    # §02
    ov = _overs(span)
    rpo = ov["Runs / over"].to_numpy(dtype=float)
    blocks.append(Block(
        key="ph_02",
        title="Over by over — selected span v all seasons",
        df=ov,
        good_high=["Runs / over"],
        center={"Runs / over": float(np.nanmedian(rpo))} if np.isfinite(rpo).any() else {},
        bars=["Wkts / over"],
        fmt={"Runs / over": "{:,.2f}", "Wkts / over": "{:,.2f}", "Boundary %": "{:.1%}",
             "Dot %": "{:.1%}", "Spin share": "{:.1%}", "RPO — all seasons": "{:,.2f}"},
        chart={
            "type": "line",
            "x": "Over",
            "y": ["RPO — all seasons", "Runs / over"],
            "title": "Runs per over, over by over",
            "labels": {"RPO — all seasons": "All seasons", "Runs / over": "Selected span",
                       "Over": "Over"},
            "color": "green",
        },
    ))

    # §03–§05
    econ, bpw, share = _type_phase(span)
    ph_cols = [PHASE_HEAD[p] for p in d.PHASES]
    all_idx = econ.index[econ["Bowling type"] == ALL_TYPES].tolist()
    blocks.append(Block(
        key="ph_03",
        title="Economy by bowling type and phase",
        df=econ,
        note="selected span",
        rules=_vs_all_rule(econ, ph_cols),
        fmt={c: "{:,.2f}" for c in ph_cols},
        bold_rows=all_idx,
    ))
    blocks.append(Block(
        key="ph_04",
        title="Balls per wicket by bowling type and phase",
        df=bpw,
        note="selected span",
        rules=_vs_all_rule(bpw, ph_cols),
        fmt={c: "{:,.1f}" for c in ph_cols},
        bold_rows=all_idx,
    ))
    blocks.append(Block(
        key="ph_05",
        title="Share of each phase bowled by each type",
        df=share,
        note="selected span",
        bars=list(ph_cols),
        fmt={c: "{:.1%}" for c in ph_cols},
    ))

    # §06
    ht, avg_sr = _hand_type(span)
    blocks.append(Block(
        key="ph_06",
        title="Batter hand v bowling type",
        df=ht,
        note="selected span · strike rate, balls per bowler wicket, dot %, boundary %",
        rules={"Strike rate": {"good": ("<=", avg_sr * 0.93), "bad": (">=", avg_sr * 1.02)}}
        if np.isfinite(avg_sr) else {},
        fmt={"Balls": "{:,.0f}", "Strike rate": "{:,.1f}", "Balls / wkt": "{:,.1f}",
             "Dot %": "{:.1%}", "Boundary %": "{:.1%}"},
    ))

    # How to read
    blocks.append(Block(
        key="ph_howto",
        title="How to read",
        kind="text",
        text=("Every table follows the Seasons box at the top. Run rates include extras; "
              "economy uses runs charged to the bowler (wides and no-balls included).\n\n"
              + ("Balls / wkt = legal balls per wicket (bowler wickets in the type tables). "
                 "Type tints compare each type with the \"All types\" row: green = 5%+ better "
                 "for the bowler.\n\n"
                 "Hand v type: green = strike rate 7%+ below the span average (bowler wins the "
                 "matchup), pink = 2%+ above." if d.has("has_hand_type") else
                 "Balls / wkt = legal balls per wicket.")),
    ))
    return blocks
