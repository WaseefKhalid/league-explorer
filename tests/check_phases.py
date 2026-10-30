"""
Validate analytics/phases.py against the workbook's "Phases" sheet.

    cd /home/claude/waseefkhalid/cricsheet && python3 tests/check_phases.py

* build((2016, 2026)) is compared cell by cell with the workbook's cached
  values (text exact, numbers equal after rounding to the displayed format),
  plus the conditional-formatting thresholds and the chart series.
* Smoke runs for other spans, with spot checks against a direct SUMIFS-style
  recomputation from Ball Data (the workbook only caches 2016–2026).
"""
from __future__ import annotations

import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analytics.data as d  # noqa: E402
from analytics import phases as mod  # noqa: E402
from tools.xlcheck import grid, cell  # noqa: E402

SHEET = "Phases"
FMT_MAP = {"0": "{:,.0f}", "0.0": "{:,.1f}", "0.00": "{:,.2f}", "0%": "{:.0%}",
           "0.0%": "{:.1%}", "#,##0": "{:,.0f}"}
# Identifier columns shown with Excel format '0' (season, over number): compared
# exactly and deliberately left without a thousands-separator fmt ("2,016").
IDENT = {"Season", "Over"}


# ── generic cell-by-cell comparison ──────────────────────────────────────────
def _norm_text(x) -> str:
    return re.sub(r"\s+", " ", str(x)).strip()


def _blank(x) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    return isinstance(x, str) and x.strip() in ("", "—")


def compare_block(blk, rng: str, problems: list[str]) -> int:
    vals = grid(SHEET, rng)
    fmts = grid(SHEET, rng, formulas="numfmt")
    head, rows, frow = vals[0], vals[1:], fmts[1:]
    df = blk.df
    n = 0
    if len(head) != len(df.columns):
        problems.append(f"{blk.key}: {len(df.columns)} columns, workbook has {len(head)}")
    for j, (h, c) in enumerate(zip(head, df.columns)):
        n += 1
        if _norm_text(h) != _norm_text(c):
            problems.append(f"{blk.key}: header {j}: got {c!r}, workbook {h!r}")
    if len(rows) != len(df):
        problems.append(f"{blk.key}: {len(df)} rows, workbook has {len(rows)}")
    for i, (wr, fr) in enumerate(zip(rows, frow)):
        for j, col in enumerate(df.columns):
            n += 1
            want, got = wr[j], df.iloc[i, j]
            nf = fr[j]
            if _blank(want) or _blank(got):
                if not (_blank(want) and _blank(got)):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
                continue
            if isinstance(want, str) or isinstance(got, str):
                if _norm_text(want) != _norm_text(got):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
                continue
            f = FMT_MAP.get(nf)
            if col in IDENT:              # identifiers (2016, over 7): exact, no fmt
                if not _close(got, want):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
                continue
            if f is not None:
                if blk.fmt.get(col) != f:
                    problems.append(f"{blk.key}: fmt for {col!r} is {blk.fmt.get(col)!r}, "
                                    f"workbook {nf!r} → {f!r}")
                if f.format(float(got)) != f.format(float(want)):
                    problems.append(f"{blk.key}[{i},{col}]: got {f.format(float(got))}, "
                                    f"workbook {f.format(float(want))}")
            else:
                if not math.isclose(float(got), float(want), rel_tol=1e-9, abs_tol=1e-9):
                    problems.append(f"{blk.key}[{i},{col}]: got {got!r}, workbook {want!r}")
    return n


def report(name: str, problems: list[str], n: int) -> bool:
    ok = not problems
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({n} cells/checks)")
    for p in problems[:8]:
        print("        ", p)
    if len(problems) > 8:
        print(f"         … {len(problems) - 8} more")
    return ok


def _close(a, b) -> bool:
    if _blank(a) and _blank(b):
        return True
    if _blank(a) or _blank(b):
        return False
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)


def _rule_thr(rule, row):
    """threshold from a rules entry (scalar or per-row Series)."""
    op, thr = rule
    return op, (thr.loc[row] if isinstance(thr, pd.Series) else thr)


