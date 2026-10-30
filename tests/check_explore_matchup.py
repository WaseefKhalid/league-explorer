"""Validate analytics/explore_matchup.py against the workbook ('Matchup Explorer').

Run from the repo root:  python3 tests/check_explore_matchup.py
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import analytics.explore_matchup as mod  # noqa: E402
from analytics.explore_matchup import xl_fmt  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Matchup Explorer"
DASH = "—"


# ── generic comparison helpers ───────────────────────────────────────────────
def _nan(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def cmp_table(block, rng):
    """Header row + data rows of `rng` v block.df, every cell."""
    vals = grid(SHEET, rng)
    fmts = grid(SHEET, rng, formulas="numfmt")
    bad = []
    hdr = [h for h in vals[0]]
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
                ok = _nan(mv)
            elif isinstance(xv, str):
                ok = (mv == xv)
            else:
                if _nan(mv):
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


CHECKS = {
    "mx_02": ("kpis", tiles([(6, 7), (9, 10)])),
    "mx_03": ("table", "E13:L24"),
    "mx_04": ("table", "E27:L31"),
    "mx_06": ("kpis", tiles([(35, 36), (38, 39)])),
    "mx_07": ("table", "E42:J53"),
}


def main():
    ok_all = True
    # DEFAULTS = the saved workbook selections
    saved = {"batter": cell(SHEET, "C6"), "bowler": cell(SHEET, "C7"), "phase": cell(SHEET, "C10"),
             "venue": cell(SHEET, "C11"), "match_type": cell(SHEET, "C12"),
             "team_a": cell(SHEET, "C35"), "team_b": cell(SHEET, "C36"),
             "team_venue": cell(SHEET, "C39"), "team_match_type": cell(SHEET, "C40")}
    span_saved = [(cell(SHEET, "C8"), cell(SHEET, "C9")), (cell(SHEET, "C37"), cell(SHEET, "C38"))]
    if saved != mod.DEFAULTS:
        ok_all = False
        print("FAIL DEFAULTS", saved, mod.DEFAULTS)
    else:
        print(f"PASS DEFAULTS  {mod.DEFAULTS}  spans={span_saved}")
    opts = mod.filter_options((2016, 2026))
    assert list(opts) == mod.FILTERS, "filter_options keys must follow FILTERS"
    for k, v in mod.DEFAULTS.items():
        assert v in opts[k], f"default {k}={v!r} not in options"

    blocks = {b.key: b for b in mod.build((2016, 2026), **mod.DEFAULTS)}
    for key, (kind, spec) in CHECKS.items():
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
    extra = set(blocks) - set(CHECKS)
    if extra:
        print("unchecked blocks:", extra)

    # ── verdict logic cross-check: every pair on the Matchups sheet ─────────
    # (the Matchups "Edge" column uses the same verdict formula, full span)
    import analytics.data as d
    b = d.ball()
    agg = b.groupby(["Batter", "Bowler"])[["Ball Faced", "Bat Runs"]].sum()
    outs = b[b["Bowler Wkt"] == 1].groupby(["Player Out", "Bowler"]).size()
    rows = [r for r in grid("Matchups", "B13:P1916") if r[0]]
    vbad = []
    for r in rows:
        bat, bowl, edge = r[0], r[2], r[14]
        balls, runs = agg.loc[(bat, bowl)] if (bat, bowl) in agg.index else (0, 0)
        dis = int(outs.get((bat, bowl), 0))
        c_sr, c_bpd = mod._career(bat)
        mine = mod.verdict(balls, 100 * runs / balls if balls else 0.0, dis, c_sr, c_bpd)
        if (balls, runs, dis) != (r[4], r[5], r[6]) or mine != edge:
            vbad.append(f"{bat} v {bowl}: mine={(balls, runs, dis, mine)} xl={(r[4], r[5], r[6], edge)}")
    print(f"{'PASS' if not vbad else 'FAIL'} verdict cross-check v Matchups sheet ({len(rows)} pairs)")
    for m in vbad[:8]:
        print("      ", m)
    ok_all &= not vbad

    # ── team v team cross-check: every pair on the Teams head-to-head grid ──
    h2h = grid("Teams", "B30:J38")
    cols = h2h[0][1:]
    hbad, npairs = [], 0
    for r in h2h[1:]:
        for opp, txt in zip(cols, r[1:]):
            if r[0] == opp:
                continue
            k = {lab: val for lab, val, _ in
                 mod.build((2016, 2026), **{**mod.DEFAULTS, "team_a": r[0], "team_b": opp})[3].kpis}
            mine = f"{k['TEAM A WINS']} – {k['TEAM B WINS']}"
            npairs += 1
            if mine != txt:
                hbad.append(f"{r[0]} v {opp}: mine={mine} Teams sheet={txt}")
    print(f"{'PASS' if not hbad else 'FAIL'} team h2h cross-check v Teams sheet ({npairs} pairs)")
    for m in hbad[:8]:
        print("      ", m)
    ok_all &= not hbad

    # ── smoke tests: spans and filter combos (incl. empty) ─────────────────
    combos = [
        {},
        {"phase": "Death"},
        {"venue": "Gaddafi Stadium", "match_type": "Playoff"},
        {"batter": "A Lyth", "bowler": "A Zampa"},              # never met
        {"batter": "Fakhar Zaman", "bowler": "Rashid Khan", "phase": "MO2"},
        {"batter": "Nobody", "bowler": "Nobody"},
        {"team_a": "Rawalpindiz", "team_b": "Hyderabad Kingsmen"},
        {"team_a": "Lahore Qalandars", "team_b": "Lahore Qalandars"},
        {"team_venue": "Sharjah Cricket Stadium", "team_match_type": "Playoff"},
        {"team_a": "Multan Sultans", "team_b": "Peshawar Zalmi", "team_venue": "Multan Cricket Stadium"},
    ]
    spans = [(2016, 2026), (2016, 2016), (2016, 2017), (2020, 2022), (2026, 2026), (2026, 2016)]
    worst = 0.0
    n = 0
    for sp in spans:
        for c in combos:
            t = time.perf_counter()
            out = mod.build(sp, **{**mod.DEFAULTS, **c})
            worst = max(worst, time.perf_counter() - t)
            n += 1
            assert [b.key for b in out] == list(CHECKS), [b.key for b in out]
            for b in out:
                if b.kind == "table":
                    assert list(b.df.columns) == list(blocks[b.key].df.columns)
    print(f"PASS smoke: {n} builds over {len(spans)} spans x {len(combos)} combos, "
          f"worst {worst * 1000:.0f} ms")
    # timing on defaults
    ts = []
    for _ in range(5):
        t = time.perf_counter()
        mod.build((2016, 2026), **mod.DEFAULTS)
        ts.append(time.perf_counter() - t)
    print(f"timing build(full span, DEFAULTS): best {min(ts) * 1000:.0f} ms, worst {max(ts) * 1000:.0f} ms")
    print("ALL PASS" if ok_all else "SOME FAILURES")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
