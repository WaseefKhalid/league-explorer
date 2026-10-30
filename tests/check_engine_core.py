"""Compare engine core tables built from raw/psl_male_csv2.zip with the PSL workbook data.

    python3 tests/check_engine_core.py [table ...]
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from engine.cricsheet import read_zip  # noqa: E402
from engine.core import build_core  # noqa: E402

KEYS = {
    "matches": ["Match ID"],
    "ball": None,                      # same row order
    "team_matches": ["Match ID", "Team"],
    "bat_inns": ["Match ID", "Innings", "Batter"],
    "bowl_inns": ["Match ID", "Innings", "Bowler"],
    "partnerships": ["Match ID", "Innings", "Wicket"],
    "pair_seasons": ["Batter", "Bowler", "Season"],
}
SKIP = {"ball": ["Bat Run Impact", "Exp Out Cost", "Out Impact", "Bowl Run Impact", "Bowl Wkt Impact"]}


def same(a: pd.Series, b: pd.Series) -> pd.Series:
    an, bn = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
    both_num = an.notna() & bn.notna()
    eq = pd.Series(False, index=a.index)
    eq[both_num] = np.isclose(an[both_num].astype(float), bn[both_num].astype(float), atol=1e-6)
    both_na = a.isna() & b.isna()
    txt = ~both_num & ~both_na
    eq[txt] = a[txt].astype(str) == b[txt].astype(str)
    return eq | both_na


def compare(name: str, mine: pd.DataFrame, key: pd.DataFrame) -> bool:
    keys = KEYS[name]
    print(f"\n=== {name}: mine {mine.shape} · answer key {key.shape}")
    cols_missing = [c for c in key.columns if c not in mine.columns and c not in SKIP.get(name, [])]
    extra = [c for c in mine.columns if c not in key.columns]
    if cols_missing:
        print("  MISSING columns:", cols_missing)
    if extra:
        print("  extra columns:", extra)
    if list(mine.columns) != [c for c in key.columns if c in mine.columns]:
        print("  column ORDER differs")
    if keys:
        a = mine.set_index(keys)
        b = key.set_index(keys)
        only_mine, only_key = a.index.difference(b.index), b.index.difference(a.index)
        if len(only_mine) or len(only_key):
            print(f"  rows only in mine: {len(only_mine)}  only in key: {len(only_key)}  e.g. {list(only_key[:3])}")
        common = a.index.intersection(b.index)
        a, b = a.loc[common], b.loc[common]
        if not mine.set_index(keys).index.equals(key.set_index(keys).index):
            print("  row ORDER differs")
    else:
        a, b = mine.reset_index(drop=True), key.reset_index(drop=True)
    ok = True
    for c in key.columns:
        if c in SKIP.get(name, []) or c not in a.columns or (keys and c in keys):
            continue
        eq = same(a[c], b[c])
        rate = eq.mean()
        if rate < 1:
            ok = False
            bad = eq[~eq].index[:3]
            ex = [(i, a.at[i, c], b.at[i, c]) for i in bad]
            print(f"  {c:28s} {rate:8.4%}  e.g. (mine, key): {ex}")
    if ok and not cols_missing:
        print("  ALL MATCH")
    return ok


if __name__ == "__main__":
    want = sys.argv[1:] or list(KEYS)
    t = time.time()
    dl, infos, people = read_zip("raw/psl_male_csv2.zip")
    import json
    ov = json.load(open("engine/overrides/psl.json"))
    reg = pd.read_parquet("data/registry/players_meta.parquet")
    tables = build_core(dl, infos, people, registry=reg, overrides=ov)
    print(f"built in {time.time() - t:.1f}s")
    for n in want:
        if n in tables:
            compare(n, tables[n], pd.read_parquet(f"data/leagues/psl/{n}.parquet"))
        else:
            print(f"\n=== {n}: not built yet")
