"""Validate analytics/toss_chasing.py against the workbook's "Toss & Chasing" sheet (span 2016–2026)."""
from __future__ import annotations

import math
import re
import sys
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analytics.data as d  # noqa: E402
from analytics import toss_chasing as mod  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Toss & Chasing"
BLANK = {None, "", "—", "–"}


def _decimals(fmt: str | None) -> int | None:
    if not fmt:
        return None
    m = re.search(r"\.(\d+)([f%])", fmt)
    if not m:
        return None
    n = int(m.group(1))
    return n + 2 if m.group(2) == "%" else n


def xl_round(x: float, nd: int) -> Decimal:
    v = Decimal(format(float(x), ".15g"))
    return v.quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)


def is_blank(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and v in BLANK)


def same(ours, theirs, fmt: str | None) -> bool:
    if is_blank(theirs) or is_blank(ours):
        return is_blank(ours) and is_blank(theirs)
    if isinstance(theirs, (int, float)) and not isinstance(theirs, bool):
        if isinstance(ours, str):
            return float(theirs).is_integer() and ours == str(int(theirs))
        return xl_round(ours, _decimals(fmt) or 0) == xl_round(theirs, _decimals(fmt) or 0)
    return str(ours) == str(theirs)


def compare(name, df: pd.DataFrame, cols: list[str], wb_rows: list[list], fmt: dict,
            strict_text: bool = False) -> list[str]:
    bad = []
    if len(df) != len(wb_rows):
        bad.append(f"{name}: row count {len(df)} v workbook {len(wb_rows)}")
    for i, row in enumerate(wb_rows[: len(df)]):
        for j, c in enumerate(cols):
            ours = df.iloc[i][c]
            ok = (str(ours) == str(row[j])) if strict_text else same(ours, row[j], fmt.get(c))
            if not ok:
                bad.append(f"{name}: row {i} [{c}] ours={ours!r} workbook={row[j]!r}")
    return bad


def main() -> int:
    for t in ("matches", "team_matches", "lists"):
        d.load(t)
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    mod.build((2016, 2026))
    ms2 = (time.perf_counter() - t0) * 1000
    by = {b.key: b for b in blocks}
    res = {}

    def table(key, rng_h, rng):
        b = by[key]
        hdr = grid(SHEET, rng_h)[0]
        bad = [] if list(b.df.columns) == hdr else [f"{key} headers {list(b.df.columns)} v {hdr}"]
        bad += compare(key, b.df, list(b.df.columns), grid(SHEET, rng), b.fmt)
        return bad

    # §01 by season B8:I21 ; §02 by venue B24:I32
    res["toss_01"] = table("toss_01", "B8:I8", "B9:I21")
    if by["toss_01"].muted_rows or by["toss_01"].bold_rows != [11]:
        res["toss_01"].append(f"muted/bold {by['toss_01'].muted_rows} {by['toss_01'].bold_rows}")
    res["toss_02"] = table("toss_02", "B24:I24", "B25:I32")

    # §03 Par score guide B35:J40: numbers where the workbook shows a number, labels everywhere
    b = by["toss_03"]
    wb = grid(SHEET, "B35:J40")
    bad = [] if list(b.df.columns) == wb[0] else [f"toss_03 headers {list(b.df.columns)} v {wb[0]}"]
    for i, row in enumerate(wb[1:]):
        for j, v in enumerate(row):
            c = b.df.columns[j]
            ours_n, ours_l = b.df.iloc[i][c], b.labels.iloc[i][c]
            if j == 0:
                if ours_n != v or ours_l != v:
                    bad.append(f"toss_03 row label {ours_n!r} v {v!r}")
            elif isinstance(v, (int, float)):
                if not same(ours_n, v, "{:.0%}"):
                    bad.append(f"toss_03 {row[0]} [{c}] num {ours_n!r} v {v!r}")
                exp = f"{xl_round(v * 100, 0)}%"
                if ours_l != exp:
                    bad.append(f"toss_03 {row[0]} [{c}] label {ours_l!r} v {exp!r}")
            else:
                if not (isinstance(ours_n, float) and math.isnan(ours_n)) or ours_l != v:
                    bad.append(f"toss_03 {row[0]} [{c}] text ours=({ours_n!r}, {ours_l!r}) v {v!r}")
    res["toss_03"] = bad

    # §04 / §05 chase calculators: win % C:G (numbers) and chases (n) H:L (parsed from labels)
    for key, rng in (("toss_04", "B45:L51"), ("toss_05", "B55:L61")):
        b = by[key]
        wb = grid(SHEET, rng)
        bad = [] if list(b.df.columns) == wb[0][:6] else [f"{key} headers {list(b.df.columns)} v {wb[0][:6]}"]
        for i, row in enumerate(wb[1:]):
            if b.df.iloc[i, 0] != row[0] or b.labels.iloc[i, 0] != row[0]:
                bad.append(f"{key} row label {b.df.iloc[i, 0]!r} v {row[0]!r}")
            for j in range(5):
                c = b.df.columns[j + 1]
                pct, n = row[1 + j], row[6 + j]
                ours_n, ours_l = b.df.iloc[i][c], b.labels.iloc[i][c]
                if not same(ours_n, pct, "{:.0%}"):
                    bad.append(f"{key} {row[0]} [{c}] pct {ours_n!r} v {pct!r}")
                exp = (f"{xl_round(pct * 100, 0)}% ({n})" if isinstance(pct, (int, float)) else f"{pct} ({n})")
                if ours_l != exp:
                    bad.append(f"{key} {row[0]} [{c}] label {ours_l!r} v {exp!r}")
        res[key] = bad

    # §06 PP wickets B64:F69 ; §07 League v playoffs B72:D74
    res["toss_06"] = table("toss_06", "B64:F64", "B65:F69")
    res["toss_07"] = table("toss_07", "B72:D72", "B73:D74")

    ok = True
    for k, bad in res.items():
        print(f"{k:10s} {'PASS' if not bad else 'FAIL'}" + (f"  ({len(bad)} mismatches)" if bad else ""))
        for x in bad[:8]:
            print("    ", x)
        ok &= not bad

    for sp in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017)]:
        t0 = time.perf_counter()
        bl = mod.build(sp)
        t = (time.perf_counter() - t0) * 1000
        print(f"smoke {sp}: {len(bl)} blocks, {t:.0f} ms, span row={bl[0].df.iloc[11, 1:4].tolist()}, "
              f"par All<160={bl[2].labels.iloc[0, 1]!r}, chase15 ≤30 all={bl[3].labels.iloc[0, 5]!r}")
    print(f"build((2016, 2026)): first {ms:.0f} ms, warm {ms2:.0f} ms")
    print("ALL PASS" if ok else "SOME FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
