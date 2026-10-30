"""Validate analytics/explore_batter.py against the workbook ('Batter Explorer').

1. build((2016, 2026), **DEFAULTS) v the saved workbook: every KPI tile and
   every table cell (text exact, numbers equal at the displayed precision),
   plus titles, subtitles, headers and DEFAULTS v the filter cells.
2. Non-default filter combos v a literal, row-by-row SUMIFS/COUNTIFS
   re-implementation in plain pandas (independent of the module's numpy path).
3. Smoke test of many spans / filter combos (incl. no-data) + timing.

Run from the repo root:  python3 tests/check_explore_batter.py
"""
from __future__ import annotations

import itertools
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analytics.data as d  # noqa: E402
import analytics.explore_batter as mod  # noqa: E402
from analytics.explore_batter import xl_fmt  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Batter Explorer"
DASH = "—"
COLS = "EFGHIJKLMN"


def _nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def _same(mine, xv, nf):
    """Workbook value xv (format nf) v my number."""
    if xv == DASH or xv is None:
        return _nan(mine)
    if isinstance(xv, str):
        return mine == xv
    if _nan(mine):
        return False
    return xl_fmt(mine, nf) == xl_fmt(xv, nf) or abs(float(mine) - float(xv)) < 1e-9


# ── 1. workbook comparison ───────────────────────────────────────────────────
KPI_ROWS = {"bx_02": [6, 9], "bx_02b": [12], "bx_02c": [15]}
TABLES = {  # key: (title/subtitle row, header row, first data row, last data row)
    "bx_03": (18, 19, 20, 23), "bx_04": (25, 26, 27, 32), "bx_05": (34, 35, 36, 37),
    "bx_06": (39, 40, 41, 44), "bx_07": (46, 47, 48, 58), "bx_08": (60, 61, 62, 69),
    "bx_09": (71, 72, 73, 79),
}


def check_workbook(blocks):
    by = {b.key: b for b in blocks}
    results = {}

    # DEFAULTS v filter cells
    cells = {"batter": "C6", "venue": "C9", "phase": "C10", "bowler_type": "C11",
             "pace_spin": "C12", "opposition": "C13", "innings": "C14", "match_type": "C15",
             "host": "C16", "batter_hand": "C17"}
    bad = [f"{k}: {mod.DEFAULTS[k]!r} != {cell(SHEET, c)!r}" for k, c in cells.items()
           if mod.DEFAULTS[k] != cell(SHEET, c)]
    if (cell(SHEET, "C7"), cell(SHEET, "C8")) != (2016, 2026):
        bad.append("saved season range is not 2016–2026")
    if list(mod.DEFAULTS) != mod.FILTERS:
        bad.append("FILTERS order != DEFAULTS order")
    opts = mod.filter_options((2016, 2026))
    for k in mod.FILTERS:
        if mod.DEFAULTS[k] not in opts[k]:
            bad.append(f"default {k} not in options")
    results["defaults"] = bad

    # KPI tiles
    for key, rows in KPI_ROWS.items():
        b = by[key]
        bad = []
        exp = []
        for r in rows:
            for c in "EGIKM":
                exp.append((cell(SHEET, f"{c}{r}"), cell(SHEET, f"{c}{r + 1}"),
                            grid(SHEET, f"{c}{r + 1}", formulas="numfmt")[0][0] or "General"))
        if len(exp) != len(b.kpis):
            bad.append(f"{len(b.kpis)} tiles, workbook has {len(exp)}")
        for (lab, xv, nf), (mlab, mval, _) in zip(exp, b.kpis):
            want = xv if isinstance(xv, str) else xl_fmt(xv, nf)
            if lab != mlab:
                bad.append(f"label {mlab!r} != {lab!r}")
            if mval != want:
                bad.append(f"{lab}: {mval!r} != {want!r}")
        results[key] = bad
    results["bx_02 notes"] = [] if (by["bx_02"].note == cell(SHEET, "B21")
                                    and by["bx_02b"].note == cell(SHEET, "E14")
                                    and by["bx_02"].title == cell(SHEET, "E5")) \
        else ["how-to / † note / title text differs"]

    # tables
    for key, (tr, hr, r0, r1) in TABLES.items():
        b = by[key]
        bad = []
        if b.title != cell(SHEET, f"E{tr}"):
            bad.append(f"title {b.title!r} != {cell(SHEET, f'E{tr}')!r}")
        if b.note != cell(SHEET, f"H{tr}"):
            bad.append(f"note {b.note!r} != {cell(SHEET, f'H{tr}')!r}")
        hdr = grid(SHEET, f"E{hr}:N{hr}")[0]
        if hdr != list(b.df.columns):
            bad.append(f"header {list(b.df.columns)} != {hdr}")
        vals = grid(SHEET, f"E{r0}:N{r1}")
        fmts = grid(SHEET, f"E{r0}:N{r1}", formulas="numfmt")
        if len(vals) != len(b.df):
            bad.append(f"{len(b.df)} rows, workbook has {len(vals)}")
        for i, (xr, fr) in enumerate(zip(vals, fmts)):
            if i >= len(b.df):
                break
            for j, col in enumerate(b.df.columns):
                mv = b.df.iloc[i, j]
                mv = mv.item() if hasattr(mv, "item") else mv
                if not _same(mv, xr[j], fr[j] or "General"):
                    bad.append(f"{COLS[j]}{r0 + i} [{b.df.iloc[i, 0]} / {col}]: "
                               f"{mv!r} != {xr[j]!r}")
        results[key] = bad
    return results


