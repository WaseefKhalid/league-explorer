"""
Key Insights — eighteen numbered findings (workbook sheet "Key Insights"),
for any league.

Each finding is one Block (ki_01 … ki_18) in workbook order. The title names
the question in neutral words; the `finding` sentence carries the
conclusion and is worked out from the data for the selected span, so it is
right for every league and every span. Every table recalculates for `span`,
exactly like the sheet's Seasons box (BI5/BJ5).

League-specific choices (which grounds the par-score and toss tables show,
which teams the home-advantage table compares, which left-arm pacers the
third left-arm row leaves out) come from analytics/presets.py for leagues
we know (the PSL keeps the workbook's choices); any other league gets them
from its own data (busiest grounds, teams with home games, the three
left-arm pacers with most balls).

§17 and §18 replicate the hidden Calc sheet: per-player span sums from
Player Seasons, a "key" = metric (or ±999 when below the ball threshold)
+ ROW()/1E9, then LARGE/SMALL + MATCH. Calc rows follow players() order
(row = position + 2), so ties break exactly as in Excel.
"""
from __future__ import annotations

import html
import math

import numpy as np
import pandas as pd

from analytics import data as d
from analytics import presets
from analytics.blocks import Block

NAN = float("nan")

# ── number formats (from the workbook's cell formats) ────────────────────────
P1 = "{:.1%}"     # 0.0%
P0 = "{:.0%}"     # 0%
I0 = "{:,.0f}"    # 0 / #,##0
F1 = "{:,.1f}"    # 0.0
F2 = "{:,.2f}"    # 0.00


