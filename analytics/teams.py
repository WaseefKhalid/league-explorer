"""
"Teams" sheet of the PSL Analytics Workbook.

§01 Record in the selected span (+ chart "Win % in the selected span")
§02 Season-by-season finish
§03 Head-to-head in the selected span
§04 Phase profile in the selected span
§05 Team batting v bowling types — strike rate
§06 Team batting v bowling types — balls per bowler wicket

build(span) -> list[Block]; keys "team_…".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analytics.data as d
from analytics.blocks import Block

PHASES = d.PHASES
BOWL_TYPES = d.BOWL_TYPES
FINISH_RANK = {"Champion": 4, "Runner-up": 3, "Playoffs": 2, "League": 1}


# ── helpers ──────────────────────────────────────────────────────────────────
def _div(a, b, scale=1.0):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a * scale / b
    out = np.where(np.isfinite(out), out, np.nan)
    return out


@d.per_league()
def teams() -> tuple[str, ...]:
    """Workbook row order: by first PSL season, then name (IU, KK, LQ, PZ, QG, MS, HK, RP)."""
    tm = d.team_matches()
    first = tm.groupby("Team")["Season"].min()
    listed = [t for t in d.lists()["Teams"].dropna().tolist()]
    return tuple(sorted(listed, key=lambda t: (first.get(t, 9999), t)))


def _span_tm(span):
    return d.in_span(d.team_matches(), span)


def _span_ball(span):
    return d.in_span(d.ball(), span)


# ── §01 Record ───────────────────────────────────────────────────────────────
RECORD_COLS = ["Team", "Seasons", "Played", "Won", "Lost", "NR", "Win %", "Titles", "Finals",
               "Playoff games", "Bat-first win %", "Chase win %", "Tosses won %",
               "Highest total", "Lowest completed", "Sixes / match"]
RECORD_FMT = {"Seasons": "{:,.0f}", "Played": "{:,.0f}", "Won": "{:,.0f}", "Lost": "{:,.0f}",
              "NR": "{:,.0f}", "Win %": "{:.1%}", "Titles": "{:,.0f}", "Finals": "{:,.0f}",
              "Playoff games": "{:,.0f}", "Bat-first win %": "{:.1%}", "Chase win %": "{:.1%}",
              "Tosses won %": "{:.1%}", "Highest total": "{:,.0f}", "Lowest completed": "{:,.0f}",
              "Sixes / match": "{:,.1f}"}


def record(span) -> pd.DataFrame:
    T = list(teams())
    tm = _span_tm(span)
    g = tm.groupby("Team")
    won = tm["Result"] == "Won"
    lost = tm["Result"] == "Lost"
    bf = tm["Batting Order"] == "Bat first"
    ch = tm["Batting Order"] == "Chasing"
    team = tm["Team"]

    def cnt(mask):
        return mask.groupby(team).sum().reindex(T, fill_value=0).astype(float)

    played = g.size().reindex(T, fill_value=0).astype(float)
    W, L, NR = cnt(won), cnt(lost), cnt(tm["Result"] == "No result")
    m = d.in_span(d.matches(), span)
    fin = m[m["Stage"] == "Final"]
    titles = fin["Winner"].value_counts().reindex(T, fill_value=0).astype(float)
    finals = (fin["Team 1"].value_counts().reindex(T, fill_value=0)
              + fin["Team 2"].value_counts().reindex(T, fill_value=0)).astype(float)
    bfw, bfl = cnt(bf & won), cnt(bf & lost)
    chw, chl = cnt(ch & won), cnt(ch & lost)
    hi = g["Runs Scored"].max().reindex(T)
    hi = hi.where(played > 0)
    hi = hi.where(hi.notna() | (played == 0), 0.0)           # MAXIFS of all-blank = 0
    lo = tm[tm["Completed Inns"] == 1].groupby("Team")["Runs Scored"].min().reindex(T)
    sixes = g["Sixes"].sum().reindex(T, fill_value=0)

    df = pd.DataFrame({
        "Team": T,
        "Seasons": tm.groupby("Team")["Season"].nunique().reindex(T, fill_value=0).astype(float).to_numpy(),
        "Played": played.to_numpy(),
        "Won": W.to_numpy(), "Lost": L.to_numpy(), "NR": NR.to_numpy(),
        "Win %": _div(W, played - NR),
        "Titles": titles.to_numpy(), "Finals": finals.to_numpy(),
        "Playoff games": cnt(tm["Match Type"] == "Playoff").to_numpy(),
        "Bat-first win %": _div(bfw, bfw + bfl),
        "Chase win %": _div(chw, chw + chl),
        "Tosses won %": _div(cnt(tm["Toss"] == "Won"), played),
        "Highest total": hi.to_numpy(dtype=float),
        "Lowest completed": lo.to_numpy(dtype=float),
        "Sixes / match": _div(sixes, played),
    })
    return df[RECORD_COLS]


# ── §02 Season-by-season finish ──────────────────────────────────────────────
FINISH_SEP = " · "      # the workbook wraps "Champion" and "4-4" onto two lines; one line here


@d.per_league()
def _finish_grid() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rows = teams, columns = seasons (as in the workbook). Numbers = finish rank
    (4 Champion … 1 League, for the tint), labels = "Champion · 4-4" (finish +
    league-stage W-L), "—" where the team wasn't in the league."""
    T = list(teams())
    seasons = [str(s) for s in d.seasons()]
    lst = d.lists()[["FinishKey", "FinishLabel"]].dropna()
    finish = dict(zip(lst["FinishKey"], lst["FinishLabel"]))
    tm = d.team_matches()
    lg = tm[tm["Match Type"] == "League"]
    wl = lg.groupby(["Team", "Season"])[["Win", "Loss"]].sum()

    num = pd.DataFrame(np.nan, index=range(len(T)), columns=seasons)
    lab = pd.DataFrame("—", index=range(len(T)), columns=seasons, dtype=object)
    for i, t in enumerate(T):
        for j, s in enumerate(seasons):
            f = finish.get(f"{t}|{s}")
            if f is None:
                continue
            key = (t, int(s))
            w, l_ = wl.loc[key].tolist() if key in wl.index else (0, 0)
            lab.iat[i, j] = f"{f}{FINISH_SEP}{int(w)}-{int(l_)}"
            num.iat[i, j] = FINISH_RANK.get(f, np.nan)
    num.insert(0, "Team", T)
    lab.insert(0, "Team", T)
    return num, lab