# ── 2. literal SUMIFS reference ──────────────────────────────────────────────
def _crit(series, v):
    return series.notna() if v == "*" else (series == v)


def ref_masks(span, f):
    """The workbook's criteria, as written in the cell formulas (one dict per range)."""
    aa = {k: ("*" if v == "All" else v) for k, v in f.items()}
    inn_lo = 2 if f["innings"] == "2nd innings" else 1
    inn_hi = 1 if f["innings"] == "1st innings" else 2
    return aa, (min(span), max(span)), (inn_lo, inn_hi)


def ref_sums(b, aa, seasons, inns, override=None, extra=None):
    """SUMIFS over ball rows with the summary criteria, one criterion replaced."""
    crit = {"venue": ("Venue", aa["venue"]), "phase": ("Phase", aa["phase"]),
            "btype": ("Bowler Type", aa["bowler_type"]), "ps": ("Pace/Spin", aa["pace_spin"]),
            "opp": ("Bowling Team", aa["opposition"]), "mtype": ("Match Type", aa["match_type"]),
            "host": ("Host", aa["host"]), "hand": ("Bat Hand", aa["batter_hand"])}
    m = pd.Series(True, index=b.index)
    s_lo, s_hi = seasons
    if override and "season" in override:
        m &= b["Season"] == override["season"]
    else:
        m &= (b["Season"] >= s_lo) & (b["Season"] <= s_hi)
    m &= (b["Innings"] >= inns[0]) & (b["Innings"] <= inns[1])
    for k, (col, v) in crit.items():
        if override and k in override:
            v = override[k]
        if v is None:              # criterion dropped (by bowler type drops pace/spin)
            continue
        m &= _crit(b[col], v)
    if extra is not None:
        m &= extra
    bm = m & _crit(b["Batter"], aa["batter"])
    om = m & _crit(b["Player Out"], aa["batter"])
    return dict(balls=b.loc[bm, "Ball Faced"].sum(), runs=b.loc[bm, "Bat Runs"].sum(),
                outs=int(om.sum()), dots=b.loc[bm, "Bat Dot"].sum(),
                fours=b.loc[bm, "Four"].sum(), sixes=b.loc[bm, "Six"].sum(),
                rimp=b.loc[bm, "Bat Run Impact"].sum(), oexp=b.loc[bm, "Exp Out Cost"].sum(),
                oimp=b.loc[om, "Out Impact"].sum())


