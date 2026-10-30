"""
Records: the analyses from the original Streamlit site that the workbook
doesn't have — record totals, best innings and figures, partnerships and
batting by position. Built from the same workbook data (plus partnerships
from the raw Cricsheet file, which carries the non-striker).
"""
from __future__ import annotations

import pandas as pd

from analytics import data as d
from analytics.blocks import Block

FILTERS = ["player"]


def _date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _partnerships() -> pd.DataFrame:
    try:
        return d.load("partnerships")
    except FileNotFoundError:
        return pd.DataFrame()


def filter_options(span) -> dict:
    bi = d.in_span(d.bat_inns(), span)
    names = sorted(bi["Batter"].dropna().unique().tolist())
    return {"player": ["All batters"] + names}


DEFAULTS = {"player": "All batters"}


def build(span: tuple[int, int], player: str = "All batters") -> list[Block]:
    out: list[Block] = []
    tm = d.in_span(d.team_matches(), span)
    bi = d.in_span(d.bat_inns(), span)
    bo = d.in_span(d.bowl_inns(), span)

    # ── team totals ───────────────────────────────────────────────────────
    t = tm[tm["Balls Faced"] > 0].copy()
    t["Overs"] = (t["Balls Faced"] // 6) + (t["Balls Faced"] % 6) / 10
    t["Run rate"] = t["Runs Scored"] / t["Balls Faced"] * 6
    t["Score"] = t["Runs Scored"].astype(int).astype(str) + "/" + t["Wkts Lost"].astype(int).astype(str)
    t["Date"] = _date(t["Date"])
    cols = ["Team", "Opposition", "Season", "Date", "Venue", "Score", "Runs Scored", "Overs", "Run rate", "Result"]
    hi = t.sort_values(["Runs Scored", "Balls Faced"], ascending=[False, True]).head(10)[cols].reset_index(drop=True)
    hi.insert(0, "#", range(1, len(hi) + 1))
    out.append(Block("rec_high", "Highest team totals", hi,
                     note="Top 10 innings totals in the span. Super overs excluded.",
                     fmt={"Overs": "{:.1f}", "Run rate": "{:.2f}", "Runs Scored": "{:,.0f}"},
                     good_high=["Run rate"]))
    low = t[(t["Completed Inns"] == 1) & (t["DLS"] == 0)]
    lo_t = low.sort_values(["Runs Scored", "Balls Faced"], ascending=[True, True]).head(10)[cols].reset_index(drop=True)
    lo_t.insert(0, "#", range(1, len(lo_t) + 1))
    out.append(Block("rec_low", "Lowest completed team totals", lo_t,
                     note="Bowled out or batted the full overs, no DLS.",
                     fmt={"Overs": "{:.1f}", "Run rate": "{:.2f}", "Runs Scored": "{:,.0f}"},
                     good_low=[]))

    # ── individual innings ────────────────────────────────────────────────
    b = bi.copy()
    b["Date"] = _date(b["Date"])
    b["Score"] = b["Runs"].astype(int).astype(str) + b["Out"].map(lambda o: "" if o == 1 else "*")
    top_b = b.sort_values(["Runs", "Balls"], ascending=[False, True]).head(15)
    top_b = top_b[["Batter", "Team", "Opposition", "Season", "Date", "Venue", "Score", "Runs", "Balls", "Fours",
                   "Sixes", "Strike Rate"]].reset_index(drop=True)
    top_b.insert(0, "#", range(1, len(top_b) + 1))
    out.append(Block("rec_innings", "Highest individual innings", top_b,
                     note="Top 15 scores in the span. * = not out.",
                     fmt={"Strike Rate": "{:.1f}"}, good_high=["Strike Rate"]))

    # ── bowling figures ───────────────────────────────────────────────────
    w = bo.copy()
    w["Date"] = _date(w["Date"])
    w["Figures"] = w["Wickets"].astype(int).astype(str) + "/" + w["Runs"].astype(int).astype(str)
    top_w = w.sort_values(["Wickets", "Runs", "Balls"], ascending=[False, True, True]).head(15)
    top_w = top_w[["Bowler", "Team", "Opposition", "Season", "Date", "Venue", "Figures", "Overs", "Dots",
                   "Economy"]].reset_index(drop=True)
    top_w.insert(0, "#", range(1, len(top_w) + 1))
    out.append(Block("rec_figures", "Best bowling figures", top_w,
                     note="Top 15 in the span: most wickets, then fewest runs.",
                     fmt={"Overs": "{:.1f}", "Economy": "{:.2f}"}, good_low=["Economy"]))

    # ── partnerships ──────────────────────────────────────────────────────
    p = d.in_span(_partnerships(), span) if not _partnerships().empty else pd.DataFrame()
    if not p.empty:
        pp = p.copy()
        pp["Date"] = _date(pp["Date"])
        pp["Stand"] = pp["Batter 1"] + " (" + pp["Batter 1 Runs"].astype(str) + ") & " + \
            pp["Batter 2"] + " (" + pp["Batter 2 Runs"].astype(str) + ")"
        pp["Run rate"] = pp["Runs"] / pp["Balls"].where(pp["Balls"] > 0) * 6
        pp["Runs label"] = pp["Runs"].astype(str) + pp["Unbroken"].map(lambda u: "*" if u else "")
        top_p = pp.sort_values(["Runs", "Balls"], ascending=[False, True]).head(10)
        tp = top_p[["Stand", "Batting Team", "Bowling Team", "Season", "Wicket", "Runs", "Balls", "Run rate"]] \
            .rename(columns={"Batting Team": "Team", "Bowling Team": "Opposition"}).reset_index(drop=True)
        tp.insert(0, "#", range(1, len(tp) + 1))
        out.append(Block("rec_stands", "Biggest partnerships", tp,
                         note="Top 10 stands for any wicket. Runs include extras; balls exclude wides.",
                         fmt={"Run rate": "{:.2f}"}, good_high=["Run rate"]))

        best = pp.sort_values(["Runs", "Balls"], ascending=[False, True]).groupby("Wicket").head(1)
        bw = best.sort_values("Wicket")[["Wicket", "Stand", "Batting Team", "Bowling Team", "Season", "Runs",
                                         "Balls", "Run rate"]] \
            .rename(columns={"Batting Team": "Team", "Bowling Team": "Opposition"}).reset_index(drop=True)
        out.append(Block("rec_wicket", "Best partnership for each wicket", bw,
                         fmt={"Run rate": "{:.2f}"}))

        if player and player != "All batters":
            mine = pp[(pp["Batter 1"] == player) | (pp["Batter 2"] == player)].copy()
            mine["Partner"] = mine.apply(lambda r: r["Batter 2"] if r["Batter 1"] == player else r["Batter 1"],
                                         axis=1)
            g = mine.groupby("Partner").agg(Innings=("Runs", "size"), Runs=("Runs", "sum"),
                                            Balls=("Balls", "sum"), Best=("Runs", "max"),
                                            Outs=("Unbroken", lambda s: int((s == 0).sum())))
            g["Average"] = g["Runs"] / g["Outs"].where(g["Outs"] > 0)
            g["Run rate"] = g["Runs"] / g["Balls"].where(g["Balls"] > 0) * 6
            g = g[g["Runs"] >= 50].sort_values(["Runs", "Average"], ascending=False).reset_index()
            g = g[["Partner", "Innings", "Runs", "Balls", "Average", "Run rate", "Best"]]
            out.append(Block("rec_partners", f"{player}'s partners", g,
                             note="Partners with 50+ runs together in the span, most runs first. Average = runs per "
                                  "completed stand.",
                             fmt={"Average": "{:.1f}", "Run rate": "{:.2f}"}, good_high=["Average", "Run rate"],
                             chart={"type": "hbar", "x": "Partner", "y": "Runs", "title": "Runs together",
                                    "data": g.head(10)} if len(g) else None))

    # ── batting by position ───────────────────────────────────────────────
    src = bi if not player or player == "All batters" else bi[bi["Batter"] == player]
    pos = src.groupby("Position").agg(Innings=("Runs", "size"), Runs=("Runs", "sum"), Balls=("Balls", "sum"),
                                      Outs=("Out", "sum"), Fours=("Fours", "sum"), Sixes=("Sixes", "sum"),
                                      Fifties=("Runs", lambda s: int(((s >= 50) & (s < 100)).sum())),
                                      Hundreds=("Runs", lambda s: int((s >= 100).sum())),
                                      Highest=("Runs", "max"))
    pos["Average"] = pos["Runs"] / pos["Outs"].where(pos["Outs"] > 0)
    pos["Strike rate"] = pos["Runs"] / pos["Balls"].where(pos["Balls"] > 0) * 100
    pos = pos.reset_index()[["Position", "Innings", "Runs", "Balls", "Average", "Strike rate", "Fifties",
                             "Hundreds", "Highest", "Fours", "Sixes"]]
    pos = pos.rename(columns={"Fifties": "50s", "Hundreds": "100s", "Fours": "4s", "Sixes": "6s"})
    who = "every batter" if not player or player == "All batters" else player
    out.append(Block("rec_position", f"Batting by position — {who}", pos,
                     note="Position = order the batter came in. Average = runs ÷ dismissals.",
                     fmt={"Average": "{:.1f}", "Strike rate": "{:.1f}", "Position": "{:.0f}"},
                     good_high=["Average", "Strike rate"],
                     chart={"type": "bar", "x": "Position", "y": "Strike rate",
                            "title": "Strike rate by batting position", "color": "sky"} if len(pos) else None))
    return out