# ── §03 Head-to-head ─────────────────────────────────────────────────────────
def head_to_head(span) -> tuple[pd.DataFrame, pd.DataFrame]:
    T = list(teams())
    tm = _span_tm(span)
    key = [tm["Team"], tm["Opposition"]]
    n = tm.groupby(key).size().unstack().reindex(index=T, columns=T).fillna(0)
    w = (tm["Result"] == "Won").groupby(key).sum().unstack().reindex(index=T, columns=T).fillna(0)
    l_ = (tm["Result"] == "Lost").groupby(key).sum().unstack().reindex(index=T, columns=T).fillna(0)
    pct = pd.DataFrame(_div(w, w + l_), index=T, columns=T)
    wi, li, ni = w.astype(int).astype(str), l_.astype(int).astype(str), n.to_numpy()
    lab = wi + " – " + li
    lab = lab.where(ni > 0, "–")
    for t in T:
        lab.loc[t, t] = "—"
        pct.loc[t, t] = np.nan
    pct = pct.where(ni > 0)
    num = pct.reset_index(drop=True)
    num.insert(0, "Team", T)
    lab = lab.reset_index(drop=True)
    lab.insert(0, "Team", T)
    return num, lab.astype(object)


# ── §04 Phase profile ────────────────────────────────────────────────────────
PHASE_COLS = [f"Bat {p}" for p in PHASES] + [f"Bowl {p}" for p in PHASES]


