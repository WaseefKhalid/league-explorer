"""
Player of the Match sheet — who wins the award, how often, for what kind of
performance — for any span.

Mirrors the workbook's 'Player of the Match' sheet: Match Data POTM columns
plus the hidden 'Calc' sheet (AO = awards in span, AP = matches in span,
AQ = ranking key AO - AP/10000 + ROW()/1E9, BN = losing-side award index).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import data as d
from analytics.blocks import Block

TYPES = ["Batting", "Bowling", "All-round", "Other"]
ORIGINS = ["Local", "Overseas"]
DASH = "—"


def _span(span):
    return int(min(span)), int(max(span))


def _matches(span) -> pd.DataFrame:
    lo, hi = _span(span)
    m = d.matches()
    return m[(m["Season"] >= lo) & (m["Season"] <= hi)]


def _has_award(m: pd.DataFrame) -> pd.Series:
    """COUNTIFS(md_potm,"?*") — a non-empty text value."""
    p = m["Player of Match"]
    return p.notna() & (p.astype(str).str.len() > 0)


def _dash_labels(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame | None:
    """'—' where the workbook's IFERROR(...,"—") would fire (NaN here)."""
    if not df[cols].isna().any().any():
        return None
    lab = pd.DataFrame(None, index=df.index, columns=df.columns, dtype=object)
    for c in cols:
        lab.loc[df[c].isna(), c] = DASH
    return lab


def _calc_potm(span) -> pd.DataFrame:
    """Calc!A, AO, AP, AQ for the span (Players order, Excel row in `_row`)."""
    lo, hi = _span(span)
    m = _matches(span)
    awards = m.loc[_has_award(m), "Player of Match"].astype(str).value_counts()
    ps = d.player_seasons()
    ps = ps[(ps["Season"] >= lo) & (ps["Season"] <= hi)]
    mat = ps.groupby("Player", sort=False)["Mat"].sum()
    names = d.players()["Player"]
    c = pd.DataFrame({"Player": names.values})
    c["AO"] = awards.reindex(names.values).fillna(0).astype(int).values
    c["AP"] = mat.reindex(names.values).fillna(0).astype(int).values
    c["_row"] = np.arange(len(c)) + 2
    return c


# ── sections ─────────────────────────────────────────────────────────────────
def _kpis(m: pd.DataFrame, c: pd.DataFrame) -> Block:
    n = int(_has_award(m).sum())
    overseas = int((m["POTM Origin"] == "Overseas").sum())
    lost = int((m["POTM Side"] == "Lost").sum())
    batting = int((m["POTM Type"] == "Batting").sum())
    pct = (lambda k: DASH if n == 0 else f"{k / n:.1%}")
    return Block(
        key="potm_kpis", title="At a glance", kind="kpis",
        kpis=[
            ("AWARDS IN SPAN", f"{n:,.0f}", None),
            ("DIFFERENT WINNERS", f"{int((c['AO'] > 0).sum()):,.0f}", None),
            ("WON BY OVERSEAS PLAYERS", pct(overseas), None),
            ("FROM THE LOSING SIDE", f"{lost:,.0f}", None),
            ("BATTING-LED AWARDS", pct(batting), None),
        ],
    )


def _most_awards(m: pd.DataFrame, c: pd.DataFrame) -> Block:
    cols = ["#", "Player", "Awards", "Matches", "Award rate"] + TYPES
    q = c[c["AO"] > 0].copy()
    q["_key"] = (q["AO"] - q["AP"] / 10000).round(7) + q["_row"] / 1e9
    t = q.sort_values("_key", ascending=False).head(20).reset_index(drop=True)
    by_type = (m[_has_award(m)].groupby(["Player of Match", "POTM Type"]).size()
               .unstack(fill_value=0).reindex(columns=TYPES, fill_value=0))
    by_type = by_type.reindex(t["Player"].values).fillna(0).astype(int).reset_index(drop=True)
    df = pd.DataFrame({
        "#": np.arange(1, len(t) + 1),
        "Player": t["Player"].values,
        "Awards": t["AO"].values,
        "Matches": t["AP"].values,
        "Award rate": (t["AO"] / t["AP"].where(t["AP"] > 0)).values,
    })
    for ty in TYPES:
        df[ty] = by_type[ty].values
    df = df[cols]
    fmt = {"#": "{:.0f}", "Awards": "{:,.0f}", "Matches": "{:,.0f}", "Award rate": "{:.1%}"}
    fmt.update({ty: "{:,.0f}" for ty in TYPES})
    return Block(
        key="potm_01", title="Most awards — top 20", df=df,
        note="ties: fewer matches first", fmt=fmt,
        bars=["Awards"], good_high=["Award rate"],
    )


