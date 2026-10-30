"""
MVP · Impact Performances tables, built from the core tables of any T20 league.

    build_mvp(tables, people) -> {"mvp/definitions": df, "mvp/glance": df, ...}

These are the tables the MVP pages (analytics/mvp_*.py) read. For the PSL they
reproduce the "Players — Impact Performances" workbook that tools/build_mvp.py
extracted into data/leagues/psl/mvp/*.parquet.

What counts (same rules as the workbook):
  impact performance  3+ wickets in an innings; an economy spell (economy 6.00 or
                      better from at least 3 overs, spells with 3+ wickets counted
                      under wickets); 50–99 (fifty); 100+ (hundred); 30–49 at a
                      strike rate of 150+ (quick-fire)
  knockout match      any play-off (Match Type == "Playoff")
  close finish        won by 10 runs or fewer, by 3 wickets or fewer, with 6 balls
                      or fewer left, or tied (super over); no-results excluded

Inputs
  tables  the core tables: matches, team_matches, bat_inns, bowl_inns, ball and
          player_seasons are used (the others are ignored). Optional:
          tables["match_players"] = the playing XIs, columns Match ID, Team,
          Player (same player names as the core tables). Cricsheet's info files
          list every XI; without it a player's matches in a knockout / close
          finish are the ones they batted, bowled or were Player of the Match
          in (the workbook counts the whole XI).
  people  Player, player_id: used to count distinct players (by Cricsheet id).

Rates are computed and rounded exactly as the workbook's generator did:
strike rate = runs / balls * 100, economy = runs / (balls / 6), then Python's
round() (half-even on the binary value: 166.25 -> 166.2, 7.475 -> 7.47).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ["build_mvp", "CATEGORIES"]

CATEGORIES = ["3+ wickets", "Economy spells", "Hundreds", "Fifties", "Quick-fire 30+"]
SINGULAR = {"3+ wickets": "3+ wickets", "Economy spells": "Economy spell", "Hundreds": "Hundred",
            "Fifties": "Fifty", "Quick-fire 30+": "Quick-fire 30+"}
T20_BALLS = 120
DEATH_OVERS = (17, 20)


# --------------------------------------------------------------------------- helpers
def _r(x, d: int) -> float:
    """Python's round() (half-even on the binary value, as the workbook did), NaN-safe."""
    if x is None:
        return np.nan
    try:
        x = float(x)
    except (TypeError, ValueError):
        return np.nan
    if not math.isfinite(x):
        return np.nan
    return float(round(x, d))


def _rs(s: pd.Series, d: int) -> pd.Series:
    return pd.Series([_r(v, d) for v in s], index=s.index, dtype="float64")


def _fmt(x, d: int) -> str:
    return f"{_r(x, d):.{d}f}"


def _overs_txt(balls: int) -> str:
    balls = int(balls)
    return f"{balls // 6}" if balls % 6 == 0 else f"{balls // 6}.{balls % 6}"


def _overs_num(balls) -> float:
    if balls is None or pd.isna(balls):
        return np.nan
    return float(_overs_txt(balls))


def _balls_from_overs(o) -> int:
    """19.3 (overs notation) -> 117 balls."""
    if o is None or pd.isna(o):
        return 0
    whole = int(math.floor(float(o) + 1e-9))
    return whole * 6 + int(round((float(o) - whole) * 10))


def _sr(runs, balls):
    """Strike rate as the workbook computed it: runs / balls * 100."""
    return _div(runs, balls) * 100


def _econ(runs, balls):
    """Economy as the workbook computed it: runs / (balls / 6)."""
    return _div(runs, pd.to_numeric(balls, errors="coerce").astype(float) / 6)


def _div(a, b):
    a = pd.to_numeric(a, errors="coerce").astype(float)
    b = pd.to_numeric(b, errors="coerce").astype(float)
    return (a / b.where(b != 0)).astype(float)


def _span(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}–{hi}"


