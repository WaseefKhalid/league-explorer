"""Validate engine/impact.py against the PSL answer key.

Loads data/leagues/psl/ball.parquet, drops the five impact columns, rebuilds them
with engine.impact.add_impact and reports, per column: share of rows equal at
3 decimals, max abs difference and correlation; then player-level agreement
(career totals and top-25 rank overlap) against the key's ball table and
data/leagues/psl/player_seasons.parquet.

Run from the repo root:  python3 tests/check_engine_impact.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.impact import IMPACT_COLS, add_impact  # noqa: E402

DATA = ROOT / "data" / "leagues" / "psl"


def player_totals(b: pd.DataFrame) -> pd.DataFrame:
    """Career totals per player from a ball table with impact columns."""
    bat_run = b.groupby("Batter")["Bat Run Impact"].sum()
    exp_out = b.groupby("Batter")["Exp Out Cost"].sum()
    outs = b.groupby("Player Out")["Out Impact"].sum()
    bowl = b.groupby("Bowler")[["Bowl Run Impact", "Bowl Wkt Impact"]].sum()
    wv = (-b["Out Impact"] * b["Bowler Wkt"]).groupby(b["Bowler"]).sum()
    idx = bat_run.index.union(outs.index).union(bowl.index)
    t = pd.DataFrame(index=idx)
    t["Bat Run Impact"] = bat_run.reindex(idx).fillna(0)
    t["Bat Out Impact"] = outs.reindex(idx).fillna(0) - exp_out.reindex(idx).fillna(0)
    t["Bowl Run Impact"] = bowl["Bowl Run Impact"].reindex(idx).fillna(0)
    t["Bowl Wkt Impact"] = bowl["Bowl Wkt Impact"].reindex(idx).fillna(0)
    t["Wicket Value"] = wv.reindex(idx).fillna(0)
    t["Batting impact"] = t["Bat Run Impact"] + t["Bat Out Impact"]
    t["Bowling impact"] = t["Bowl Run Impact"] + t["Bowl Wkt Impact"]
    return t


def compare_players(mine: pd.DataFrame, ref: pd.DataFrame, label: str) -> bool:
    ok = True
    print(f"\nPlayer career totals vs {label}  ({len(ref)} players)")
    print(f"  {'column':<16} {'max |diff|':>10} {'mean |diff|':>11} {'corr':>9}")
    idx = ref.index.union(mine.index)
    for c in ["Bat Run Impact", "Bat Out Impact", "Bowl Run Impact", "Bowl Wkt Impact",
              "Wicket Value", "Batting impact", "Bowling impact"]:
        a = mine[c].reindex(idx).fillna(0)
        r = ref[c].reindex(idx).fillna(0)
        d = (a - r).abs()
        print(f"  {c:<16} {d.max():>10.3f} {d.mean():>11.4f} {np.corrcoef(a, r)[0, 1]:>9.6f}")
    for c in ["Batting impact", "Bowling impact"]:
        top_m = list(mine[c].sort_values(ascending=False, kind="mergesort").index[:25])
        top_r = list(ref[c].sort_values(ascending=False, kind="mergesort").index[:25])
        overlap = len(set(top_m) & set(top_r))
        same_order = sum(x == y for x, y in zip(top_m, top_r))
        print(f"  top-25 {c.lower():<15}: overlap {overlap}/25, same rank {same_order}/25")
        ok &= overlap == 25
    return ok


def main() -> int:
    key = pd.read_parquet(DATA / "ball.parquet")
    matches = pd.read_parquet(DATA / "matches.parquet")
    ball = key.drop(columns=IMPACT_COLS)

    t0 = time.time()
    got = add_impact(ball, matches)
    secs = time.time() - t0

    ok = True
    print(f"add_impact: {len(got):,} rows in {secs:.1f}s")
    if list(got.columns) != list(key.columns):
        print("COLUMN ORDER MISMATCH:", list(got.columns)[-6:], "vs", list(key.columns)[-6:])
        ok = False
    bad_dtype = [c for c in IMPACT_COLS if got[c].dtype != key[c].dtype]
    if bad_dtype:
        print("DTYPE MISMATCH:", bad_dtype)
        ok = False
    if not got[ball.columns].equals(ball):
        print("INPUT COLUMNS WERE CHANGED")
        ok = False

    print(f"\n  {'column':<16} {'equal@3dp':>10} {'rows off':>8} {'max |diff|':>10} {'corr':>10}")
    for c in IMPACT_COLS:
        d = (got[c] - key[c]).abs()
        eq = d < 0.0005
        print(f"  {c:<16} {eq.mean():>10.4%} {int((~eq).sum()):>8} {d.max():>10.4f} "
              f"{np.corrcoef(got[c], key[c])[0, 1]:>10.7f}")
        ok &= bool(d.max() <= 0.0010001)

    mine = player_totals(got)
    ok &= compare_players(mine, player_totals(key), "key ball table (rounded per-ball values)")

    ps = pd.read_parquet(DATA / "player_seasons.parquet")
    ref = ps.groupby("Player")[["Bat Run Impact", "Bat Out Impact", "Bowl Run Impact",
                                "Bowl Wkt Impact", "Wicket Value"]].sum()
    ref["Batting impact"] = ref["Bat Run Impact"] + ref["Bat Out Impact"]
    ref["Bowling impact"] = ref["Bowl Run Impact"] + ref["Bowl Wkt Impact"]
    # the workbook summed UNROUNDED per-ball values into player_seasons
    raw = add_impact(ball, matches, decimals=None)
    ok &= compare_players(player_totals(raw), ref,
                          "player_seasons.parquet (workbook sums; mine unrounded, decimals=None)")

    print("\nPlayer-season sums of unrounded values (decimals=None) vs player_seasons.parquet")
    ps_idx = ps.set_index(["Player", "Season"])
    bat_run = raw.groupby(["Batter", "Season"])["Bat Run Impact"].sum()
    exp_out = raw.groupby(["Batter", "Season"])["Exp Out Cost"].sum()
    outs = raw.groupby(["Player Out", "Season"])["Out Impact"].sum()
    outs.index.names = exp_out.index.names
    ix = exp_out.index.union(outs.index)
    sums = {
        "Bat Run Impact": bat_run,
        "Bat Out Impact": outs.reindex(ix).fillna(0) - exp_out.reindex(ix).fillna(0),
        "Bowl Run Impact": raw.groupby(["Bowler", "Season"])["Bowl Run Impact"].sum(),
        "Bowl Wkt Impact": raw.groupby(["Bowler", "Season"])["Bowl Wkt Impact"].sum(),
        "Wicket Value": (-raw["Out Impact"] * raw["Bowler Wkt"]).groupby([raw["Bowler"], raw["Season"]]).sum(),
    }
    print(f"  {'column':<16} {'equal@3dp':>10} {'rows off':>8} {'max |diff|':>10}")
    for c, s in sums.items():
        s.index.names = ["Player", "Season"]
        d = (s.reindex(ps_idx.index).fillna(0).round(3) - ps_idx[c]).abs()
        print(f"  {c:<16} {(d < 0.0005).mean():>10.4%} {int((d >= 0.0005).sum()):>8} {d.max():>10.4f}")
        ok &= bool(d.max() <= 0.0010001)

    print("\nRESULT:", "PASS (every value within 0.001, top-25 lists identical)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
