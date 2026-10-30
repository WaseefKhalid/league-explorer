"""Validate analytics/batting.py against the workbook's 'Batting' sheet.

Run from the repo root:  python3 tests/check_batting.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from analytics import batting  # noqa: E402
from analytics import data as d  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Batting"
HDR_ROW, R0, R1, C0, C1 = 14, 15, 441, "B", "AM"


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
    """Cell as displayed: the label where one is set, else the number/text."""
    if block.labels is not None:
        lab = block.labels.iloc[i][col]
        if not _blank(lab):
            return lab
    return block.df.iloc[i][col]


def check_full():
    t = time.perf_counter()
    blocks = batting.build((2016, 2026))
    ms = (time.perf_counter() - t) * 1000
    by = {b.key: b for b in blocks}
    results = {}

    # bat_intro: how-to-read text (B7 title, B8:B11 lines)
    mism = []
    b = by["bat_intro"]
    wb_lines = [r[0] for r in grid(SHEET, "B8:B11")]
    if grid(SHEET, "B7:B7")[0][0] != b.title:
        mism.append(f"title {b.title!r}")
    if b.text != "\n".join(f"- {t}" for t in wb_lines):
        mism.append(f"text {b.text!r} != {wb_lines!r}")
    results["bat_intro"] = (4, mism)

    # bat_all: header, subtitle, every cell B15:AM441
    mism = []
    b = by["bat_all"]
    if grid(SHEET, "B2:B2")[0][0] != b.title:
        mism.append(f"title {b.title!r}")
    if grid(SHEET, "B3:B3")[0][0] != b.note:
        mism.append(f"note {b.note!r} != {grid(SHEET, 'B3:B3')[0][0]!r}")
    hdr = grid(SHEET, f"{C0}{HDR_ROW}:{C1}{HDR_ROW}")[0]
    mine_hdr = [batting.WB_HEADERS[c] for c in b.df.columns]
    if mine_hdr != hdr:
        mism.append(f"header {mine_hdr} != {hdr}")
    groups = grid(SHEET, f"{C0}13:{C1}13")[0]
    wb_groups = {}
    cur = None
    for col, g in zip(b.df.columns, groups):
        cur = g or cur
        wb_groups.setdefault(cur, []).append(col)
    if wb_groups != batting.GROUPS:
        mism.append(f"groups {batting.GROUPS} != {wb_groups}")
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
    # number formats present for every numeric column
    for col in b.df.columns:
        if pd.api.types.is_numeric_dtype(b.df[col]) and col not in b.fmt:
            mism.append(f"no fmt for {col}")
    # league figures behind the tints (BI7:BV7)
    lg = batting.league((2016, 2026))
    wb_lg = grid(SHEET, "BI7:BV7")[0]
    keys = ["SR", "Avg", "PP SR", "MO1 SR", "MO2 SR", "Death SR", "SR v RA pace", "SR v LA pace",
            "SR v off-spin", "SR v leg-spin", "SR v LA orthodox", "SR v LA wrist-spin",
            "SR v pace", "SR v spin"]
    for k, v in zip(keys, wb_lg):
        n += 1
        if abs(lg[k] - v) > 1e-9:
            mism.append(f"league {k}: mine={lg[k]} wb={v}")
    results["bat_all"] = (n, mism)
    return results, ms


def smoke():
    out = []
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2026, 2016)]:
        t = time.perf_counter()
        blocks = batting.build(span)
        ms = (time.perf_counter() - t) * 1000
        df = blocks[1].df
        assert list(df.columns) == batting.COLUMNS
        assert (df["Inns"] > 0).all()
        out.append(f"  {span}: {len(df)} rows, {ms:.0f} ms")
    # a span with no data must still return the table with the same columns
    blocks = batting.build((2030, 2031))
    assert blocks[1].df.empty and list(blocks[1].df.columns) == batting.COLUMNS
    out.append("  (2030, 2031): empty df OK")
    return out


def main():
    d.player_seasons(); d.players()  # load before timing
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
