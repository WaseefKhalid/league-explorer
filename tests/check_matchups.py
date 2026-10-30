"""Validate analytics/matchups.py against the workbook's "Matchups" sheet, cell by cell."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics import matchups as mod  # noqa: E402
import analytics.data as d  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Matchups"


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and math.isnan(v))


def same(a, b, fmt):
    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    a, b = float(a), float(b)
    return abs(a - b) <= 1e-9 * max(1.0, abs(b)) or (fmt is not None and fmt.format(a) == fmt.format(b))


def compare(name, df, labels, wb_rows, cols, fmt, max_show=8):
    bad = []
    if len(df) != len(wb_rows):
        bad.append(f"row count {len(df)} != workbook {len(wb_rows)}")
    vals = df.to_numpy(object)
    labs = labels.to_numpy(object) if labels is not None else None
    for i, wrow in enumerate(wb_rows[: len(df)]):
        for j, c in enumerate(cols):
            ours = vals[i, j]
            if labs is not None and isinstance(labs[i, j], str):
                ours = labs[i, j]
            if not same(ours, wrow[j], fmt.get(c) if not isinstance(ours, str) else None):
                bad.append(f"row {i} ({vals[i, 0]} v {vals[i, 2]}) [{c}]: ours={ours!r} wb={wrow[j]!r}")
    print(f"{'PASS' if not bad else 'FAIL'}  {name}: {len(df)} rows x {len(cols)} cols, {len(bad)} mismatches")
    for b in bad[:max_show]:
        print("     ", b)
    return not bad


def main() -> int:
    d.pair_seasons(); d.player_seasons(); d.players()
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    ms = (time.perf_counter() - t0) * 1000
    by = {b.key: b for b in blocks}
    ok = True

    txt = by["mu_intro"].text
    tok = all(t in txt for t in (cell(SHEET, "B8"), cell(SHEET, "B9")))
    print(("PASS" if tok else "FAIL") + "  mu_intro: how-to-read rows 8–9")
    ok &= tok

    b = by["mu_all"]
    sok = b.note == cell(SHEET, "B3")
    print(("PASS" if sok else "FAIL") + f"  mu_all subtitle: {b.note!r}")
    ok &= sok
    hdr = grid(SHEET, "B12:P12")[0]
    hok = hdr == mod.COLUMNS
    print(("PASS" if hok else "FAIL") + "  header row")
    ok &= hok
    ok &= compare("mu_all", b.df, b.labels, grid(SHEET, "B13:P1916"), mod.COLUMNS, b.fmt)

    edge_counts = b.labels["Edge"].value_counts().to_dict()
    print(f"build((2016, 2026)) {ms:.0f} ms · Edge counts {edge_counts}")
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2030, 2031)]:
        t0 = time.perf_counter()
        bl = mod.build(span)[1]
        df = bl.df
        assert list(df.columns) == mod.COLUMNS
        assert bl.labels.shape == df.shape
        assert df.empty or (df["Balls"] >= 12).all() and df["Balls"].is_monotonic_decreasing
        print(f"smoke {span}: {len(df)} rows, {(time.perf_counter() - t0) * 1000:.0f} ms, note={bl.note!r}")
    print("ALL PASS" if ok else "SOME FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