def ref_row(s):
    dv = lambda a, c, k=1.0: (k * a / c) if c > 0 else float("nan")  # noqa: E731
    return [s["balls"], s["runs"], dv(s["runs"], s["balls"], 100), s["outs"],
            dv(s["runs"], s["outs"]), dv(s["dots"], s["balls"]),
            dv(s["fours"] + s["sixes"], s["balls"]), s["fours"], s["sixes"]]


def check_reference(span, f):
    b = d.ball()
    aa, seasons, inns = ref_masks(span, f)
    blocks = {x.key: x for x in mod.build(span, **f)}
    bad = []

    s = ref_sums(b, aa, seasons, inns)
    row = ref_row(s)
    dv = lambda a, c, k=1.0: (k * a / c) if c > 0 else float("nan")  # noqa: E731
    lg = ref_sums(b, dict(aa, batter="*"), seasons, inns)
    sr_lg = dv(lg["runs"], lg["balls"], 100)
    imp = s["rimp"] + s["oimp"] - s["oexp"]
    exp = [xl_fmt(row[1], "#,##0"), xl_fmt(row[0], "#,##0"), xl_fmt(row[2], "0.0"),
           xl_fmt(row[4], "0.00"), xl_fmt(row[3], "0"), xl_fmt(row[7], "0"), xl_fmt(row[8], "0"),
           xl_fmt(row[5], "0.0%"), xl_fmt(row[6], "0.0%"), xl_fmt(dv(row[0], row[3]), "0.0")]
    got = [v for _, v, _ in blocks["bx_02"].kpis]
    if got != exp:
        bad.append(f"summary {got} != {exp}")
    sg = "+0.0;-0.0;0.0"
    exp = [xl_fmt(imp, sg), xl_fmt(dv(imp, s["balls"], 100), sg), xl_fmt(s["rimp"], sg),
           xl_fmt(s["oimp"] - s["oexp"], sg), xl_fmt(row[2] - sr_lg, sg)]
    got = [v for _, v, _ in blocks["bx_02c"].kpis]
    if got != exp:
        bad.append(f"impact {got} != {exp}")

    # innings level (Batting Innings, COUNTIFS/MAXIFS)
    bi = d.bat_inns()
    mi = (bi["Season"] >= seasons[0]) & (bi["Season"] <= seasons[1]) & \
         (bi["Innings"] >= inns[0]) & (bi["Innings"] <= inns[1])
    for col, k in [("Batter", "batter"), ("Venue", "venue"), ("Opposition", "opposition"),
                   ("Match Type", "match_type"), ("Host", "host"), ("Bat Hand", "batter_hand")]:
        mi &= _crit(bi[col], aa[k])
    x = bi[mi]
    exp = [str(len(x)), str(int((x["Out"] == 0).sum())),
           str(int(((x["Runs"] >= 50) & (x["Runs"] < 100)).sum())),
           str(int((x["Runs"] >= 100).sum())), str(int(x["Runs"].max())) if len(x) else DASH]
    got = [v for _, v, _ in blocks["bx_02b"].kpis]
    if got != exp:
        bad.append(f"innings {got} != {exp}")

    def cmp(key, rows):
        df = blocks[key].df
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                mv = df.iloc[i, j + 1]
                if _nan(v) != _nan(mv) or (not _nan(v) and abs(float(v) - float(mv)) > 1e-6):
                    bad.append(f"{key} row {df.iloc[i, 0]} {df.columns[j + 1]}: {mv} != {v}")

    cmp("bx_03", [ref_row(ref_sums(b, aa, seasons, inns, {"phase": p})) for p in d.PHASES])
    cmp("bx_04", [ref_row(ref_sums(b, aa, seasons, inns, {"btype": t, "ps": None}))
                  for t in d.BOWL_TYPES])
    cmp("bx_05", [ref_row(ref_sums(b, aa, seasons, inns, {"hand": h})) for h in d.HANDS])
    cmp("bx_06", [ref_row(ref_sums(b, aa, seasons, inns, extra=(b["Batter Ball No"] >= lo) &
                                   (b["Batter Ball No"] <= hi))) for _, lo, hi in mod.STAGES])
    cmp("bx_07", [ref_row(ref_sums(b, aa, seasons, inns, {"season": s})) for s in d.seasons()])
    cmp("bx_08", [ref_row(ref_sums(b, aa, seasons, inns, {"opp": t}))
                  for t in d.lists()["Teams"].dropna()])
    cmp("bx_09", [ref_row(ref_sums(b, aa, seasons, inns, {"venue": v}))
                  for v in d.lists()["Venues+All"].dropna().tolist()[1:]])
    return bad