def _bat_txt(runs, balls, out, with_balls: bool = True) -> str:
    s = f"{int(runs)}{'' if int(out) else '*'}"
    return f"{s} ({int(balls)})" if with_balls else s


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# --------------------------------------------------------------------------- matches
def _match_frame(m: pd.DataFrame, bat_inns: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per match with everything the MVP tables need about it."""
    x = m.copy()
    x["Date"] = pd.to_datetime(x["Date"])
    x["Place"] = x["City"].where(x["City"].notna() & (x["City"].astype(str).str.strip() != ""), x["Venue"]) \
        if "City" in x.columns else x["Venue"]
    res = x["Result"].fillna("").astype(str).str.lower()
    x["NR"] = res.str.startswith("no result") | x["Winner"].isna() & ~res.str.startswith("tie")
    x["Tie"] = res.str.startswith("tie")
    marg = x["Margin"].fillna("").astype(str)
    x["By runs"] = pd.to_numeric(marg.str.extract(r"^(\d+)\s+runs?\b")[0], errors="coerce")
    x["By wkts"] = pd.to_numeric(marg.str.extract(r"^(\d+)\s+wickets?\b")[0], errors="coerce")
    x["DLS"] = x["Method"].notna() if "Method" in x.columns else False

    b1 = x["1st Inns Overs"].map(_balls_from_overs)
    b2 = x["2nd Inns Overs"].map(_balls_from_overs)
    w1 = x["1st Inns Wkts"].fillna(0).astype(int)
    w2 = x["2nd Inns Wkts"].fillna(0).astype(int)
    if bat_inns is not None and "How Out" in bat_inns.columns:
        # wickets in a score count every batter out or retired (Cricsheet's player_dismissed), as the workbook
        how = bat_inns["How Out"].astype(str).str.lower()
        gone = bat_inns[bat_inns["How Out"].notna() & ~how.isin(["not out", "nan", ""])]
        n = gone.groupby(["Match ID", "Innings"]).size()
        w1 = pd.Series([int(n.get((i, 1), w)) for i, w in zip(x["Match ID"], w1)], index=x.index)
        w2 = pd.Series([int(n.get((i, 2), w)) for i, w in zip(x["Match ID"], w2)], index=x.index)
    x["B1"], x["B2"], x["W1"], x["W2"] = b1, b2, w1, w2
    # Balls the chasing side had: the first innings' allotment (a full T20 unless
    # the match was shortened before it ended). With DLS the revised target overs
    # are not in Cricsheet's CSV data, so the over the chase ended in is used.
    allot1 = np.where((w1 >= 10) | (b1 >= T20_BALLS), T20_BALLS, np.ceil(b1 / 6) * 6)
    allot2 = np.where(x["DLS"], np.ceil(b2 / 6) * 6, allot1)
    x["Balls left"] = np.where(x["By wkts"].notna(), allot2 - b2, np.nan)
    x["Close"] = ~x["NR"] & (x["Tie"] | (x["By runs"] <= 10) | (x["By wkts"] <= 3) |
                             (x["Balls left"] <= 6)).fillna(False)

    def score(runs, wkts, balls, show):
        if pd.isna(runs):
            return None
        s = f"{int(runs)}" if wkts >= 10 else f"{int(runs)}/{int(wkts)}"
        return f"{s} ({_overs_txt(balls)} ov)" if show else s

    chase_won = x["Winner"].notna() & (x["Winner"] == x["Chasing"]) & ~x["Tie"] & x["By wkts"].notna()
    x["Score 1"] = [score(r, w, bb, w >= 10 or bb < T20_BALLS)
                    for r, w, bb in zip(x["1st Inns Runs"], w1, b1)]
    x["Score 2"] = [score(r, w, bb, w >= 10 or (cw and bb < T20_BALLS))
                    for r, w, bb, cw in zip(x["2nd Inns Runs"], w2, b2, chase_won)]
    x["Fixture"] = x["Bat First"].astype(str) + " v " + x["Chasing"].astype(str)

    def margin_txt(r):
        if r["Tie"]:
            return "Tie (super over)"
        if pd.notna(r["By runs"]):
            return _plural(int(r["By runs"]), "run")
        if pd.notna(r["By wkts"]):
            return _plural(int(r["By wkts"]), "wicket")
        return None

    x["Margin text"] = x.apply(margin_txt, axis=1)

    def ko_result(r):
        if r["NR"]:
            return "No result"
        if r["Tie"]:
            return f"Tied — {r['Winner']} won super over" if pd.notna(r["Winner"]) else "Tied"
        s = f"{r['Winner']} won by {r['Margin text']}" + (" (DLS)" if r["DLS"] else "")
        return s + (" — Champions" if r["Stage"] == "Final" else "")

    x["KO result"] = x.apply(ko_result, axis=1)
    x["Banner result"] = x["KO result"].str.replace(" — Champions", "", regex=False)
    return x.sort_values(["Date", "Match ID"], kind="stable").reset_index(drop=True)


def _team_results(tm: pd.DataFrame) -> pd.DataFrame:
    """Match ID, Team, Opposition, Team result ('Won', 'Lost', 'Tied — won super over', ...)."""
    t = tm[["Match ID", "Team", "Opposition", "Result"]].copy()
    tie = tm["Tie (SO)"].fillna(0).astype(int) == 1 if "Tie (SO)" in tm.columns else False
    res = t["Result"].astype(str)
    t["Team result"] = np.where(tie & res.eq("Won"), "Tied — won super over",
                                np.where(tie & res.eq("Lost"), "Tied — lost super over", res))
    t.loc[res.str.lower().str.startswith("no result"), "Team result"] = "No result"
    return t.drop(columns="Result")


# --------------------------------------------------------------------------- innings
def _batting(bat_inns: pd.DataFrame, ball: pd.DataFrame) -> pd.DataFrame:
    """bat_inns with 'Batted': faced a delivery (wides included) or was dismissed.
    A batter who walked out but never faced and wasn't out is not an innings."""
    b = bat_inns.copy()
    faced = (ball.assign(_six=ball["Bat Runs"].eq(6).astype(int))
                 .groupby(["Match ID", "Innings", "Batter"], as_index=False)["_six"].sum().assign(_f=True))
    b = b.merge(faced, on=["Match ID", "Innings", "Batter"], how="left")
    b["Batted"] = b["_f"].fillna(False).astype(bool) | (b["Out"].fillna(0).astype(int) == 1)
    # sixes: every 6 off the bat (the workbook's count; the core's Six flag leaves out a few)
    b["Sixes"] = b["_six"].fillna(b["Sixes"]).astype(int)
    return b.drop(columns=["_f", "_six"])


def _impacts(bat: pd.DataFrame, bowl: pd.DataFrame) -> pd.DataFrame:
    """Every impact performance: Match ID, Innings, Player, Team, Opposition, Category,
    Figures, Detail and the sort keys."""
    bt = bat[bat["Batted"]].copy()
    r, bl = bt["Runs"].astype(int), bt["Balls"].astype(int)
    cat = np.select([r >= 100, r >= 50, (r >= 30) & (r * 100 >= 150 * bl) & (bl > 0)],
                    ["Hundreds", "Fifties", "Quick-fire 30+"], default="")
    bt["Category"] = cat
    bt = bt[bt["Category"] != ""].copy()
    bt["Player"] = bt["Batter"]
    bt["Figures"] = [_bat_txt(a, b_, o) for a, b_, o in zip(bt["Runs"], bt["Balls"], bt["Out"])]
    bt["SRx"] = _sr(bt["Runs"], bt["Balls"])
    bt["Detail"] = [f"{int(f)} fours · {int(s)} sixes · SR {_fmt(v, 1)}"
                    for f, s, v in zip(bt["Fours"], bt["Sixes"], bt["SRx"])]

    bw = bowl.copy()
    w, rr, bb = bw["Wickets"].astype(int), bw["Runs"].astype(int), bw["Balls"].astype(int)
    cat = np.select([w >= 3, (bb >= 18) & (rr <= bb)], ["3+ wickets", "Economy spells"], default="")
    bw["Category"] = cat
    bw = bw[bw["Category"] != ""].copy()
    bw["Player"] = bw["Bowler"]
    bw["Figures"] = bw["Wickets"].astype(int).astype(str) + "/" + bw["Runs"].astype(int).astype(str)
    bw["Econx"] = _econ(bw["Runs"], bw["Balls"])
    bw["Detail"] = [f"{_overs_txt(b_)} overs · economy {_fmt(e, 2)}" for b_, e in zip(bw["Balls"], bw["Econx"])]

    # TeamInn: the innings the player's team batted in (ties are listed batting-first team first)
    bt["TeamInn"] = bt["Innings"]
    bw["TeamInn"] = 3 - bw["Innings"]
    keep = ["Match ID", "Innings", "TeamInn", "Player", "Team", "Opposition", "Category", "Figures", "Detail",
            "Runs", "Balls", "Wickets"]
    bt["Wickets"] = np.nan
    out = pd.concat([bw.assign(SRx=np.nan)[keep + ["Econx", "SRx"]],
                     bt.assign(Econx=np.nan)[keep + ["Econx", "SRx"]]], ignore_index=True)
    return out


def _rank(h: pd.DataFrame) -> pd.DataFrame:
    """Rank within each category, best first: wickets then fewest runs; economy then most balls and
    wickets; runs then fewest balls; strike rate then most runs."""
    parts = []
    for c in CATEGORIES:
        g = h[h["Category"] == c].copy()
        if c == "3+ wickets":
            keys, asc = ["Wickets", "Runs", "Balls"], [False, True, False]
        elif c == "Economy spells":
            keys, asc = ["Econx", "Balls", "Wickets"], [True, False, False]
        elif c == "Quick-fire 30+":
            keys, asc = ["SRx", "Runs"], [False, False]
        else:
            keys, asc = ["Runs", "Balls"], [False, True]
        # ties: the earlier match, then the team that batted first, then by name (as the workbook)
        g = g.sort_values(keys + ["Date", "Match ID", "TeamInn", "Player"], ascending=asc + [True, True, True, True],
                          kind="stable")
        g["Rank"] = np.arange(1, len(g) + 1)
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else h.assign(Rank=pd.Series(dtype=int))


# --------------------------------------------------------------------------- appearances
def _appearances(tables: dict, bat: pd.DataFrame, bowl: pd.DataFrame, mf: pd.DataFrame) -> pd.DataFrame:
    """Match ID, Team, Player, Order for every player in every match. From the XIs when given
    (tables['match_players'], in team-sheet order: Team 1's XI then Team 2's); otherwise the players
    who batted (batting order), bowled or were Player of the Match. Order = position in the match."""
    xi = tables.get("match_players")
    if xi is not None and len(xi):
        a = xi[["Match ID", "Team", "Player"]].copy()
        a["_o"] = np.arange(len(a))
        # team names as the core tables spell them: a team sheet whose team name is not one of the match's
        # teams there (a renamed franchise) takes the team its players batted / bowled for
        teams = mf.set_index("Match ID")[["Team 1", "Team 2"]]
        known = a["Match ID"].map(teams["Team 1"]).eq(a["Team"]) | a["Match ID"].map(teams["Team 2"]).eq(a["Team"])
        if not known.all():
            played = pd.concat([bat[["Match ID", "Batter", "Team"]].rename(columns={"Batter": "Player"}),
                                bowl[["Match ID", "Bowler", "Team"]].rename(columns={"Bowler": "Player"})])
            vote = (a[~known].merge(played.rename(columns={"Team": "Core"}), on=["Match ID", "Player"])
                     .groupby(["Match ID", "Team"])["Core"].agg(lambda t: t.value_counts().index[0]))
            fix = pd.Series(list(zip(a.loc[~known, "Match ID"], a.loc[~known, "Team"])), index=a.index[~known]).map(vote)
            a.loc[~known, "Team"] = fix.fillna(a.loc[~known, "Team"])
    else:
        potm = mf[["Match ID", "POTM Team", "Player of Match"]].dropna() if "POTM Team" in mf.columns \
            else pd.DataFrame(columns=["Match ID", "POTM Team", "Player of Match"])
        a = pd.concat([bat[["Match ID", "Team", "Batter", "Position"]].rename(columns={"Batter": "Player"}),
                       bowl[["Match ID", "Team", "Bowler"]].rename(columns={"Bowler": "Player"})
                           .assign(Position=lambda d: 20 + d.groupby(["Match ID", "Team"]).cumcount()),
                       potm.rename(columns={"POTM Team": "Team", "Player of Match": "Player"}).assign(Position=99)],
                      ignore_index=True)
        t1 = a["Match ID"].map(mf.set_index("Match ID")["Team 1"])
        a["_t"] = (a["Team"] != t1).astype(int)
        a = a.sort_values(["Match ID", "_t", "Position"], kind="stable")
        a["_o"] = np.arange(len(a))
        a = a.drop(columns=["_t", "Position"])
    a = a.drop_duplicates(["Match ID", "Player"])
    a["Order"] = a.groupby("Match ID").cumcount()
    a = a.drop(columns="_o")
    return a.merge(mf[["Match ID", "Date", "Season"]], on="Match ID", how="inner")


def _first_seen(app: pd.DataFrame) -> pd.Series:
    """Player -> rank of his first appearance in `app` (date, match, place in the team sheets)."""
    a = app.sort_values(["Date", "Match ID", "Order"], kind="stable").drop_duplicates("Player")
    return pd.Series(np.arange(len(a)), index=a["Player"].values)


def _teams_latest_first(app: pd.DataFrame) -> pd.Series:
    """Player -> 'Team A, Team B' ordered by each team's latest appearance."""
    if app.empty:
        return pd.Series(dtype=object)
    last = app.groupby(["Player", "Team"], as_index=False)["Date"].max()
    last = last.sort_values(["Player", "Date"], ascending=[True, False], kind="stable")
    return last.groupby("Player", sort=False)["Team"].agg(", ".join)


def _season_teams(ps: pd.DataFrame, app: pd.DataFrame) -> pd.DataFrame:
    """Player, Team (full name), Season from player_seasons, whose Team is an
    abbreviation: mapped to full names through the seasons players batted/bowled in."""
    s = ps[["Player", "Season", "Team"]].rename(columns={"Team": "Abbr"})
    j = s.merge(app[["Player", "Season", "Team"]].drop_duplicates(), on=["Player", "Season"], how="inner")
    amap = (j.groupby(["Abbr", "Team"]).size().reset_index(name="n")
              .sort_values(["Abbr", "n"], ascending=[True, False]).drop_duplicates("Abbr")
              .set_index("Abbr")["Team"])
    s = s.assign(Team=s["Abbr"].map(amap).fillna(s["Abbr"]))
    return s[["Player", "Team", "Season"]]


# --------------------------------------------------------------------------- aggregates
def _bat_agg(bat: pd.DataFrame, key: str = "Batter") -> pd.DataFrame:
    bt = bat[bat["Batted"]]
    g = bt.groupby(key).agg(Inns=("Runs", "size"), Runs=("Runs", "sum"), Balls=("Balls", "sum"),
                            Outs=("Out", "sum"),
                            F50=("Runs", lambda s: int(((s >= 50) & (s < 100)).sum())),
                            H100=("Runs", lambda s: int((s >= 100).sum())))
    hs = bt.sort_values(["Runs", "Out"], ascending=[False, True], kind="stable").drop_duplicates(key)
    g["Highest"] = pd.Series([_bat_txt(r, 0, o, with_balls=False) for r, o in zip(hs["Runs"], hs["Out"])],
                             index=hs[key].values)
    return g


def _bowl_agg(bowl: pd.DataFrame, key: str = "Bowler") -> pd.DataFrame:
    g = bowl.groupby(key).agg(BInns=("Runs", "size"), BBalls=("Balls", "sum"), BRuns=("Runs", "sum"),
                              Wkts=("Wickets", "sum"))
    best = bowl.sort_values(["Wickets", "Runs"], ascending=[False, True], kind="stable").drop_duplicates(key)
    g["Best"] = pd.Series((best["Wickets"].astype(int).astype(str) + "/" + best["Runs"].astype(int).astype(str)).values,
                          index=best[key].values)
    return g


def _order(df: pd.DataFrame, primary: str, runs, wickets, first_seen: pd.Series) -> pd.Index:
    """The workbook's player order (as df index labels): `primary` (most first), then runs + 25 x wickets
    (most first), then whoever first played in these matches earliest (date, match, team-sheet order)."""
    key = pd.DataFrame({"p": df[primary].to_numpy(),
                        "c": np.nan_to_num(np.asarray(runs, dtype=float)) +
                        25 * np.nan_to_num(np.asarray(wickets, dtype=float)),
                        "f": df["Player"].map(first_seen).to_numpy(dtype=float),
                        "n": df["Player"].to_numpy()}, index=df.index)
    return key.sort_values(["p", "c", "f", "n"], ascending=[False, False, True, True], kind="stable",
                           na_position="last").index


def _role(matches, bat_inns, runs, bowl_inns) -> str:
    """Batter unless the player bowled in 3+ innings and in at least half their
    matches; then an all-rounder if they also batted in half their matches at 8+
    runs an innings, else a bowler."""
    if bowl_inns >= 3 and matches and bowl_inns / matches >= 0.5:
        rpi = runs / bat_inns if bat_inns else 0.0
        return "All-rounder" if bat_inns / matches >= 0.5 and rpi >= 8 else "Bowler"
    return "Batter"


# --------------------------------------------------------------------------- tables
def _definitions(mf: pd.DataFrame) -> pd.DataFrame:
    stages = mf.loc[mf["Match Type"] == "Playoff"].sort_values("Date", kind="stable")["Stage"].dropna().unique()
    words = []
    for s in stages:                      # in the order they are played: qualifier, eliminator, final
        w = str(s).rstrip("0123456789 ").strip().lower()
        if w and w not in words:
            words.append(w)
    if "final" in words:
        words = [w for w in words if w != "final"] + ["final"]
    ko = "any play-off" + (": " + (", ".join(words[:-1]) + " or " + words[-1] if len(words) > 1 else words[0])
                           if words else "")
    return pd.DataFrame([
        ("Bowling · wickets in an innings", "3 or more wickets"),
        ("Bowling · economy spell", "economy 6.00 or better from at least 3 overs "
                                    "(spells with 3+ wickets are counted under wickets)"),
        ("Batting · fifty / hundred", "50 or more runs"),
        ("Batting · quick-fire runs", "30–49 runs at a strike rate of 150 or more"),
        ("Knockout match", ko),
        ("Close finish", "won by 10 runs or fewer, by 3 wickets or fewer, with 6 balls or fewer left, "
                         "or tied (super over)"),
    ], columns=["What", "Counts when"])


def _key_performers(bt: pd.DataFrame, bw: pd.DataFrame, sheet: dict) -> str | None:
    """One match's top two run-scorers ('65* (43)': most runs, fewest balls, then in innings and batting
    order) and top two wicket-takers ('3/19': most wickets, fewest runs, fewest balls, then in team-sheet
    order), as the workbook lists them. bt / bw: the match's batting and bowling innings."""
    bt = bt[bt["Batted"]]
    bt = bt.sort_values(["Runs", "Balls", "Innings", "Position"], ascending=[False, True, True, True], kind="stable")
    bw = bw[bw["Wickets"] > 0].assign(_s=lambda d: d["Bowler"].map(sheet).fillna(1000))
    bw = bw.sort_values(["Wickets", "Runs", "Balls", "_s", "Bowler"], ascending=[False, True, True, True, True],
                        kind="stable")
    parts = [f"{p} {_bat_txt(r, b_, o)}" for p, r, b_, o in
             bt.head(2)[["Batter", "Runs", "Balls", "Out"]].itertuples(index=False)]
    parts += [f"{p} {int(w)}/{int(r)}" for p, w, r in bw.head(2)[["Bowler", "Wickets", "Runs"]].itertuples(index=False)]
    return " · ".join(parts) if parts else None


def match_players_from_infos(infos: list[dict], people: pd.DataFrame | None) -> pd.DataFrame:
    """The playing XIs (Match ID, Team, Player) from Cricsheet info dicts (engine.cricsheet.read_zip), with
    each player's name resolved through his Cricsheet id to the name the core tables use (`people`)."""
    id2name = {}
    if people is not None and len(people) and "player_id" in people.columns:
        id2name = dict(zip(people["player_id"], people["Player"]))
    rows = []
    for d in infos or []:
        reg = d.get("registry", {}) or {}
        for team, names in (d.get("players", {}) or {}).items():
            for nm in names:
                rows.append((int(d["match_id"]), team, id2name.get(reg.get(nm), nm)))
    return pd.DataFrame(rows, columns=["Match ID", "Team", "Player"])


def build_mvp(tables: dict[str, pd.DataFrame], people: pd.DataFrame,
              infos: list[dict] | None = None) -> dict[str, pd.DataFrame]:
    """The MVP · Impact Performances tables, keyed 'mvp/<name>'.

    `infos` (optional, Cricsheet info dicts from engine.cricsheet.read_zip) gives the playing XIs, so a
    player's knockout / close-finish matches include games he neither batted nor bowled in (as the
    workbook counts them). tables['match_players'] (Match ID, Team, Player) does the same."""
    if infos is not None and "match_players" not in tables:
        tables = {**tables, "match_players": match_players_from_infos(infos, people)}
    mf = _match_frame(tables["matches"], tables["bat_inns"])
    tr = _team_results(tables["team_matches"])
    ball = tables["ball"]
    ps = tables["player_seasons"]
    bat = _batting(tables["bat_inns"], ball)
    bowl = tables["bowl_inns"].copy()

    minfo = mf[["Match ID", "Date", "Season", "Stage", "Match Type", "Place", "Close"]]
    bat = bat.drop(columns=[c for c in ("Date", "Season", "Stage", "Match Type") if c in bat.columns]) \
             .merge(minfo, on="Match ID", how="inner")
    bowl = bowl.drop(columns=[c for c in ("Date", "Season", "Stage", "Match Type") if c in bowl.columns]) \
               .merge(minfo, on="Match ID", how="inner")
    app = _appearances(tables, bat, bowl, mf)
    is_ko = mf.set_index("Match ID")["Match Type"].eq("Playoff")
    is_close = mf.set_index("Match ID")["Close"]
    app["KO"] = app["Match ID"].map(is_ko).fillna(False).astype(bool)
    app["CloseM"] = app["Match ID"].map(is_close).fillna(False).astype(bool)

    # ---- every impact performance
    imp = _impacts(bat, bowl).merge(minfo, on="Match ID", how="left") \
                             .merge(tr[["Match ID", "Team", "Team result"]], on=["Match ID", "Team"], how="left")
    imp = _rank(imp)
    highlights = pd.DataFrame({
        "Category": imp["Category"], "Rank": imp["Rank"].astype("int64"), "Player": imp["Player"],
        "Team": imp["Team"], "Figures": imp["Figures"], "Detail": imp["Detail"], "Opposition": imp["Opposition"],
        "Venue": imp["Place"], "Date": pd.to_datetime(imp["Date"]).astype("datetime64[us]"),
        "Season": imp["Season"].astype("int64"), "Match stage": imp["Stage"], "Team result": imp["Team result"],
        "Close finish": imp["Close"].fillna(False).astype(bool)})

    # ---- scoreboard
    players = ps.groupby("Player").agg(Matches=("Mat", "sum"), S0=("Season", "min"), S1=("Season", "max"))
    st = _season_teams(ps, app)
    team_src = pd.concat([app[["Player", "Team", "Date", "Season"]],
                          st.assign(Date=pd.NaT)], ignore_index=True)
    team_last = team_src.groupby(["Player", "Team"], as_index=False).agg(S=("Season", "max"), D=("Date", "max"))
    team_last = team_last.sort_values(["Player", "S", "D"], ascending=[True, False, False], kind="stable",
                                      na_position="last")
    teams = team_last.groupby("Player", sort=False)["Team"].agg(", ".join)
    ba, bo = _bat_agg(bat), _bowl_agg(bowl)
    cnt = imp.groupby(["Player", "Category"]).size().unstack(fill_value=0).reindex(columns=CATEGORIES, fill_value=0)
    potm = mf["Player of Match"].dropna().value_counts()
    ko_n = app[app["KO"]].groupby("Player").size()
    cl_n = app[app["CloseM"]].groupby("Player").size()

    sb = players.join(ba, how="left").join(bo, how="left")
    sb["Player"] = sb.index
    has_bat = sb["Inns"].fillna(0) > 0
    has_bowl = sb["BInns"].fillna(0) > 0
    board = pd.DataFrame({
        "Player": sb.index,
        "Team(s)": teams.reindex(sb.index).values,
        "Role": [_role(mt, bi_ if bi_ == bi_ else 0, ru if ru == ru else 0, bw if bw == bw else 0)
                 for mt, bi_, ru, bw in zip(sb["Matches"], sb["Inns"], sb["Runs"], sb["BInns"])],
        "Seasons": [_span(a, b_) for a, b_ in zip(sb["S0"], sb["S1"])],
        "Matches": sb["Matches"].astype("int64").values,
        "Batting inns": sb["Inns"].where(has_bat).astype(float).values,
        "Runs": sb["Runs"].where(has_bat).astype(float).values,
        "Highest": sb["Highest"].where(has_bat).values,
        "Average": _rs(_div(sb["Runs"], sb["Outs"]), 2).values,
        "Strike rate": _rs(_sr(sb["Runs"], sb["Balls"]), 1).where(has_bat.values).values,
        "Fifties": sb["F50"].where(has_bat).astype(float).values,
        "Hundreds": sb["H100"].where(has_bat).astype(float).values,
        "Quick-fire 30+": cnt["Quick-fire 30+"].reindex(sb.index).fillna(0).where(has_bat).astype(float).values,
        "Bowling inns": sb["BInns"].where(has_bowl).astype(float).values,
        "Wickets": sb["Wkts"].where(has_bowl).astype(float).values,
        "Best": sb["Best"].where(has_bowl).values,
        "Economy": _rs(_econ(sb["BRuns"], sb["BBalls"]), 2).values,
        "3+ wkt hauls": cnt["3+ wickets"].reindex(sb.index).fillna(0).where(has_bowl).astype(float).values,
        "Economy spells": cnt["Economy spells"].reindex(sb.index).fillna(0).where(has_bowl).astype(float).values,
        "Impact innings": cnt.sum(axis=1).reindex(sb.index).fillna(0).astype("int64").values,
        "Player of the Match": potm.reindex(sb.index).fillna(0).astype("int64").values,
        "Knockout matches": ko_n.reindex(sb.index).fillna(0).astype("int64").values,
        "Close finishes": cl_n.reindex(sb.index).fillna(0).astype("int64").values,
    })
    board = board.loc[_order(board, "Impact innings", board["Runs"], board["Wickets"], _first_seen(app))] \
                 .reset_index(drop=True)

    # ---- glance
    n_players = len(board)
    if people is not None and len(people) and "player_id" in people.columns:
        ids = people.loc[people["Player"].isin(board["Player"]), "player_id"].dropna()
        if ids.nunique() >= n_players:
            n_players = int(ids.nunique())
    ncat = highlights["Category"].value_counts()
    glance = pd.DataFrame([
        ("Matches in the data", len(mf)), ("Impact performances", len(highlights)),
        ("Players", n_players), ("Hundreds", int(ncat.get("Hundreds", 0))),
        ("Knockout matches", int(is_ko.sum())), ("Fifties", int(ncat.get("Fifties", 0))),
        ("Close finishes", int(mf["Close"].sum())), ("3+ wicket hauls", int(ncat.get("3+ wickets", 0))),
    ], columns=["Label", "Value"]).astype({"Value": "int64"})

    out = {
        "mvp/definitions": _definitions(mf),
        "mvp/glance": glance,
        "mvp/scoreboard": board,
        "mvp/highlights": highlights,
        "mvp/highlights_note": pd.DataFrame({"note": [
            "Spells with 3+ wickets that were also economical are listed once, under 3+ wickets. "
            "Fifties are 50–99; hundreds are listed separately."]}),
    }
    out.update(_knockouts(mf, tr, bat, bowl, imp, app))
    out.update(_close(mf, tr, bat, bowl, ball, app))
    return {k: _text_cols(v, _TEXT.get(k.split("/", 1)[1], ())) for k, v in out.items()}


def _text_cols(df: pd.DataFrame, text) -> pd.DataFrame:
    """Text columns as pandas' str dtype, also when a table is empty or a column has no values."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object or (c in text and str(df[c].dtype) != "str"):
            df[c] = df[c].astype(object).where(df[c].notna(), None).astype("str")
    return df


_TEXT = {   # text columns of tables that can come out empty (no play-offs / no close finishes)
    "ko_matches": ("Stage", "Match", "Score · 1st", "Score · 2nd", "Result", "Venue", "Player of the Match",
                   "Stage only"),
    "ko_players": ("Player", "Team(s)", "Runs (balls)", "Highest", "Best", "In the finals"),
    "ko_cards": ("Match", "Player", "Team", "Opposition", "Runs", "4s / 6s", "Team result", "Impact"),
    "close_teams": ("Team",),
    "close_players": ("Player", "Team(s)"),
    "close_players_wb_tints": ("Strike rate", "Economy"),
    "close_matches": ("Match", "Stage", "Score · 1st", "Score · 2nd", "Result", "Margin", "Key performers"),
}


# --------------------------------------------------------------------------- knockouts
def _knockouts(mf, tr, bat, bowl, imp, app) -> dict[str, pd.DataFrame]:
    ko = mf[mf["Match Type"] == "Playoff"].copy()
    matches = pd.DataFrame({
        "Stage": ko["Season"].astype(str) + " · " + ko["Stage"].astype(str),
        "Match": ko["Fixture"], "Date": ko["Date"].astype("datetime64[us]"),
        "Score · 1st": ko["Score 1"], "Score · 2nd": ko["Score 2"], "Result": ko["KO result"],
        "Venue": ko["Place"], "Player of the Match": ko["Player of Match"],
        "Season": ko["Season"].astype("int64"), "Stage only": ko["Stage"]}).reset_index(drop=True)

    ids = set(ko["Match ID"])
    kb = bat[bat["Match ID"].isin(ids)]
    kw = bowl[bowl["Match ID"].isin(ids)]
    ki = imp[imp["Match ID"].isin(ids)]

    # ---- match by match
    tags = (ki.assign(_o=ki["Category"].map({c: i for i, c in enumerate(CATEGORIES)}))
              .sort_values("_o").groupby(["Match ID", "Player"])["Category"]
              .agg(lambda s: ", ".join(SINGULAR[c] for c in s)))
    rows = []
    xi_pos = {mid: dict(zip(g["Player"], g["Order"])) for mid, g in app[app["Match ID"].isin(ids)].groupby("Match ID")}
    for _, mrow in ko.iterrows():
        mid = mrow["Match ID"]
        banner = (f"{mrow['Date']:%d %b %Y} · {mrow['Season']} {mrow['Stage']} · {mrow['Fixture']} · "
                  f"{mrow['Banner result']}")
        for inn, team in ((1, mrow["Bat First"]), (2, mrow["Chasing"])):
            bt = kb[(kb["Match ID"] == mid) & (kb["Team"] == team)].sort_values("Position")
            bw = kw[(kw["Match ID"] == mid) & (kw["Team"] == team)]
            # batters in batting order, then those who only bowled: most balls first, then team-sheet order
            order = list(bt.loc[bt["Batted"], "Batter"])
            dnb = bw[~bw["Bowler"].isin(order)].assign(_bo=lambda d: np.arange(len(d)))
            dnb = dnb.assign(_xi=dnb["Bowler"].map(xi_pos.get(mid, {})).fillna(1000 + dnb["_bo"]))
            order += list(dnb.sort_values(["Balls", "_xi"], ascending=[False, True], kind="stable")["Bowler"])
            bt_i = bt.set_index("Batter")
            bw_i = bw.drop_duplicates("Bowler").set_index("Bowler")
            res = tr[(tr["Match ID"] == mid) & (tr["Team"] == team)]
            res_txt = res["Team result"].iloc[0] if len(res) else None
            opp = mrow["Chasing"] if inn == 1 else mrow["Bat First"]
            for p in order:
                batted = p in bt_i.index and bool(bt_i.loc[p, "Batted"])
                bowled = p in bw_i.index
                rec = {"Match": banner, "Player": p, "Team": team, "Opposition": opp}
                if batted:
                    r = bt_i.loc[p]
                    rec.update({"Runs": _bat_txt(r["Runs"], 0, r["Out"], with_balls=False),
                                "Balls": float(r["Balls"]),
                                "SR": _r(r["Runs"] / r["Balls"] * 100, 1) if r["Balls"] else np.nan,
                                "4s / 6s": f"{int(r['Fours'])} / {int(r['Sixes'])}"})
                else:
                    rec.update({"Runs": "DNB", "Balls": np.nan, "SR": np.nan, "4s / 6s": None})
                if bowled:
                    w = bw_i.loc[p]
                    rec.update({"Overs": _overs_num(w["Balls"]), "Runs conc.": float(w["Runs"]),
                                "Wickets": float(w["Wickets"]), "Economy": _r(w["Runs"] / (w["Balls"] / 6), 2)})
                else:
                    rec.update({"Overs": np.nan, "Runs conc.": np.nan, "Wickets": np.nan, "Economy": np.nan})
                rec.update({"Team result": res_txt, "Impact": tags.get((mid, p)),
                            "Date": mrow["Date"], "Season": int(mrow["Season"])})
                rows.append(rec)
    cards = pd.DataFrame(rows, columns=["Match", "Player", "Team", "Opposition", "Runs", "Balls", "SR", "4s / 6s",
                                        "Overs", "Runs conc.", "Wickets", "Economy", "Team result", "Impact",
                                        "Date", "Season"])
    cards["Date"] = pd.to_datetime(cards["Date"]).astype("datetime64[us]")
    cards["Season"] = cards["Season"].astype("int64")
    for c in ("Balls", "SR", "Overs", "Runs conc.", "Wickets", "Economy"):
        cards[c] = cards[c].astype("float64")

    # ---- player summary
    kapp = app[app["KO"]]
    pl = kapp.groupby("Player").agg(Matches=("Match ID", "nunique"))
    played = set(kb.loc[kb["Batted"], "Batter"]) | set(kw["Bowler"])
    pl = pl[pl.index.isin(played)]
    teams = _teams_latest_first(kapp)
    ba, bo = _bat_agg(kb), _bowl_agg(kw)
    ba["F50"] = ba["F50"] + ba["H100"]          # "Fifties" here = 50+ scores
    nimp = ki.groupby("Player").size()
    finals = mf[(mf["Match Type"] == "Playoff") & (mf["Stage"] == "Final")].sort_values("Date")

    fb = kb[kb["Match ID"].isin(set(finals["Match ID"])) & kb["Batted"]]
    fw = kw[kw["Match ID"].isin(set(finals["Match ID"]))]
    f_bat = {(i, p): _bat_txt(r, b_, o) for i, p, r, b_, o in
             zip(fb["Match ID"], fb["Batter"], fb["Runs"], fb["Balls"], fb["Out"])}
    f_bowl = {(i, p): f"{int(w)}/{int(r)}" for i, p, w, r in zip(fw["Match ID"], fw["Bowler"], fw["Wickets"], fw["Runs"])}
    final_list = list(zip(finals["Match ID"], finals["Season"]))

    def in_finals(p):
        """'2017: 2/13 · 2018: 28* (14), 2/28': every final the player batted or bowled in."""
        bits = []
        for i, season in final_list:
            parts = [t for t in (f_bat.get((i, p)), f_bowl.get((i, p))) if t]
            if parts:
                bits.append(f"{season}: " + ", ".join(parts))
        return " · ".join(bits) if bits else None

    j = pl.join(ba, how="left").join(bo, how="left")
    hb, hw = j["Inns"].fillna(0) > 0, j["BInns"].fillna(0) > 0
    kp = pd.DataFrame({
        "Player": j.index,
        "Team(s)": teams.reindex(j.index).values,
        "Matches": j["Matches"].astype("int64").values,
        "Runs (balls)": [f"{int(r)} ({int(b_)})" if h else None for r, b_, h in zip(j["Runs"], j["Balls"], hb)],
        "Strike rate": _rs(_sr(j["Runs"], j["Balls"]), 1).where(hb.values).values,
        "Highest": j["Highest"].where(hb).values,
        "Fifties": j["F50"].where(hb).astype(float).values,
        "Wickets": j["Wkts"].where(hw).astype(float).values,
        "Overs": [_overs_num(b_) if h else np.nan for b_, h in zip(j["BBalls"], hw)],
        "Runs conceded": j["BRuns"].where(hw).astype(float).values,
        "Economy": _rs(_econ(j["BRuns"], j["BBalls"]), 2).values,
        "Best": j["Best"].where(hw).values,
        "Impact innings": nimp.reindex(j.index).fillna(0).astype("int64").values,
        "In the finals": [in_finals(p) for p in j.index],
    })
    kp["Overs"] = kp["Overs"].astype("float64")
    kp = kp.loc[_order(kp, "Matches", j["Runs"].where(hb).to_numpy(), kp["Wickets"], _first_seen(kapp))] \
           .reset_index(drop=True)
    return {"mvp/ko_matches": matches, "mvp/ko_players": kp, "mvp/ko_cards": cards}


# --------------------------------------------------------------------------- close finishes
def _close(mf, tr, bat, bowl, ball, app) -> dict[str, pd.DataFrame]:
    cm = mf[mf["Close"]].copy()
    ids = set(cm["Match ID"])
    completed = int((~mf["NR"]).sum())

    defs = pd.DataFrame([("Won or lost by runs", "10 runs or fewer"),
                         ("Won or lost by wickets", "3 wickets or fewer"),
                         ("Chase finished with balls left", "6 balls or fewer"),
                         ("Ties and super overs", "Included")], columns=["What", "Close when"])
    note = pd.DataFrame({"note": [
        "A match is close if it meets any one of the four. No-result matches are excluded.",
        "Sorted by close finishes played. Green = better in close finishes than in all matches, red = worse "
        "(shown when the sample is at least 30 balls faced or 10 overs bowled in close finishes). "
        f"Death overs = overs {DEATH_OVERS[0]}–{DEATH_OVERS[1]}.",
        "Key performers = top two run-scorers and top two wicket-takers in the match."]})
    glance = pd.DataFrame([
        ("Matches in the data", str(len(mf))),
        ("Close finishes", str(len(cm))),
        ("Share of completed matches", f"{_r(100 * len(cm) / completed, 0):.0f}%" if completed else "—"),
        ("Ties / super overs", str(int(cm["Tie"].sum()))),
        ("Close knockout matches", str(int((cm["Match Type"] == "Playoff").sum()))),
    ], columns=["Label", "Value"])

    # ---- teams
    t = tr[~tr["Team result"].eq("No result")].copy()
    t["W"] = t["Team result"].isin(["Won", "Tied — won super over"]).astype(int)
    t["L"] = t["Team result"].isin(["Lost", "Tied — lost super over"]).astype(int)
    allm = t.groupby("Team").agg(n=("W", "size"), w=("W", "sum"))
    tc = t[t["Match ID"].isin(ids)].groupby("Team").agg(n=("W", "size"), w=("W", "sum"), l=("L", "sum"))
    teams = pd.DataFrame({"Team": tc.index, "Close finishes": tc["n"].astype("int64").values,
                          "Won": tc["w"].astype("int64").values, "Lost": tc["l"].astype("int64").values,
                          "Win %": (tc["w"] / tc["n"]).values,
                          "All matches · win %": (allm["w"] / allm["n"]).reindex(tc.index).values})
    teams = teams.sort_values(["Close finishes", "Won", "Team"], ascending=[False, False, True], kind="stable") \
                 .reset_index(drop=True)

    # ---- players
    capp = app[app["CloseM"]]
    pl = capp.groupby("Player").agg(n=("Match ID", "nunique"))
    cb, cw = bat[bat["Match ID"].isin(ids)], bowl[bowl["Match ID"].isin(ids)]
    ba, bo = _bat_agg(cb), _bowl_agg(cw)
    all_bat = bat[bat["Batted"]].groupby("Batter").agg(R=("Runs", "sum"), B=("Balls", "sum"))
    all_bow = bowl.groupby("Bowler").agg(R=("Runs", "sum"), B=("Balls", "sum"))
    cball = ball[ball["Match ID"].isin(ids)]
    death = cball[cball["Over"].between(*DEATH_OVERS)]
    dbat = death.groupby("Batter").agg(R=("Bat Runs", "sum"), B=("Ball Faced", "sum"))
    dbow = death.groupby("Bowler").agg(R=("Bowler Runs", "sum"), B=("Legal Ball", "sum"))
    cdot = cball.groupby("Bowler").agg(D=("Bowl Dot", "sum"), B=("Legal Ball", "sum"))
    teams_p = _teams_latest_first(capp)

    j = pl.join(ba, how="left").join(bo, how="left")
    idx = j.index
    hb, hw = j["Inns"].fillna(0) > 0, j["BInns"].fillna(0) > 0
    sr_c = _sr(j["Runs"], j["Balls"]).where(hb)
    sr_a = _sr(all_bat["R"], all_bat["B"]).reindex(idx)
    ec_c = _econ(j["BRuns"], j["BBalls"]).where(hw)
    ec_a = _econ(all_bow["R"], all_bow["B"]).reindex(idx)
    players = pd.DataFrame({
        "Player": idx,
        "Team(s)": teams_p.reindex(idx).values,
        "Close matches": j["n"].astype("int64").values,
        "Runs": j["Runs"].where(hb).astype(float).values,
        "Balls": j["Balls"].where(hb).astype(float).values,
        "Strike rate": _rs(sr_c, 1).values,
        "SR · all matches": _rs(sr_a, 1).values,
        "Average": _rs(_div(j["Runs"], j["Outs"]).where(hb), 2).values,
        "Wickets": j["Wkts"].where(hw).astype(float).values,
        "Overs": [_overs_num(b_) if h else np.nan for b_, h in zip(j["BBalls"], hw)],
        "Economy": _rs(ec_c, 2).values,
        "Econ. · all matches": _rs(ec_a, 2).values,
        "Death-over SR (bat)": _rs(_sr(dbat["R"], dbat["B"]).reindex(idx), 1).values,
        "Death-over econ.": _rs(_econ(dbow["R"], dbow["B"]).reindex(idx), 2).values,
        "Dot % (bowl)": _rs(_div(cdot["D"], cdot["B"]).reindex(idx), 3).where(hw.values).values,
    })
    players["Overs"] = players["Overs"].astype("float64")
    # the workbook's green / red cells, compared unrounded
    # (green = better than in all matches, otherwise red - an equal rate is red too, as in the workbook)
    sr_n, ec_n = j["Balls"].fillna(0) >= 30, j["BBalls"].fillna(0) >= 60
    good_sr = (sr_c > sr_a) & sr_n
    bad_sr = ~(sr_c > sr_a) & sr_n & sr_c.notna() & sr_a.notna()
    good_ec = (ec_c < ec_a) & ec_n
    bad_ec = ~(ec_c < ec_a) & ec_n & ec_c.notna() & ec_a.notna()
    tints = pd.DataFrame({"Strike rate": np.where(good_sr, "good", np.where(bad_sr, "bad", "")),
                          "Economy": np.where(good_ec, "good", np.where(bad_ec, "bad", ""))},
                         index=idx.rename(None))
    players = players.reset_index(drop=True)
    tints = tints.reset_index(drop=True)
    order = _order(players, "Close matches", players["Runs"], players["Wickets"], _first_seen(capp))
    players = players.loc[order].reset_index(drop=True)
    tints = tints.loc[order].reset_index(drop=True)

    # ---- the matches
    sheet = {mid: dict(zip(g["Player"], g["Order"])) for mid, g in capp.groupby("Match ID")}
    cb_by, cw_by = dict(tuple(cb.groupby("Match ID"))), dict(tuple(cw.groupby("Match ID")))
    empty_b, empty_w = cb.iloc[:0], cw.iloc[:0]
    lst = pd.DataFrame({
        "Date": cm["Date"].astype("datetime64[us]"), "Match": cm["Fixture"], "Stage": cm["Stage"],
        "Score · 1st": cm["Score 1"], "Score · 2nd": cm["Score 2"],
        "Result": [("No result" if nr else (f"Tied — {w} won super over" if pd.notna(w) else "Tied") if tie else
                    f"{w} won" + (" (DLS)" if dls else ""))
                   for nr, tie, w, dls in zip(cm["NR"], cm["Tie"], cm["Winner"], cm["DLS"])],
        "Margin": [txt if tie or pd.isna(bl) else f"{txt} ({_plural(int(bl), 'ball')} left)"
                   for txt, tie, bl in zip(cm["Margin text"], cm["Tie"], cm["Balls left"])],
        "Key performers": [_key_performers(cb_by.get(mid, empty_b), cw_by.get(mid, empty_w), sheet.get(mid, {}))
                           for mid in cm["Match ID"]],
        "Season": cm["Season"].astype("int32"),
    }).reset_index(drop=True)

    return {"mvp/close_definitions": defs, "mvp/close_note": note, "mvp/close_glance": glance,
            "mvp/close_teams": teams, "mvp/close_players": players, "mvp/close_players_wb_tints": tints,
            "mvp/close_matches": lst}
