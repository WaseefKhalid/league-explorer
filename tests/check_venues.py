"""
Validate analytics/venues.py against the workbook's "Venues" sheet.

    cd /home/claude/waseefkhalid/cricsheet && python3 tests/check_venues.py

* build((2016, 2026)) is compared cell by cell with the workbook's cached
  values (text exact, numbers equal after rounding to the displayed format).
* Smoke runs for other spans, with spot checks against a direct SUMIFS-style
  recomputation from the raw tables (the workbook only caches 2016–2026).
"""
from __future__ import annotations

import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analytics.data as d  # noqa: E402
from analytics import venues as mod  # noqa: E402
from tools.xlcheck import grid, cell  # noqa: E402

SHEET = "Venues"
FMT_MAP = {"0": "{:,.0f}", "0.0": "{:,.1f}", "0.00": "{:,.2f}", "0%": "{:.0%}",
           "0.0%": "{:.1%}", "#,##0": "{:,.0f}"}


# ── generic cell-by-cell comparison ──────────────────────────────────────────
def _norm_text(x) -> str:
    return re.sub(r"\s+", " ", str(x)).strip()


def _blank(x) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    return isinstance(x, str) and x.strip() in ("", "—")


def compare_block(blk, rng: str, problems: list[str]) -> int:
    """Header row + data rows of `rng` vs blk.df. Returns number of cells checked."""
    vals = grid(SHEET, rng)
    fmts = grid(SHEET, rng, formulas="numfmt")
    head, rows, frow = vals[0], vals[1:], fmts[1:]
    df = blk.df
    n = 0
    # headers
    if len(head) != len(df.columns):
        problems.append(f"{blk.key}: {len(df.columns)} columns, workbook has {len(head)}")
    for j, (h, c) in enumerate(zip(head, df.columns)):
        n += 1
        if _norm_text(h) != _norm_text(c):
            problems.append(f"{blk.key}: header {j}: got {c!r}, workbook {h!r}")
    if len(rows) != len(df):
        problems.append(f"{blk.key}: {len(df)} rows, workbook has {len(rows)}")
    for i, (wr, fr) in enumerate(zip(rows, frow)):
        for j, col in enumerate(df.columns):
            n += 1
            want, got = wr[j], df.iloc[i, j]
            nf = fr[j]
            if _blank(want) or _blank(got):
                if not (_blank(want) and _blank(got)):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
                continue
            if isinstance(want, str) or isinstance(got, str):
                if _norm_text(want) != _norm_text(got):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
                continue
            f = FMT_MAP.get(nf)
            if f is not None:
                if blk.fmt.get(col) != f:
                    problems.append(f"{blk.key}: fmt for {col!r} is {blk.fmt.get(col)!r}, "
                                    f"workbook {nf!r} → {f!r}")
                if f.format(float(got)) != f.format(float(want)):
                    problems.append(f"{blk.key}[{i},{col}]: got {f.format(float(got))}, "
                                    f"workbook {f.format(float(want))}")
            else:
                if not math.isclose(float(got), float(want), rel_tol=1e-9, abs_tol=1e-9):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
    return n


def report(name: str, problems: list[str], n: int) -> bool:
    ok = not problems
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({n} cells/checks)")
    for p in problems[:8]:
        print("        ", p)
    if len(problems) > 8:
        print(f"         … {len(problems) - 8} more")
    return ok


# ── independent SUMIFS-style recomputation (spot checks for any span) ─────────
def _naive_profile(venue: str | None, span):
    lo, hi = min(span), max(span)
    m = d.matches()
    b = d.ball()
    m = m[(m["Season"] >= lo) & (m["Season"] <= hi)]
    b = b[(b["Season"] >= lo) & (b["Season"] <= hi)]
    if venue:
        m = m[m["Venue"] == venue]
        b = b[b["Venue"] == venue]
    out = {}
    out["Matches"] = int((m["Season"] > 0).sum())
    f = m[m["Full 1st Inns"] == 1]["1st Inns Runs"]
    out["Avg 1st-inns"] = f.mean() if len(f) else np.nan
    out["Highest"] = (max(m["1st Inns Runs"].max(), m["2nd Inns Runs"].max())
                      if out["Matches"] else np.nan)
    dec = m["Decided (no DLS)"] == 1
    out["Chase win %"] = ((dec & (m["Bat First Won"] == 0)).sum() / dec.sum()) if dec.sum() else np.nan
    out["Run rate"] = 6 * b["Total Runs"].sum() / b["Legal Ball"].sum() if len(b) else np.nan
    dp = b[b["Phase"] == "Death"]
    out["Death"] = 6 * dp["Total Runs"].sum() / dp["Legal Ball"].sum() if len(dp) else np.nan
    sp = b[b["Pace/Spin"] == "Spin"]
    out["Spin econ"] = 6 * sp["Bowler Runs"].sum() / sp["Legal Ball"].sum() if len(sp) else np.nan
    out["Spin balls / wkt"] = (sp["Legal Ball"].sum() / sp["Bowler Wkt"].sum()
                               if sp["Bowler Wkt"].sum() else np.nan)
    out["Sixes / match"] = b["Six"].sum() / out["Matches"] if out["Matches"] else np.nan
    return out


