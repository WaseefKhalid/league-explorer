"""Validate analytics/players_list.py against the workbook's 'Players' sheet.

Run from the repo root:  python3 tests/check_players_list.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from analytics import data as d  # noqa: E402
from analytics import players_list  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Players"
HDR_ROW, R0, R1, C0, C1 = 13, 14, 472, "B", "U"


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


def check_full():
    t = time.perf_counter()
    blocks = players_list.build((2016, 2026))
    ms = (time.perf_counter() - t) * 1000
    by = {b.key: b for b in blocks}
    results = {}

    mism = []
    b = by["pl_intro"]
    wb_lines = [r[0] for r in grid(SHEET, "B8:B10")]
    if grid(SHEET, "B7:B7")[0][0] != b.title:
        mism.append(f"title {b.title!r}")
    if b.text != "\n".join(f"- {t}" for t in wb_lines):
        mism.append(f"text {b.text!r} != {wb_lines!r}")
    results["pl_intro"] = (3, mism)

    mism = []
    b = by["pl_all"]
    if grid(SHEET, "B2:B2")[0][0] != b.title:
        mism.append(f"title {b.title!r}")
    if grid(SHEET, "B3:B3")[0][0] != b.note:
        mism.append(f"note {b.note!r} != {grid(SHEET, 'B3:B3')[0][0]!r}")
    hdr = grid(SHEET, f"{C0}{HDR_ROW}:{C1}{HDR_ROW}")[0]
    if list(b.df.columns) != hdr:
        mism.append(f"header {list(b.df.columns)} != {hdr}")
    groups = grid(SHEET, f"{C0}12:{C1}12")[0]
    wb_groups, cur = {}, None
    for col, g in zip(b.df.columns, groups):
        cur = g or cur
        wb_groups.setdefault(cur, []).append(col)
    if wb_groups != players_list.GROUPS:
        mism.append(f"groups {players_list.GROUPS} != {wb_groups}")
    rows = grid(SHEET, f"{C0}{R0}:{C1}{R1}")
    if len(b.df) != len(rows):
        mism.append(f"row count {len(b.df)} != {len(rows)}")
    n = 0
    for i, wrow in enumerate(rows[: len(b.df)]):
        for j, col in enumerate(b.df.columns):
            n += 1
            mine = b.df.iloc[i, j]
            if not same(mine, wrow[j], b.fmt.get(col)):
                mism.append(f"r{R0 + i} {col}: mine={mine!r} wb={wrow[j]!r}")
    for col in b.df.columns:
        if pd.api.types.is_numeric_dtype(b.df[col]) and col not in b.fmt:
            mism.append(f"no fmt for {col}")
    results["pl_all"] = (n, mism)
    return results, ms


def smoke():
    out = []
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017)]:
        t = time.perf_counter()
        blocks = players_list.build(span)
        ms = (time.perf_counter() - t) * 1000
        b = blocks[1]
        assert list(b.df.columns) == players_list.COLUMNS and len(b.df) == 459
        out.append(f"  {span}: {len(b.df)} rows ({len(b.df) - len(b.muted_rows)} with matches), {ms:.0f} ms")
    b = players_list.build((2030, 2031))[1]
    assert len(b.df) == 459 and (b.df["Matches"] == 0).all()
    out.append("  (2030, 2031): no-data span OK (all muted)")
    return out


def main():
    d.player_seasons(); d.players()
    results, ms = check_full()
    ok = True
    for key, (n, mism) in results.items():
        status = "PASS" if not mism else "FAIL"
        ok &= not mism
        print(f"{key:10s} {status}  ({n} cells checked, {len(mism)} mismatches)")
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
