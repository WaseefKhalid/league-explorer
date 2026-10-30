"""Validate analytics/explore_team.py against the workbook ('Team Explorer').

Run from the repo root:  python3 tests/check_explore_team.py
"""
from __future__ import annotations

import itertools
import math
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import analytics.explore_team as mod  # noqa: E402
from analytics.explore_team import xl_fmt  # noqa: E402
from tools.xlcheck import cell, grid  # noqa: E402

SHEET = "Team Explorer"
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
    "tx_02": ("kpis", tiles([(6, 7), (9, 10), (12, 13)])),
    "tx_03": ("table", "E16:L20"),
    "tx_04": ("table", "E23:L27"),
    "tx_05": ("table", "E30:L36"),
    "tx_06": ("table", "E39:L41"),
    "tx_07": ("table", "E44:J55"),
}


def main():
    ok_all = True
    saved = {"team": cell(SHEET, "C6"), "venue": cell(SHEET, "C9"), "opposition": cell(SHEET, "C10"),
             "match_type": cell(SHEET, "C11"), "host": cell(SHEET, "C12"), "toss": cell(SHEET, "C13"),
             "batting_order": cell(SHEET, "C14")}
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

    # ── cross-check every team's record v the Teams sheet (full span) ───────
    xbad = []
    hdr = grid("Teams", "B8:N8")[0]
    for r in grid("Teams", "B9:N16"):
        row = dict(zip(hdr, r))
        k = {lab: val for lab, val, _ in mod.build((2016, 2026), **{**mod.DEFAULTS, "team": row["Team"]})[0].kpis}
        exp = {"PLAYED": xl_fmt(row["Played"], "0"), "WON": xl_fmt(row["Won"], "0"),
               "LOST": xl_fmt(row["Lost"], "0"), "NO RESULT": xl_fmt(row["NR"], "0"),
               "WIN %": xl_fmt(row["Win %"], "0.0%"), "BAT-FIRST WIN %": xl_fmt(row["Bat-first win %"], "0.0%"),
               "CHASING WIN %": xl_fmt(row["Chase win %"], "0.0%"),
               "TOSSES WON": xl_fmt(round(row["Tosses won %"] * row["Played"]), "0")}
        for lab, v in exp.items():
            if k[lab] != v:
                xbad.append(f"{row['Team']} {lab}: mine={k[lab]} Teams sheet={v}")
    # filter partitions must add up (toss and batting-order splits)
    def kp(**c):
        return {lab: val for lab, val, _ in mod.build((2016, 2026), **{**mod.DEFAULTS, **c})[0].kpis}
    def tb(key, **c):
        return {b.key: b for b in mod.build((2016, 2026), **{**mod.DEFAULTS, **c})}[key].df
    a, w, l = kp(), kp(toss="Won toss"), kp(toss="Lost toss")
    if int(w["PLAYED"]) + int(l["PLAYED"]) != int(a["PLAYED"]) or w["TOSSES WON"] != w["PLAYED"] or l["TOSSES WON"] != "0":
        xbad.append("toss split does not add up")
    for key, col in [("tx_03", "Runs"), ("tx_04", "Runs conceded"), ("tx_05", "Runs"), ("tx_06", "Runs conceded")]:
        s = tb(key, batting_order="Bat first")[col].sum() + tb(key, batting_order="Chasing")[col].sum()
        if s != tb(key)[col].sum():
            xbad.append(f"{key} batting-order split does not add up")
    bf = kp(batting_order="Bat first")
    if bf["WINS CHASING"] != "0" or bf["BAT-FIRST WIN %"] != a["BAT-FIRST WIN %"]:
        xbad.append("batting-order filter inconsistent with record")
    print(f"{'PASS' if not xbad else 'FAIL'} cross-check: 8 team records v Teams sheet + toss/order splits")
    for m in xbad[:8]:
        print("      ", m)
    ok_all &= not xbad

    # ── smoke tests ──────────────────────────────────────────────────────────
    combos = [
        {},
        {"toss": "Won toss"}, {"toss": "Lost toss"},
        {"batting_order": "Bat first"}, {"batting_order": "Chasing"},
        {"team": "Rawalpindiz"}, {"team": "Hyderabad Kingsmen", "host": "UAE"},     # no data
        {"venue": "Sharjah Cricket Stadium", "match_type": "Playoff", "opposition": "Karachi Kings"},
        {"opposition": "Lahore Qalandars"},                                          # self -> empty
        {"team": "Peshawar Zalmi", "host": "Pakistan", "toss": "Won toss", "batting_order": "Chasing"},
    ]
    spans = [(2016, 2026), (2016, 2016), (2016, 2017), (2020, 2022), (2026, 2026)]
    worst, n = 0.0, 0
    for sp, c in itertools.product(spans, combos):
        t = time.perf_counter()
        out = mod.build(sp, **{**mod.DEFAULTS, **c})
        worst = max(worst, time.perf_counter() - t)
        n += 1
        assert [b.key for b in out] == list(CHECKS)
        for b in out:
            if b.kind == "table":
                assert list(b.df.columns) == list(blocks[b.key].df.columns)
    # every option of every filter at least once
    opts = mod.filter_options((2016, 2026))
    for k, vals in opts.items():
        for v in vals:
            mod.build((2020, 2022), **{**mod.DEFAULTS, k: v})
            n += 1
    print(f"PASS smoke: {n} builds (spans x combos + every filter option), worst {worst * 1000:.0f} ms")

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