def _by_team(m: pd.DataFrame) -> Block:
    teams = d.lists()["Teams"].dropna().astype(str).tolist()
    aw = m
    awards = aw.groupby("POTM Team").size().reindex(teams, fill_value=0)
    wins = m.groupby("Winner").size().reindex(teams, fill_value=0)
    ty = aw.groupby(["POTM Team", "POTM Type"]).size().unstack(fill_value=0) \
        .reindex(index=teams, columns=TYPES, fill_value=0)
    ov = aw[aw["POTM Origin"] == "Overseas"].groupby("POTM Team").size().reindex(teams, fill_value=0)
    a = awards.where(awards > 0)
    df = pd.DataFrame({
        "Team": teams,
        "Awards": awards.values,
        "Team wins": wins.values,
        "Awards per win": (awards / wins.where(wins > 0)).values,
        "Batting-led": (ty["Batting"] / a).values,
        "Bowling-led": (ty["Bowling"] / a).values,
        "All-round": (ty["All-round"] / a).values,
        "Overseas winners": (ov / a).values,
    })
    pcts = ["Awards per win", "Batting-led", "Bowling-led", "All-round", "Overseas winners"]
    fmt = {"Awards": "{:,.0f}", "Team wins": "{:,.0f}"}
    fmt.update({c: "{:.1%}" for c in pcts})
    return Block(
        key="potm_02", title="Awards by team", df=df,
        note="POTM almost always comes from the winning side", fmt=fmt,
        labels=_dash_labels(df, pcts),
    )


def _award_types(m: pd.DataFrame) -> Block:
    n = int(_has_award(m).sum())
    g = m.groupby("POTM Type")
    cnt = g.size().reindex(TYPES, fill_value=0)
    sums = g[["POTM Runs", "POTM Balls", "POTM Runs Conceded", "POTM Balls Bowled"]].sum() \
        .reindex(TYPES).fillna(0)
    avg_runs = g["POTM Runs"].mean().reindex(TYPES)        # AVERAGEIFS skips blanks
    avg_wkts = g["POTM Wkts"].mean().reindex(TYPES)
    balls = sums["POTM Balls"].where(sums["POTM Balls"] != 0)
    bb = sums["POTM Balls Bowled"].where(sums["POTM Balls Bowled"] != 0)
    df = pd.DataFrame({
        "Award type": TYPES,
        "Awards": cnt.values,
        "Share": (cnt / n).values if n else np.full(len(TYPES), np.nan),
        "Avg runs": avg_runs.values,
        "Avg strike rate": (100 * sums["POTM Runs"] / balls).values,
        "Avg wickets": avg_wkts.values,
        "Avg economy": (6 * sums["POTM Runs Conceded"] / bb).values,
    })
    num = ["Share", "Avg runs", "Avg strike rate", "Avg wickets", "Avg economy"]
    return Block(
        key="potm_03", title="What wins the award", df=df,
        note="performance type of each award",
        fmt={"Awards": "{:,.0f}", "Share": "{:.1%}", "Avg runs": "{:,.1f}",
             "Avg strike rate": "{:,.1f}", "Avg wickets": "{:,.2f}", "Avg economy": "{:,.2f}"},
        labels=_dash_labels(df, num),
    )