REF_COMBOS = [
    ((2016, 2026), dict(batter="All")),
    ((2016, 2026), dict(batter="All", venue="Gaddafi Stadium", phase="Death")),
    ((2020, 2022), dict(batter="Fakhar Zaman", bowler_type="Leg-spin", innings="2nd innings")),
    ((2018, 2024), dict(batter="Mohammad Rizwan", pace_spin="Spin", host="UAE",
                        match_type="Playoff")),
    ((2016, 2016), dict(batter="All", batter_hand="LHB", opposition="Karachi Kings")),
    ((2026, 2026), dict(batter="Babar Azam", innings="1st innings", venue="National Stadium")),
    ((2016, 2026), dict(batter="Babar Azam", venue="Multan Cricket Stadium", phase="Death",
                        bowler_type="Left-arm wrist-spin")),   # no data
]


# ── 3. smoke + timing ────────────────────────────────────────────────────────
def smoke():
    errs, times = [], []
    opts = mod.filter_options((2016, 2026))
    spans = [(2016, 2026), (2016, 2016), (2016, 2017), (2020, 2022), (2026, 2026), (2026, 2016)]
    combos = [dict(), dict(batter="All"), dict(batter="BR Dunk"),
              dict(batter="All", venue="Sharjah Cricket Stadium", phase="PP"),
              dict(batter="Babar Azam", opposition="Rawalpindiz", host="UAE"),     # no data
              dict(batter="Nobody At All"),                                       # unknown name
              dict(batter=None, venue=None)]
    rnd = random.Random(7)
    for _ in range(40):
        combos.append({k: rnd.choice(opts[k]) for k in mod.FILTERS})
    for span, f in itertools.product(spans, combos):
        try:
            t = time.perf_counter()
            bl = mod.build(span, **f)
            times.append(time.perf_counter() - t)
            for b in bl:
                if b.kind == "table":
                    assert list(b.df.columns)[1:] == mod.COLS, b.key
                    assert set(b.fmt) >= set(mod.COLS), b.key
                else:
                    assert len(b.kpis) in (5, 10), b.key
        except Exception as e:  # noqa: BLE001
            errs.append(f"{span} {f}: {type(e).__name__}: {e}")
    return errs, times


def main():
    t = time.perf_counter()
    blocks = mod.build((2016, 2026), **mod.DEFAULTS)
    first = time.perf_counter() - t
    res = check_workbook(blocks)
    ok = True
    print("── workbook (saved selections) ──")
    for k, bad in res.items():
        print(f"{'PASS' if not bad else 'FAIL'}  {k}" + ("" if not bad else f"  ({len(bad)})"))
        for x in bad[:6]:
            print("      ", x)
        ok &= not bad
    print("── literal SUMIFS reference, other combos ──")
    for span, f in REF_COMBOS:
        bad = check_reference(span, dict(mod.DEFAULTS, **f))
        print(f"{'PASS' if not bad else 'FAIL'}  {span} {f}")
        for x in bad[:6]:
            print("      ", x)
        ok &= not bad
    errs, times = smoke()
    print("── smoke ──")
    print(f"{'PASS' if not errs else 'FAIL'}  {len(times)} builds without error"
          + ("" if not errs else f", {len(errs)} errors"))
    for x in errs[:6]:
        print("      ", x)
    ok &= not errs
    ts = np.array(times) * 1000
    print(f"timing: first build (incl. data load) {first * 1000:.0f} ms; "
          f"warm median {np.median(ts):.1f} ms, max {ts.max():.1f} ms")
    ok &= ts.max() < 500
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
