"""Validate analytics/best_batting.py against the workbook's 'Best Batting Seasons' sheet.

Run from the repo root:  python3 tests/check_best_batting.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from analytics import best_batting  # noqa: E402
from analytics import data as d  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Best Batting Seasons"
HDR_ROW, R0, R1, C0, C1 = 12, 13, 162, "B", "S"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and math.isnan(v))


def _fmt(fmt, v) -> str:
    if fmt is None:
        return str(v)
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def same(mine, wb, fmt) -> bool:
    if _blank(wb):
        return _blank(mine)
    if _blank(mine):
        return False
    if isinstance(wb, str) or isinstance(mine, str):
        return isinstance(wb, str) and isinstance(mine, str) and mine == wb
    a, b = float(mine), float(wb)
    return abs(a - b) < 1e-9 or _fmt(fmt, a) == _fmt(fmt, b)


def shown(block, i, col):
    if block.labels is not None:
        lab = block.labels.iloc[i][col]
        if not _blank(lab):
            return lab
    return block.df.iloc[i][col]


def check_full():
    t = time.perf_counter()
    blocks = best_batting.build((2016, 2026))
    ms = (time.perf_counter() - t) * 1000
    b = {x.key: x for x in blocks}["bbs_top150"]
    mism = []
    if grid(SHEET, "B2:B2")[0][0] != b.title:
        mism.append(f"title {b.title!r}")
    want_note = grid(SHEET, "B3:B3")[0][0] + ". " + " ".join(r[0] for r in grid(SHEET, "B8:B9"))
    if b.note != want_note:
        mism.append(f"note {b.note!r} != {want_note!r}")
    hdr = grid(SHEET, f"{C0}{HDR_ROW}:{C1}{HDR_ROW}")[0]
    if list(b.df.columns) != hdr:
        mism.append(f"header {list(b.df.columns)} != {hdr}")
    groups = grid(SHEET, f"{C0}11:{C1}11")[0]
    wb_groups, cur = {}, None
    for col, g in zip(b.df.columns, groups):
        cur = g or cur
        wb_groups.setdefault(cur, []).append(col)
    if wb_groups != best_batting.GROUPS:
        mism.append(f"groups {best_batting.GROUPS} != {wb_groups}")
    rows = grid(SHEET, f"{C0}{R0}:{C1}{R1}")
    if len(b.df) != len(rows):
        mism.append(f"row count {len(b.df)} != {len(rows)}")
    n = 0
    for i, wrow in enumerate(rows[: len(b.df)]):
        for j, col in enumerate(b.df.columns):
            n += 1
            mine = shown(b, i, col)
            if not same(mine, wrow[j], b.fmt.get(col)):
                mism.append(f"r{R0 + i} {col}: mine={mine!r} wb={wrow[j]!r}")
    for col in b.df.columns:
        if pd.api.types.is_numeric_dtype(b.df[col]) and col not in b.fmt:
            mism.append(f"no fmt for {col}")
    return {"bbs_top150": (n, mism)}, ms


def smoke():
    out = []
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017)]:
        t = time.perf_counter()
        df = best_batting.build(span)[0].df
        ms = (time.perf_counter() - t) * 1000
        assert list(df.columns) == best_batting.COLUMNS
        assert len(df) <= 150 and df["Season"].between(min(span), max(span)).all()
        assert df["Runs"].is_monotonic_decreasing
        out.append(f"  {span}: {len(df)} rows, {ms:.0f} ms")
    df = best_batting.build((2030, 2031))[0].df
    assert df.empty and list(df.columns) == best_batting.COLUMNS
    out.append("  (2030, 2031): empty df OK")
    return out


def main():
    d.player_seasons()
    results, ms = check_full()
    ok = True
    for key, (n, mism) in results.items():
        status = "PASS" if not mism else "FAIL"
        ok &= not mism
        print(f"{key:12s} {status}  ({n} cells checked, {len(mism)} mismatches)")
        for m in mism[:8]:
            print("    ", m)
    print(f"build((2016, 2026)) {ms:.0f} ms")
    print("smoke:")
    for line in smoke():
        print(line)
    print("ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