@d.per_league(maxsize=32)
def _ball_agg(kind: str) -> pd.DataFrame:
    """Span-independent per-season sums of Ball Data (small; summed over the span on demand)."""
    b = d.ball()
    if kind == "bat_phase":
        return b.groupby(["Season", "Batting Team", "Phase"])[["Total Runs", "Legal Ball"]].sum()
    if kind == "bowl_phase":
        return b.groupby(["Season", "Bowling Team", "Phase"])[["Total Runs", "Legal Ball"]].sum()
    return b.groupby(["Season", "Batting Team", "Bowler Type"])[["Bat Runs", "Ball Faced", "Bowler Wkt"]].sum()


def _span_sum(kind: str, span) -> pd.DataFrame:
    agg = _ball_agg(kind)
    s = agg.index.get_level_values("Season")
    sub = agg[(s >= span[0]) & (s <= span[1])]
    return sub.groupby(level=[1, 2]).sum()


def phase_profile(span) -> pd.DataFrame:
    T = list(teams())
    df = pd.DataFrame({"Team": T})
    for side, kind in (("Bat", "bat_phase"), ("Bowl", "bowl_phase")):
        s = _span_sum(kind, span)
        runs = s["Total Runs"].unstack().reindex(index=T, columns=PHASES).fillna(0)
        legal = s["Legal Ball"].unstack().reindex(index=T, columns=PHASES).fillna(0)
        rr = _div(runs, legal, 6)
        for k, p in enumerate(PHASES):
            df[f"{side} {p}"] = rr[:, k]
    return df


# ── §05 / §06 Team batting v bowling types ───────────────────────────────────
LEAGUE = "League (all teams)"


def by_type(span, what: str, s: pd.DataFrame | None = None) -> pd.DataFrame:
    """what = 'sr' (100*bat runs/balls faced) or 'bpw' (balls faced/bowler wickets)."""
    T = list(teams())
    if s is None:
        s = _span_sum("type", span)
    lg = s.groupby(level=1).sum().reindex(BOWL_TYPES).fillna(0)

    def piv(c):
        return s[c].unstack().reindex(index=T, columns=BOWL_TYPES).fillna(0)

    if what == "sr":
        team_v = _div(piv("Bat Runs"), piv("Ball Faced"), 100)
        lg_v = _div(lg["Bat Runs"], lg["Ball Faced"], 100)
    else:
        team_v = _div(piv("Ball Faced"), piv("Bowler Wkt"))
        lg_v = _div(lg["Ball Faced"], lg["Bowler Wkt"])
    df = pd.DataFrame(np.vstack([team_v, lg_v[None, :]]), columns=BOWL_TYPES)
    df.insert(0, "Team", T + [LEAGUE])
    return df


def _league_rules(df: pd.DataFrame, up: float, down: float) -> dict:
    """Mirror 'C54>=C$62*1.05' style rules: thresholds per row (League row: none)."""
    rules = {}
    n = len(df) - 1
    for c in BOWL_TYPES:
        lg = df[c].iloc[n]
        if not np.isfinite(lg):
            continue
        hi = pd.Series([lg * up] * n + [np.nan], index=df.index)
        lo = pd.Series([lg * down] * n + [np.nan], index=df.index)
        rules[c] = {"good": (">=", hi), "bad": ("<=", lo)}
    return rules


