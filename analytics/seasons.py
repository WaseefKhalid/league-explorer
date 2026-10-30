"""
"Seasons" sheet of the PSL Analytics Workbook — season by season, for any league.

§01 Season summary  (one row per season + "Selected span" + "All seasons")
§02 Trends — every season (the sheet's two line charts)

build(span) -> list[Block]; keys "sea_…".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analytics.data as d
from analytics import presets
from analytics.blocks import Block

PHASES = d.PHASES

ABROAD = "In UAE"      # placeholder name in COLS / FMT; the real header is abroad_label()
COLS = ["Season", "Edition", "Teams", "Matches", ABROAD, "Champion", "Runner-up",
        "Final POTM", "Avg 1st-inns", "Run rate", "PP RR", "MO1 RR", "MO2 RR",
        "Death RR", "200+ totals", "Sixes / match", "Boundary %", "Dot %",
        "Chase win %", "Toss → bowl %", "Toss winner won %", "Top run-scorer",
        "Top wicket-taker"]

FMT = {
    "Teams": "{:,.0f}", "Matches": "{:,.0f}", ABROAD: "{:,.0f}",
    "Avg 1st-inns": "{:,.1f}", "Run rate": "{:,.2f}",
    "PP RR": "{:,.2f}", "MO1 RR": "{:,.2f}", "MO2 RR": "{:,.2f}", "Death RR": "{:,.2f}",
    "200+ totals": "{:,.0f}", "Sixes / match": "{:,.1f}",
    "Boundary %": "{:.1%}", "Dot %": "{:.1%}", "Chase win %": "{:.1%}",
    "Toss → bowl %": "{:.1%}", "Toss winner won %": "{:.1%}",
}


def _div(a, b, scale=1.0):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a * scale / b
    out[~np.isfinite(out)] = np.nan
    return out


@d.per_league()
def abroad_label() -> str:
    """Header of the 'matches played outside the home country' column:
    "In UAE" for the PSL (one other host), "Abroad" when there are several."""
    home = presets.home_country()
    hosts = sorted(set(d.matches()["Host"].dropna().astype(str)) - {home, "Unknown", ""})
    return f"In {hosts[0]}" if len(hosts) == 1 else "Abroad"


def _abroad(host: pd.Series) -> pd.Series:
    home = presets.home_country()
    return host.notna() & ~host.astype(str).isin([home, "Unknown", ""])


@d.per_league()
def _season_sums() -> pd.DataFrame:
    """Additive per-season sums (span rows are sums of these)."""
    seasons = list(d.seasons())
    m = d.matches()
    b = d.ball()

    g = m.groupby("Season")
    full1 = m["Full 1st Inns"] == 1
    S = pd.DataFrame(index=pd.Index(seasons, name="Season"))
    S["matches"] = g.size()
    S["uae"] = _abroad(m["Host"]).groupby(m["Season"]).sum()
    S["inn1_sum"] = m["1st Inns Runs"].where(full1).groupby(m["Season"]).sum()
    S["inn1_n"] = full1.groupby(m["Season"]).sum()
    S["n200"] = ((m["1st Inns Runs"] >= 200).astype(int) + (m["2nd Inns Runs"] >= 200).astype(int)).groupby(m["Season"]).sum()
    dec = m["Decided (no DLS)"] == 1
    S["dec"] = dec.groupby(m["Season"]).sum()
    S["chase_w"] = (dec & (m["Bat First Won"] == 0)).groupby(m["Season"]).sum()
    S["field"] = (m["Toss Decision"] == "Field").groupby(m["Season"]).sum()
    S["tw1"] = (m["Toss Winner Won"] == 1).groupby(m["Season"]).sum()
    S["tw0"] = (m["Toss Winner Won"] == 0).groupby(m["Season"]).sum()

    bs = b.groupby("Season")[["Total Runs", "Legal Ball", "Six", "Four", "Ball Faced", "Bowl Dot"]].sum()
    S["runs"] = bs["Total Runs"]
    S["legal"] = bs["Legal Ball"]
    S["six"] = bs["Six"]
    S["four"] = bs["Four"]
    S["faced"] = bs["Ball Faced"]
    S["bowldot"] = bs["Bowl Dot"]
    ph = b.groupby(["Season", "Phase"])[["Total Runs", "Legal Ball"]].sum().unstack("Phase")
    for p in PHASES:
        S[f"runs_{p}"] = ph[("Total Runs", p)] if ("Total Runs", p) in ph.columns else 0
        S[f"legal_{p}"] = ph[("Legal Ball", p)] if ("Legal Ball", p) in ph.columns else 0
    return S.fillna(0)


def _ratios(S: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=S.index)
    out["Matches"] = S["matches"].astype(float)
    out[ABROAD] = S["uae"].astype(float)
    out["Avg 1st-inns"] = _div(S["inn1_sum"], S["inn1_n"])
    out["Run rate"] = _div(S["runs"], S["legal"], 6)
    for p in PHASES:
        out[f"{p} RR"] = _div(S[f"runs_{p}"], S[f"legal_{p}"], 6)
    out["200+ totals"] = S["n200"].astype(float)
    out["Sixes / match"] = _div(S["six"], S["matches"])
    out["Boundary %"] = _div(S["four"] + S["six"], S["faced"])
    out["Dot %"] = _div(S["bowldot"], S["legal"])
    out["Chase win %"] = _div(S["chase_w"], S["dec"])
    out["Toss → bowl %"] = _div(S["field"], S["matches"])
    out["Toss winner won %"] = _div(S["tw1"], S["tw1"] + S["tw0"])
    return out


@d.per_league()
def _player_sums() -> pd.DataFrame:
    ps = d.player_seasons()
    return ps.groupby(["Player", "Season"])[["Runs", "Wkts", "Bowl Runs"]].sum()


@d.per_league(maxsize=256)
def _top_players(lo: int, hi: int) -> tuple[str, str]:
    """Calc!D/E/F logic: most runs (first player in Calc order on ties);
    most wickets, ties broken by fewer runs conceded."""
    P = _player_sums()
    sub = P[(P.index.get_level_values("Season") >= lo) & (P.index.get_level_values("Season") <= hi)]
    if sub.empty:
        return "—", "—"
    t = sub.groupby(level="Player").sum()          # sorted by name (Calc order)
    bat = t["Runs"].idxmax()
    key = np.where(t["Wkts"] > 0, t["Wkts"] - t["Bowl Runs"] / 1_000_000, -1.0)
    bowl = t.index[int(np.argmax(key))]
    return (f"{bat} ({int(t.loc[bat, 'Runs'])})",
            f"{bowl} ({int(t.loc[bowl, 'Wkts'])})")


def _edition(lo: int, hi: int) -> str:
    """'PSL 3', 'PSL 2–5': the league's short name and the season's number in the data."""
    a, b = d.edition(lo), d.edition(hi)
    return f"{d.short()} {a}" + (f"–{b}" if hi > lo else "")


def season_table(span: tuple[int, int]) -> tuple[pd.DataFrame, list, list]:
    lo, hi = min(span), max(span)
    seasons = list(d.seasons())
    S = _season_sums()
    span_s = S.loc[[s for s in seasons if lo <= s <= hi]].sum()
    all_s = S.sum()
    R = _ratios(pd.concat([S, span_s.to_frame("Selected span").T, all_s.to_frame("All seasons").T]))

    m = d.matches()
    finals = m[m["Key"].astype(str).str.endswith("|Final")].drop_duplicates("Season").set_index("Season")
    tm = d.team_matches()
    n_teams = tm.groupby("Season")["Team"].nunique()
    in_span_teams = tm[(tm["Season"] >= lo) & (tm["Season"] <= hi)]["Team"]
    span_teams = int(in_span_teams[in_span_teams.isin(d.lists()["Teams"].dropna())].nunique())
    rows = []
    for s in seasons:
        bat, bowl = _top_players(s, s)
        rows.append({
            "Season": str(s), "Edition": _edition(s, s),
            "Teams": float(n_teams.get(s, 0)),
            "Champion": finals["Winner"].get(s, "") if s in finals.index else "",
            "Runner-up": finals["Loser"].get(s, "") if s in finals.index else "",
            "Final POTM": finals["Player of Match"].get(s, "") if s in finals.index else "",
            "Top run-scorer": bat, "Top wicket-taker": bowl,
        })
    bat, bowl = _top_players(lo, hi)
    rows.append({"Season": "Selected span", "Edition": _edition(lo, hi), "Teams": float(span_teams),
                 "Champion": "—", "Runner-up": "—", "Final POTM": "—",
                 "Top run-scorer": bat, "Top wicket-taker": bowl})
    bat, bowl = _top_players(min(seasons), max(seasons))
    rows.append({"Season": "All seasons", "Edition": _edition(min(seasons), max(seasons)),
                 "Teams": float(tm["Team"].nunique()),
                 "Champion": "—", "Runner-up": "—", "Final POTM": "—",
                 "Top run-scorer": bat, "Top wicket-taker": bowl})
    df = pd.DataFrame(rows)
    for c in R.columns:
        df[c] = R[c].to_numpy()
    df = df[COLS].reset_index(drop=True).rename(columns={ABROAD: abroad_label()})

    muted = [i for i, s in enumerate(seasons) if s < lo or s > hi]
    span_row = len(seasons)
    return df, muted, [span_row]


def build(span: tuple[int, int]) -> list[Block]:
    lo, hi = min(span), max(span)
    df, muted, bold = season_table((lo, hi))

    b1 = Block(
        key="sea_01",
        title="Season summary",
        df=df,
        note='Seasons outside your span are greyed · "Selected span" adds up your span',
        rules={"Chase win %": {"good": (">=", 0.60), "bad": ("<=", 0.45)}},
        fmt={(abroad_label() if k == ABROAD else k): v for k, v in FMT.items()},
        muted_rows=muted,
        bold_rows=bold,
    )

    n = len(d.seasons())
    trend = df.iloc[:n][["Season", "Avg 1st-inns", "PP RR", "MO1 RR", "MO2 RR", "Death RR"]].reset_index(drop=True)
    b2 = Block(
        key="sea_02a",
        title="Trends — every season · average first-innings score",
        df=trend[["Season", "Avg 1st-inns"]].copy(),
        note="Every season, whatever the span. Completed first innings only.",
        fmt={"Avg 1st-inns": "{:,.1f}"},
        chart={"type": "line", "x": "Season", "y": "Avg 1st-inns",
               "title": "Average first-innings score",
               "labels": {"Avg 1st-inns": "Average first-innings score"}, "color": "amber"},
    )
    b3 = Block(
        key="sea_02b",
        title="Trends — every season · run rate by phase",
        df=trend[["Season", "PP RR", "MO1 RR", "MO2 RR", "Death RR"]].copy(),
        note="Every season, whatever the span. Runs per over including extras: PP (1–6), MO1 (7–10), MO2 (11–16), Death (17–20).",
        fmt={c: "{:,.2f}" for c in ["PP RR", "MO1 RR", "MO2 RR", "Death RR"]},
        chart={"type": "line", "x": "Season", "y": ["PP RR", "MO1 RR", "MO2 RR", "Death RR"],
               "title": "Run rate by phase"},
    )
    b4 = Block(
        key="sea_howto",
        title="How to read",
        kind="text",
        text=_howto(),
    )
    return [b1, b2, b3, b4]


def _howto() -> str:
    seasons = d.seasons()
    sh, n = d.short(), len(seasons)
    lines = [
        f"Season = the year the season ends in ({sh} 1 = {seasons[0]} … {sh} {n} = {seasons[-1]}).",
        '"Selected span" uses the Seasons box at the top: every column (including the top '
        "run-scorer and wicket-taker) is recalculated for that span.",
        "Avg 1st-inns uses completed first innings only. Run rates include extras. Chase win % "
        "excludes ties and DLS games (tint: green ≥ 60%, pink ≤ 45%).",
    ]
    if d.has("has_host"):
        lines.append(f"{abroad_label()} = matches played outside {presets.home_country() or 'the home country'}.")
    lines += presets.preset("season_notes", [])
    return "\n".join(f"- {t}" for t in lines)