# ── helpers ──────────────────────────────────────────────────────────────────
def _div(a, b, scale: float = 1.0):
    """(scale*a)/b like the workbook's formulas; NaN where b == 0 ("—")."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, (scale * a) / np.where(b != 0, b, 1.0), np.nan)
    return out if out.ndim else float(out)


def _bounds(span):
    return min(span), max(span)


def _lower(s: pd.Series) -> np.ndarray:
    """Lower-cased object array (COUNTIFS text criteria are case-insensitive)."""
    return s.astype("string").str.lower().fillna("").to_numpy(object)


def _codes(s: pd.Series, cats: list[str]) -> np.ndarray:
    """Case-insensitive category codes; -1 for anything else (incl. blanks)."""
    low = pd.Series(_lower(s))
    return pd.Categorical(low, categories=[c.lower() for c in cats]).codes.astype(np.int64)


def _ok(*xs) -> bool:
    """Every value is a finite number (so a finding can quote it)."""
    try:
        return all(x is not None and math.isfinite(float(x)) for x in xs)
    except (TypeError, ValueError):
        return False


def _nm(x) -> str:
    """A name in a finding (findings are shown as HTML)."""
    return html.escape(str(x), quote=False)


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


BTYPES = list(d.BOWL_TYPES)                       # workbook order
BTYPE_CATS = BTYPES + ["Unknown"]                 # code 6 = "Unknown"
PHASE_CATS = ["PP", "MO1", "MO2", "Death"]
PAIR_CATS = ["Left–right pair", "Same-hand pair"]
HOW_CATS = ["bowled", "lbw", "caught", "caught and bowled", "stumped"]


# ── league choices (preset, else from the data) ──────────────────────────────
@d.per_league()
def _par_venues() -> list[tuple[str, str]]:
    """(header, venue) for the extra par-score columns: the three busiest grounds."""
    p = presets.preset("par_venues")
    if p:
        return [tuple(x) for x in p]
    v = d.matches()["Venue"].dropna().value_counts()
    return [(str(x), str(x)) for x in v.index[:3]]


@d.per_league()
def _toss_venues() -> list[str]:
    """Grounds in the toss table: every ground with 10+ matches (busiest first, at most 8)."""
    p = presets.preset("toss_venues")
    if p:
        return list(p)
    v = d.matches()["Venue"].dropna().value_counts()
    keep = v[v >= 10]
    if len(keep) < 3:
        keep = v
    return [str(x) for x in keep.index[:8]]


@d.per_league()
def _home_teams() -> list[tuple[str, str]]:
    """(team, home ground) for the home-advantage table: teams with 5+ home games,
    most home games first; the ground is where they played most of them."""
    p = presets.preset("home_teams")
    if p:
        return [tuple(x) for x in p]
    tm = d.team_matches()
    h = tm[tm["Home Ground"].astype(str).str.lower() == "home"]
    if h.empty:
        return []
    g = h.groupby("Team").agg(n=("Venue", "size"), ground=("Venue", lambda s: s.value_counts().index[0]))
    g = g[g["n"] >= 5].sort_values(["n"], ascending=False, kind="stable")
    return [(str(t), str(r["ground"])) for t, r in g.iterrows()]


@d.per_league()
def _left_arm_stars() -> tuple[tuple[str, ...], str]:
    """The left-arm pacers the third row leaves out, and how the row names them:
    the three with most legal balls in the league."""
    p = presets.preset("left_arm_stars")
    if p:
        return tuple(p[0]), str(p[1])
    b = d.ball()
    lap = b[b["Bowler Type"] == "Left-arm pace"].groupby("Bowler")["Legal Ball"].sum()
    names = [str(x) for x in lap.sort_values(ascending=False, kind="stable").index[:3]]
    return tuple(names), (_and(names) if names else "the top three")


@d.per_league()
def _ball_arrays() -> dict[str, np.ndarray]:
    """Read-only numpy views of the Ball Data columns this sheet uses."""
    b = d.ball()
    A: dict[str, np.ndarray] = {"season": b["Season"].to_numpy(np.int64)}
    for k, c in [("runs", "Total Runs"), ("batruns", "Bat Runs"), ("bowlruns", "Bowler Runs"),
                 ("legal", "Legal Ball"), ("faced", "Ball Faced"), ("four", "Four"),
                 ("six", "Six"), ("wkt", "Wicket"), ("bwkt", "Bowler Wkt"),
                 ("sout", "Striker Out"), ("over", "Over"), ("ballno", "Batter Ball No"),
                 ("streak", "Dot Streak"), ("prevb", "Prev Bdry")]:
        A[k] = b[c].to_numpy(np.float64)
    A["phase"] = _codes(b["Phase"], PHASE_CATS)
    A["btype"] = _codes(b["Bowler Type"], BTYPE_CATS)
    A["hand"] = _codes(b["Bat Hand"], ["RHB", "LHB"])
    A["pair"] = _codes(b["Pair"], PAIR_CATS)
    A["how"] = _codes(b["How Out"], HOW_CATS)
    A["bos"] = _lower(b["Batter Origin"]) == "overseas"
    A["wos"] = _lower(b["Bowler Origin"]) == "overseas"
    A["big3"] = np.isin(_lower(b["Bowler"]), [n.lower() for n in _left_arm_stars()[0]])
    for v in A.values():
        v.setflags(write=False)
    return A


def _bc(codes: np.ndarray, mask: np.ndarray, weights: np.ndarray | None, n: int) -> np.ndarray:
    """Per-code sums (codes 0..n-1) over `mask` — the SUMIFS/COUNTIFS grid."""
    c = codes[mask]
    ok = (c >= 0) & (c < n)
    w = None if weights is None else weights[mask][ok]
    return np.bincount(c[ok].astype(np.int64), weights=w, minlength=n)[:n].astype(float)


def _frame(rows: list[list], cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=cols)


# ── §01–§07: match-level findings (Match Data / Team Match Data) ─────────────
def _ki01(m: pd.DataFrame) -> Block:
    spec = [("a higher boundary % (4s + 6s per ball faced)", "Bdry% Edge Won"),
            ("a lower dot-ball % when batting", "Dot% Edge Won"),
            ("a higher six-hitting rate", "Six Edge Won")]
    rows = []
    for label, col in spec:
        v = m[col]
        rows.append([label, v.mean() if v.notna().any() else NAN, int((v >= 0).sum())])
    df = _frame(rows, ["The team that had…", "Won the match", "Matches"])

    finding = None
    (b, nb), (dt, _), (sx, _) = [(r[1], r[2]) for r in rows]
    if _ok(b, dt, sx):
        lead = {0: "Finding the rope consistently beats clearing it.",
                1: "Keeping the scoreboard moving matters most.",
                2: "Clearing the rope matters most."}[int(np.argmax([b, dt, sx]))]
        finding = (f"In decided matches the side that found the boundary more often per ball won {b:.0%} of "
                   f"the time ({nb:,} games); a lower dot-ball % predicts {dt:.0%} and a higher six-hitting "
                   f"rate {sx:.0%}. {lead}")
    return Block(
        key="ki_01",
        title="What predicts the winner: boundary %, dot-ball % or sixes",
        finding=finding,
        note="Decided matches only (no ties, no DLS).",
        df=df, fmt={"Won the match": P1, "Matches": I0}, good_high=["Won the match"],
    )


def _ki02(m: pd.DataFrame) -> Block:
    spec = [("PP (Overs 1–6)", "PP"), ("MO1 (Overs 7–10)", "MO1"),
            ("MO2 (Overs 11–16)", "MO2"), ("Death (Overs 17–20)", "Death")]
    rows = []
    for label, ph in spec:
        rr, wk = m[f"{ph} RR Edge Won"], m[f"{ph} Wkt Edge Won"]
        rows.append([label, rr.mean() if rr.notna().any() else NAN,
                     wk.mean() if wk.notna().any() else NAN])
    c1, c2 = "Higher run rate in phase → won", "Fewer wickets lost in phase → won"
    df = _frame(rows, ["Phase", c1, c2])

    finding = None
    pairs = [(r[1], r[2]) for r in rows if _ok(r[1], r[2])]
    if pairs and _ok(rows[0][1], rows[0][2]):
        w = sum(b > a for a, b in pairs)
        n = len(pairs)
        if w * 2 > n:
            lead = f"Losing fewer wickets predicted the result better than scoring faster in {w} of {n} phases."
        elif w * 2 < n:
            lead = f"Scoring faster predicted the result better than losing fewer wickets in {n - w} of {n} phases."
        else:
            lead = "Runs and wickets split the phases evenly."
        finding = (f"{lead} Winning the powerplay on run rate converted to a win {rows[0][1]:.0%} of the time; "
                   f"losing fewer powerplay wickets converted {rows[0][2]:.0%}.")
    return Block(
        key="ki_02",
        title="Runs or wickets: which phase edge predicts the result",
        finding=finding,
        note="Decided matches; a phase counts only when both sides batted at least 12 balls in it.",
        df=df, fmt={c1: P1, c2: P1}, good_high=[c1, c2],
    )


def _ki03(m: pd.DataFrame) -> Block:
    bins = [("≤30 runs", 0, 30), ("31–40 runs", 31, 40), ("41–50 runs", 41, 50),
            ("51–60 runs", 51, 60), ("61–70 runs", 61, 70), ("71+ runs", 71, 999)]
    alive = m["Alive@15"].to_numpy() == 1
    need = m["Need@15"].to_numpy(float)
    wk = m["Wkts@15"].to_numpy(float)
    won = m["Chase Won"].to_numpy(float) == 1
    rows, wins = [], []
    for label, lo, hi in bins:
        base = alive & (need >= lo) & (need <= hi)
        w34 = base & (wk >= 3) & (wk <= 4)
        w56 = base & (wk >= 5) & (wk <= 6)
        rows.append([label, _div((base & won).sum(), base.sum()), int(base.sum()),
                     _div((w34 & won).sum(), w34.sum()), _div((w56 & won).sum(), w56.sum())])
        wins.append(int((base & won).sum()))
    cols = ["Runs still needed after 15 overs", "Chasing side won", "Chases",
            "With 3–4 down", "With 5–6 down"]
    df = _frame(rows, cols)
    pct = ["Chasing side won", "With 3–4 down", "With 5–6 down"]

    parts = []
    n40 = rows[0][2] + rows[1][2]
    if n40:
        parts.append(f"Needing 40 or fewer off the last five overs, chasers won {(wins[0] + wins[1]) / n40:.0%} "
                     f"of {n40:,} chases.")
    mid = [(rows[i][0].replace(" runs", ""), rows[i][1]) for i in (2, 3) if rows[i][2] and _ok(rows[i][1])]
    if mid:
        parts.append("Needing " + "; ".join(f"{lab}, {p:.0%}" for lab, p in mid) + ".")
    if rows[5][2]:
        parts.append(f"71+ was chased {wins[5]} time{'s' if wins[5] != 1 else ''} in {rows[5][2]:,}.")
    return Block(
        key="ki_03",
        title="The chase calculator: what is gettable off the last five overs",
        finding=" ".join(parts) or None,
        note="Every non-DLS chase still alive after 15 overs (not yet won, not all out). Full grids: Toss & "
             "Chasing.",
        df=df, fmt={"Chasing side won": P1, "Chases": I0, "With 3–4 down": P1, "With 5–6 down": P1},
        good_high=pct, center={c: 0.5 for c in pct},
    )


def _ki04(m: pd.DataFrame) -> Block:
    bins = [("Under 160", 0, 159), ("160–179", 160, 179), ("180–199", 180, 199),
            ("200–219", 200, 219), ("220+", 220, 999)]
    venues = _par_venues()
    base0 = (m["Full 1st Inns"].to_numpy() == 1) & (m["Decided (no DLS)"].to_numpy() == 1)
    inn1 = m["1st Inns Runs"].to_numpy(float)
    bfw = m["Bat First Won"].to_numpy(float) == 1
    ven = _lower(m["Venue"])
    rows = []
    for label, lo, hi in bins:
        base = base0 & (inn1 >= lo) & (inn1 <= hi)
        row = [label, _div((base & bfw).sum(), base.sum()), int(base.sum())]
        for _, vname in venues:
            bv = base & (ven == vname.lower())
            row.append(_div((bv & bfw).sum(), bv.sum()))
        rows.append(row)
    vcols = [h for h, _ in venues]
    cols = ["First-innings total", "Bat-first won (all grounds)", "Matches"] + vcols
    df = _frame(rows, cols)
    pct = ["Bat-first won (all grounds)"] + vcols
    fmt = {"Bat-first won (all grounds)": P1, "Matches": I0, **{c: P0 for c in vcols}}

    shown = [(r[0], r[1]) for r in rows if r[2] and _ok(r[1])]
    finding = None
    if shown:
        bits = [f"{lab.lower() if lab.startswith('Under') else lab} {p:.0%}" for lab, p in shown]
        bits[0] = bits[0].replace(" ", " won ", 1) if not bits[0].startswith("under") else \
            bits[0].replace("under 160 ", "under 160 won ")
        bands = bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " and " + bits[-1]
        finding = f"Batting first, totals of {bands}."
        flip = [(abs(r[1] - 0.5), r[0]) for r in rows if r[2] >= 5 and _ok(r[1])]
        if flip:
            finding += f" The coin-flip band is {min(flip)[1]}."
    return Block(
        key="ki_04",
        title="Par scores: how often each first-innings total wins",
        finding=finding,
        note="Completed first innings in decided matches." + (f" Ground columns: {', '.join(vcols)}." if vcols else ""),
        df=df, fmt=fmt, good_high=pct, center={c: 0.5 for c in pct},
    )


def _ki05(m: pd.DataFrame) -> Block:
    venues = _toss_venues()
    base0 = (_lower(m["Toss Decision"]) == "field") & (m["Decided (no DLS)"].to_numpy() == 1)
    tww = m["Toss Winner Won"].to_numpy(float) == 1
    ven = _lower(m["Venue"])
    rows = []
    for v in venues:
        base = base0 & (ven == v.lower())
        rows.append([v, _div((base & tww).sum(), base.sum()), int(base.sum())])
    rows.append(["All venues", _div((base0 & tww).sum(), base0.sum()), int(base0.sum())])
    c = "Toss winner chose to bowl → won"
    df = _frame(rows, ["Venue", c, "Matches"])

    finding = None
    allp, alln = rows[-1][1], rows[-1][2]
    if _ok(allp) and alln:
        finding = f"Toss winners who chose to bowl won {allp:.0%} of {alln:,} decided games."
        grounds = [(r[1], r[0], r[2]) for r in rows[:-1] if r[2] >= 5 and _ok(r[1])]
        if len(grounds) >= 2:
            hi, lo = max(grounds), min(grounds)
            finding += (f" Best at {_nm(hi[1])} ({hi[0]:.0%} of {hi[2]}), worst at {_nm(lo[1])} "
                        f"({lo[0]:.0%} of {lo[2]})")
            finding += (" — there, winning the toss and bowling has lost more often than it has won."
                        if lo[0] < 0.5 else ".")
    return Block(
        key="ki_05",
        title="The toss: does bowling first pay at each ground?",
        finding=finding,
        note="Decided matches in which the toss winner chose to field.",
        df=df, fmt={c: P1, "Matches": I0}, good_high=[c], center={c: 0.5},
        bold_rows=[len(df) - 1],
    )


def _ki06(m: pd.DataFrame) -> Block:
    mt = _lower(m["Match Type"])
    dec = m["Decided (no DLS)"].to_numpy() == 1
    chase = m["Bat First Won"].to_numpy(float) == 0
    rows = []
    for label, t in [("League", "league"), ("Playoffs", "playoff")]:
        base = dec & (mt == t)
        rows.append([label, _div((base & chase).sum(), base.sum()), int(base.sum())])
    df = _frame(rows, ["Match type", "Chasing side won", "Decided matches"])

    finding = None
    (lg, nl), (po, npo) = (rows[0][1], rows[0][2]), (rows[1][1], rows[1][2])
    if _ok(lg) and _ok(po) and npo:
        finding = (f"Chasing sides won {lg:.0%} of league games but {po:.0%} of playoffs ({npo} decided)."
                   if po < lg else
                   f"Chasing sides won {lg:.0%} of league games and {po:.0%} of playoffs ({npo} decided).")
        if po < lg - 0.05:
            finding += " In a must-win game, runs on the board have been worth more than knowing the target."
        elif po > lg + 0.05:
            finding += " In knockouts, knowing the target has been worth even more."
    elif _ok(lg) and nl:
        finding = f"Chasing sides won {lg:.0%} of {nl:,} decided league games; no decided playoffs in the span."
    return Block(
        key="ki_06",
        title="Chasing in league games v playoffs",
        finding=finding,
        note="Decided matches only.",
        df=df, fmt={"Chasing side won": P1, "Decided matches": I0},
        good_high=["Chasing side won"], center={"Chasing side won": 0.5},
    )


def _ki07(tm: pd.DataFrame) -> Block:
    spec = _home_teams()
    country = presets.home_country()
    team = _lower(tm["Team"])
    home = _lower(tm["Home Ground"])
    res = _lower(tm["Result"])
    won, lost = res == "won", res == "lost"
    rows = []
    for t, ground in spec:
        row = [t, ground]
        for where in ("home", "away"):
            base = (team == t.lower()) & (home == where)
            w, l = int((base & won).sum()), int((base & lost).sum())
            row += [_div(w, w + l), w + l]
        rows.append(row)
    away = f"Win % elsewhere in {country}" if country else "Win % elsewhere"
    cols = ["Team", "Home ground", "Win % at home", "Home games", away, "Other games"]
    df = _frame(rows, cols)
    pct = ["Win % at home", away]

    finding = None
    gaps = [(r[2] - r[4], r) for r in rows if r[3] >= 3 and r[5] >= 3 and _ok(r[2], r[4])]
    if gaps:
        gaps.sort(key=lambda x: x[0])
        best = gaps[-1][1]
        finding = f"{_nm(best[0])} won {best[2]:.0%} at {_nm(best[1])} v {best[4]:.0%} elsewhere."
        worst_gap, worst = gaps[0]
        if worst_gap < 0 and worst is not best:
            finding += (f" {_nm(worst[0])} are the outlier: {worst[2]:.0%} at {_nm(worst[1])} v {worst[4]:.0%} "
                        f"away.")
    where = f"{country}-hosted games only" if country else "home and away games only"
    return Block(
        key="ki_07",
        title="Home advantage",
        finding=finding,
        note=f"Win % = wins ÷ (wins + losses); {where} (neutral grounds are left out).",
        df=df, fmt={"Win % at home": P1, "Home games": I0, away: P1, "Other games": I0},
        good_high=pct, center={c: 0.5 for c in pct},
    )


# ── §08–§16: ball-level findings (Ball Data) ─────────────────────────────────
def _ki08(A, sm) -> Block:
    overs = [(1, "PP"), (5, "PP"), (6, "PP"), (7, "MO1"), (8, "MO1"),
             (12, "MO2"), (16, "MO2"), (19, "Death"), (20, "Death")]
    ov = A["over"].astype(np.int64)
    s = {k: _bc(ov, sm, A[k], 21) for k in ("runs", "legal", "wkt", "four", "six", "faced")}
    rows = []
    for o, ph in overs:
        rows.append([o, ph, _div(s["runs"][o], s["legal"][o], 6), _div(s["wkt"][o], s["legal"][o], 6),
                     _div(s["four"][o] + s["six"][o], s["faced"][o])])
    df = _frame(rows, ["Over", "Phase", "Runs per over", "Wickets per over", "Boundary %"])

    rr = {r[0]: r[2] for r in rows}
    wk = {r[0]: r[3] for r in rows}
    parts = []
    if _ok(rr[6], rr[7]) and rr[6] > 0:
        if rr[7] < rr[6]:
            parts.append(f"Scoring falls {1 - rr[7] / rr[6]:.0%} from over 6 ({rr[6]:.1f} an over) to over 7 "
                         f"({rr[7]:.1f}).")
        else:
            parts.append(f"Scoring holds up after the powerplay: {rr[6]:.1f} an over in over 6, {rr[7]:.1f} in "
                         f"over 7.")
    if _ok(rr[20], wk[20]):
        tail = f", {wk[20] / wk[1]:.1f}× the rate of over 1" if _ok(wk[1]) and wk[1] > 0 else ""
        parts.append(f"Over 20 goes at {rr[20]:.1f} and brings {wk[20]:.2f} wickets per over{tail}.")
    return Block(
        key="ki_08",
        title="Scoring and wickets over by over",
        finding=" ".join(parts) or None,
        df=df, fmt={"Over": "{:.0f}", "Runs per over": F2, "Wickets per over": F2, "Boundary %": P1},
    )


def _ki09(A, sm) -> Block:
    base = sm & (A["legal"] == 1)
    st = np.where(np.isnan(A["streak"]), -1, A["streak"]).astype(np.int64)
    n = _bc(st, base, None, 5)
    w = _bc(st, base, A["wkt"], 5)
    bd = _bc(st, base, A["four"] + A["six"], 5)
    labels = ["0 (previous ball scored)", "1 dot", "2 dots", "3 dots", "4+ dots"]
    rows = [[labels[k], _div(w[k], n[k]), _div(bd[k], n[k]), int(n[k])] for k in range(5)]
    pb = base & (A["prevb"] == 1)
    npb = int(pb.sum())
    rows.append(["Previous ball was a boundary", _div(A["wkt"][pb].sum(), npb),
                 _div(A["four"][pb].sum() + A["six"][pb].sum(), npb), npb])
    df = _frame(rows, ["Before this ball", "Wicket chance", "Boundary chance", "Balls"])

    parts = []
    wc = [r[1] for r in rows[:5] if r[3] >= 100 and _ok(r[1])]
    if len(wc) >= 2:
        lo, hi = min(wc), max(wc)
        verb = "stays between" if hi - lo < 0.015 else "ranges from"
        sep = "and" if verb == "stays between" else "to"
        parts.append(f"The chance of a wicket on the next ball {verb} {lo:.1%} {sep} {hi:.1%} however many dots "
                     f"came before it.")
    avg = _div(bd.sum(), n.sum())
    if npb and _ok(rows[5][2], avg) and avg > 0:
        parts.append(f"After a boundary, the next legal ball goes for four or six {rows[5][2]:.1%} of the time v "
                     f"{avg:.1%} on all balls ({rows[5][2] / avg - 1:+.0%}).")
    return Block(
        key="ki_09",
        title="Does dot-ball pressure take wickets?",
        finding=" ".join(parts) or None,
        df=df, fmt={"Wicket chance": P1, "Boundary chance": P1, "Balls": I0},
    )


def _ki10(A, sm) -> Block:
    bins = [("Balls 1–5", 1, 5), ("6–10", 6, 10), ("11–20", 11, 20), ("21–30", 21, 30),
            ("31+", 31, 999)]
    base = sm & (A["faced"] == 1)
    bn = A["ballno"]
    rows = []
    for label, lo, hi in bins:
        mk = base & (bn >= lo) & (bn <= hi)
        f = A["faced"][mk].sum()
        rows.append([label, _div(A["batruns"][mk].sum(), f, 100), _div(A["sout"][mk].sum(), f, 100),
                     int(f)])
    df = _frame(rows, ["Batter's balls faced", "Strike rate", "Dismissals per 100 balls", "Balls"])

    finding = None
    later = [r[1] for r in rows[1:] if _ok(r[1])]
    if _ok(rows[0][1], rows[0][2]) and later:
        finding = (f"Strike rate is {rows[0][1]:.0f} in a batter's first five balls v {min(later):.0f}–"
                   f"{max(later):.0f} later. Dismissals run at {rows[0][2]:.1f} per 100 balls early")
        finding += (f" and {rows[4][2]:.1f} after 30 balls." if _ok(rows[4][2]) else ".")
    return Block(
        key="ki_10",
        title="New batters: strike rate and dismissal risk by balls faced",
        finding=finding,
        df=df, fmt={"Strike rate": F1, "Dismissals per 100 balls": F2, "Balls": I0},
    )


def _ki11(A, sm) -> Block:
    nt = len(BTYPES)
    ok = sm & (A["hand"] >= 0) & (A["btype"] >= 0) & (A["btype"] < nt)
    key = np.where(ok, A["hand"] * nt + A["btype"], -1)
    r = _bc(key, ok, A["batruns"], 2 * nt)
    f = _bc(key, ok, A["faced"], 2 * nt)
    sr = _div(r, f, 100).reshape(2, nt)
    df = pd.DataFrame(sr, columns=BTYPES)
    df.insert(0, "Strike rate", ["RHB", "LHB"])

    parts = []
    fb = f.reshape(2, nt)
    for i, who in enumerate(["Right-handers", "left-handers"]):
        vals = [(sr[i, j], BTYPES[j]) for j in range(nt) if fb[i, j] >= 120 and _ok(sr[i, j])]
        if vals:
            v, t = min(vals)
            parts.append(f"{who} score slowest against {t.lower()} (SR {v:.0f})")
    finding = (" and ".join(parts) + ".") if parts else None
    return Block(
        key="ki_11",
        title="Batter hand v bowling type: strike rate",
        finding=finding,
        note="Strike rate (runs per 100 balls) of right- and left-handers against each bowling type. Green ≤ 125, "
             "pink ≥ 137.",
        df=df, kind="matrix",
        fmt={c: F1 for c in BTYPES},
        # CF on C102:H103: <=125 green, >=137 red, otherwise yellow
        rules={"*": {"good": ("<=", 125), "bad": (">=", 137)}},
    )


def _ki12(A, sm) -> Block:
    lap, rap = A["btype"] == 1, A["btype"] == 0
    stars = _left_arm_stars()[1]
    spec = [("Left-arm pace", lap), ("Right-arm pace", rap),
            (f"Left-arm pace without {stars}", lap & ~A["big3"])]
    pp, death = A["phase"] == 0, A["phase"] == 3
    rows = []
    for label, t in spec:
        mk = sm & t
        mp, md = mk & pp, mk & death
        rows.append([label,
                     _div(A["batruns"][mk].sum(), A["faced"][mk].sum(), 100),
                     _div(A["bowlruns"][mp].sum(), A["legal"][mp].sum(), 6),
                     _div(A["bowlruns"][md].sum(), A["legal"][md].sum(), 6)])
    cols = ["Bowling type", "Batters' strike rate against", "Powerplay economy", "Death economy"]
    df = _frame(rows, cols)

    parts = []
    (_, sl, pl, dl), (_, sr_, pr, dr), (_, sx, _, _) = rows
    if _ok(sl, sr_):
        parts.append(f"Batters strike at {sl:.0f} against left-arm pace and {sr_:.0f} against right-arm pace.")
    if _ok(pl, pr, dl, dr):
        parts.append(f"Left-armers concede {pl:.2f} v {pr:.2f} an over in the powerplay and {dl:.2f} v {dr:.2f} "
                     f"at the death.")
    if _ok(sx):
        parts.append(f"Without {_nm(stars)}, batters strike at {sx:.0f} against left-arm pace.")
    return Block(
        key="ki_12",
        title="Left-arm v right-arm pace",
        finding=" ".join(parts) or None,
        df=df, fmt={cols[1]: F1, cols[2]: F2, cols[3]: F2}, good_low=cols[1:],
    )


def _ki13(A, sm) -> Block:
    nt = len(BTYPES)
    md = sm & (A["phase"] == 3)
    runs = _bc(A["btype"], md, A["bowlruns"], nt)
    legal = _bc(A["btype"], md, A["legal"], nt)
    wk = _bc(A["btype"], md, A["bwkt"], nt)
    known = A["legal"][md & (A["btype"] != 6)].sum()     # bd_btype "<>Unknown"
    df = pd.DataFrame({
        "Bowling type": BTYPES,
        "Death economy": _div(runs, legal, 6),
        "Balls per wicket at death": _div(legal, wk),
        "Share of death balls": _div(legal, np.full(nt, known)),
        "Death balls bowled": legal.astype(np.int64),
    })

    finding = None
    econ, bpw, share = df["Death economy"].to_numpy(), df["Balls per wicket at death"].to_numpy(), \
        df["Share of death balls"].to_numpy()
    cand = [(econ[j], j) for j in range(nt) if legal[j] >= 60 and _ok(econ[j])]
    if cand:
        j = min(cand)[1]
        w = f", a wicket every {bpw[j]:.0f} balls" if _ok(bpw[j]) else ""
        finding = (f"At the death, {BTYPES[j].lower()} is the cheapest type ({econ[j]:.1f} an over{w}) and bowls "
                   f"{share[j]:.1%} of death balls.")
        if j != 0 and legal[0] >= 60 and _ok(econ[0]):
            w0 = f" (a wicket every {bpw[0]:.0f} balls)" if _ok(bpw[0]) else ""
            finding += f" Right-arm pace goes at {econ[0]:.1f}{w0} and bowls {share[0]:.0%} of them."
    return Block(
        key="ki_13",
        title="Bowling types at the death",
        finding=finding,
        note="Overs 17–20. Economy uses runs charged to the bowler; wickets are bowler wickets.",
        df=df, fmt={"Death economy": F2, "Balls per wicket at death": F1, "Share of death balls": P1,
                    "Death balls bowled": I0},
        good_low=["Death economy", "Balls per wicket at death"],
    )


def _ki14(A, sm) -> Block:
    runs = _bc(A["pair"], sm, A["runs"], 2)
    legal = _bc(A["pair"], sm, A["legal"], 2)
    wkt = _bc(A["pair"], sm, A["wkt"], 2)
    mo2 = sm & (A["phase"] == 2)
    r2 = _bc(A["pair"], mo2, A["runs"], 2)
    l2 = _bc(A["pair"], mo2, A["legal"], 2)
    df = pd.DataFrame({
        "Batting pair": PAIR_CATS,
        "Runs per over": _div(runs, legal, 6),
        "Balls per wicket": _div(legal, wkt),
        "MO2 runs per over": _div(r2, l2, 6),
    })
    cols = ["Runs per over", "Balls per wicket", "MO2 runs per over"]

    finding = None
    rpo, bpw = df["Runs per over"].to_numpy(), df["Balls per wicket"].to_numpy()
    if _ok(*rpo, *bpw):
        finding = (f"With a left- and right-hander together, teams scored {rpo[0]:.2f} an over v {rpo[1]:.2f} for "
                   f"same-hand pairs, and lost a wicket every {bpw[0]:.1f} balls v {bpw[1]:.1f}.")
    return Block(
        key="ki_14",
        title="Left–right batting pairs v same-hand pairs",
        finding=finding,
        df=df, fmt={"Runs per over": F2, "Balls per wicket": F1, "MO2 runs per over": F2},
        good_high=cols,
    )


def _ki15(A, span) -> Block:
    lo, hi = _bounds(span)
    seasons = list(d.seasons())
    sidx = np.searchsorted(np.array(seasons), A["season"])     # position in the league's seasons (gaps allowed)
    n = len(seasons)
    allm = np.ones_like(A["legal"], dtype=bool)
    death = A["phase"] == 3
    # SUMIFS(bd_batruns, bd_legal, ">=0", …) — every row has a numeric Legal Ball
    run_os = _bc(sidx, A["bos"], A["batruns"], n)
    run_all = _bc(sidx, allm, A["batruns"], n)
    wk_os = _bc(sidx, A["wos"], A["bwkt"], n)
    wk_all = _bc(sidx, allm, A["bwkt"], n)
    db_os = _bc(sidx, death & A["wos"], A["legal"], n)
    db_all = _bc(sidx, death, A["legal"], n)
    sel = np.array([lo <= s <= hi for s in seasons])
    rows = [[s, _div(run_os[i], run_all[i]), _div(wk_os[i], wk_all[i]), _div(db_os[i], db_all[i])]
            for i, s in enumerate(seasons)]
    rows.append(["Selected span",
                 _div(run_os[sel].sum(), run_all[sel].sum()),
                 _div(wk_os[sel].sum(), wk_all[sel].sum()),
                 _div(db_os[sel].sum(), db_all[sel].sum())])
    cols = ["Season", "Overseas share of runs", "Overseas share of wickets",
            "Overseas share of death balls"]
    df = pd.DataFrame(rows, columns=cols)
    df["Season"] = df["Season"].astype(object)
    chart_df = df.iloc[:-1].copy()
    chart_df["Season"] = chart_df["Season"].astype(int)

    parts = []
    _, r, w, db = rows[-1]
    if _ok(r, w, db):
        parts.append(f"In the selected span overseas batters scored {r:.0%} of the runs; overseas bowlers took "
                     f"{w:.0%} of the wickets and bowled {db:.0%} of the death balls.")
    inside = [row for row in rows[:-1] if lo <= row[0] <= hi and _ok(row[1], row[2])]
    if len(inside) >= 2:
        a, b = inside[0], inside[-1]
        parts.append(f"Their share of runs went from {a[1]:.0%} in {a[0]} to {b[1]:.0%} in {b[0]}; of wickets, "
                     f"from {a[2]:.0%} to {b[2]:.0%}.")
    return Block(
        key="ki_15",
        title="Overseas players' share of runs, wickets and death overs",
        finding=" ".join(parts) or None,
        note="Every season is listed; seasons outside your span are greyed.",
        df=df, fmt={c: P1 for c in cols[1:]},
        muted_rows=[i for i, s in enumerate(seasons) if not (lo <= s <= hi)],
        bold_rows=[len(df) - 1],
        chart={"type": "line", "x": "Season", "y": cols[1:], "data": chart_df,
               "title": "Overseas share by season", "color": "sky"},
    )


def _ki16(A, sm) -> Block:
    nt = len(BTYPES)
    base = sm & (A["bwkt"] == 1)
    tot = _bc(A["btype"], base, None, nt)
    hw = {h: _bc(A["btype"], base & (A["how"] == i), None, nt) for i, h in enumerate(HOW_CATS)}
    df = pd.DataFrame({
        "Bowling type": BTYPES,
        "Bowled": _div(hw["bowled"], tot),
        "LBW": _div(hw["lbw"], tot),
        "Caught (incl. c&b)": _div(hw["caught"] + hw["caught and bowled"], tot),
        "Stumped": _div(hw["stumped"], tot),
    })

    parts = []
    ls = BTYPES.index("Leg-spin")
    pace = [BTYPES.index("Right-arm pace"), BTYPES.index("Left-arm pace")]
    finger = [BTYPES.index("Off-spin"), BTYPES.index("Left-arm orthodox")]
    if tot[ls] >= 20:
        parts.append(f"Leg-spinners hit the stumps or pads for {(hw['bowled'][ls] + hw['lbw'][ls]) / tot[ls]:.0%} "
                     f"of their wickets")
    tp = tot[pace].sum()
    if tp >= 20:
        parts.append(f"pace takes {(hw['caught'][pace].sum() + hw['caught and bowled'][pace].sum()) / tp:.0%} "
                     f"caught")
    tf = tot[finger].sum()
    if tf >= 20:
        parts.append(f"finger spinners earn {hw['stumped'][finger].sum() / tf:.0%} stumpings")
    finding = None
    if parts:
        finding = "; ".join(parts) + "."
        finding = finding[0].upper() + finding[1:]
    return Block(
        key="ki_16",
        title="Dismissal fingerprints: how each type takes wickets",
        finding=finding,
        note="Share of each type's bowler wickets by mode of dismissal.",
        df=df, fmt={c: P1 for c in ["Bowled", "LBW", "Caught (incl. c&b)", "Stumped"]},
    )


# ── §17–§18: player rankings via the Calc sheet logic ───────────────────────
_CALC_COLS = ["B b1-10", "R b1-10", "B b21+", "R b21+", "B Death", "R Death",
              "BB MO1", "BR MO1", "BB Death", "BR Death"]


def _calc(span) -> pd.DataFrame:
    """Calc!A:T — per-player span sums in Calc row order (players() order),
    plus the four ranking keys (metric or ±999, + ROW()/1E9)."""
    lo, hi = _bounds(span)
    ps = d.player_seasons()
    s = ps["Season"].to_numpy()
    sub = ps.loc[(s >= lo) & (s <= hi), ["Player"] + _CALC_COLS]
    g = sub.groupby("Player", sort=False)[_CALC_COLS].sum()
    names = d.players()["Player"].to_numpy()
    g = g.reindex(names, fill_value=0).astype(float)
    row = np.arange(len(names), dtype=float) + 2             # Excel ROW() on Calc
    G, H, I, J = (g[k].to_numpy() for k in ("B b1-10", "R b1-10", "B b21+", "R b21+"))
    L, M = g["B Death"].to_numpy(), g["R Death"].to_numpy()
    O, P = g["BB MO1"].to_numpy(), g["BR MO1"].to_numpy()
    R, S = g["BB Death"].to_numpy(), g["BR Death"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        # K: =IF(AND(G>=150,I>=150),100*J/I-100*H/G,-999)+ROW()/1E9
        g["Gear key"] = np.where((G >= 150) & (I >= 150), (100 * J) / I - (100 * H) / G, -999.0) + row / 1e9
        # N: =IF(L>=100,100*M/L,-999)+ROW()/1E9
        g["Death SR key"] = np.where(L >= 100, (100 * M) / L, -999.0) + row / 1e9
        # Q: =IF(O>=150,6*P/O,999)+ROW()/1E9
        g["MO1 econ key"] = np.where(O >= 150, (6 * P) / O, 999.0) + row / 1e9
        # T: =IF(R>=150,6*S/R,999)+ROW()/1E9
        g["Death econ key"] = np.where(R >= 150, (6 * S) / R, 999.0) + row / 1e9
    return g


def _rank(key: np.ndarray, n: int, largest: bool, limit: float) -> np.ndarray:
    """Positions of LARGE/SMALL(key, 1..n) that pass the IF(>-900 / <900) guard."""
    order = np.argsort(-key if largest else key, kind="stable")[:n]
    ok = key[order] > limit if largest else key[order] < limit
    return order[ok]


def _ki17(c: pd.DataFrame) -> Block:
    G, H, I, J = (c[k].to_numpy() for k in ("B b1-10", "R b1-10", "B b21+", "R b21+"))
    pos = _rank(c["Gear key"].to_numpy(), 8, True, -900)     # LARGE(K,1..8) + MATCH
    with np.errstate(divide="ignore", invalid="ignore"):
        c1 = (100 * H[pos]) / G[pos]
        c2 = (100 * J[pos]) / I[pos]
    df = pd.DataFrame({
        "Batter": c.index.to_numpy()[pos].astype(object),
        "SR in first 10 balls": c1,
        "SR after 20 balls": c2,
        "Gear change": c2 - c1,
    }).reset_index(drop=True)

    finding = None
    if len(df) and _ok(c1[0], c2[0]):
        finding = (f"{_nm(df['Batter'].iloc[0])} changes gear the most: strike rate {c1[0]:.0f} in the first 10 "
                   f"balls, {c2[0]:.0f} after 20 ({c2[0] - c1[0]:+.0f}).")
    return Block(
        key="ki_17",
        title="Who changes gear the most",
        finding=finding,
        note=("Batters with the biggest jump in strike rate from their first 10 balls to after 20 balls "
              "(150+ balls in each stage within the span). These are the players to bowl at early — "
              "and to fear once set."),
        df=df, fmt={"SR in first 10 balls": F1, "SR after 20 balls": F1, "Gear change": "{:+.1f}"},
    )


def _ki18(c: pd.DataFrame) -> Block:
    names = c.index.to_numpy()
    L, M = c["B Death"].to_numpy(), c["R Death"].to_numpy()
    O, P = c["BB MO1"].to_numpy(), c["BR MO1"].to_numpy()
    R, S = c["BB Death"].to_numpy(), c["BR Death"].to_numpy()
    hit = _rank(c["Death SR key"].to_numpy(), 6, True, -900)    # LARGE(N,1..6)
    mo1 = _rank(c["MO1 econ key"].to_numpy(), 6, False, 900)    # SMALL(Q,1..6)
    dth = _rank(c["Death econ key"].to_numpy(), 6, False, 900)  # SMALL(T,1..6)
    n = max(len(hit), len(mo1), len(dth))

    def col(pos, vals):
        out = np.full(n, np.nan)
        out[:len(pos)] = vals
        return out

    def nm(pos):
        out = [None] * n
        out[:len(pos)] = list(names[pos])
        return out

    with np.errstate(divide="ignore", invalid="ignore"):
        df = pd.DataFrame({
            "Death-overs hitters": nm(hit),
            "SR": col(hit, (100 * M[hit]) / L[hit]),
            "Overs 7–10 bowlers": nm(mo1),
            "Econ": col(mo1, (6 * P[mo1]) / O[mo1]),
            "Death bowlers": nm(dth),
            "Econ ": col(dth, (6 * S[dth]) / R[dth]),
        })

    parts = []
    if len(hit):
        parts.append(f"Fastest finisher: {_nm(names[hit[0]])} (SR {100 * M[hit[0]] / L[hit[0]]:.0f} in overs 17–20).")
    if len(mo1):
        parts.append(f"Tightest in overs 7–10: {_nm(names[mo1[0]])} ({6 * P[mo1[0]] / O[mo1[0]]:.2f} an over).")
    if len(dth):
        parts.append(f"Cheapest at the death: {_nm(names[dth[0]])} ({6 * S[dth[0]] / R[dth[0]]:.2f}).")
    return Block(
        key="ki_18",
        title="Phase specialists",
        finding=" ".join(parts) or None,
        note=("The fastest finishers in overs 17–20 (100+ balls), the tightest bowlers in the "
              "overs-7–10 squeeze (150+ balls) and the cheapest death bowlers (150+ balls) — within "
              "the span."),
        df=df, fmt={"SR": F1, "Econ": F2, "Econ ": F2},
    )


HOW_TO_READ = (
    "Every finding and every table follows the Seasons box at the top. Win-% comparisons use decided "
    "matches only (no ties, no DLS).\n\n"
    "Phase \"winner\" comparisons count only phases in which both sides batted at least 12 balls. "
    "Samples are shown next to every percentage.\n\n"
    "Treat cells with fewer than ~20 cases as indicative; very short spans (one season) can turn "
    "small samples upside down."
)


def build(span: tuple[int, int]) -> list[Block]:
    lo, hi = _bounds(span)
    m = d.in_span(d.matches(), (lo, hi))
    tm = d.in_span(d.team_matches(), (lo, hi))
    A = _ball_arrays()
    sm = (A["season"] >= lo) & (A["season"] <= hi)
    calc = _calc((lo, hi))
    return [
        _ki01(m), _ki02(m), _ki03(m), _ki04(m), _ki05(m), _ki06(m), _ki07(tm),
        _ki08(A, sm), _ki09(A, sm), _ki10(A, sm), _ki11(A, sm), _ki12(A, sm),
        _ki13(A, sm), _ki14(A, sm), _ki15(A, (lo, hi)), _ki16(A, sm),
        _ki17(calc), _ki18(calc),
        Block(key="ki_read", title="How to read", kind="text", text=HOW_TO_READ),
    ]
