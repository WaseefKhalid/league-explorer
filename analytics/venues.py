"""
Venues sheet — how each ground plays (scoring, chasing, toss, pace v spin).

Mirrors the workbook's "Venues" sheet:
  §01 Ground profiles in the selected span  (+ §03 chart "Average first-innings
      score — selected span", attached to this block)
  §02 Average first-innings score by venue and season (heat map; every season
      is shown, seasons outside the span are greyed)
  How to read (footnotes)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analytics.data as d
from analytics.blocks import Block

PROFILE_COLS = ["Venue", "City", "Host", "Matches", "Seasons hosted", "Avg 1st-inns",
                "Highest", "Chase win %", "Toss → bowl %", "Toss winner won %",
                "Run rate", "PP", "MO1", "MO2", "Death", "Boundary %", "Sixes / match",
                "Pace econ", "Spin econ", "Pace balls / wkt", "Spin balls / wkt",
                "Spin share"]

PROFILE_FMT = {
    "Matches": "{:,.0f}", "Avg 1st-inns": "{:,.1f}", "Highest": "{:,.0f}",
    "Chase win %": "{:.1%}", "Toss → bowl %": "{:.1%}", "Toss winner won %": "{:.1%}",
    "Run rate": "{:,.2f}", "PP": "{:,.2f}", "MO1": "{:,.2f}", "MO2": "{:,.2f}",
    "Death": "{:,.2f}", "Boundary %": "{:.1%}", "Sixes / match": "{:,.1f}",
    "Pace econ": "{:,.2f}", "Spin econ": "{:,.2f}", "Pace balls / wkt": "{:,.1f}",
    "Spin balls / wkt": "{:,.1f}", "Spin share": "{:.1%}",
}

ALL_LABEL = "All venues"
_BALL_SUMS = ["Total Runs", "Bowler Runs", "Legal Ball", "Ball Faced", "Four", "Six", "Bowler Wkt"]


# ── cached, span-independent helpers ─────────────────────────────────────────
@d.per_league()
def _venue_meta() -> pd.DataFrame:
    """Venue list (alphabetical, every venue that ever hosted), City, Host and
    'Seasons hosted' (first–last season, all time — static text in the workbook)."""
    m = d.matches()
    m = m[m["Season"] > 0]
    g = m.groupby("Venue", sort=True)
    meta = pd.DataFrame({
        "City": g["City"].first(),
        "Host": g["Host"].first(),
        "first": g["Season"].min(),
        "last": g["Season"].max(),
    })
    meta["Seasons hosted"] = [
        f"{a}–{b}" if a != b else f"{a}" for a, b in zip(meta["first"], meta["last"])
    ]
    meta.attrs["all_hosted"] = f"{int(m['Season'].min())}–{int(m['Season'].max())}"
    return meta


@d.per_league()
def _ball_cube() -> pd.DataFrame:
    """Ball Data summed by Season x Venue x Phase x Pace/Spin (small, cached)."""
    b = d.ball()
    return (b.groupby(["Season", "Venue", "Phase", "Pace/Spin"], observed=True, dropna=False)
             [_BALL_SUMS].sum().reset_index())


@d.per_league()
def _heat_values() -> pd.DataFrame:
    """AVERAGEIFS(md_inn1, venue, season, md_full1=1) for every venue x season."""
    m = d.matches()
    full = m[m["Full 1st Inns"] == 1]
    grid = full.pivot_table(index="Venue", columns="Season", values="1st Inns Runs",
                            aggfunc="mean")
    return grid


def _div(a, b, scale=1.0):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a * scale / b
    out[~np.isfinite(out)] = np.nan
    return out


# ── §01 ──────────────────────────────────────────────────────────────────────
def _profiles(span: tuple[int, int]) -> pd.DataFrame:
    lo, hi = min(span), max(span)
    meta = _venue_meta()
    venues = list(meta.index)
    keys = venues + [ALL_LABEL]

    # Match Data part
    m = d.matches()
    m = m[(m["Season"] >= lo) & (m["Season"] <= hi)]
    mv = pd.DataFrame({
        "Venue": m["Venue"],
        "match": (m["Season"] > 0).astype(int),
        "full_inn1": m["1st Inns Runs"].where(m["Full 1st Inns"] == 1),
        "full1": (m["Full 1st Inns"] == 1).astype(int),
        "hi1": m["1st Inns Runs"].where(m["Season"] > 0),
        "hi2": m["2nd Inns Runs"].where(m["Season"] > 0),
        "dec": (m["Decided (no DLS)"] == 1).astype(int),
        "chase_won": ((m["Decided (no DLS)"] == 1) & (m["Bat First Won"] == 0)).astype(int),
        "field": (m["Toss Decision"] == "Field").astype(int),
        "tw1": (m["Toss Winner Won"] == 1).astype(int),
        "tw0": (m["Toss Winner Won"] == 0).astype(int),
    })
    sums = mv.groupby("Venue")[["match", "full1", "dec", "chase_won", "field", "tw1", "tw0"]].sum()
    inn_sum = mv.groupby("Venue")["full_inn1"].sum()
    top = mv.groupby("Venue")[["hi1", "hi2"]].max().max(axis=1)
    sums["inn_sum"] = inn_sum
    sums["hi"] = top
    tot = sums[["match", "full1", "dec", "chase_won", "field", "tw1", "tw0", "inn_sum"]].sum()
    tot["hi"] = top.max() if len(top) else np.nan
    sums.loc[ALL_LABEL] = tot
    sums = sums.reindex(keys)
    sums[["match", "full1", "dec", "chase_won", "field", "tw1", "tw0", "inn_sum"]] = (
        sums[["match", "full1", "dec", "chase_won", "field", "tw1", "tw0", "inn_sum"]].fillna(0))

    # Ball Data part
    cube = _ball_cube()
    c = cube[(cube["Season"] >= lo) & (cube["Season"] <= hi)]
    by_v = c.groupby("Venue")[_BALL_SUMS].sum()
    by_v.loc[ALL_LABEL] = c[_BALL_SUMS].sum()
    by_v = by_v.reindex(keys).fillna(0)

    ph = c.groupby(["Venue", "Phase"])[["Total Runs", "Legal Ball"]].sum().unstack("Phase")
    ph_all = c.groupby("Phase")[["Total Runs", "Legal Ball"]].sum()
    for col in ["Total Runs", "Legal Ball"]:
        for p in d.PHASES:
            if (col, p) not in ph.columns:
                ph[(col, p)] = 0
    ph = ph.reindex(keys).fillna(0)
    for p in d.PHASES:
        for col in ["Total Runs", "Legal Ball"]:
            ph.loc[ALL_LABEL, (col, p)] = ph_all[col].get(p, 0) if len(ph_all) else 0

    ps = c.groupby(["Venue", "Pace/Spin"])[["Bowler Runs", "Legal Ball", "Bowler Wkt"]].sum().unstack("Pace/Spin")
    ps_all = c.groupby("Pace/Spin")[["Bowler Runs", "Legal Ball", "Bowler Wkt"]].sum()
    for col in ["Bowler Runs", "Legal Ball", "Bowler Wkt"]:
        for k in ["Pace", "Spin"]:
            if (col, k) not in ps.columns:
                ps[(col, k)] = 0
    ps = ps.reindex(keys).fillna(0)
    for col in ["Bowler Runs", "Legal Ball", "Bowler Wkt"]:
        for k in ["Pace", "Spin"]:
            ps.loc[ALL_LABEL, (col, k)] = ps_all[col].get(k, 0) if len(ps_all) else 0

    matches_n = sums["match"].to_numpy(dtype=float)
    out = pd.DataFrame({
        "Venue": keys,
        "City": list(meta["City"]) + [""],
        "Host": list(meta["Host"]) + [""],
        "Matches": sums["match"].to_numpy(dtype=float),
        "Seasons hosted": list(meta["Seasons hosted"]) + [meta.attrs["all_hosted"]],
        "Avg 1st-inns": _div(sums["inn_sum"], sums["full1"]),
        "Highest": np.where(matches_n > 0, sums["hi"].to_numpy(dtype=float), np.nan),
        "Chase win %": _div(sums["chase_won"], sums["dec"]),
        "Toss → bowl %": _div(sums["field"], sums["match"]),
        "Toss winner won %": _div(sums["tw1"], sums["tw1"] + sums["tw0"]),
        "Run rate": _div(by_v["Total Runs"], by_v["Legal Ball"], 6),
    })
    for p in d.PHASES:
        out[p] = _div(ph[("Total Runs", p)], ph[("Legal Ball", p)], 6)
    out["Boundary %"] = _div(by_v["Four"] + by_v["Six"], by_v["Ball Faced"])
    out["Sixes / match"] = _div(by_v["Six"], sums["match"])
    out["Pace econ"] = _div(ps[("Bowler Runs", "Pace")], ps[("Legal Ball", "Pace")], 6)
    out["Spin econ"] = _div(ps[("Bowler Runs", "Spin")], ps[("Legal Ball", "Spin")], 6)
    out["Pace balls / wkt"] = _div(ps[("Legal Ball", "Pace")], ps[("Bowler Wkt", "Pace")])
    out["Spin balls / wkt"] = _div(ps[("Legal Ball", "Spin")], ps[("Bowler Wkt", "Spin")])
    out["Spin share"] = _div(ps[("Legal Ball", "Spin")], by_v["Legal Ball"])
    out = out[PROFILE_COLS].reset_index(drop=True)
    out["Matches"] = out["Matches"].astype(int)
    return out


# ── §02 ──────────────────────────────────────────────────────────────────────
def _heat(span: tuple[int, int]):
    lo, hi = min(span), max(span)
    venues = list(_venue_meta().index)
    seasons = list(d.seasons())
    g = _heat_values().reindex(index=venues, columns=seasons)
    df = pd.DataFrame({"Venue": venues})
    for s in seasons:
        df[str(s)] = g[s].to_numpy(dtype=float)
    season_cols = [str(s) for s in seasons]
    greyed = [str(s) for s in seasons if s < lo or s > hi]
    vals = df[season_cols].to_numpy(dtype=float)
    mid = float(np.nanmedian(vals)) if np.isfinite(vals).any() else np.nan
    return df, season_cols, greyed, mid


def _span_text(cols: list[str]) -> str:
    """'2016–2019, 2026' style text for a list of season strings."""
    ys = sorted(int(c) for c in cols)
    runs, start, prev = [], None, None
    for y in ys:
        if start is None:
            start = prev = y
        elif y == prev + 1:
            prev = y
        else:
            runs.append((start, prev))
            start = prev = y
    if start is not None:
        runs.append((start, prev))
    return ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in runs)


# ── build ────────────────────────────────────────────────────────────────────
def build(span: tuple[int, int]) -> list[Block]:
    lo, hi = min(span), max(span)
    blocks: list[Block] = []

    # §01 Ground profiles (+ §03 chart)
    prof = _profiles(span)
    all_idx = prof.index[prof["Venue"] == ALL_LABEL].tolist()
    chart_df = prof.loc[prof["Venue"] != ALL_LABEL, ["Venue", "Avg 1st-inns"]].reset_index(drop=True)
    blocks.append(Block(
        key="ven_01",
        title="Ground profiles in the selected span",
        df=prof,
        note=("Run rate by phase: PP · MO1 · MO2 · Death.  Pace v spin: Pace econ · "
              "Spin econ · Pace balls / wkt · Spin balls / wkt · Spin share."),
        rules={
            "Chase win %": {"good": (">=", 0.60), "bad": ("<=", 0.45)},
            "Toss winner won %": {"good": (">=", 0.60), "bad": ("<=", 0.45)},
        },
        fmt=dict(PROFILE_FMT),
        bold_rows=all_idx,
        chart={
            "type": "hbar",
            "x": "Venue",
            "y": "Avg 1st-inns",
            "title": "Average first-innings score — selected span",
            "labels": {"Avg 1st-inns": "Avg 1st-inns"},
            "color": "green",
            "data": chart_df,
        },
    ))

    # §02 Heat map
    heat, season_cols, greyed, mid = _heat(span)
    note = "completed first innings · seasons outside your span are greyed"
    if greyed:
        note += f" (greyed: {_span_text(greyed)})"
    in_span_cols = [c for c in season_cols if c not in greyed]
    blk = Block(
        key="ven_02",
        title="Average first-innings score by venue and season",
        df=heat,
        note=note,
        kind="matrix",
        # Workbook: 3-colour scale (min → 50th percentile → max, light → dark
        # green) over the whole grid; greyed seasons get a grey fill instead.
        good_high=in_span_cols,
        center={c: mid for c in in_span_cols} if np.isfinite(mid) else {},
        fmt={c: "{:,.0f}" for c in season_cols},
    )
    blk.muted_cols = greyed  # extra hint for the renderer: greyed season columns
    blocks.append(blk)

    # How to read
    blocks.append(Block(
        key="ven_howto",
        title="How to read",
        kind="text",
        text=("Every table follows the Seasons box at the top (the heat map always shows "
              "each season, greying those outside your span).\n\n"
              "Run rates include extras. Pace / spin economy uses runs charged to the "
              "bowler. Balls / wkt = legal balls per bowler wicket.\n\n"
              "Chase win % and toss-winner tints: green ≥ 60%, pink ≤ 45%. Heat map: "
              "darker green = higher average first-innings score."),
    ))
    return blocks
