"""Validate analytics/potm.py against the workbook's 'Player of the Match' sheet.

Run from the repo root:  python3 tests/check_potm.py
"""
from __future__ import annotations

import datetime as dt
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from analytics import potm  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Player of the Match"
# key -> (title cell, header row, first data row, last data row, first col, last col)
RANGES = {
    "potm_01": ("B10", 11, 12, 31, "B", "J"),
    "potm_02": ("B33", 34, 35, 42, "C", "J"),
    "potm_03": ("B44", 45, 46, 49, "C", "I"),
    "potm_04": ("B51", 52, 53, 54, "C", "G"),
    "potm_05": ("B56", 57, 58, 67, "B", "I"),
    "potm_06": ("B69", 70, 71, 81, "B", "H"),
}


def _blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v == ""
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _fmt(fmt: str | None, v) -> str:
    if fmt is None:
        return str(v)
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return str(v)


def same(mine, wb, fmt: str | None, label=None) -> bool:
    if isinstance(wb, str) and wb == "—":            # IFERROR(...,"—")
        return _blank(mine) and label == "—"
    if _blank(wb):
        return _blank(mine)
    if _blank(mine):
        return False
    if isinstance(wb, (dt.datetime, dt.date)):
        return pd.Timestamp(mine) == pd.Timestamp(wb)
    if isinstance(wb, str):
        return isinstance(mine, str) and mine == wb
    if isinstance(mine, str):
        return False
    a, b = float(mine), float(wb)
    if abs(a - b) < 1e-9:
        return True
    return _fmt(fmt, a) == _fmt(fmt, b)


def check_table(block, hdr_row, r0, r1, c0, c1, mism):
    hdr = grid(SHEET, f"{c0}{hdr_row}:{c1}{hdr_row}")[0]
    if list(block.df.columns) != hdr:
        mism.append(f"{block.key} header {list(block.df.columns)} != {hdr}")
    rows = grid(SHEET, f"{c0}{r0}:{c1}{r1}")
    df, n = block.df, 0
    has_rank = df.columns[0] == "#"
    for i, wrow in enumerate(rows):
        if i < len(df):
            for j, col in enumerate(df.columns):
                n += 1
                lab = None if block.labels is None else block.labels.iloc[i, j]
                if not same(df.iloc[i, j], wrow[j], block.fmt.get(col), lab):
                    mism.append(f"{block.key} r{r0 + i} {col}: mine={df.iloc[i, j]!r} wb={wrow[j]!r}")
        else:
            for j, v in enumerate(wrow[1 if has_rank else 0:]):
                n += 1
                if not _blank(v):
                    mism.append(f"{block.key} r{r0 + i} extra workbook value {v!r}")
    return n


def main() -> int:
    t0 = time.perf_counter()
    blocks = potm.build((2016, 2026))
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    blocks = potm.build((2016, 2026))
    t_warm = time.perf_counter() - t0
    by = {b.key: b for b in blocks}
    total, ok_all = 0, True

    for key, (tcell, h, r0, r1, c0, c1) in RANGES.items():
        b = by[key]
        mism: list[str] = []
        title = grid(SHEET, f"{tcell}:{tcell}")[0][0]
        if b.title != title:
            mism.append(f"{key} title {b.title!r} != {title!r}")
        n = check_table(b, h, r0, r1, c0, c1, mism)
        total += n
        ok_all &= not mism
        print(f"{key:8s} {'PASS' if not mism else 'FAIL'}  cells={n}  rows={len(b.df)}")
        for m in mism[:8]:
            print("   ", m)

    # muted rows of §06 for a narrower span (CF rule B71:H81)
    b6 = {b.key: b for b in potm.build((2019, 2022))}["potm_06"]
    want = [i for i, s in enumerate(range(2016, 2027)) if s < 2019 or s > 2022]
    good = b6.muted_rows == want
    ok_all &= good
    print(f"potm_06 muted rows (2019-22) {'PASS' if good else 'FAIL'} {b6.muted_rows}")

    # KPI strip (row 7 labels, row 8 values)
    k = by["potm_kpis"]
    labels = grid(SHEET, "C7:K7")[0]
    vals = grid(SHEET, "C8:K8")[0]
    fmts = ["{:,.0f}", "{:,.0f}", "{:.1%}", "{:,.0f}", "{:.1%}"]
    mism = []
    for i, (kp, f) in enumerate(zip(k.kpis, fmts)):
        total += 1
        lab, wv = labels[2 * i], vals[2 * i]
        if kp[0] != lab or kp[1] != f.format(wv):
            mism.append(f"kpi {lab!r}: mine=({kp[0]!r}, {kp[1]!r}) wb={f.format(wv)!r}")
    ok_all &= not mism
    print(f"potm_kpis {'PASS' if not mism else 'FAIL'}  cells=5")
    for m in mism:
        print("   ", m)

    howto = " ".join(r[0] for r in grid(SHEET, "B84:B85"))
    good = " ".join(by["potm_howto"].text.split()) == " ".join(howto.split())
    ok_all &= good
    print(f"potm_howto {'PASS' if good else 'FAIL'}")

    print(f"\nTOTAL cells checked: {total}  ->  {'PASS' if ok_all else 'FAIL'}")
    print(f"build() first call {t_first * 1000:.0f} ms (incl. data load), warm {t_warm * 1000:.0f} ms")

    for sp in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2022, 2020), (2030, 2031)]:
        t0 = time.perf_counter()
        bl = potm.build(sp)
        ms = (time.perf_counter() - t0) * 1000
        sizes = ", ".join(f"{b.key}:{len(b.df)}" for b in bl if b.df is not None)
        print(f"smoke {sp}: OK {ms:.0f} ms  [{sizes}]")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