def spot_check(span, blocks, problems):
    prof = blocks[0].df.set_index("Venue")
    n = 0
    for venue in list(prof.index):
        exp = _naive_profile(None if venue == mod.ALL_LABEL else venue, span)
        for k, v in exp.items():
            n += 1
            got = prof.loc[venue, k]
            if _blank(v) and _blank(got):
                continue
            if _blank(v) != _blank(got) or not math.isclose(float(got), float(v), rel_tol=1e-9):
                problems.append(f"{span} {venue} {k}: got {got!r}, expected {v!r}")
    # heat map values never change with the span; greyed columns do
    heat = blocks[1]
    exp_grey = [str(s) for s in d.seasons() if s < min(span) or s > max(span)]
    n += 1
    if getattr(heat, "muted_cols", None) != exp_grey:
        problems.append(f"{span}: muted_cols {getattr(heat, 'muted_cols', None)} != {exp_grey}")
    if set(heat.good_high) & set(exp_grey):
        problems.append(f"{span}: greyed season columns are still tinted")
    return n


def check_structure(blocks, problems) -> int:
    for b in blocks:
        if b.df is not None and not isinstance(b.df.index, pd.RangeIndex):
            problems.append(f"{b.key}: index is not a RangeIndex")
    return len(blocks)


def main() -> int:
    ok = True
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(5):
        blocks = mod.build((2016, 2026))
    t_warm = (time.perf_counter() - t0) / 5
    by = {b.key: b for b in blocks}
    print(f"Venues — build((2016, 2026)): first {t_first*1000:.0f} ms, warm {t_warm*1000:.0f} ms")
    print("Blocks:", ", ".join(f"{b.key} — {b.title}" for b in blocks))

    # §01 Ground profiles
    p: list[str] = []
    n = compare_block(by["ven_01"], "B9:W17", p)
    if by["ven_01"].title != cell(SHEET, "B7"):
        p.append(f"title {by['ven_01'].title!r} != {cell(SHEET, 'B7')!r}")
    if by["ven_01"].bold_rows != [7]:
        p.append(f"bold_rows {by['ven_01'].bold_rows}")
    r = by["ven_01"].rules
    for col in ("Chase win %", "Toss winner won %"):
        if r.get(col) != {"good": (">=", 0.60), "bad": ("<=", 0.45)}:
            p.append(f"rule for {col}: {r.get(col)}")
    # §03 chart = G10:G16 by venue
    ch = by["ven_01"].chart
    chart_want = [row[0] for row in grid(SHEET, "G10:G16")]
    chart_got = ch["data"][ch["y"]].tolist()
    n += len(chart_want)
    if ch["title"] != "Average first-innings score — selected span" or ch["type"] != "hbar":
        p.append(f"chart meta {ch['type']} {ch['title']!r}")
    if [round(x, 6) for x in chart_got] != [round(x, 6) for x in chart_want]:
        p.append(f"chart values {chart_got} != {chart_want}")
    if ch["data"]["Venue"].tolist() != [row[0] for row in grid(SHEET, "B10:B16")]:
        p.append("chart categories differ")
    ok &= report("ven_01 Ground profiles (+ §03 chart)", p, n)

    # §02 Heat map
    p = []
    n = compare_block(by["ven_02"], "B20:M27", p)
    if by["ven_02"].title != cell(SHEET, "B19"):
        p.append(f"title {by['ven_02'].title!r} != {cell(SHEET, 'B19')!r}")
    if by["ven_02"].note != cell(SHEET, "G19"):
        p.append(f"note {by['ven_02'].note!r} != {cell(SHEET, 'G19')!r}")
    if getattr(by["ven_02"], "muted_cols", None) != []:
        p.append(f"muted_cols for full span: {getattr(by['ven_02'], 'muted_cols', None)}")
    ok &= report("ven_02 Avg first-innings heat map", p, n)

    # How to read
    p = []
    want = " ".join(_norm_text(cell(SHEET, f"B{r}")) for r in (47, 48, 49))
    if _norm_text(by["ven_howto"].text) != want:
        p.append("how-to-read text differs")
    ok &= report("ven_howto How to read", p, 1)

    p = []
    n = check_structure(blocks, p)
    n += spot_check((2016, 2026), blocks, p)
    ok &= report("structure + independent recomputation (2016–2026)", p, n)

    # Smoke runs
    print("Smoke runs:")
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2019, 2017), (2030, 2031)]:
        p = []
        try:
            t0 = time.perf_counter()
            bl = mod.build(span)
            dt = (time.perf_counter() - t0) * 1000
            n = check_structure(bl, p)
            for b in bl:
                if b.df is not None and list(b.df.columns) != list(by[b.key].df.columns):
                    p.append(f"{b.key}: columns differ from full span")
            n += spot_check(span, bl, p)
        except Exception as e:  # noqa: BLE001
            p.append(f"exception: {type(e).__name__}: {e}")
            n, dt = 0, float("nan")
        ok &= report(f"span {span}  ({dt:.0f} ms)", p, n)

    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