# ── independent SUMIFS-style recomputation for any span ──────────────────────
def _sumifs(col, span=None, **eq):
    b = d.ball()
    m = pd.Series(True, index=b.index)
    if span is not None:
        m &= (b["Season"] >= min(span)) & (b["Season"] <= max(span))
    for k, v in eq.items():
        k = {"phase": "Phase", "ps": "Pace/Spin", "btype": "Bowler Type", "hand": "Bat Hand",
             "over": "Over", "season": "Season"}[k]
        if isinstance(v, str) and v.startswith("<>"):
            m &= b[k] != v[2:]
        else:
            m &= b[k] == v
    return float(b.loc[m, col].sum())


def _q(a, b, s=1.0):
    return a * s / b if b else np.nan


def spot_check(span, blocks, problems) -> int:
    by = {b.key: b for b in blocks}
    n = 0

    def chk(label, got, want):
        nonlocal n
        n += 1
        if not _close(got, want):
            problems.append(f"{span} {label}: got {got!r}, expected {want!r}")

    lo, hi = min(span), max(span)
    tr = by["ph_01"].df
    sel = tr.index[tr["Season"] == "Selected span"][0]
    for p in d.PHASES:
        chk(f"ph_01 Selected span {p} RR", tr.loc[sel, f"{p} Run rate"],
            _q(_sumifs("Total Runs", span, phase=p), _sumifs("Legal Ball", span, phase=p), 6))
        chk(f"ph_01 Selected span {p} Balls/wkt", tr.loc[sel, f"{p} Balls/wkt"],
            _q(_sumifs("Legal Ball", span, phase=p), _sumifs("Wicket", span, phase=p)))
        chk(f"ph_01 Selected span {p} Spin %", tr.loc[sel, f"{p} Spin %"],
            _q(_sumifs("Legal Ball", span, phase=p, ps="Spin"), _sumifs("Legal Ball", span, phase=p)))
    # muted / bold rows
    exp_muted = [i for i, s in enumerate(d.seasons()) if s < lo or s > hi]
    n += 2
    if by["ph_01"].muted_rows != exp_muted:
        problems.append(f"{span} ph_01 muted_rows {by['ph_01'].muted_rows} != {exp_muted}")
    if by["ph_01"].bold_rows != [len(d.seasons()), len(d.seasons()) + 1]:
        problems.append(f"{span} ph_01 bold_rows {by['ph_01'].bold_rows}")

    ov = by["ph_02"].df.set_index("Over")
    for o in (1, 7, 15, 20):
        chk(f"ph_02 over {o} RPO", ov.loc[o, "Runs / over"],
            _q(_sumifs("Total Runs", span, over=o), _sumifs("Legal Ball", span, over=o), 6))
        chk(f"ph_02 over {o} Dot %", ov.loc[o, "Dot %"],
            _q(_sumifs("Bowl Dot", span, over=o), _sumifs("Legal Ball", span, over=o)))
        chk(f"ph_02 over {o} Spin share", ov.loc[o, "Spin share"],
            _q(_sumifs("Legal Ball", span, over=o, ps="Spin"), _sumifs("Legal Ball", span, over=o)))

    ec = by["ph_03"].df.set_index("Bowling type")
    bw = by["ph_04"].df.set_index("Bowling type")
    sh = by["ph_05"].df.set_index("Bowling type")
    for t in ("Leg-spin", "Left-arm wrist-spin", "Right-arm pace"):
        for p in ("PP", "Death"):
            col = mod.PHASE_HEAD[p]
            chk(f"ph_03 {t} {p}", ec.loc[t, col],
                _q(_sumifs("Bowler Runs", span, btype=t, phase=p),
                   _sumifs("Legal Ball", span, btype=t, phase=p), 6))
            chk(f"ph_04 {t} {p}", bw.loc[t, col],
                _q(_sumifs("Legal Ball", span, btype=t, phase=p),
                   _sumifs("Bowler Wkt", span, btype=t, phase=p)))
            chk(f"ph_05 {t} {p}", sh.loc[t, col],
                _q(_sumifs("Legal Ball", span, btype=t, phase=p),
                   _sumifs("Legal Ball", span, btype="<>Unknown", phase=p)))
    for p in d.PHASES:
        col = mod.PHASE_HEAD[p]
        chk(f"ph_03 All types {p}", ec.loc["All types", col],
            _q(_sumifs("Bowler Runs", span, btype="<>Unknown", phase=p),
               _sumifs("Legal Ball", span, btype="<>Unknown", phase=p), 6))

    ht = by["ph_06"].df
    for h in d.HANDS:
        for t in ("Off-spin", "Left-arm pace"):
            row = ht[(ht["Batter hand"] == h) & (ht["Bowling type"] == t)].iloc[0]
            faced = _sumifs("Ball Faced", span, hand=h, btype=t)
            chk(f"ph_06 {h} v {t} Balls", row["Balls"], faced)
            chk(f"ph_06 {h} v {t} SR", row["Strike rate"],
                _q(_sumifs("Bat Runs", span, hand=h, btype=t), faced, 100))
            chk(f"ph_06 {h} v {t} Balls/wkt", row["Balls / wkt"],
                _q(faced, _sumifs("Bowler Wkt", span, hand=h, btype=t)))
    avg = _q(_sumifs("Bat Runs", span, btype="<>Unknown", hand="<>Unknown"),
             _sumifs("Ball Faced", span, btype="<>Unknown", hand="<>Unknown"), 100)
    r = by["ph_06"].rules.get("Strike rate")
    if not _blank(avg):
        chk("ph_06 SR green threshold", r["good"][1], avg * 0.93)
        chk("ph_06 SR pink threshold", r["bad"][1], avg * 1.02)
    return n


