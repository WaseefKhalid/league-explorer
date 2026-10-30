"""
Validate analytics/key_insights.py against the workbook's "Key Insights" sheet.

    cd /home/claude/waseefkhalid/cricsheet && python3 tests/check_key_insights.py

For span (2016, 2026) every table cell (headers, row labels, numbers) is
compared with the cached workbook values: text exact, numbers equal after
rounding to the cell's displayed precision. Titles/notes are checked against
the sheet text and each column's `fmt` against the workbook number format.
Then build() is smoke-run for a few other spans.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from openpyxl.utils.cell import range_boundaries  # noqa: E402

import analytics.data as d  # noqa: E402
from analytics import key_insights as ki  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Key Insights"

# key -> (title row, header row, data range incl. the label column B)
LAYOUT = {
    "ki_01": (7, 9, "B10:D12"),
    "ki_02": (14, 16, "B17:D20"),
    "ki_03": (22, 24, "B25:F30"),
    "ki_04": (32, 34, "B35:G39"),
    "ki_05": (41, 43, "B44:D51"),
    "ki_06": (53, 55, "B56:D57"),
    "ki_07": (59, 61, "B62:G65"),
    "ki_08": (67, 69, "B70:F78"),
    "ki_09": (80, 82, "B83:E88"),
    "ki_10": (90, 92, "B93:E97"),
    "ki_11": (99, 101, "B102:H103"),
    "ki_12": (105, 107, "B108:E110"),
    "ki_13": (112, 114, "B115:F120"),
    "ki_14": (122, 124, "B125:E126"),
    "ki_15": (128, 130, "B131:E142"),
    "ki_16": (144, 146, "B147:F152"),
    "ki_17": (154, 156, "B157:E164"),
    "ki_18": (165, 167, "B168:G173"),
}

# workbook number format -> (decimals to compare at, expected Python fmt)
NUMFMT = {
    "0": (0, {"{:,.0f}", "{:.0f}"}),
    "#,##0": (0, {"{:,.0f}"}),
    "0.0": (1, {"{:,.1f}", "{:.1f}"}),
    "0.00": (2, {"{:,.2f}", "{:.2f}"}),
    "0%": (2, {"{:.0%}"}),
    "0.0%": (3, {"{:.1%}"}),
    "+0.0;-0.0": (1, {"{:+.1f}"}),
}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v in ("", "—")) or (isinstance(v, float) and math.isnan(v))


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def _same(mine, xl, nf: str) -> bool:
    if _blank(mine) and _blank(xl):
        return True
    if _num(mine) and _num(xl):
        dp = NUMFMT.get(nf, (9, None))[0]
        return round(float(mine), dp) == round(float(xl), dp) or abs(float(mine) - float(xl)) < 1e-9
    if isinstance(mine, str) and isinstance(xl, str):
        return mine == xl
    return False


def check_full_span() -> bool:
    blocks = {b.key: b for b in ki.build((2016, 2026))}
    keys = [b for b in blocks if b.startswith("ki_") and b[3:].isdigit()]
    assert keys == list(LAYOUT), f"block keys/order: {keys}"
    all_ok, total = True, 0
    for key, (trow, hrow, rng) in LAYOUT.items():
        b = blocks[key]
        c0, r0, c1, r1 = range_boundaries(rng)
        cols = f"{rng[0]}{hrow}:{rng.split(':')[1].rstrip('0123456789')}{hrow}"
        bad: list[str] = []
        n = 0

        # title / note
        title, note = grid(SHEET, f"B{trow}:B{trow + 1}")
        n += 2
        if b.title != title[0]:
            bad.append(f"title {b.title!r} != {title[0]!r}")
        if b.note != note[0]:
            bad.append(f"note {b.note!r} != {note[0]!r}")

        # headers
        hdr = grid(SHEET, cols)[0]
        n += len(hdr)
        if list(b.df.columns) != hdr:
            bad.append(f"headers {list(b.df.columns)} != {hdr}")

        # cells
        vals = grid(SHEET, rng)
        fmts = grid(SHEET, rng, formulas="numfmt")
        if len(b.df) != len(vals):
            bad.append(f"rows {len(b.df)} != {len(vals)}")
        for i, (xrow, frow) in enumerate(zip(vals, fmts)):
            for j, (xv, nf) in enumerate(zip(xrow, frow)):
                n += 1
                mine = b.df.iat[i, j] if i < len(b.df) and j < b.df.shape[1] else None
                if hasattr(mine, "item"):
                    mine = mine.item()
                if not _same(mine, xv, nf):
                    bad.append(f"{chr(64 + c0 + j)}{r0 + i}: mine={mine!r} xl={xv!r} ({nf})")

        # fmt for every numeric column matches the workbook's number format
        for j, colname in enumerate(b.df.columns):
            col_fmts = {fr[j] for fr in fmts} - {"General"}
            if not col_fmts or not pd.api.types.is_numeric_dtype(b.df[colname]):
                continue
            n += 1
            nf = col_fmts.pop()
            want = NUMFMT.get(nf, (None, set()))[1]
            if b.fmt.get(colname) not in want:
                bad.append(f"fmt[{colname!r}]={b.fmt.get(colname)!r} want one of {want} ({nf})")

        total += n
        status = "PASS" if not bad else "FAIL"
        all_ok &= not bad
        print(f"{key}  {status}  {n:4d} checks  {b.title[:70]}")
        for msg in bad[:6]:
            print("      ", msg)
    # §15 mute/bold, ki_read footnote
    b15 = blocks["ki_15"]
    ok15 = b15.muted_rows == [] and b15.bold_rows == [len(b15.df) - 1]
    rd = blocks.get("ki_read")
    xl_read = [r[0] for r in grid(SHEET, "B175:B178")]
    ok_read = rd is not None and rd.title == xl_read[0] and rd.text == "\n\n".join(xl_read[1:])
    print(f"extras  {'PASS' if ok15 and ok_read else 'FAIL'}  (§15 muted/bold rows, How-to-read text)")
    all_ok &= ok15 and ok_read
    print(f"\nFull span 2016–2026: {total} checks — {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def check_calc() -> bool:
    """Calc!A2:T460 (the span sums + ranking keys §17/§18 use) vs ki._calc."""
    mine = ki._calc((2016, 2026))
    xl = grid("Calc", "A2:T460")
    hdr = grid("Calc", "G1:T1")[0]
    cols = ["B b1-10", "R b1-10", "B b21+", "R b21+", "Gear key", "B Death", "R Death",
            "Death SR key", "BB MO1", "BR MO1", "MO1 econ key", "BB Death", "BR Death",
            "Death econ key"]
    bad, n = [], 0
    if len(mine) != len(xl):
        bad.append(f"rows {len(mine)} != {len(xl)}")
    for i, xrow in enumerate(xl):
        n += 1
        if mine.index[i] != xrow[0]:
            bad.append(f"A{i + 2}: {mine.index[i]!r} != {xrow[0]!r}")
        for j, c in enumerate(cols):
            n += 1
            a, b = float(mine[c].iat[i]), float(xrow[6 + j])
            if abs(a - b) > 1e-12 * max(1.0, abs(b)):
                bad.append(f"{hdr[j]} row {i + 2} ({xrow[0]}): mine={a!r} xl={b!r}")
    print(f"calc   {'PASS' if not bad else 'FAIL'}  {n:4d} checks  Calc!A2:T460 span sums + ranking keys")
    for msg in bad[:6]:
        print("      ", msg)
    return not bad


def smoke() -> bool:
    ok = True
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2026, 2016)]:
        try:
            blocks = ki.build(span)
            keys = [b.key for b in blocks]
            assert keys[:18] == list(LAYOUT), keys
            for b in blocks:
                if b.df is not None:
                    assert list(b.df.columns) == list(b.df.columns.unique()), b.key
                    for c in b.fmt:
                        assert c in b.df.columns, (b.key, c)
            b15 = next(b for b in blocks if b.key == "ki_15")
            lo, hi = min(span), max(span)
            exp_muted = [i for i, s in enumerate(d.seasons()) if not lo <= s <= hi]
            assert b15.muted_rows == exp_muted, (b15.muted_rows, exp_muted)
            sizes = {b.key: (0 if b.df is None else len(b.df)) for b in blocks}
            print(f"smoke {span}: OK  ki_17 rows={sizes['ki_17']}  ki_18 rows={sizes['ki_18']}")
        except Exception as e:  # pragma: no cover
            ok = False
            print(f"smoke {span}: EXCEPTION {type(e).__name__}: {e}")
    return ok


def timing() -> None:
    ki.build((2016, 2026))                       # warm caches (data + arrays)
    t = []
    for _ in range(5):
        t0 = time.perf_counter()
        ki.build((2016, 2026))
        t.append((time.perf_counter() - t0) * 1000)
    print(f"build((2016, 2026)) timing: best {min(t):.0f} ms, median {sorted(t)[2]:.0f} ms")


if __name__ == "__main__":
    ok = check_full_span()
    ok &= check_calc()
    ok &= smoke()
    timing()
    sys.exit(0 if ok else 1)
