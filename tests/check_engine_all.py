"""End to end: build the PSL from raw/psl_male_csv2.zip with build_league and compare every table with
the PSL answer keys (data/leagues/psl). Known, documented differences are listed by the per-part checks."""
from __future__ import annotations

import sys
import time

import pandas as pd

sys.path.insert(0, ".")
from engine import build_league  # noqa: E402
from tests.check_engine_core import compare, KEYS, same  # noqa: E402

t = time.time()
tables, meta = build_league("raw/psl_male_csv2.zip", name="Pakistan Super League", short="PSL",
                            progress=lambda f, s: print(f"  {f:4.0%} {s}  ({time.time() - t:.0f}s)"))
print({k: v for k, v in meta.items() if k != "seasons"})
KEYS.update({"player_seasons": ["Player", "Season"], "players": ["Player"], "lists": None})
for name in ["matches", "ball", "team_matches", "bat_inns", "bowl_inns", "pair_seasons", "player_seasons", "players",
             "lists"]:
    key = pd.read_parquet(f"data/leagues/psl/{name}.parquet")
    if name == "ball":
        import tests.check_engine_core as c
        c.SKIP["ball"] = []
    compare(name, tables[name], key)
mvp = [k for k in tables if k.startswith("mvp/")]
print("\nMVP tables built:", mvp)
for k in mvp:
    key = pd.read_parquet(f"data/leagues/psl/{k}.parquet")
    print(f"  {k}: mine {tables[k].shape} key {key.shape}")
