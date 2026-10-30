"""Validate analytics/explore_venue.py against the workbook ('Venue Explorer').

Run from the repo root:  python3 tests/check_explore_venue.py
"""
from __future__ import annotations

import itertools
import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import analytics.explore_venue as mod  # noqa: E402
from analytics.explore_venue import xl_fmt  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Venue Explorer"
DASH = "—"


# ── generic comparison helpers ───────────────────────────────────────────────
def _nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def cmp_table(block, rng):
    """Header row + data rows of `rng` v block.df, every cell."""
    vals = grid(SHEET, rng)
    fmts = grid(SHEET, rng, formulas="numfmt")
    bad = []
    hdr = list(vals[0])
    if hdr != list(block.df.columns):
        bad.append(f"header {hdr} != {list(block.df.columns)}")
    rows = vals[1:]
    if len(rows) != len(block.df):
        bad.append(f"rows {len(rows)} != {len(block.df)}")
    for i, (xr, fr) in enumerate(zip(rows, fmts[1:])):
        if i >= len(block.df):
            break
        for j, col in enumerate(block.df.columns):
            xv, nf, mv = xr[j], fr[j] or "General", block.df.iloc[i, j]
            if xv == DASH or xv is None:
                ok = _nan(mv) or mv == DASH
            elif isinstance(xv, str):
                ok = (mv == xv)
            elif _nan(mv):
                ok = False
            elif nf in ("General", "@"):
                ok = abs(float(mv) - float(xv)) < 1e-9
            else:
                ok = xl_fmt(float(mv), nf) == xl_fmt(float(xv), nf)
            if not ok:
                bad.append(f"r{i} {col}: mine={mv!r} xl={xv!r} ({nf})")
    return bad


def cmp_kpis(block, cells):
    """cells: list of (label_ref, value_ref) in tile order."""
    bad = []
    if len(cells) != len(block.kpis):
        bad.append(f"tiles {len(block.kpis)} != {len(cells)}")
    for (lref, vref), (lab, val, _sub) in zip(cells, block.kpis):
        xl_lab = cell(SHEET, lref)
        xv = cell(SHEET, vref)
        nf = cell(SHEET, vref, formulas="numfmt") or "General"
        exp = xv if isinstance(xv, str) else xl_fmt(xv, nf)
        if xl_lab != lab:
            bad.append(f"label {lref}: {lab!r} != {xl_lab!r}")
        if exp != val:
            bad.append(f"{lab} ({vref}): mine={val!r} xl={exp!r}")
    return bad


def tiles(rows_lab_val, cols="EGIKM"):
    out = []
    for lr, vr in rows_lab_val:
        out += [(f"{c}{lr}", f"{c}{vr}") for c in cols]
    return out


def run_checks(checks, blocks):
    ok_all = True
    for key, (kind, spec) in checks.items():
        b = blocks.get(key)
        if b is None:
            print(f"FAIL {key}: missing block")
            ok_all = False
            continue
        bad = cmp_kpis(b, spec) if kind == "kpis" else cmp_table(b, spec)
        n = len(spec) if kind == "kpis" else b.df.size
        print(f"{'PASS' if not bad else 'FAIL'} {key:6s} {b.title!r:45s} ({n} cells)")
        for m in bad[:8]:
            print("      ", m)
        ok_all &= not bad
    extra = set(blocks) - set(checks)
    if extra:
        print("unchecked blocks:", extra)
    return ok_all


CHECKS = {
    "vx_02": ("kpis", tiles([(6, 7), (9, 10)])),
    "vx_03": ("table", "E13:H18"),
    "vx_04": ("table", "E21:L25"),
    "vx_05": ("table", "E28:L34"),
    "vx_06": ("table", "E37:I48"),
    "vx_07": ("table", "E51:I59"),
}


