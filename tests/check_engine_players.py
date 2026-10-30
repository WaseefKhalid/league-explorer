"""Compare engine/players.py output with the PSL answer keys, cell by cell.

    python3 tests/check_engine_players.py            # core tables = data/leagues/psl/*.parquet
    python3 tests/check_engine_players.py --no-xi    # same, without the playing XIs (shows what Mat loses)

Inputs: the answer-key core tables (ball with impact columns, matches, team_matches, bat_inns, bowl_inns,
partnerships, pair_seasons), people = player_seasons[[Player, player_id]], registry =
data/registry/players_meta.parquet, home_country = "Pakistan", and the playing XIs from the info files
of raw/psl_male_csv2.zip (names mapped to the answer key's names through the Cricsheet registry ids).

Columns are reported in three groups:
  derived      - must match exactly (ints / text) or within 1e-6 (floats)
  rounding     - impact sums: built from the ball table's 3-dp impact values, so they can only match
                 within accumulated rounding. Shown: strict rate, and the rate within the rounding bound
                 0.0005 x (balls summed) + 0.0005 (0.0005 per 3-dp ball value + the final 3-dp rounding)
  not derivable- values the PSL workbook had from outside Cricsheet CSV2 (fielding, data provenance)
Registry-dependent columns (match only because the registry holds the PSL players' metadata) are
listed separately at the end.
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from engine.players import build_player_tables  # noqa: E402

D = "data/leagues/psl/"
CORE = ["ball", "matches", "team_matches", "bat_inns", "bowl_inns", "partnerships", "pair_seasons"]
KEYS = {"player_seasons": ["Player", "Season"], "players": ["Player"], "lists": None}

ROUNDING = {
    "player_seasons": ["Bat Run Impact", "Bowl Run Impact", "Bowl Wkt Impact", "Wicket Value", "Bat Out Impact"],
    "players": ["Batting impact", "Bowling impact"],
}
NOT_DERIVABLE = {
    "player_seasons": {c: "fielding: Cricsheet CSV2 has no fielder names" for c in ["Catches", "Stumpings", "Run-outs"]},
    "players": {"Catches": "fielding: Cricsheet CSV2 has no fielder names",
                "Hand Source": "provenance of the batting hand (Cricinfo / You) - not in the registry",
                "Style Source": "provenance of the bowling style (Cricinfo / You / Web check) - not in the registry"},
}
REGISTRY_DEPENDENT = {
    "player_seasons": ["Origin", "Hand", "Bowl Type", "player_id (from people)",
                       "BB/BR/BW v RHB/LHB, R/B v type, R/B/Outs v Pace/Spin (via ball's Bat Hand / Bowler Type)"],
    "players": ["Full Name", "Country", "Overseas/Local (the '*' = registry country without a Cricinfo profile,"
                " i.e. no Full Name)", "Role (Cricinfo)", "Bat Hand", "Bowling Style", "Bowling Type",
                "Still Missing"],
    "lists": ["Types+All", "Hands+All", "PaceSpin+All"],
}


def same(a: pd.Series, b: pd.Series, atol: float = 1e-6) -> pd.Series:
    a = a.reset_index(drop=True)
    b = b.reset_index(drop=True)
    num = pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b)
    both_na = a.isna() & b.isna()
    if num:
        av, bv = a.astype(float).to_numpy(), b.astype(float).to_numpy()
        eq = pd.Series(np.isclose(av, bv, atol=atol, rtol=0), index=a.index)
    else:
        eq = (a.astype(object).astype(str) == b.astype(object).astype(str)) & a.notna() & b.notna()
    return eq | both_na


def rounding_bounds(ball: pd.DataFrame, ps_key: pd.DataFrame) -> dict[str, dict[str, pd.Series]]:
    """Max error of a sum of n values rounded to 3 dp, then rounded to 3 dp: 0.0005*n + 0.0005."""
    k = ["Player", "Season"]

    def n(by, mask=None):
        d = ball if mask is None else ball[mask]
        return d.groupby([by, "Season"]).size().rename_axis(k)

    idx = pd.MultiIndex.from_frame(ps_key[k])
    cnt = {"Bat Run Impact": n("Batter"),
           "Bat Out Impact": n("Batter").add(n("Player Out", ball["Player Out"].notna()), fill_value=0),
           "Bowl Run Impact": n("Bowler"), "Bowl Wkt Impact": n("Bowler"),
           "Wicket Value": n("Bowler", ball["Bowler Wkt"] == 1)}
    ps_b = {c: 0.0005 * v.reindex(idx).fillna(0) + 0.0005 for c, v in cnt.items()}
    per_player = {c: (0.0005 * v.reindex(idx).fillna(0) + 0.0005).groupby(level=0).sum() for c, v in cnt.items()}
    pl = {"Batting impact": per_player["Bat Run Impact"] + per_player["Bat Out Impact"],
          "Bowling impact": per_player["Bowl Run Impact"] + per_player["Bowl Wkt Impact"]}
    return {"player_seasons": ps_b, "players": pl}


BOUNDS: dict = {}


def compare(name: str, mine: pd.DataFrame, key: pd.DataFrame) -> dict:
    res = {"fail": [], "rounding": {}, "nd": {}}
    print(f"\n=== {name}: mine {mine.shape} · answer key {key.shape}")
    if list(mine.columns) != list(key.columns):
        missing = [c for c in key.columns if c not in mine.columns]
        extra = [c for c in mine.columns if c not in key.columns]
        print(f"  COLUMNS differ  missing={missing} extra={extra}")
        res["fail"].append("columns")
    else:
        print("  columns + order: identical")
    dt = [(c, str(mine[c].dtype), str(key[c].dtype)) for c in key.columns
          if c in mine.columns and str(mine[c].dtype) != str(key[c].dtype)]
    if dt:
        print("  dtype differences (mine, key):", dt)
    keys = KEYS[name]
    if keys:
        same_rows = mine[keys].reset_index(drop=True).equals(key[keys].reset_index(drop=True))
        print(f"  row keys + order: {'identical' if same_rows else 'DIFFER'}")
        if not same_rows:
            res["fail"].append("rows")
            a, b = mine.set_index(keys), key.set_index(keys)
            print(f"    only in mine: {list(a.index.difference(b.index))[:5]}  "
                  f"only in key: {list(b.index.difference(a.index))[:5]}")
            common = b.index.intersection(a.index)
            mine, key = a.loc[common].reset_index(), b.loc[common].reset_index()
    else:
        if len(mine) != len(key):
            res["fail"].append("rows")
        n = min(len(mine), len(key))
        mine, key = mine.iloc[:n], key.iloc[:n]

    print(f"  {'column':24s} {'match':>9s}")
    for c in key.columns:
        if c not in mine.columns:
            continue
        eq = same(mine[c], key[c])
        rate = eq.mean()
        tag = ""
        if c in NOT_DERIVABLE.get(name, {}):
            tag = "  [not derivable]"
            res["nd"][c] = rate
        elif c in ROUNDING.get(name, []):
            d = (mine[c].astype(float) - key[c].astype(float)).abs().reset_index(drop=True)
            rows = pd.MultiIndex.from_frame(key[keys]) if len(keys) > 1 else pd.Index(key[keys[0]])
            bound = pd.Series(BOUNDS[name][c].reindex(rows).to_numpy())
            loose = ((d <= bound + 1e-9) | (mine[c].isna() & key[c].isna()).reset_index(drop=True)).mean()
            diff = d.max()
            tag = f"  [rounding] within bound: {loose:.2%}  max|d|={diff:.3f}"
            res["rounding"][c] = (rate, loose, diff)
        elif rate < 1:
            res["fail"].append(c)
        print(f"  {c:24s} {rate:9.2%}{tag}")
        if rate < 1 and not tag.startswith("  [rounding]"):
            bad = eq[~eq].index[:4]
            ex = [(tuple(key.loc[i, keys]) if keys else i, mine[c].iloc[i] if not keys else mine.at[i, c],
                   key.at[i, c]) for i in bad]
            print(f"      e.g. (row, mine, key): {ex}")
    return res


def main() -> None:
    t0 = time.time()
    tables = {t: pd.read_parquet(D + f"{t}.parquet") for t in CORE}
    answer = {t: pd.read_parquet(D + f"{t}.parquet") for t in ["player_seasons", "players", "lists"]}
    people = answer["player_seasons"][["Player", "player_id"]].drop_duplicates().reset_index(drop=True)
    registry = pd.read_parquet("data/registry/players_meta.parquet")
    infos = None
    if "--no-xi" not in sys.argv:
        from engine.cricsheet import read_zip
        _, infos, _ = read_zip("raw/psl_male_csv2.zip")
    t1 = time.time()
    out = build_player_tables(tables, people, registry, home_country="Pakistan", infos=infos)
    print(f"build_player_tables: {time.time() - t1:.1f}s (inputs loaded in {t1 - t0:.1f}s)"
          f"{'  [no playing XIs]' if infos is None else ''}")

    BOUNDS.update(rounding_bounds(tables["ball"], answer["player_seasons"]))
    results = {n: compare(n, out[n], answer[n]) for n in ["player_seasons", "players", "lists"]}

    print("\n=== SUMMARY")
    for n, r in results.items():
        status = "ALL DERIVABLE COLUMNS MATCH" if not r["fail"] else f"MISMATCH in {r['fail']}"
        print(f"  {n:15s} {status}")
        for c, (strict, loose, diff) in r["rounding"].items():
            print(f"      rounding   {c:18s} strict {strict:7.2%} · within rounding bound {loose:7.2%} · max|d| {diff:.3f}")
        for c, rate in r["nd"].items():
            print(f"      not deriv. {c:18s} {rate:7.2%}  ({NOT_DERIVABLE[n][c]})")
    print("\n  Registry-dependent (match only because the registry holds the PSL players' metadata):")
    for n, cols in REGISTRY_DEPENDENT.items():
        print(f"    {n}: {', '.join(cols)}")
    smoke_ok = generic_smoke(tables)
    sys.exit(1 if (any(r["fail"] for r in results.values()) or not smoke_ok) else 0)


def generic_smoke(tables: dict) -> bool:
    """Another 'league': renamed teams (one single-word name), shifted seasons, no registry, no home
    country, no playing XIs. Must run and fall back to Unknown / NaN without errors."""
    # "Multan Stars" clashes with "Multan Sultans" (both MS) to exercise the clash rule
    ren = {"Lahore Qalandars": "Thunder", "Karachi Kings": "Kandy Kings", "Islamabad United": "Kings XI Punjab",
           "Hyderabad Kingsmen": "Multan Stars"}
    t = {}
    for name, df in tables.items():
        df = df.copy()
        for c in df.columns:
            if df[c].dtype == object or str(df[c].dtype) == "str":
                if df[c].isin(list(ren)).any():
                    df[c] = df[c].replace(ren)
        if "Season" in df:
            df["Season"] = df["Season"] + 100
        t[name] = df
    # without a registry the core has no hand / bowling type for anyone
    t["ball"][["Bat Hand", "Bowler Type", "Pace/Spin"]] = "Unknown"
    people = pd.DataFrame({"Player": pd.unique(t["ball"]["Batter"]), "player_id": None})
    out = build_player_tables(t, people, None, home_country=None)
    ps, pl, li = out["player_seasons"], out["players"], out["lists"]
    checks = {
        "columns": list(ps.columns) == list(pd.read_parquet(D + "player_seasons.parquet").columns),
        "origin Unknown": set(ps["Origin"]) == {"Unknown"},
        "hand Unknown": set(ps["Hand"]) == {"Unknown"},
        "bowl type Unknown": set(ps["Bowl Type"]) == {"Unknown"},
        "team codes": {"TH", "KK", "KXIP", "MS", "MSU"} <= set(ps["Team"]),
        "seasons shifted": ps["Season"].min() == 2116,
        "players Country Unknown": set(pl["Country"]) == {"Unknown"},
        "Types/Hands/PaceSpin only All": all(li[c].dropna().tolist() == ["All"]
                                             for c in ["Types+All", "Hands+All", "PaceSpin+All"]),
        "Catches NaN": ps["Catches"].isna().all() and pl["Catches"].isna().all(),
        "finish keys": "Thunder|2122" in set(li["FinishKey"].dropna()),
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"\n=== generic smoke test (renamed teams, seasons +100, no registry/XI/home): "
          f"{'OK' if not bad else 'FAILED ' + str(bad)}")
    print(f"    team codes: {sorted(set('/'.join(ps['Team']).split('/')))}")
    return not bad


if __name__ == "__main__":
    main()