def _origin(m: pd.DataFrame, span) -> Block:
    lo, hi = _span(span)
    n = int(_has_award(m).sum())
    aw = m.groupby("POTM Origin").size().reindex(ORIGINS, fill_value=0)
    ps = d.player_seasons()
    ps = ps[(ps["Season"] >= lo) & (ps["Season"] <= hi)]
    mat = ps.groupby("Origin")["Mat"].sum().reindex(ORIGINS, fill_value=0)
    tot = ps["Mat"].sum()
    matn = mat.where(mat != 0)
    df = pd.DataFrame({
        "Players": ORIGINS,
        "Awards": aw.values,
        "Share of awards": (aw / n).values if n else np.full(2, np.nan),
        "Share of appearances": (mat / tot).values if tot else np.full(2, np.nan),
        "Awards per 100 appearances": (100 * aw / matn).values,
    })
    num = ["Share of awards", "Share of appearances", "Awards per 100 appearances"]
    return Block(
        key="potm_04", title="Overseas v local", df=df,
        note="share of awards against share of appearances",
        fmt={"Awards": "{:,.0f}", "Share of awards": "{:.1%}",
             "Share of appearances": "{:.1%}", "Awards per 100 appearances": "{:,.2f}"},
        labels=_dash_labels(df, num),
    )


def _losing_side(m: pd.DataFrame) -> Block:
    # Calc!BN + SMALL(): Match Data order, first 10 in the span
    t = m[m["POTM Side"] == "Lost"].head(10)
    df = pd.DataFrame({
        "#": np.arange(1, len(t) + 1),
        "Player": t["Player of Match"].values,
        "Date": pd.to_datetime(t["Date"]).values,
        "Season": t["Season"].values,
        "Team": t["POTM Team"].values,
        "Runs": t["POTM Runs"].fillna(0).values,        # INDEX() of a blank cell = 0
        "Beaten by": t["Winner"].values,
        "Wickets": t["POTM Wkts"].fillna(0).values,
    })
    return Block(
        key="potm_05", title="Awards won from the losing side", df=df,
        note="up to 10 in the span, oldest first",
        fmt={"#": "{:.0f}", "Date": "{:%d-%b-%Y}", "Season": "{:.0f}",
             "Runs": "{:,.0f}", "Wickets": "{:,.0f}"},
    )


def _finals(span) -> Block:
    lo, hi = _span(span)
    m = d.matches()
    seasons = list(d.seasons())
    fin = m[m["Key"].isin([f"{s}|Final" for s in seasons])].drop_duplicates("Key")
    fin = fin.set_index("Season").reindex(seasons)
    has = fin["Key"].notna()
    df = pd.DataFrame({
        "Season": seasons,
        "Player of the Match": fin["Player of Match"].values,
        "Award type": fin["POTM Type"].values,
        "Runs": fin["POTM Runs"].fillna(0).where(has).values,      # INDEX() of a blank = 0
        "Team": fin["POTM Team"].values,
        "Wickets": fin["POTM Wkts"].fillna(0).where(has).values,
        "Champion": fin["Winner"].values,
    })
    muted = [i for i, s in enumerate(seasons) if s < lo or s > hi]
    return Block(
        key="potm_06", title="Player of the Match in every final", df=df,
        note="seasons outside your span are greyed",
        fmt={"Season": "{:.0f}", "Runs": "{:,.0f}", "Wickets": "{:,.0f}"},
        muted_rows=muted,
    )


def _howto(m: pd.DataFrame) -> Block:
    none = m[~_has_award(m)]
    nr = int((none["Result"] == "No result").sum())
    k = len(none)
    if k == 0:
        gaps = "Every match in the span had an award."
    else:
        gaps = (f"{k} match{'es' if k != 1 else ''} in the span had no award ({nr} no-result"
                f"{'s' if nr != 1 else ''} and {k - nr} other{'s' if k - nr != 1 else ''}).")
    return Block(
        key="potm_howto", title="How to read", kind="text",
        text=(
            "Award type: Batting = 30+ runs (or 15+ without a wicket); Bowling = 2+ wickets (or 1 "
            "wicket with 3+ overs at 6.5 an over or better); All-round = 25+ runs and 2+ wickets, "
            "or both batting and bowling cases; Other = fielding / keeping / economy.\n\n"
            f"Award rate = awards ÷ matches played in the span. {gaps} Every table follows the Seasons box."
        ),
    )


def build(span: tuple[int, int]) -> list[Block]:
    m = _matches(span)
    c = _calc_potm(span)
    return [
        _kpis(m, c),
        _most_awards(m, c),
        _by_team(m),
        _award_types(m),
        _origin(m, span),
        _losing_side(m),
        _finals(span),
        _howto(m),
    ]
