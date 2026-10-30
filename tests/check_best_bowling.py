"""Validate analytics/best_bowling.py against the workbook's "Best Bowling Seasons" sheet, cell by cell."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics import best_bowling as mod  # noqa: E402
import analytics.data as d  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Best Bowling Seasons"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and math.isnan(v))


def same(a, b, fmt):
    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(b, str):  # numeric shown as text in the workbook (Overs)
        return fmt is not None and fmt.format(float(a)) == b
    if isinstance(a, str):
        return False
    a, b = float(a), float(b)
    return abs(a - b) <= 1e-9 * max(1.0, abs(b)) or (fmt is not None and fmt.format(a) == fmt.format(b))


def compare(name, df, wb_rows, cols, fmt, max_show=8):
    bad = []
    if len(df) != len(wb_rows):
        bad.append(f"row count {len(df)} != workbook {len(wb_rows)}")
    for i, wrow in enumerate(wb_rows[: len(df)]):
        for j, c in enumerate(cols):
            if not same(df.iloc[i][c], wrow[j], fmt.get(c)):
                bad.append(f"row {i} [{c}]: ours={df.iloc[i][c]!r} wb={wrow[j]!r}")
    print(f"{'PASS' if not bad else 'FAIL'}  {name}: {len(df)} rows x {len(cols)} cols, {len(bad)} mismatches")
    for b in bad[:max_show]:
        print("     ", b)
    return not bad


def main() -> int:
    d.player_seasons()
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    ms = (time.perf_counter() - t0) * 1000
    b = blocks[0]
    ok = True
    hdr = grid(SHEET, "B12:R12")[0]
    hok = hdr == mod.COLUMNS
    print(("PASS" if hok else "FAIL") + f"  header row: {hdr}")
    ok &= hok
    nok = cell(SHEET, "B3") in b.note and all(t in b.note for t in (cell(SHEET, "B8"), cell(SHEET, "B9")))
    print(("PASS" if nok else "FAIL") + "  subtitle / how-to-read text")
    ok &= nok
    ok &= compare("bws_top150", b.df, grid(SHEET, "B13:R162"), mod.COLUMNS, b.fmt)
    print(f"build((2016, 2026)) {ms:.0f} ms")
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2030, 2031)]:
        t0 = time.perf_counter()
        df = mod.build(span)[0].df
        assert list(df.columns) == mod.COLUMNS
        assert df.empty or (df["Season"].between(min(span), max(span)).all() and df["Wkts"].is_monotonic_decreasing)
        print(f"smoke {span}: {len(df)} rows, {(time.perf_counter() - t0) * 1000:.0f} ms")
    print("ALL PASS" if ok else "SOME FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