def check_structure(blocks, problems) -> int:
    for b in blocks:
        if b.df is not None and not isinstance(b.df.index, pd.RangeIndex):
            problems.append(f"{b.key}: index is not a RangeIndex")
    return len(blocks)


def main() -> int:
    ok = True
    t0 = time.perf_counter()
    blocks = mod.build((2016, 2026))
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(5):
        blocks = mod.build((2016, 2026))
    t_warm = (time.perf_counter() - t0) / 5
    by = {b.key: b for b in blocks}
    print(f"Phases — build((2016, 2026)): first {t_first*1000:.0f} ms, warm {t_warm*1000:.0f} ms")
    print("Blocks:", ", ".join(f"{b.key} — {b.title}" for b in blocks))

    sections = [
        ("ph_01", "B9:R22", "B7", "G7"),
        ("ph_02", "B25:I45", "B24", None),
        ("ph_03", "B48:F55", "B47", "G47"),
        ("ph_04", "B58:F65", "B57", "G57"),
        ("ph_05", "B68:F74", "B67", "G67"),
        ("ph_06", "B77:H89", "B76", "G76"),
    ]
    for key, rng, tcell, ncell in sections:
        p: list[str] = []
        blk = by[key]
        n = compare_block(blk, rng, p)
        if blk.title != cell(SHEET, tcell):
            p.append(f"title {blk.title!r} != {cell(SHEET, tcell)!r}")
        if ncell and blk.note != cell(SHEET, ncell):
            p.append(f"note {blk.note!r} != {cell(SHEET, ncell)!r}")

        # conditional formatting mirrors
        if key == "ph_01":
            n += 3
            if blk.muted_rows != []:
                p.append(f"muted_rows for full span: {blk.muted_rows}")
            if blk.bold_rows != [11, 12]:
                p.append(f"bold_rows {blk.bold_rows}")
            if blk.good_high != ["PP Run rate", "MO1 Run rate", "MO2 Run rate", "Death Run rate"]:
                p.append(f"colour-scale columns {blk.good_high}")
            for col, xl in zip(blk.good_high, "CGKO"):
                n += 1
                med = float(np.median([r[0] for r in grid(SHEET, f"{xl}10:{xl}20")]))
                if not _close(blk.center.get(col), med):
                    p.append(f"centre for {col}: {blk.center.get(col)} != {med}")
        if key == "ph_02":
            n += 3
            if blk.bars != ["Wkts / over"] or blk.good_high != ["Runs / over"]:
                p.append(f"bars {blk.bars} / colour scale {blk.good_high}")
            med = float(np.median([r[0] for r in grid(SHEET, "D26:D45")]))
            if not _close(blk.center.get("Runs / over"), med):
                p.append("colour-scale centre for Runs / over")
            ch = blk.chart
            if (ch["type"] != "line" or ch["title"] != "Runs per over, over by over"
                    or ch["x"] != "Over" or ch["y"] != ["RPO — all seasons", "Runs / over"]):
                p.append(f"chart meta {ch}")
        if key in ("ph_03", "ph_04"):
            top = int(rng[1:3]) + 1           # first data row
            all_row = top + 6                 # "All types" row
            for j, xl in enumerate("CDEF"):
                col = blk.df.columns[j + 1]
                ref = cell(SHEET, f"{xl}{all_row}")
                for i in range(6):
                    n += 2
                    op_g, thr_g = _rule_thr(blk.rules[col]["good"], i)
                    op_b, thr_b = _rule_thr(blk.rules[col]["bad"], i)
                    if op_g != "<=" or not _close(thr_g, ref * 0.95):
                        p.append(f"{col} row {i} green threshold {thr_g} != {ref*0.95}")
                    if op_b != ">=" or not _close(thr_b, ref * 1.05):
                        p.append(f"{col} row {i} pink threshold {thr_b} != {ref*1.05}")
                n += 1
                _, thr_all = _rule_thr(blk.rules[col]["good"], 6)
                if not _blank(thr_all):
                    p.append(f"{col}: All types row should carry no threshold")
            if blk.bold_rows != [6]:
                p.append(f"bold_rows {blk.bold_rows}")
        if key == "ph_05":
            n += 1
            if blk.bars != list(blk.df.columns[1:]):
                p.append(f"bars {blk.bars}")
        if key == "ph_06":
            n += 2
            b = d.ball()
            k = b[(b["Bowler Type"] != "Unknown") & (b["Bat Hand"] != "Unknown")]
            avg = 100 * k["Bat Runs"].sum() / k["Ball Faced"].sum()
            r = blk.rules["Strike rate"]
            if r["good"][0] != "<=" or not _close(r["good"][1], avg * 0.93):
                p.append(f"SR green rule {r['good']} (avg {avg})")
            if r["bad"][0] != ">=" or not _close(r["bad"][1], avg * 1.02):
                p.append(f"SR pink rule {r['bad']} (avg {avg})")
            # tint outcome must match the workbook's CF on E78:E89
            for i, sr in enumerate(blk.df["Strike rate"]):
                n += 1
                want = "good" if sr <= avg * 0.93 else "bad" if sr >= avg * 1.02 else "mid"
                got = ("good" if sr <= r["good"][1] else "bad" if sr >= r["bad"][1] else "mid")
                if want != got:
                    p.append(f"row {i} tint {got} != {want}")
        ok &= report(f"{key} {blk.title}", p, n)

    # chart series vs workbook (I26:I45 'All seasons', D26:D45 'Selected span')
    p = []
    ch = by["ph_02"].chart
    data = ch.get("data", by["ph_02"].df)
    want_all = [r[0] for r in grid(SHEET, "I26:I45")]
    want_sel = [r[0] for r in grid(SHEET, "D26:D45")]
    if not all(_close(a, b) for a, b in zip(data["RPO — all seasons"], want_all)):
        p.append("All seasons series differs")
    if not all(_close(a, b) for a, b in zip(data["Runs / over"], want_sel)):
        p.append("Selected span series differs")
    if ch["labels"].get("RPO — all seasons") != "All seasons" or ch["labels"].get("Runs / over") != "Selected span":
        p.append(f"series names {ch['labels']}")
    ok &= report("ph_02 chart 'Runs per over, over by over'", p, 40)

    p = []
    want = " ".join(_norm_text(cell(SHEET, f"B{r}")) for r in (92, 93, 94))
    if _norm_text(by["ph_howto"].text) != want:
        p.append("how-to-read text differs")
    ok &= report("ph_howto How to read", p, 1)

    p = []
    n = check_structure(blocks, p)
    n += spot_check((2016, 2026), blocks, p)
    ok &= report("structure + independent recomputation (2016–2026)", p, n)

    print("Smoke runs:")
    for span in [(2016, 2016), (2020, 2022), (2026, 2026), (2016, 2017), (2022, 2019), (2030, 2031)]:
        p = []
        try:
            t0 = time.perf_counter()
            bl = mod.build(span)
            dt = (time.perf_counter() - t0) * 1000
            n = check_structure(bl, p)
            for b in bl:
                if b.df is not None and list(b.df.columns) != list(by[b.key].df.columns):
                    p.append(f"{b.key}: columns differ from full span")
            n += spot_check(span, bl, p)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            p.append(f"exception: {type(e).__name__}: {e}")
            n, dt = 0, float("nan")
        ok &= report(f"span {span}  ({dt:.0f} ms)", p, n)

    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
