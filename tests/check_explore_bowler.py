"""Validate analytics/explore_bowler.py against the workbook ('Bowler Explorer').

1. build((2016, 2026), **DEFAULTS) v the saved workbook: every KPI tile and
   every table cell (text exact, numbers equal at the displayed precision),
   plus titles, subtitles, headers and DEFAULTS v the filter cells.
2. Non-default filter combos v a literal, row-by-row SUMIFS/COUNTIFS
   re-implementation in plain pandas (independent of the module's numpy path).
3. Smoke test of many spans / filter combos (incl. no-data) + timing.

Run from the repo root:  python3 tests/check_explore_bowler.py
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
import analytics.explore_bowler as mod  # noqa: E402
from analytics.explore_bowler import xl_fmt, overs_text  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Bowler Explorer"
DASH = "—"
COLS = "EFGHIJKLMN"


def _nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def _same(mine, xv, nf, col):
    """Workbook value xv (format nf) v my number."""
    if xv == DASH or xv is None:
        return _nan(mine)
    if col == "Overs":                       # text "347.4" in the workbook
        return (not _nan(mine)) and f"{mine:.1f}" == xv
    if isinstance(xv, str):
        return mine == xv
    if _nan(mine):
        return False
    return xl_fmt(mine, nf) == xl_fmt(xv, nf) or abs(float(mine) - float(xv)) < 1e-9


# ── 1. workbook comparison ───────────────────────────────────────────────────
KPI_ROWS = {"wx_02": [6, 9], "wx_02b": [12], "wx_02c": [15]}
TABLES = {  # key: (title/subtitle row, header row, first data row, last data row)
    "wx_03": (18, 19, 20, 23), "wx_04": (25, 26, 27, 28), "wx_05": (30, 31, 32, 37),
    "wx_06": (39, 40, 41, 51), "wx_07": (53, 54, 55, 62), "wx_08": (64, 65, 66, 72),
}


def check_workbook(blocks):
    by = {b.key: b for b in blocks}
    results = {}

    cells = {"bowler": "C6", "venue": "C9", "phase": "C10", "batter_hand": "C11",
             "opposition": "C12", "innings": "C13", "match_type": "C14", "host": "C15",
             "bowler_type": "C16", "pace_spin": "C17"}
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
    results["wx_02 notes"] = [] if (by["wx_02"].note == cell(SHEET, "B21")
                                    and by["wx_02b"].note == cell(SHEET, "E14")
                                    and by["wx_02"].title == cell(SHEET, "E5")) \
        else ["how-to / † note / title text differs"]

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
                if not _same(mv, xr[j], fr[j] or "General", col):
                    bad.append(f"{COLS[j]}{r0 + i} [{b.df.iloc[i, 0]} / {col}]: "
                               f"{mv!r} != {xr[j]!r}")
        results[key] = bad
    return results


# ── 2. literal SUMIFS reference ──────────────────────────────────────────────
def _crit(series, v):
    return series.notna() if v == "*" else (series == v)


def ref_sums(b, aa, seasons, inns, override=None):
    crit = {"venue": ("Venue", aa["venue"]), "phase": ("Phase", aa["phase"]),
            "hand": ("Bat Hand", aa["batter_hand"]), "opp": ("Batting Team", aa["opposition"]),
            "mtype": ("Match Type", aa["match_type"]), "host": ("Host", aa["host"]),
            "btype": ("Bowler Type", aa["bowler_type"]), "ps": ("Pace/Spin", aa["pace_spin"])}
    m = pd.Series(True, index=b.index)
    if override and "season" in override:
        m &= b["Season"] == override["season"]
    else:
        m &= (b["Season"] >= seasons[0]) & (b["Season"] <= seasons[1])
    m &= (b["Innings"] >= inns[0]) & (b["Innings"] <= inns[1])
    for k, (col, v) in crit.items():
        if override and k in override:
            v = override[k]
        if v is None:
            continue
        m &= _crit(b[col], v)
    m &= _crit(b["Bowler"], aa["bowler"])
    x = b[m]
    return dict(legal=x["Legal Ball"].sum(), runs=x["Bowler Runs"].sum(),
                wkts=x["Bowler Wkt"].sum(), dots=x["Bowl Dot"].sum(),
                b4=x["Four"].sum() + x["Six"].sum(), wd=x["Wides"].sum(), nb=x["No-balls"].sum(),
                rimp=x["Bowl Run Impact"].sum(), wimp=x["Bowl Wkt Impact"].sum())


def _dv(a, c, k=1.0):
    return (k * a / c) if c > 0 else float("nan")


def ref_row(s):
    return [overs_text(s["legal"]), s["legal"], s["runs"], s["wkts"],
            _dv(s["runs"], s["legal"], 6), _dv(s["runs"], s["wkts"]), _dv(s["legal"], s["wkts"]),
            _dv(s["dots"], s["legal"]), _dv(s["b4"], s["legal"])]


def check_reference(span, f):
    b = d.ball()
    aa = {k: ("*" if v == "All" else v) for k, v in f.items()}
    seasons = (min(span), max(span))
    inns = (2 if f["innings"] == "2nd innings" else 1, 1 if f["innings"] == "1st innings" else 2)
    blocks = {x.key: x for x in mod.build(span, **f)}
    bad = []

    s = ref_sums(b, aa, seasons, inns)
    r = ref_row(s)
    exp = [xl_fmt(r[3], "0"), r[0], xl_fmt(r[4], "0.00"), xl_fmt(r[5], "0.00"),
           xl_fmt(r[6], "0.0"), xl_fmt(r[7], "0.0%"), xl_fmt(r[8], "0.0%"),
           f"{int(s['wd'])} · {int(s['nb'])}", xl_fmt(r[1], "#,##0"), xl_fmt(r[2], "#,##0")]
    got = [v for _, v, _ in blocks["wx_02"].kpis]
    if got != exp:
        bad.append(f"summary {got} != {exp}")
    lg = ref_sums(b, dict(aa, bowler="*"), seasons, inns)
    imp = s["rimp"] + s["wimp"]
    sg = "+0.0;-0.0;0.0"
    exp = [xl_fmt(imp, sg), xl_fmt(_dv(imp, s["legal"], 24), sg), xl_fmt(s["rimp"], sg),
           xl_fmt(s["wimp"], sg),
           xl_fmt(r[4] - _dv(lg["runs"], lg["legal"], 6), "+0.00;-0.00;0.00")]
    got = [v for _, v, _ in blocks["wx_02c"].kpis]
    if got != exp:
        bad.append(f"impact {got} != {exp}")

    bo = d.bowl_inns()
    mi = (bo["Season"] >= seasons[0]) & (bo["Season"] <= seasons[1]) & \
         (bo["Innings"] >= inns[0]) & (bo["Innings"] <= inns[1])
    for col, k in [("Bowler", "bowler"), ("Venue", "venue"), ("Opposition", "opposition"),
                   ("Match Type", "match_type"), ("Host", "host"), ("Bowler Type", "bowler_type")]:
        mi &= _crit(bo[col], aa[k])
    x = bo[mi]
    exp = [str(len(x)), str(int((x["Wickets"] == 3).sum())), str(int((x["Wickets"] >= 4).sum())),
           str(int(x["Maidens"].sum())), str(int(x["Wickets"].max())) if len(x) else DASH]
    got = [v for _, v, _ in blocks["wx_02b"].kpis]
    if got != exp:
        bad.append(f"innings {got} != {exp}")

    def cmp(key, rows):
        df = blocks[key].df
        for i, rr in enumerate(rows):
            for j, v in enumerate(rr):
                mv = df.iloc[i, j + 1]
                if j == 0:
                    ok = f"{mv:.1f}" == v
                else:
                    ok = _nan(v) == _nan(mv) and (_nan(v) or abs(float(v) - float(mv)) < 1e-6)
                if not ok:
                    bad.append(f"{key} row {df.iloc[i, 0]} {df.columns[j + 1]}: {mv} != {v}")

    cmp("wx_03", [ref_row(ref_sums(b, aa, seasons, inns, {"phase": p})) for p in d.PHASES])
    cmp("wx_04", [ref_row(ref_sums(b, aa, seasons, inns, {"hand": h})) for h in d.HANDS])
    cmp("wx_05", [ref_row(ref_sums(b, aa, seasons, inns, {"btype": t, "ps": None}))
                  for t in d.BOWL_TYPES])
    cmp("wx_06", [ref_row(ref_sums(b, aa, seasons, inns, {"season": s})) for s in d.seasons()])
    cmp("wx_07", [ref_row(ref_sums(b, aa, seasons, inns, {"opp": t}))
                  for t in d.lists()["Teams"].dropna()])
    cmp("wx_08", [ref_row(ref_sums(b, aa, seasons, inns, {"venue": v}))
                  for v in d.lists()["Venues+All"].dropna().tolist()[1:]])
    return bad


REF_COMBOS = [
    ((2016, 2026), dict(bowler="All")),
    ((2016, 2026), dict(bowler="All", bowler_type="Leg-spin")),              # every leg-spinner
    ((2016, 2026), dict(bowler="All", venue="Gaddafi Stadium", phase="Death")),
    ((2020, 2022), dict(bowler="Rashid Khan", batter_hand="LHB", innings="2nd innings")),
    ((2018, 2024), dict(bowler="Wahab Riaz", host="UAE", match_type="Playoff")),
    ((2016, 2016), dict(bowler="All", pace_spin="Spin", opposition="Karachi Kings")),
    ((2026, 2026), dict(bowler="Shaheen Shah Afridi", innings="1st innings")),
    ((2016, 2026), dict(bowler="Shaheen Shah Afridi", bowler_type="Off-spin")),   # no data
]


# ── 3. smoke + timing ────────────────────────────────────────────────────────
def smoke():
    errs, times = [], []
    opts = mod.filter_options((2016, 2026))
    spans = [(2016, 2026), (2016, 2016), (2016, 2017), (2020, 2022), (2026, 2026), (2026, 2016)]
    combos = [dict(), dict(bowler="All"), dict(bowler="Usama Mir"),
              dict(bowler="All", bowler_type="Left-arm wrist-spin", phase="PP"),
              dict(bowler="Shaheen Shah Afridi", opposition="Lahore Qalandars"),   # no data
              dict(bowler="Nobody At All"),                                        # unknown name
              dict(bowler=None, venue=None)]
    rnd = random.Random(11)
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
