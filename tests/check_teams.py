"""Validate analytics/teams.py against the workbook's "Teams" sheet (span 2016–2026)."""
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
from analytics import teams as mod  # noqa: E402
from tools.xlcheck import grid  # noqa: E402

SHEET = "Teams"
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
    for t in ("ball", "matches", "team_matches", "lists"):
        d.load(t)
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    mod.build((2016, 2026))
    ms2 = (time.perf_counter() - t0) * 1000
    by = {b.key: b for b in blocks}
    res = {}

    # §01 Record  B8:Q16
    b = by["team_01"]
    hdr = grid(SHEET, "B8:Q8")[0]
    bad = [] if list(b.df.columns) == hdr else [f"headers {list(b.df.columns)} v {hdr}"]
    bad += compare("team_01", b.df, list(b.df.columns), grid(SHEET, "B9:Q16"), b.fmt)
    res["team_01"] = bad

    # §02 Season-by-season finish  B19:M27 (labels: workbook's line break shown as " · ")
    b = by["team_02"]
    wb = grid(SHEET, "B19:M27")
    bad = []
    if [str(x) for x in wb[0][1:]] != list(b.df.columns[1:]) or list(b.labels.columns) != list(b.df.columns):
        bad.append(f"team_02 season columns {list(b.df.columns)} v {wb[0]}")
    for i, row in enumerate(wb[1:]):
        if b.df.iloc[i, 0] != row[0] or b.labels.iloc[i, 0] != row[0]:
            bad.append(f"team_02 team order {b.df.iloc[i, 0]!r} v {row[0]!r}")
        for j, txt in enumerate(row[1:]):
            ours = b.labels.iloc[i, j + 1]
            exp = str(txt).replace("\n", mod.FINISH_SEP)
            if ours != exp:
                bad.append(f"team_02 {row[0]} {wb[0][j+1]}: ours={ours!r} workbook={txt!r}")
            rank = b.df.iloc[i, j + 1]
            er = mod.FINISH_RANK.get(str(txt).split("\n")[0], np.nan)
            if not (np.isnan(rank) and np.isnan(er)) and rank != er:
                bad.append(f"team_02 rank {row[0]} {wb[0][j+1]}: {rank} v {er}")
    if b.muted_cols or b.muted_rows:
        bad.append(f"team_02 muted {b.muted_cols} {b.muted_rows}")
    res["team_02"] = bad

    # §03 Head-to-head  B30:J38 (labels exact; numbers = wins/(wins+losses))
    b = by["team_03"]
    wb = grid(SHEET, "B30:J38")
    bad = [] if list(b.labels.columns[1:]) == wb[0][1:] else [f"h2h cols {list(b.labels.columns)}"]
    bad += compare("team_03 labels", b.labels, list(b.labels.columns), wb[1:], {}, strict_text=True)
    for i, row in enumerate(wb[1:]):
        for j, txt in enumerate(row[1:]):
            m = re.fullmatch(r"(\d+) – (\d+)", str(txt))
            ours = b.df.iloc[i, j + 1]
            if m and int(m.group(1)) + int(m.group(2)) > 0:
                exp = int(m.group(1)) / (int(m.group(1)) + int(m.group(2)))
                if not math.isclose(ours, exp, abs_tol=1e-12):
                    bad.append(f"team_03 num {row[0]} v {wb[0][j+1]}: {ours} v {exp}")
            elif not np.isnan(ours):
                bad.append(f"team_03 num {row[0]} v {wb[0][j+1]}: {ours} v blank")
    res["team_03"] = bad

    # §04 Phase profile  B42:J50
    b = by["team_04"]
    hdr = grid(SHEET, "B42:J42")[0]
    bad = [] if list(b.df.columns) == hdr else [f"headers {list(b.df.columns)} v {hdr}"]
    bad += compare("team_04", b.df, list(b.df.columns), grid(SHEET, "B43:J50"), b.fmt)
    res["team_04"] = bad

    # §05 SR v types  B53:H62 ; §06 BPW  B65:H74
    for key, rng_h, rng in (("team_05", "B53:H53", "B54:H62"), ("team_06", "B65:H65", "B66:H74")):
        b = by[key]
        hdr = grid(SHEET, rng_h)[0]
        bad = [] if list(b.df.columns) == hdr else [f"headers {list(b.df.columns)} v {hdr}"]
        bad += compare(key, b.df, list(b.df.columns), grid(SHEET, rng), b.fmt)
        res[key] = bad

    # CF thresholds sanity: phase rules use the eight-team average
    b = by["team_04"]
    avg = np.mean([r[0] for r in grid(SHEET, "C43:C50")])
    if not math.isclose(b.rules["Bat PP"]["good"][1], avg * 1.03, rel_tol=1e-12):
        res["team_04"].append("CF threshold Bat PP mismatch")

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
        r = bl[0].df
        print(f"smoke {sp}: {len(bl)} blocks, {t:.0f} ms, played={r['Played'].astype(int).tolist()}, "
              f"muted finish cols={bl[1].muted_cols}")
    print(f"build((2016, 2026)): first {ms:.0f} ms, warm {ms2:.0f} ms")
    print("ALL PASS" if ok else "SOME FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
