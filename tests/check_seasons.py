"""Validate analytics/seasons.py against the workbook's "Seasons" sheet (span 2016–2026)."""
from __future__ import annotations

import math
import sys
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

import analytics.data as d  # noqa: E402
from analytics import seasons as mod  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Seasons"
BLANK = {None, "", "—", "–"}


def _decimals(fmt: str | None) -> int | None:
    if not fmt:
        return None
    import re
    m = re.search(r"\.(\d+)([f%])", fmt)
    if not m:
        return None
    n = int(m.group(1))
    return n + 2 if m.group(2) == "%" else n


def xl_round(x: float, nd: int) -> Decimal:
    v = Decimal(format(float(x), ".15g"))
    return v.quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)


def same(ours, theirs, fmt: str | None) -> bool:
    o_blank = ours is None or (isinstance(ours, float) and math.isnan(ours)) or ours in BLANK
    if theirs in BLANK or o_blank:
        return o_blank and theirs in BLANK
    if isinstance(theirs, (int, float)) and not isinstance(theirs, bool):
        if isinstance(ours, str):
            return ours == str(int(theirs)) if float(theirs).is_integer() else False
        nd = _decimals(fmt)
        if nd is None:
            nd = 0
        return xl_round(ours, nd) == xl_round(theirs, nd)
    return str(ours) == str(theirs)


def compare(name, df: pd.DataFrame, cols: list[str], wb_rows: list[list], fmt: dict) -> list[str]:
    bad = []
    if len(df) != len(wb_rows):
        bad.append(f"{name}: row count {len(df)} v workbook {len(wb_rows)}")
    for i, row in enumerate(wb_rows[: len(df)]):
        for j, c in enumerate(cols):
            ours = df.iloc[i][c]
            if not same(ours, row[j], fmt.get(c)):
                bad.append(f"{name}: row {i} [{c}] ours={ours!r} workbook={row[j]!r}")
    return bad


def main() -> int:
    for t in ("ball", "matches", "team_matches", "player_seasons", "lists"):
        d.load(t)
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    mod.build((2016, 2026))
    ms2 = (time.perf_counter() - t0) * 1000
    by = {b.key: b for b in blocks}
    results = {}

    # §01 Season summary  B9:X22
    b = by["sea_01"]
    hdr = grid(SHEET, "B9:X9")[0]
    bad = [] if list(b.df.columns) == hdr else [f"sea_01 headers {list(b.df.columns)} v {hdr}"]
    bad += compare("sea_01", b.df, list(b.df.columns), grid(SHEET, "B10:X22"), b.fmt)
    if b.muted_rows != []:
        bad.append(f"sea_01 muted_rows {b.muted_rows}")
    if b.bold_rows != [11]:
        bad.append(f"sea_01 bold_rows {b.bold_rows}")
    results["sea_01"] = bad

    # §02 Trends (chart source ranges B10:B20, J10:J20, L10:O20)
    b = by["sea_02a"]
    wb = [[r[0], r[8]] for r in grid(SHEET, "B10:J20")]
    results["sea_02a"] = compare("sea_02a", b.df, ["Season", "Avg 1st-inns"], wb, b.fmt)
    b = by["sea_02b"]
    wb = [[r[0]] + r[10:14] for r in grid(SHEET, "B10:O20")]
    results["sea_02b"] = compare("sea_02b", b.df, ["Season", "PP RR", "MO1 RR", "MO2 RR", "Death RR"], wb, b.fmt)

    ok = True
    for k, bad in results.items():
        print(f"{k:10s} {'PASS' if not bad else 'FAIL'}" + (f"  ({len(bad)} mismatches)" if bad else ""))
        for x in bad[:8]:
            print("    ", x)
        ok &= not bad

    # smoke runs
    for sp in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2022, 2018)]:
        t0 = time.perf_counter()
        bl = mod.build(sp)
        t = (time.perf_counter() - t0) * 1000
        s01 = bl[0]
        print(f"smoke {sp}: {len(bl)} blocks, {t:.0f} ms, muted={s01.muted_rows}, "
              f"span row={s01.df.iloc[11][['Edition', 'Teams', 'Matches', 'Top run-scorer', 'Top wicket-taker']].tolist()}")
    print(f"build((2016, 2026)): first {ms:.0f} ms, warm {ms2:.0f} ms")
    print("ALL PASS" if ok else "SOME FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
