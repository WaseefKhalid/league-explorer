"""Validate analytics/bowling.py against the workbook's "Bowling" sheet, cell by cell."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from analytics import bowling as mod  # noqa: E402
import analytics.data as d  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Bowling"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and math.isnan(v))


def same(a, b, fmt: str | None) -> bool:
    """a = ours, b = workbook value."""
    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    if isinstance(b, str) or isinstance(a, str):
        if isinstance(a, str) and isinstance(b, str):
            return a == b
        # numeric shown as text in the workbook (e.g. Overs "382.0")
        return fmt is not None and fmt.format(float(a if not isinstance(a, str) else b)) == (b if isinstance(b, str) else a)
    a, b = float(a), float(b)
    if abs(a - b) <= 1e-9 * max(1.0, abs(b)):
        return True
    return fmt is not None and fmt.format(a) == fmt.format(b)


def compare(name, df, wb_rows, cols, fmt, labels=None, max_show=8):
    bad = []
    if len(df) != len(wb_rows):
        bad.append(f"row count {len(df)} != workbook {len(wb_rows)}")
    for i, wrow in enumerate(wb_rows[: len(df)]):
        for j, c in enumerate(cols):
            if c is None:
                continue
            ours = df.iloc[i][c]
            if labels is not None and c in labels.columns and isinstance(labels.iloc[i][c], str):
                ours = labels.iloc[i][c]
            if not same(ours, wrow[j], fmt.get(c)):
                bad.append(f"row {i} ({df.iloc[i, 0]}) [{c}]: ours={ours!r} wb={wrow[j]!r}")
    status = "PASS" if not bad else "FAIL"
    print(f"{status}  {name}: {len(df)} rows x {len(cols)} cols, {len(bad)} mismatches")
    for b in bad[:max_show]:
        print("     ", b)
    return not bad


def main() -> int:
    d.player_seasons(); d.players()  # warm the loaders
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    ms = (time.perf_counter() - t0) * 1000
    by = {b.key: b for b in blocks}
    ok = True

    # bowl_intro: how-to-read rows B8:B11
    txt = by["bowl_intro"].text
    wb_txt = [r[0] for r in grid(SHEET, "B8:B11")]
    good = all(t in txt for t in wb_txt)
    print(("PASS" if good else "FAIL") + "  bowl_intro: how-to-read text")
    ok &= good

    b = by["bowl_all"]
    sub_ok = b.note == cell(SHEET, "B3")
    print(("PASS" if sub_ok else "FAIL") + f"  bowl_all subtitle: {b.note!r}")
    ok &= sub_ok
    # header check (workbook names → ours)
    hdr = grid(SHEET, "B14:AP14")[0]
    print("      header map:", {h: c for h, c in zip(hdr, mod.COLUMNS) if h != c})
    ok &= compare("bowl_all", b.df, grid(SHEET, "B15:AP313"), mod.COLUMNS, b.fmt)

    # league helper cells BI7:BO7
    lg = mod.league((2016, 2026))
    wb_lg = grid(SHEET, "BI7:BO7")[0]
    ours_lg = [lg[k] for k in ("econ", "avg", "sr", "PP", "MO1", "MO2", "Death")]
    lg_ok = all(abs(a - b) < 1e-9 for a, b in zip(ours_lg, wb_lg))
    print(("PASS" if lg_ok else "FAIL") + "  league thresholds BI7:BO7")
    ok &= lg_ok

    # rules sanity: every rule column exists
    rok = all(c in b.df.columns for c in b.rules) and all(c in b.df.columns for c in b.fmt)
    print(("PASS" if rok else "FAIL") + f"  rules ({len(b.rules)} columns) / fmt reference real columns")
    ok &= rok

    print(f"build((2016, 2026)) {ms:.0f} ms")
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2030, 2031)]:
        t0 = time.perf_counter()
        bl = mod.build(span)
        ms = (time.perf_counter() - t0) * 1000
        df = bl[1].df
        assert list(df.columns) == mod.COLUMNS
        print(f"smoke {span}: {len(df)} rows, {ms:.0f} ms, note={bl[1].note!r}")
    print("ALL PASS" if ok else "SOME FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
