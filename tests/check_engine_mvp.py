"""Check engine/mvp.py against the PSL MVP answer key (data/leagues/psl/mvp/*.parquet).

Run from the repo root:  python3 tests/check_engine_mvp.py [--xi | --league] [--quiet]

Builds the MVP tables from the PSL core tables (data/leagues/psl/*.parquet) and compares every table with
the answer key cell by cell, after aligning rows on key columns. Two match rates per column:

  raw   exact cell equality
  norm  after the documented label differences are normalised on both sides:
        - player names: the core tables keep same-named players apart as "Khurram Shahzad (PZ, 2023-2024)",
          "Rameez Raja (2)", ...; the workbook shows the bare name
        - play-off names: the workbook uses the PSL's historical names (2016/17 "Qualifier 1/2/3",
          2025 "Qualifier 1 / Eliminator / Qualifier 2"); the core tables use Qualifier, Eliminator 1,
          Eliminator 2, Final
        - wording: the engine never says "PSL" (any league)

--xi also passes the playing XIs (read from raw/psl_male_csv2.zip) so knockout / close-finish match counts
can count players who neither batted nor bowled, as the workbook does.
--league builds the core tables with engine.build_league from the zip (end to end) and passes the XIs.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "leagues" / "psl"
CORE = ["ball", "matches", "team_matches", "bat_inns", "bowl_inns", "partnerships", "pair_seasons", "player_seasons"]
NAMES = ["definitions", "glance", "scoreboard", "highlights", "highlights_note", "ko_matches", "ko_players",
         "ko_cards", "close_definitions", "close_note", "close_glance", "close_teams", "close_players",
         "close_players_wb_tints", "close_matches"]

# Row keys per table (None = compare by position). Duplicate keys are numbered in order of appearance.
KEYS = {
    "definitions": None, "glance": ["Label"], "highlights_note": None,
    "scoreboard": ["Player", "Seasons"],
    "highlights": ["Category", "Player", "Date"],
    "ko_matches": ["Date", "Match"],
    "ko_players": ["Player"],
    "ko_cards": ["Date", "Team", "Player"],
    "close_definitions": None, "close_note": None, "close_glance": None,
    "close_teams": ["Team"],
    "close_players": ["Player"],
    "close_players_wb_tints": None,       # aligned through close_players
    "close_matches": ["Date", "Match"],
}


def load_engine():
    spec = importlib.util.spec_from_file_location("engine_mvp", ROOT / "engine" / "mvp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT or (
        not isinstance(v, (str, bytes)) and pd.isna(v))


def same(a, b) -> bool:
    if blank(a) or blank(b):
        return blank(a) and blank(b)
    if isinstance(a, (pd.Timestamp, np.datetime64)) or isinstance(b, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(a) == pd.Timestamp(b)
    if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
        return bool(a) == bool(b)
    if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))
    return str(a) == str(b)


# ── normalisation of the documented label differences ────────────────────────────────────────
class Norm:
    def __init__(self, mine: dict, key: dict):
        universe = set()
        for n in ("scoreboard", "ko_players", "close_players", "highlights", "ko_cards"):
            universe |= set(key[n]["Player"].dropna())
        ours = set(mine["mvp/scoreboard"]["Player"].dropna())
        self.alias = {}
        for p in ours - universe:
            base = re.sub(r"\s*\([^)]*\)$", "", p)
            if base in universe:
                self.alias[p] = base
        # play-off stage labels by match (date + fixture)
        mk, kk = mine["mvp/ko_matches"], key["ko_matches"]
        j = mk.merge(kk, on=["Date", "Match"], suffixes=("_m", "_k"))
        self.stage = {(d, a): b for d, a, b in zip(j["Date"], j["Stage only_m"], j["Stage only_k"]) if a != b}
        self.stage_by_date = {}
        for (d, a), b in self.stage.items():
            self.stage_by_date.setdefault(d, {})[a] = b
        self._names = sorted(self.alias, key=len, reverse=True)

    def name(self, v):
        return self.alias.get(v, v) if isinstance(v, str) else v

    def text(self, v):
        if not isinstance(v, str):
            return v
        for n in self._names:
            if n in v:
                v = v.replace(n, self.alias[n])
        return v.replace("any PSL play-off", "any play-off").replace("PSL matches in the data", "Matches in the data")

    def frame(self, name: str, df: pd.DataFrame, ours: bool) -> pd.DataFrame:
        df = df.copy()
        for c in df.columns:
            if df[c].dtype == object or str(df[c].dtype) in ("str", "string"):
                df[c] = df[c].map(self.text).astype(object)
        if not ours:
            return df
        if "Player" in df.columns:
            df["Player"] = df["Player"].map(self.name)
        if name == "highlights":
            df["Match stage"] = [self.stage_by_date.get(d, {}).get(s, s) for d, s in zip(df["Date"], df["Match stage"])]
        if name == "close_matches":
            df["Stage"] = [self.stage_by_date.get(d, {}).get(s, s) for d, s in zip(df["Date"], df["Stage"])]
        if name == "ko_matches":
            new = [self.stage_by_date.get(d, {}).get(s, s) for d, s in zip(df["Date"], df["Stage only"])]
            df["Stage"] = [st.replace(f" · {a}", f" · {b}") for st, a, b in zip(df["Stage"], df["Stage only"], new)]
            df["Stage only"] = new
        if name == "ko_cards":
            out = []
            for d, s, mt in zip(df["Date"], df["Season"], df["Match"]):
                for a, b in self.stage_by_date.get(d, {}).items():
                    mt = mt.replace(f" · {s} {a} · ", f" · {s} {b} · ")
                out.append(mt)
            df["Match"] = out
        return df


# ── comparison ───────────────────────────────────────────────────────────────────────────────
def keyed(df: pd.DataFrame, keys) -> pd.DataFrame:
    df = df.reset_index(drop=True).copy()
    if keys is None:
        df["_k"] = [(i,) for i in range(len(df))]
    else:
        k = df[keys].astype(object).map(lambda v: str(v)).agg(" | ".join, axis=1)
        df["_k"] = list(zip(k, k.groupby(k).cumcount()))
    df["_pos"] = np.arange(len(df))
    return df.set_index("_k")


def compare(name: str, mine: pd.DataFrame, key: pd.DataFrame, norm: Norm | None, quiet: bool,
            mine_rows=None, key_rows=None) -> dict:
    """Per-column raw / normalised match rates over rows present on both sides."""
    res = {"name": name, "shape": (mine.shape, key.shape), "cols": {}, "missing": [], "extra": []}
    if list(mine.columns) != list(key.columns):
        res["colnames"] = (list(mine.columns), list(key.columns))
    dt = {c: (str(mine[c].dtype), str(key[c].dtype)) for c in key.columns if c in mine.columns
          and str(mine[c].dtype) != str(key[c].dtype)}
    res["dtypes"] = dt
    out = {}
    for label, (a, b) in {"raw": (mine, key),
                          "norm": (norm.frame(name, mine, True), norm.frame(name, key, False)) if norm else (mine, key)
                          }.items():
        if mine_rows is not None:      # tints: rows aligned through another table
            ka, kb = a.iloc[mine_rows].reset_index(drop=True), b.iloc[key_rows].reset_index(drop=True)
            ka.index = kb.index = range(len(ka))
            common = list(range(len(ka)))
            pos_ok = None
        else:
            ka, kb = keyed(a, KEYS[name]), keyed(b, KEYS[name])
            common = [k for k in kb.index if k in ka.index]
            if label == "norm":
                res["missing"] = [k for k in kb.index if k not in ka.index]
                res["extra"] = [k for k in ka.index if k not in kb.index]
            # order check: same relative order of the common rows (first rows out of place reported)
            pa = ka.loc[common, "_pos"].to_numpy()
            pos_ok = bool((np.diff(pa) > 0).all()) if len(pa) > 1 else True
            if label == "norm" and not pos_ok:
                rank = pd.Series(pa).rank().to_numpy()
                off = [str(k[0]) for k, r_, i in zip(common, rank, range(1, len(common) + 1)) if r_ != i]
                res["order"] = (len(off), off[:6])
        cols = {}
        for c in key.columns:
            if c not in a.columns:
                cols[c] = (0, len(common), [])
                continue
            va, vb = ka.loc[common, c].tolist(), kb.loc[common, c].tolist()
            bad = [(k, x, y) for k, x, y in zip(common, va, vb) if not same(x, y)]
            cols[c] = (len(common) - len(bad), len(common), bad)
        out[label] = (cols, pos_ok, len(common))
    res["out"] = out
    return res


def report(res: dict, quiet: bool) -> tuple[int, int, int, int]:
    (ms, ks) = res["shape"]
    raw_cols, raw_pos, n_raw = res["out"]["raw"]
    nrm_cols, nrm_pos, n_nrm = res["out"]["norm"]
    tot_raw = sum(v[0] for v in raw_cols.values())
    tot_nrm = sum(v[0] for v in nrm_cols.values())
    cells = ks[0] * ks[1]
    print(f"\n=== mvp/{res['name']}  mine {ms}  key {ks}  rows matched {n_nrm}/{ks[0]}"
          f"  order {'ok' if nrm_pos in (True, None) else 'DIFFERENT'}")
    print(f"    cells equal: raw {tot_raw}/{cells} ({tot_raw / max(cells, 1):.2%})   "
          f"normalised {tot_nrm}/{cells} ({tot_nrm / max(cells, 1):.2%})")
    if res.get("order"):
        print(f"    rows in a different position ({res['order'][0]}), first:", res["order"][1])
    if res.get("colnames"):
        print("    COLUMNS differ:", res["colnames"])
    if res["dtypes"]:
        print("    dtypes differ (mine, key):", res["dtypes"])
    if res["missing"]:
        print(f"    rows only in key ({len(res['missing'])}):", [k[0] for k in res["missing"][:8]])
    if res["extra"]:
        print(f"    rows only in mine ({len(res['extra'])}):", [k[0] for k in res["extra"][:8]])
    for c in nrm_cols:
        okr, nr, _ = raw_cols[c]
        ok, n, bad = nrm_cols[c]
        if ok == n and okr == nr and quiet:
            continue
        flag = "" if ok == n else "   <-- differs"
        print(f"    {c:24s} raw {okr}/{nr} ({okr / max(nr, 1):.1%})  norm {ok}/{n} ({ok / max(n, 1):.1%}){flag}")
        for k, x, y in bad[:5]:
            lab = str(k[0] if isinstance(k, tuple) else k)
            print(f"        {lab[:70]:70s} mine={x!r}  key={y!r}")
    return tot_raw, tot_nrm, cells, n_nrm


def run(xi: bool, quiet: bool, league: bool = False) -> int:
    mvp = load_engine()
    if league:      # the engine's own core tables, built from the zip (end to end)
        sys.path.insert(0, str(ROOT))
        from engine import build_league
        built, _ = build_league(ROOT / "raw" / "psl_male_csv2.zip", name="Pakistan Super League", short="PSL")
        tables = {k: built[k] for k in CORE}
        xi = True
    else:
        tables = {k: pd.read_parquet(DATA / f"{k}.parquet") for k in CORE}
    people = tables["player_seasons"][["Player", "player_id"]].drop_duplicates()
    kwargs = {}
    if xi:
        sys.path.insert(0, str(ROOT))
        from engine.cricsheet import read_zip
        _, infos, _ = read_zip(ROOT / "raw" / "psl_male_csv2.zip")
        kwargs["infos"] = infos
        # people as the engine's core gives it: one row per Cricsheet id. player_seasons has one id per
        # name, so add the ids it lacks (the second "Tayyab Abbas", 6b972db7) under their team-sheet name.
        known, extra = set(people["player_id"]), {}
        for d in infos:
            for names in d["players"].values():
                for nm in names:
                    pid = d["registry"].get(nm)
                    if pid and pid not in known:
                        extra[pid] = nm
        people = pd.concat([people, pd.DataFrame([(n, i) for i, n in extra.items()], columns=["Player", "player_id"])],
                           ignore_index=True)
    t0 = time.perf_counter()
    mine = mvp.build_mvp(tables, people, **kwargs)
    took = time.perf_counter() - t0
    key = {n: pd.read_parquet(DATA / "mvp" / f"{n}.parquet") for n in NAMES}
    missing = [n for n in NAMES if f"mvp/{n}" not in mine]
    print(f"build_mvp: {took:.1f}s, {len(mine)} tables{'  MISSING ' + str(missing) if missing else ''}"
          f"  ({'engine-built core tables, ' if league else ''}{'with playing XIs' if xi else 'core tables only'})")
    norm = Norm(mine, key)
    print("name aliases (core name -> workbook name):", norm.alias)
    print("play-off labels (core -> workbook):", sorted({(a, b) for (d, a), b in norm.stage.items()}))

    totals = [0, 0, 0]
    for n in NAMES:
        if n in missing:
            continue
        if n == "close_players_wb_tints":
            # align through close_players' rows
            kp = keyed(norm.frame("close_players", mine["mvp/close_players"], True), KEYS["close_players"])
            kk = keyed(norm.frame("close_players", key["close_players"], False), KEYS["close_players"])
            common = [k for k in kk.index if k in kp.index]
            res = compare(n, mine[f"mvp/{n}"], key[n], norm, quiet,
                          mine_rows=kp.loc[common, "_pos"].tolist(), key_rows=kk.loc[common, "_pos"].tolist())
            res["missing"], res["extra"] = [], []
        else:
            res = compare(n, mine[f"mvp/{n}"], key[n], norm, quiet)
        r, nn, c, _ = report(res, quiet)
        totals[0] += r
        totals[1] += nn
        totals[2] += c
    print(f"\nALL TABLES  cells equal: raw {totals[0]}/{totals[2]} ({totals[0] / totals[2]:.2%})   "
          f"normalised {totals[1]}/{totals[2]} ({totals[1] / totals[2]:.2%})")
    return 0


if __name__ == "__main__":
    sys.exit(run(xi="--xi" in sys.argv, quiet="--quiet" in sys.argv, league="--league" in sys.argv))
