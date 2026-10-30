"""Validate analytics/impact.py against the workbook's 'Impact' sheet.

Run from the repo root:  python3 tests/check_impact.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from analytics import impact  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Impact"
# key -> (header row, first data row, last data row, first col, last col)
RANGES = {
    "imp_01": (16, 17, 41, "B", "J"),
    "imp_02": (44, 45, 69, "B", "J"),
    "imp_03": (72, 73, 87, "B", "I"),
    "imp_04": (90, 91, 105, "B", "K"),
    "imp_05": (108, 109, 120, "B", "H"),
    "imp_06": (123, 124, 135, "B", "G"),
    "imp_07": (138, 139, 150, "B", "G"),
}
TITLES = {"imp_01": "B15", "imp_02": "B43", "imp_03": "B71", "imp_04": "B89",
          "imp_05": "B107", "imp_06": "B122", "imp_07": "B137"}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and math.isnan(v))


def _fmt(fmt: str | None, v) -> str:
    if fmt is None:
        return str(v)
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def same(mine, wb, fmt: str | None) -> bool:
    if _blank(wb):
        return _blank(mine)
    if _blank(mine):
        return False
    if isinstance(wb, str):
        if isinstance(mine, str):
            return mine == wb
        return _fmt(fmt, mine).replace(",", "") == wb.replace(",", "")
    if isinstance(mine, str):
        return False
    a, b = float(mine), float(wb)
    if abs(a - b) < 1e-9:
        return True
    return _fmt(fmt, a) == _fmt(fmt, b)


def check_table(block, hdr_row, r0, r1, c0, c1, mism):
    hdr = grid(SHEET, f"{c0}{hdr_row}:{c1}{hdr_row}")[0]
    n = 0
    if list(block.df.columns) != hdr:
        mism.append(f"{block.key} header {list(block.df.columns)} != {hdr}")
    rows = grid(SHEET, f"{c0}{r0}:{c1}{r1}")
    df = block.df
    for i, wrow in enumerate(rows):
        if i < len(df):
            for j, col in enumerate(df.columns):
                n += 1
                mine = df.iloc[i, j]
                if not same(mine, wrow[j], block.fmt.get(col)):
                    mism.append(f"{block.key} r{r0 + i} {col}: mine={mine!r} wb={wrow[j]!r}")
        else:  # workbook row must be blank apart from the static '#'
            for j, v in enumerate(wrow[1:], start=1):
                n += 1
                if not _blank(v):
                    mism.append(f"{block.key} r{r0 + i} extra workbook value {v!r} (col {j})")
    return n


def main() -> int:
    t0 = time.perf_counter()
    blocks = impact.build((2016, 2026))
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    blocks = impact.build((2016, 2026))
    t_warm = time.perf_counter() - t0
    by = {b.key: b for b in blocks}
    total, ok_all = 0, True

    for key, (h, r0, r1, c0, c1) in RANGES.items():
        b = by[key]
        mism: list[str] = []
        title = grid(SHEET, f"{TITLES[key]}:{TITLES[key]}")[0][0]
        if b.title != title:
            mism.append(f"{key} title {b.title!r} != {title!r}")
        n = check_table(b, h, r0, r1, c0, c1, mism)
        total += n
        ok_all &= not mism
        print(f"{key:8s} {'PASS' if not mism else 'FAIL'}  cells={n}  rows={len(b.df)}")
        for m in mism[:8]:
            print("   ", m)

    # KPI strip (row 12 labels, row 13 values)
    k = by["imp_kpis"]
    labels = grid(SHEET, "C12:L12")[0]
    vals = grid(SHEET, "C13:L13")[0]
    exp = [(labels[i], vals[i]) for i in (0, 2, 5, 7, 9)]
    fmts = [None, None, "{:,.0f}", "{:.1%}", "{:.1f}"]
    mism = []
    for (lab, wv), (ml, mv, _), f in zip(exp, k.kpis, fmts):
        total += 1
        want = wv if f is None else f.format(wv)
        if ml != lab or mv != want:
            mism.append(f"kpi {lab!r}: mine=({ml!r}, {mv!r}) wb={want!r}")
    ok_all &= not mism
    print(f"imp_kpis {'PASS' if not mism else 'FAIL'}  cells={len(exp)}")
    for m in mism:
        print("   ", m)

    # Text blocks
    intro = " ".join(r[0] for r in grid(SHEET, "B8:B10"))
    howto = " ".join(r[0] for r in grid(SHEET, "B153:B155"))
    for key, want in (("imp_intro", intro), ("imp_howto", howto)):
        got = " ".join(by[key].text.split())
        good = got == " ".join(want.split())
        ok_all &= good
        print(f"{key:9s} {'PASS' if good else 'FAIL'}")

    print(f"\nTOTAL cells checked: {total}  ->  {'PASS' if ok_all else 'FAIL'}")
    print(f"build() first call {t_first * 1000:.0f} ms (incl. data load), warm {t_warm * 1000:.0f} ms")

    # Smoke runs
    for sp in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2022, 2020)]:
        t0 = time.perf_counter()
        bl = impact.build(sp)
        dt = (time.perf_counter() - t0) * 1000
        sizes = ", ".join(f"{b.key}:{len(b.df)}" for b in bl if b.df is not None)
        print(f"smoke {sp}: OK {dt:.0f} ms  [{sizes}]")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