# ── build ────────────────────────────────────────────────────────────────────
def build(span: tuple[int, int]) -> list[Block]:
    lo, hi = min(span), max(span)
    span = (lo, hi)
    T = list(teams())
    out: list[Block] = []

    rec = record(span)
    pct_rule = {"good": (">=", 0.55), "bad": ("<=", 0.45)}
    out.append(Block(
        key="team_01",
        title="Record in the selected span",
        df=rec,
        note="A super-over win counts as a win. Win % = wins ÷ (played − no results).",
        rules={"Win %": pct_rule, "Bat-first win %": pct_rule, "Chase win %": pct_rule},
        fmt=dict(RECORD_FMT),
        chart={"type": "hbar", "x": "Team", "y": "Win %", "title": "Win % in the selected span",
               "labels": {"Win %": "Win %"}, "color": "green",
               # chart in percent points (the table keeps fractions + "{:.1%}")
               "data": pd.DataFrame({"Team": rec["Team"], "Win %": (rec["Win %"] * 100).round(1)})
                         .dropna().reset_index(drop=True)},
    ))

    num, lab = _finish_grid()
    scols = [str(s) for s in d.seasons()]
    out.append(Block(
        key="team_02",
        title="Season-by-season finish",
        df=num.copy(),
        labels=lab.copy(),
        kind="matrix",
        note=("league W-L after the finish · seasons outside your span are greyed. "
              "Champion (darkest green), Runner-up, Playoffs (light green), League stage (no tint); "
              "numbers are league-stage W-L."),
        good_high=scols,
        center={c: 1.0 for c in scols},
        muted_cols=[c for c in scols if int(c) < lo or int(c) > hi],
    ))

    h_num, h_lab = head_to_head(span)
    out.append(Block(
        key="team_03",
        title="Head-to-head in the selected span (row team wins – losses v column team)",
        df=h_num,
        labels=h_lab,
        kind="matrix",
        note="Row team's wins – losses against the column team. Tint: row team's win % (green above 50%).",
        good_high=T,
        center={t: 0.5 for t in T},
        fmt={t: "{:.0%}" for t in T},
    ))

    ph = phase_profile(span)
    rules = {}
    for c in PHASE_COLS:
        avg = float(np.nanmean(ph[c].to_numpy())) if ph[c].notna().any() else np.nan
        if not np.isfinite(avg):
            continue
        if c.startswith("Bat"):
            rules[c] = {"good": (">=", avg * 1.03), "bad": ("<=", avg * 0.97)}
        else:
            rules[c] = {"good": ("<=", avg * 0.97), "bad": (">=", avg * 1.03)}
    out.append(Block(
        key="team_04",
        title="Phase profile in the selected span",
        df=ph,
        note=("batting run rate (higher = better) · bowling run rate conceded (lower = better). "
              "Green = 3%+ better than the average of all teams, pink = worse, amber = close."),
        rules=rules,
        fmt={c: "{:,.2f}" for c in PHASE_COLS},
    ))

    type_sums = _span_sum("type", span)
    sr = by_type(span, "sr", type_sums)
    out.append(Block(
        key="team_05",
        title="Team batting v bowling types — strike rate",
        df=sr,
        note=("selected span · tint compares with the league row (higher = better for the batting team): "
              "green = 5%+ above the league, pink = 5%+ below."),
        rules=_league_rules(sr, 1.05, 0.95),
        fmt={c: "{:,.1f}" for c in BOWL_TYPES},
        bold_rows=[len(sr) - 1],
    ))

    bpw = by_type(span, "bpw", type_sums)
    out.append(Block(
        key="team_06",
        title="Team batting v bowling types — balls per bowler wicket",
        df=bpw,
        note=("selected span · tint compares with the league row (higher = better for the batting team): "
              "green = 10%+ above the league, pink = 10%+ below."),
        rules=_league_rules(bpw, 1.10, 0.90),
        fmt={c: "{:,.1f}" for c in BOWL_TYPES},
        bold_rows=[len(bpw) - 1],
    ))

    out.append(Block(
        key="team_howto",
        title="How to read",
        kind="text",
        text=("- Every table follows the Seasons box at the top. A super-over win counts as a win. "
              "Win % = wins ÷ (played − no results).\n"
              "- Season grid: Champion (dark green), Runner-up (green), Playoffs (light green), League "
              "stage (grey); numbers are league-stage W-L.\n"
              "- Phase & type tables: green = 3%+ better than the average of all teams (5% / 10% v the "
              "league row for the type tables), pink = worse, amber = close."),
    ))
    return out