def main():
    ok_all = True
    saved = {"venue": cell(SHEET, "C6"), "match_type": cell(SHEET, "C9")}
    if saved != mod.DEFAULTS:
        ok_all = False
        print("FAIL DEFAULTS", saved, mod.DEFAULTS)
    else:
        print(f"PASS DEFAULTS  {mod.DEFAULTS}  span=({cell(SHEET, 'C7')}, {cell(SHEET, 'C8')})")
    opts = mod.filter_options((2016, 2026))
    assert list(opts) == mod.FILTERS, "filter_options keys must follow FILTERS"
    for k, v in mod.DEFAULTS.items():
        assert v in opts[k], f"default {k}={v!r} not in options"

    blocks = {b.key: b for b in mod.build((2016, 2026), **mod.DEFAULTS)}
    ok_all &= run_checks(CHECKS, blocks)

    # ── cross-check v the Toss & Chasing sheet: every venue + All, every season ─
    xbad = []
    hdr = grid("Toss & Chasing", "B24:I24")[0]
    for r in grid("Toss & Chasing", "B25:I32"):
        row = dict(zip(hdr, r))
        v = "All" if row["Venue"].startswith("All") else row["Venue"]
        k = {lab: val for lab, val, _ in mod.build((2016, 2026), venue=v, match_type="All")[0].kpis}
        exp = {"MATCHES": xl_fmt(row["Matches"], "0"),
               "TOSS WINNER BOWLED FIRST": xl_fmt(row["Toss winner bowled %"], "0.0%"),
               "TOSS WINNER WON": xl_fmt(row["Toss winner won %"], "0.0%"),
               "WON BATTING FIRST": xl_fmt(row["Bat-first wins"], "0"),
               "WON CHASING": xl_fmt(row["Chase wins"], "0"),
               "CHASE WIN %": xl_fmt(row["Chase win %"], "0.0%")}
        for lab, e in exp.items():
            if k[lab] != e:
                xbad.append(f"{v} {lab}: mine={k[lab]} Toss&Chasing={e}")
    hdr = grid("Toss & Chasing", "B8:I8")[0]
    t6 = {b.key: b for b in mod.build((2016, 2026), venue="All", match_type="All")}["vx_06"].df
    for i, r in enumerate(grid("Toss & Chasing", "B9:I19")):
        row = dict(zip(hdr, r))
        mine = t6.iloc[i]
        for mc, xc in [("Matches", "Matches"), ("Chase win %", "Chase win %"),
                       ("Toss \u2192 bowl %", "Toss winner bowled %")]:
            if abs(float(mine[mc]) - float(row[xc])) > 1e-9:
                xbad.append(f"season {row['Season']} {mc}: mine={mine[mc]} Toss&Chasing={row[xc]}")
    print(f"{'PASS' if not xbad else 'FAIL'} cross-check v Toss & Chasing sheet (8 venue rows, 11 seasons)")
    for m in xbad[:8]:
        print("      ", m)
    ok_all &= not xbad

    # ── smoke tests ──────────────────────────────────────────────────────────
    spans = [(2016, 2026), (2016, 2016), (2016, 2017), (2020, 2022), (2026, 2026)]
    worst, n = 0.0, 0
    for sp, v, mt in itertools.product(spans, opts["venue"], opts["match_type"]):
        t = time.perf_counter()
        out = mod.build(sp, venue=v, match_type=mt)
        worst = max(worst, time.perf_counter() - t)
        n += 1
        assert [b.key for b in out] == list(CHECKS)
        for b in out:
            if b.kind == "table":
                assert list(b.df.columns) == list(blocks[b.key].df.columns)
    # no data: Multan in 2016 (ground first used later), unknown venue
    for c in [dict(venue="Multan Cricket Stadium"), dict(venue="Nowhere")]:
        out = {b.key: b for b in mod.build((2016, 2016), **{**mod.DEFAULTS, **c})}
        assert out["vx_04"].df["Runs"].sum() == 0
        n += 1
    print(f"PASS smoke: {n} builds (spans x venues x match types + no-data cases), worst {worst * 1000:.0f} ms")

    ts = []
    for _ in range(5):
        t = time.perf_counter()
        mod.build((2016, 2026), **mod.DEFAULTS)
        ts.append(time.perf_counter() - t)
    print(f"timing build(full span, DEFAULTS): best {min(ts) * 1000:.0f} ms, worst {max(ts) * 1000:.0f} ms")
    t = time.perf_counter()
    mod.build((2016, 2026), venue="All", match_type="All")
    print(f"timing build(full span, All venues): {(time.perf_counter() - t) * 1000:.0f} ms")
    print("ALL PASS" if ok_all else "SOME FAILURES")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
