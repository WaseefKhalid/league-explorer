"""
Core tables from Cricsheet deliveries + match info:
ball (without impact), matches, team_matches, bat_inns, bowl_inns, partnerships, pair_seasons.

Every column reproduces the PSL workbook's data sheets (see tests/check_engine_core.py).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from engine.places import city_country, same_country

PHASES = [("PP", 1, 6), ("MO1", 7, 10), ("MO2", 11, 16), ("Death", 17, 20)]
BOWLER_WICKETS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_OUT_TYPES = {"retired hurt", "retired not out"}
PLAYOFF_NAMES = {4: ["Qualifier", "Eliminator 1", "Eliminator 2", "Final"]}
TYPE_PACE = {"Right-arm pace": "Pace", "Left-arm pace": "Pace", "Off-spin": "Spin", "Leg-spin": "Spin",
             "Left-arm orthodox": "Spin", "Left-arm wrist-spin": "Spin"}


def phase_of(over: pd.Series) -> pd.Series:
    out = pd.Series("Death", index=over.index, dtype=object)
    for name, lo, hi in PHASES:
        out[(over >= lo) & (over <= hi)] = name
    return out


def season_of(label: str, date: pd.Timestamp) -> int:
    """'2016/17' → 2017; '2024' → 2024; falls back to the match year."""
    s = str(label or "").strip()
    m = re.match(r"^(\d{4})/(\d{2,4})$", s)
    if m:
        start, end = int(m.group(1)), m.group(2)
        end = int(end) if len(end) == 4 else (start // 100) * 100 + int(end)
        return end if end >= start else end + 100
    if re.match(r"^\d{4}$", s):
        return int(s)
    return int(pd.Timestamp(date).year)


def seasons_for(labels: pd.Series, dates: pd.Series) -> list[int]:
    """A season is a run of matches with no break longer than two months (or a new season label after a
    two-week break), named by the year its last match was played. So a December–January season (ILT20 4,
    Big Bash) stays whole under the year of its final, and play-offs held months later in the same year
    (PSL 2020, IPL 2021) stay with their season."""
    d = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    lab = pd.Series(labels).reset_index(drop=True).fillna("").astype(str)
    order = np.argsort(d.to_numpy(), kind="stable")
    ds, ls = d.iloc[order].reset_index(drop=True), lab.iloc[order].reset_index(drop=True)
    gap = ds.diff().dt.days.fillna(0)
    new = (gap > 60) | ((ls != ls.shift()) & (gap > 14))
    run = new.cumsum()
    end_year = ds.dt.year.groupby(run).transform("max")
    out = np.empty(len(d), dtype=int)
    out[order] = end_year.to_numpy()
    return out.tolist()


def overs_str(balls: float) -> float:
    """Legal balls → cricket overs notation as a number (17.2 = 17 overs 2 balls)."""
    if pd.isna(balls):
        return np.nan
    b = int(balls)
    return float(f"{b // 6}.{b % 6}")


def clean_venue(venue: str, city: str | None) -> str:
    v = str(venue).strip()
    if "," in v:
        head, tail = v.rsplit(",", 1)
        tail = tail.strip()
        if not city or tail.lower() == str(city).lower() or city_country(tail):
            v = head.strip()
    return v


# ── matches (part 1: everything from info + innings totals) ────────────────────────────────
def _match_frame(dl: pd.DataFrame, infos: list[dict], overrides: dict) -> pd.DataFrame:
    rows = []
    for d in infos:
        rows.append({
            "Match ID": d["match_id"], "date": d.get("date"), "season_label": d.get("season"),
            "venue": d.get("venue"), "city": d.get("city"), "teams": d.get("teams", []),
            "match_number": d.get("match_number"), "toss_winner": d.get("toss_winner"),
            "toss_decision": d.get("toss_decision"), "winner": d.get("winner"), "winner_runs": d.get("winner_runs"),
            "winner_wickets": d.get("winner_wickets"), "outcome": d.get("outcome"), "method": d.get("method"),
            "eliminator": d.get("eliminator"), "pom": d.get("player_of_match"), "stage": d.get("stage"),
            "balls_per_over": d.get("balls_per_over"),
        })
    m = pd.DataFrame(rows)
    m["Date"] = pd.to_datetime(m["date"].str.replace("/", "-"))
    m["Season"] = seasons_for(m["season_label"], m["Date"])
    # City: the info file's city, else the venue's usual city, else the venue's ", City" suffix
    m["city"] = m["city"].replace("", np.nan)
    usual = m.dropna(subset=["city"]).assign(v=lambda x: [clean_venue(a, b) for a, b in zip(x["venue"], x["city"])])
    usual = usual.groupby("v")["city"].agg(lambda s: s.value_counts().index[0]).to_dict()
    m["Venue"] = [clean_venue(v, c) for v, c in zip(m["venue"], m["city"])]
    m["City"] = [c if isinstance(c, str) else usual.get(v) or (str(raw).rsplit(",", 1)[1].strip() if "," in str(raw)
                                                               else v)
                 for c, v, raw in zip(m["city"], m["Venue"], m["venue"])]
    m["Host"] = [city_country(c) or city_country(v) or "Unknown" for c, v in zip(m["City"], m["Venue"])]
    host_over = overrides.get("host_by_match") or {}
    if host_over:
        m["Host"] = [host_over.get(i, h) for i, h in zip(m["Match ID"], m["Host"])]

    # Play-offs: no match number. Name them per season in date order.
    m = m.sort_values(["Date", "Match ID"], kind="stable").reset_index(drop=True)
    m["Match Type"] = np.where(m["match_number"].isna(), "Playoff", "League")
    m["Stage"] = "League"
    for season, g in m[m["Match Type"] == "Playoff"].groupby("Season"):
        names = PLAYOFF_NAMES.get(len(g)) or [f"Playoff {i}" for i in range(1, len(g))] + ["Final"]
        for (idx, row), name in zip(g.iterrows(), names):
            m.at[idx, "Stage"] = row["stage"] if isinstance(row["stage"], str) and row["stage"] else name
    m["Match No."] = pd.to_numeric(m["match_number"], errors="coerce").astype(float)
    m["Key"] = m["Season"].astype(str) + "|" + m["Stage"]
    return m


def resolve_names(dl: pd.DataFrame, infos: list[dict], overrides: dict) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """One display name per player (Cricsheet player id), applied to every delivery and award.

    A league override `names_by_id` wins (the PSL keeps its workbook names). Otherwise, when two different
    players share a display name, the one with more matches keeps it and the others become "Name (2)" …"""
    by_id = dict(overrides.get("names_by_id") or {})
    # players (not officials) per match: name -> id
    per_match, count = {}, {}
    for d in infos:
        reg = d.get("registry", {})
        names = {p for team in d.get("players", {}).values() for p in team}
        mp = {nm: reg.get(nm) for nm in names if reg.get(nm)}
        per_match[d["match_id"]] = mp
        for nm, pid in mp.items():
            count[(nm, pid)] = count.get((nm, pid), 0) + 1
    ids_by_name: dict[str, list] = {}
    for (nm, pid), c in sorted(count.items(), key=lambda kv: -kv[1]):
        ids_by_name.setdefault(nm, []).append(pid)
    final = {}
    for nm, ids in ids_by_name.items():
        for i, pid in enumerate(ids):
            final[pid] = by_id.get(pid) or (nm if i == 0 else f"{nm} ({i + 1})")
    # an id the override doesn't know but whose name is an override name keeps that name (merged players)
    out = dl.copy()
    cols = ["striker", "non_striker", "bowler", "player_dismissed", "other_player_dismissed"]
    ren = {(mid, nm): final[pid] for mid, mp in per_match.items() for nm, pid in mp.items()
           if final.get(pid) and final[pid] != nm}
    if ren:
        for c in cols:
            if c in out:
                keys = list(zip(out["match_id"], out[c]))
                out[c] = [ren.get(k, v) for k, v in zip(keys, out[c])]
        for d in infos:
            new = ren.get((d["match_id"], d.get("player_of_match")))
            if new:
                d["player_of_match"] = new
    people = (pd.DataFrame([(final[pid], pid) for pid in final], columns=["Player", "player_id"])
              .drop_duplicates().sort_values("Player").reset_index(drop=True))
    return out, infos, people


def build_core(dl: pd.DataFrame, infos: list[dict], people: pd.DataFrame | None = None,
               registry: pd.DataFrame | None = None, overrides: dict | None = None) -> dict[str, pd.DataFrame]:
    overrides = overrides or {}
    dl, infos, people = resolve_names(dl, [dict(d) for d in infos], overrides)
    m = _match_frame(dl, infos, overrides)
    meta = registry_lookup(people, registry)
    home_country = overrides.get("home_country") or (
        m["Host"][m["Host"] != "Unknown"].value_counts().index[0] if (m["Host"] != "Unknown").any() else None)

    ball, d = _ball(dl, m, meta, home_country)
    matches = _matches(m, d, meta, home_country)
    team_matches = _team_matches(matches, d, overrides, home_country)
    bat_inns = _bat_inns(d, matches, meta)
    bowl_inns = _bowl_inns(d, matches, meta)
    partnerships = _partnerships(d, matches)
    pair_seasons = _pair_seasons(ball)
    return {"ball": ball, "matches": matches, "team_matches": team_matches, "bat_inns": bat_inns,
            "bowl_inns": bowl_inns, "partnerships": partnerships, "pair_seasons": pair_seasons,
            "_deliveries": d, "_home_country": home_country, "_people": people}


# ── player metadata (hand, bowling type, origin) ────────────────────────────────────────────
def registry_lookup(people: pd.DataFrame, registry: pd.DataFrame | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if registry is None or registry.empty:
        return out
    reg = registry.set_index("player_id")
    for name, pid in zip(people["Player"], people["player_id"]):
        if pid in reg.index:
            r = reg.loc[pid]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            out[name] = {"hand": r.get("Bat Hand"), "type": r.get("Bowling Type"), "country": r.get("Country")}
    return out


def _origin(country, home_country) -> str:
    if not isinstance(country, str) or not country or not home_country:
        return "Unknown"
    return "Local" if same_country(country, home_country) else "Overseas"


# ── ball ─────────────────────────────────────────────────────────────────────────────────────
def _ball(dl: pd.DataFrame, m: pd.DataFrame, meta: dict, home_country) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = {mid: i for i, mid in enumerate(sorted(m["Match ID"]))}     # the ball table runs in Match ID order
    d = dl[dl["innings"].isin([1, 2])].copy()
    d["_ord"] = d["match_id"].map(order)
    d["_row"] = np.arange(len(d))
    d = d.sort_values(["_ord", "innings", "_row"], kind="stable").reset_index(drop=True)
    mm = m.set_index("Match ID")
    d["Over"] = d["ball"].astype(str).str.split(".").str[0].astype(int) + 1
    wides, nob = d["wides"].astype(int), d["noballs"].astype(int)
    d["legal"] = ((wides == 0) & (nob == 0)).astype(int)
    d["faced"] = (wides == 0).astype(int)
    d["bat_runs"] = d["runs_off_bat"].astype(int)
    d["total"] = d["runs_off_bat"].astype(int) + d["extras"].astype(int)
    d["bowler_runs"] = d["bat_runs"] + wides + nob
    wt = d["wicket_type"].fillna("")
    d["wicket"] = (d["player_dismissed"].notna() & ~wt.isin(NOT_OUT_TYPES)).astype(int)
    d["bowler_wkt"] = wt.isin(BOWLER_WICKETS).astype(int)
    key = d["match_id"].astype(str) + "|" + d["innings"].astype(str)
    d["_inn"] = key

    def hand(n):
        return (meta.get(n) or {}).get("hand") if isinstance((meta.get(n) or {}).get("hand"), str) else "Unknown"

    def btype(n):
        t = (meta.get(n) or {}).get("type")
        return t if isinstance(t, str) else "Unknown"

    ball = pd.DataFrame({
        "Match ID": d["match_id"].astype("int64"),
        "Season": d["match_id"].map(mm["Season"]).astype("int64"),
        "Match Type": d["match_id"].map(mm["Match Type"]),
        "Venue": d["match_id"].map(mm["Venue"]),
        "Host": d["match_id"].map(mm["Host"]),
        "Innings": d["innings"].astype("int64"),
        "Batting Team": d["batting_team"], "Bowling Team": d["bowling_team"],
        "Over": d["Over"].astype("int64"),
        "Phase": phase_of(d["Over"]),
        "Batter": d["striker"], "Bat Hand": d["striker"].map(hand),
        "Bowler": d["bowler"], "Bowler Type": d["bowler"].map(btype),
    })
    ball["Pace/Spin"] = ball["Bowler Type"].map(TYPE_PACE).fillna("Unknown")
    ball["Bat Runs"] = d["bat_runs"].astype("int64")
    ball["Total Runs"] = d["total"].astype("int64")
    ball["Bowler Runs"] = d["bowler_runs"].astype("int64")
    ball["Legal Ball"] = d["legal"].astype("int64")
    ball["Ball Faced"] = d["faced"].astype("int64")
    ball["Four"] = (d["bat_runs"] == 4).astype("int64")
    ball["Six"] = (d["bat_runs"] == 6).astype("int64")
    ball["Bat Dot"] = ((d["faced"] == 1) & (d["bat_runs"] == 0)).astype("int64")
    ball["Bowl Dot"] = ((d["legal"] == 1) & (d["bowler_runs"] == 0)).astype("int64")
    ball["Wides"] = wides.astype("int64")
    ball["No-balls"] = nob.astype("int64")
    ball["Bowler Wkt"] = d["bowler_wkt"].astype("int64")
    ball["Wicket"] = d["wicket"].astype("int64")
    ball["Player Out"] = d["player_dismissed"].where(d["wicket"] == 1)
    ball["How Out"] = d["wicket_type"].where(d["wicket"] == 1)
    # Balls faced by this batter so far in the innings (this ball included)
    ball["Batter Ball No"] = d.groupby([key, d["striker"]])["faced"].cumsum().astype("int64")
    # Over legal balls only (wides and no-balls are skipped): consecutive balls with nothing off the bat
    # before this one, capped at 4, and whether the previous legal ball went for a boundary.
    streak = np.full(len(d), np.nan)
    prev_b = np.full(len(d), np.nan)
    run, last_key, last_bdry = 0, None, 0
    bdry = ((d["bat_runs"] == 4) | (d["bat_runs"] == 6)).astype(int).to_numpy()
    dots = (d["total"] == 0).to_numpy()
    legal = d["legal"].to_numpy() == 1
    keys = key.to_numpy()
    for i in range(len(d)):
        if keys[i] != last_key:
            run, last_key, last_bdry = 0, keys[i], 0
        if not legal[i]:
            continue
        streak[i] = min(run, 4)
        prev_b[i] = last_bdry
        run = run + 1 if dots[i] else 0
        last_bdry = bdry[i]
    ball["Dot Streak"] = streak
    ball["Prev Bdry"] = prev_b
    ball["Striker Out"] = ((d["player_dismissed"] == d["striker"]) & (d["wicket"] == 1)).astype("int64")
    hs, hn = d["striker"].map(hand), d["non_striker"].map(hand)
    ball["Pair"] = np.where((hs == "Unknown") | (hn == "Unknown"), "Unknown",
                            np.where(hs != hn, "Left–right pair", "Same-hand pair"))
    ball["Batter Origin"] = d["striker"].map(lambda n: _origin((meta.get(n) or {}).get("country"), home_country))
    ball["Bowler Origin"] = d["bowler"].map(lambda n: _origin((meta.get(n) or {}).get("country"), home_country))
    return ball, d


# ── matches (part 2: results, edges, chase states, player of the match) ─────────────────────
def _matches(m: pd.DataFrame, d: pd.DataFrame, meta: dict, home_country) -> pd.DataFrame:
    g = d.groupby(["match_id", "innings"])
    inn = pd.DataFrame({
        "runs": g["total"].sum(), "wkts": g["wicket"].sum(), "legal": g["legal"].sum(),
        "team": g["batting_team"].first(),
    }).reset_index()
    i1 = inn[inn["innings"] == 1].set_index("match_id")
    i2 = inn[inn["innings"] == 2].set_index("match_id")
    out = m.copy()
    mid = out["Match ID"]
    out["Team 1"] = out["teams"].str[0]
    out["Team 2"] = out["teams"].str[1]
    out["Toss Winner"] = out["toss_winner"]
    out["Toss Decision"] = out["toss_decision"].str.capitalize()
    out["Bat First"] = mid.map(i1["team"])
    other = np.where(out["Bat First"] == out["Team 1"], out["Team 2"], out["Team 1"])
    out["Chasing"] = mid.map(i2["team"]).fillna(pd.Series(other, index=out.index))
    out["1st Inns Runs"] = mid.map(i1["runs"])
    out["1st Inns Wkts"] = mid.map(i1["wkts"])
    out["1st Inns Overs"] = mid.map(i1["legal"]).map(overs_str)
    out["2nd Inns Runs"] = mid.map(i2["runs"]).astype(float)
    out["2nd Inns Wkts"] = mid.map(i2["wkts"]).astype(float)
    out["2nd Inns Overs"] = mid.map(i2["legal"]).map(overs_str)
    no_result = out["outcome"].eq("no result")
    tie = out["outcome"].eq("tie")
    # Revised DLS targets are not in CSV2 files: left blank for those games.
    out["Target"] = np.where(no_result | out["method"].notna(), np.nan, out["1st Inns Runs"] + 1.0)
    out["Result"] = np.where(no_result, "No result", np.where(tie, "Tie (super over)", "Normal"))
    out["Winner"] = out["winner"].where(~tie, out["eliminator"])
    out["Loser"] = np.where(out["Winner"].isna(), None,
                            np.where(out["Winner"] == out["Team 1"], out["Team 2"], out["Team 1"]))

    def margin(r):
        if r["outcome"] == "tie":
            return "Tie – super over"
        if pd.notna(r["winner_runs"]):
            return f"{int(r['winner_runs'])} runs"
        if pd.notna(r["winner_wickets"]):
            return f"{int(r['winner_wickets'])} wickets"
        return None
    out["Margin"] = out.apply(margin, axis=1)
    out["Method"] = out["method"]
    out["Player of Match"] = out["pom"]
    decided = out["Winner"].notna()
    out["Bat First Won"] = np.where(decided, (out["Winner"] == out["Bat First"]).astype(float), np.nan)
    out["Toss Winner Won"] = np.where(decided, (out["Winner"] == out["Toss Winner"]).astype(float), np.nan)
    normal = out["Result"].eq("Normal") & out["Method"].isna()
    out["Decided (no DLS)"] = normal.astype("int64")
    full1 = (mid.map(i1["legal"]).fillna(0) >= 120) | (mid.map(i1["wkts"]).fillna(0) >= 10)
    out["Full 1st Inns"] = (full1 & out["Method"].isna() & ~no_result).astype("int64")

    out = _edges(out, d)
    out = _chase_states(out, d)
    out = _potm(out, d, meta, home_country)
    cols = ["Match ID", "Date", "Season", "Match Type", "Stage", "Match No.", "Key", "Venue", "City", "Host",
            "Team 1", "Team 2", "Toss Winner", "Toss Decision", "Bat First", "Chasing", "1st Inns Runs",
            "1st Inns Wkts", "1st Inns Overs", "2nd Inns Runs", "2nd Inns Wkts", "2nd Inns Overs", "Target", "Result",
            "Winner", "Loser", "Margin", "Method", "Player of Match", "Bat First Won", "Toss Winner Won",
            "Decided (no DLS)", "Full 1st Inns", "Bdry% Edge Won", "Dot% Edge Won", "Six Edge Won", "PP RR Edge Won",
            "MO1 RR Edge Won", "MO2 RR Edge Won", "Death RR Edge Won", "PP Wkt Edge Won", "MO1 Wkt Edge Won",
            "MO2 Wkt Edge Won", "Death Wkt Edge Won", "Alive@10", "Need@10", "Wkts@10", "Alive@15", "Need@15",
            "Wkts@15", "Final-over Chase", "Need off 20th", "Wkts Before 20th", "Chase Won", "Final-over Bowler",
            "Final-over Defended", "POTM Team", "POTM Side", "POTM Runs", "POTM Balls", "POTM Wkts",
            "POTM Runs Conceded", "POTM Balls Bowled", "POTM Type", "POTM Origin"]
    return out[cols].reset_index(drop=True)


def _edge(a, b, winner_is_a, higher_better=True):
    """1 if the side with the edge won, 0 if it lost, NaN if level or undecided."""
    res = np.full(len(a), np.nan)
    ok = ~(np.isnan(a) | np.isnan(b) | np.isnan(winner_is_a)) & (a != b)
    a_edge = (a > b) if higher_better else (a < b)
    res[ok] = np.where(a_edge[ok] == (winner_is_a[ok] == 1), 1.0, 0.0)
    return res


def _edges(out: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    dd = d.copy()
    dd["bdry"] = ((dd["bat_runs"] == 4) | (dd["bat_runs"] == 6)).astype(int)
    dd["six"] = (dd["bat_runs"] == 6).astype(int)
    dd["dot"] = ((dd["faced"] == 1) & (dd["bat_runs"] == 0)).astype(int)
    dd["phase"] = phase_of(dd["Over"])
    g = dd.groupby(["match_id", "innings"])
    s = pd.DataFrame({"faced": g["faced"].sum(), "bdry": g["bdry"].sum(), "six": g["six"].sum(),
                      "dot": g["dot"].sum()})
    p = dd.groupby(["match_id", "innings", "phase"]).agg(runs=("total", "sum"), legal=("legal", "sum"),
                                                          wk=("wicket", "sum"))
    mid = out["Match ID"]
    decided = (out["Decided (no DLS)"] == 1).to_numpy()
    w1 = np.where(decided, (out["Winner"] == out["Bat First"]).astype(float), np.nan)

    def get(frame, col, inn):
        idx = pd.MultiIndex.from_arrays([mid, np.full(len(mid), inn)])
        return frame[col].reindex(idx).to_numpy(dtype=float)

    f1, f2 = get(s, "faced", 1), get(s, "faced", 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["Bdry% Edge Won"] = _edge(get(s, "bdry", 1) / f1, get(s, "bdry", 2) / f2, w1)
        out["Dot% Edge Won"] = _edge(get(s, "dot", 1) / f1, get(s, "dot", 2) / f2, w1, higher_better=False)
        out["Six Edge Won"] = _edge(get(s, "six", 1) / f1, get(s, "six", 2) / f2, w1)
        for ph, lo, hi in PHASES:
            def pget(col, inn):
                idx = pd.MultiIndex.from_arrays([mid, np.full(len(mid), inn), np.full(len(mid), ph)])
                return p[col].reindex(idx).to_numpy(dtype=float)
            full = (pget("legal", 1) >= 12) & (pget("legal", 2) >= 12)     # both sides batted 2+ overs of the phase
            rr1 = np.where(full, pget("runs", 1) / pget("legal", 1), np.nan)
            rr2 = np.where(full, pget("runs", 2) / pget("legal", 2), np.nan)
            out[f"{ph} RR Edge Won"] = _edge(rr1, rr2, w1)
            out[f"{ph} Wkt Edge Won"] = _edge(np.where(full, pget("wk", 1), np.nan), np.where(full, pget("wk", 2), np.nan),
                                              w1, higher_better=False)
    return out


def _chase_states(out: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    c = d[d["innings"] == 2].copy()
    # chase states only for decided games with a full-length first innings (no DLS / reduced overs)
    decided = (out["Decided (no DLS)"] == 1) & (out["Full 1st Inns"] == 1)
    target = out.set_index("Match ID")["Target"]
    last_over = c.groupby("match_id")["Over"].max()
    for at in (10, 15):
        st = c[c["Over"] <= at].groupby("match_id").agg(runs=("total", "sum"), wk=("wicket", "sum"))
        alive = (out["Match ID"].map(last_over).fillna(0) > at) & decided
        need = out["Match ID"].map(target) - out["Match ID"].map(st["runs"])
        out[f"Alive@{at}"] = alive.astype("int64")
        out[f"Need@{at}"] = np.where(alive, need, np.nan)
        out[f"Wkts@{at}"] = np.where(alive, out["Match ID"].map(st["wk"]), np.nan)
    last = c[c["Over"] == 20]
    first20 = last.groupby("match_id").head(1).set_index("match_id")
    before = c[c["Over"] < 20].groupby("match_id").agg(runs=("total", "sum"), wk=("wicket", "sum"))
    fo = out["Match ID"].isin(first20.index) & decided
    out["Final-over Chase"] = fo.astype("int64")
    out["Need off 20th"] = np.where(fo, out["Match ID"].map(target) - out["Match ID"].map(before["runs"]), np.nan)
    out["Wkts Before 20th"] = np.where(fo, out["Match ID"].map(before["wk"]), np.nan)
    out["Chase Won"] = np.where(decided, (out["Winner"] == out["Chasing"]).astype(float), np.nan)
    out["Final-over Bowler"] = np.where(fo, out["Match ID"].map(first20["bowler"]), None)
    out["Final-over Defended"] = np.where(fo, (out["Winner"] != out["Chasing"]).astype(float), np.nan)
    return out


def _potm(out: pd.DataFrame, d: pd.DataFrame, meta: dict, home_country) -> pd.DataFrame:
    bat = d.groupby(["match_id", "striker"]).agg(runs=("bat_runs", "sum"), balls=("faced", "sum"),
                                                 team=("batting_team", "first"))
    bowl = d.groupby(["match_id", "bowler"]).agg(wk=("bowler_wkt", "sum"), runs=("bowler_runs", "sum"),
                                                 balls=("legal", "sum"), team=("bowling_team", "first"))
    # players who batted only at the non-striker's end
    ns = d.groupby(["match_id", "non_striker"])["batting_team"].first()
    rows = []
    for mid, pom, winner in zip(out["Match ID"], out["Player of Match"], out["Winner"]):
        r = {"POTM Team": None, "POTM Side": None, "POTM Runs": np.nan, "POTM Balls": np.nan, "POTM Wkts": np.nan,
             "POTM Runs Conceded": np.nan, "POTM Balls Bowled": np.nan, "POTM Type": None, "POTM Origin": None}
        if isinstance(pom, str):
            team = None
            if (mid, pom) in bat.index:
                b = bat.loc[(mid, pom)]
                r["POTM Runs"], r["POTM Balls"], team = float(b["runs"]), float(b["balls"]), b["team"]
            elif (mid, pom) in ns.index:
                r["POTM Runs"], r["POTM Balls"], team = 0.0, 0.0, ns.loc[(mid, pom)]
            if (mid, pom) in bowl.index:
                w = bowl.loc[(mid, pom)]
                r["POTM Wkts"], r["POTM Runs Conceded"], r["POTM Balls Bowled"] = (float(w["wk"]), float(w["runs"]),
                                                                                  float(w["balls"]))
                team = team or w["team"]
            r["POTM Team"] = team
            if team is not None and isinstance(winner, str):
                r["POTM Side"] = "Won" if team == winner else "Lost"
            r["POTM Type"] = potm_type(r)
            r["POTM Origin"] = _origin((meta.get(pom) or {}).get("country"), home_country)
        rows.append(r)
    return pd.concat([out.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def potm_type(r: dict) -> str | None:
    """Batting-led, bowling-led, all-round or other (from the award winner's match figures)."""
    runs, balls, wk = r["POTM Runs"], r["POTM Balls"], r["POTM Wkts"]
    conc, bb = r["POTM Runs Conceded"], r["POTM Balls Bowled"]
    if pd.isna(runs) and pd.isna(wk):
        return None
    # a real batting contribution: 25+ runs from 10+ balls
    batting = pd.notna(runs) and runs >= 25 and (balls or 0) >= 10
    # a real bowling contribution: 2+ wickets, or a wicket in a tight spell of 3+ overs (economy 6.5 or better)
    bowling = pd.notna(wk) and (wk >= 2 or (wk >= 1 and (bb or 0) >= 18 and 6 * conc / bb <= 6.5))
    if batting and bowling:
        return "All-round"
    return "Batting" if batting else ("Bowling" if bowling else "Other")


# ── team matches ─────────────────────────────────────────────────────────────────────────────
def _team_matches(matches: pd.DataFrame, d: pd.DataFrame, overrides: dict, home_country) -> pd.DataFrame:
    dd = d.copy()
    dd["phase"] = phase_of(dd["Over"])
    bat = dd.groupby(["match_id", "batting_team"]).agg(runs=("total", "sum"), wk=("wicket", "sum"),
                                                       faced=("legal", "sum"),
                                                       fours=("bat_runs", lambda s: int((s == 4).sum())),
                                                       sixes=("bat_runs", lambda s: int((s == 6).sum())))
    ph = dd.groupby(["match_id", "batting_team", "phase"]).agg(runs=("total", "sum"), wk=("wicket", "sum"))
    homes = overrides.get("home_venue") or infer_home_venues(matches)
    rows = []
    for _, mt in matches.iterrows():
        for team, opp in ((mt["Team 1"], mt["Team 2"]), (mt["Team 2"], mt["Team 1"])):
            r = {"Match ID": mt["Match ID"], "Date": mt["Date"], "Season": mt["Season"], "Match Type": mt["Match Type"],
                 "Stage": mt["Stage"], "Venue": mt["Venue"], "Host": mt["Host"], "Team": team, "Opposition": opp,
                 "Toss": "Won" if mt["Toss Winner"] == team else "Lost", "Toss Decision": mt["Toss Decision"],
                 "Batting Order": "Bat first" if mt["Bat First"] == team else "Chasing"}
            nr = mt["Result"] == "No result"
            r["Result"] = "No result" if nr else ("Won" if mt["Winner"] == team else "Lost")
            r["Tie (SO)"] = int(mt["Result"] == "Tie (super over)")
            r["DLS"] = int(pd.notna(mt["Method"]))
            r["Win"], r["Loss"], r["NR"] = int(r["Result"] == "Won"), int(r["Result"] == "Lost"), int(nr)
            k, ko = (mt["Match ID"], team), (mt["Match ID"], opp)
            r["Runs Scored"] = bat["runs"].get(k, np.nan)
            r["Wkts Lost"] = bat["wk"].get(k, np.nan)
            r["Balls Faced"] = bat["faced"].get(k, np.nan)
            r["Runs Conceded"] = bat["runs"].get(ko, np.nan)
            r["Wkts Taken"] = bat["wk"].get(ko, np.nan)
            r["Balls Bowled"] = bat["faced"].get(ko, np.nan)
            r["Fours"] = bat["fours"].get(k, np.nan)
            r["Sixes"] = bat["sixes"].get(k, np.nan)
            for phn, *_ in PHASES:
                r[f"{phn} Runs"] = ph["runs"].get((mt["Match ID"], team, phn), np.nan)
                r[f"{phn} Wkts"] = ph["wk"].get((mt["Match ID"], team, phn), np.nan)
            bf = r["Balls Faced"]
            r["Completed Inns"] = int(pd.notna(bf) and (bf >= 120 or r["Wkts Lost"] >= 10) and pd.isna(mt["Method"]))
            r["Full 1st Inns"] = int(mt["Bat First"] == team and mt["Full 1st Inns"] == 1)
            # Home = the team's own ground; Away = elsewhere in the home country; Neutral = abroad or no home ground
            hv = homes.get(team)
            r["Home Ground"] = ("Neutral" if not hv else "Home" if hv == mt["Venue"]
                                else "Away" if same_country(mt["Host"], home_country) else "Neutral")
            r["Decided"] = int(mt["Decided (no DLS)"] == 1)
            r["Opp Full 1st Inns"] = int(mt["Bat First"] == opp and mt["Full 1st Inns"] == 1)
            rows.append(r)
    return pd.DataFrame(rows)


def infer_home_venues(matches: pd.DataFrame) -> dict[str, str]:
    """A team's home ground = the venue whose city appears in the team's name (e.g. 'Lahore' Qalandars)."""
    out = {}
    venues = matches.groupby("Venue")["City"].agg(lambda s: s.value_counts().index[0]).to_dict()
    for team in pd.unique(matches[["Team 1", "Team 2"]].values.ravel()):
        for v, city in venues.items():
            if isinstance(city, str) and city and city.lower() in str(team).lower():
                out[team] = v
                break
    return out


# ── batting / bowling innings ──────────────────────────────────────────────────────────────
def _meta_val(meta: dict, name, field: str) -> str:
    v = (meta.get(name) or {}).get(field)
    return v if isinstance(v, str) and v else "Unknown"


def _workbook_order(df: pd.DataFrame) -> pd.DataFrame:
    """Innings tables run in Match ID order as text (as the files sit in the Cricsheet zip)."""
    return df.assign(_k=df["Match ID"].astype(str)).sort_values(["_k", "Innings"], kind="stable").drop(columns="_k")


def _bat_inns(d: pd.DataFrame, matches: pd.DataFrame, meta: dict) -> pd.DataFrame:
    mm = matches.set_index("Match ID")
    dd = d.reset_index(drop=True)
    # batting order: first appearance at either end, striker before non-striker on the same ball
    seq = pd.concat([
        pd.DataFrame({"inn": dd["_inn"], "p": dd["striker"], "o": np.arange(len(dd)) * 2}),
        pd.DataFrame({"inn": dd["_inn"], "p": dd["non_striker"], "o": np.arange(len(dd)) * 2 + 1}),
    ]).sort_values("o", kind="stable")
    first = seq.drop_duplicates(["inn", "p"]).copy()
    first["Position"] = first.groupby("inn").cumcount() + 1
    info = dd.groupby("_inn").agg(mid=("match_id", "first"), inns=("innings", "first"),
                                  team=("batting_team", "first"), opp=("bowling_team", "first"))
    dd["dot"] = ((dd["faced"] == 1) & (dd["bat_runs"] == 0)).astype(int)
    dd["four"] = (dd["bat_runs"] == 4).astype(int)
    dd["six"] = (dd["bat_runs"] == 6).astype(int)
    st = dd.groupby(["_inn", "striker"]).agg(Runs=("bat_runs", "sum"), Balls=("faced", "sum"), Fours=("four", "sum"),
                                             Sixes=("six", "sum"), Dots=("dot", "sum"))
    outs = dd[dd["wicket"] == 1].drop_duplicates(["_inn", "player_dismissed"]).set_index(["_inn", "player_dismissed"])
    ret = dd[dd["player_dismissed"].notna() & (dd["wicket"] == 0)].drop_duplicates(["_inn", "player_dismissed"])
    ret = ret.set_index(["_inn", "player_dismissed"])
    b = first.rename(columns={"p": "Batter"})
    idx = pd.MultiIndex.from_arrays([b["inn"], b["Batter"]])
    for c in ("Runs", "Balls", "Fours", "Sixes", "Dots"):
        b[c] = st[c].reindex(idx).fillna(0).astype(int).to_numpy()
    b["Out"] = idx.isin(outs.index).astype(int)
    how = outs["wicket_type"].reindex(idx).to_numpy()
    rhow = ret["wicket_type"].reindex(idx).to_numpy()
    b["How Out"] = np.where(pd.notna(how), how, np.where(pd.notna(rhow), rhow, "not out"))
    b["Strike Rate"] = np.where(b["Balls"] > 0, (100 * b["Runs"] / b["Balls"].where(b["Balls"] > 0)).round(2), np.nan)
    b["Match ID"] = b["inn"].map(info["mid"]).astype("int64")
    b["Innings"] = b["inn"].map(info["inns"]).astype("int64")
    b["Team"] = b["inn"].map(info["team"])
    b["Opposition"] = b["inn"].map(info["opp"])
    b = _workbook_order(b.sort_values(["o"])).reset_index(drop=True)
    b["Bat Hand"] = b["Batter"].map(lambda n: _meta_val(meta, n, "hand"))
    for c in ("Date", "Season", "Match Type", "Stage", "Venue", "Host"):
        b[c] = b["Match ID"].map(mm[c])
    b["Strike Rate"] = b["Strike Rate"].round(2)
    return b[["Match ID", "Date", "Season", "Match Type", "Stage", "Venue", "Host", "Innings", "Team", "Opposition",
              "Batter", "Bat Hand", "Position", "Runs", "Balls", "Fours", "Sixes", "Dots", "Out", "How Out",
              "Strike Rate"]]


def _bowl_inns(d: pd.DataFrame, matches: pd.DataFrame, meta: dict) -> pd.DataFrame:
    mm = matches.set_index("Match ID")
    dd = d.copy()
    dd["dot"] = ((dd["legal"] == 1) & (dd["bowler_runs"] == 0)).astype(int)
    over_runs = dd.groupby(["match_id", "innings", "bowler", "Over"]).agg(r=("bowler_runs", "sum"),
                                                                          l=("legal", "sum"))
    maidens = ((over_runs["r"] == 0) & (over_runs["l"] >= 6)).groupby(level=[0, 1, 2]).sum()
    g = dd.groupby(["match_id", "innings", "bowler"], sort=False)
    b = pd.DataFrame({
        "Team": g["bowling_team"].first(), "Opposition": g["batting_team"].first(),
        "Balls": g["legal"].sum(), "Runs": g["bowler_runs"].sum(), "Wickets": g["bowler_wkt"].sum(),
        "Dots": g["dot"].sum(), "Fours": g["bat_runs"].agg(lambda s: int((s == 4).sum())),
        "Sixes": g["bat_runs"].agg(lambda s: int((s == 6).sum())),
        "Wides": g["wides"].sum().astype(int), "No-balls": g["noballs"].sum().astype(int),
    }).reset_index().rename(columns={"match_id": "Match ID", "innings": "Innings", "bowler": "Bowler"})
    b["Maidens"] = [int(maidens.get((a, i, p), 0)) for a, i, p in zip(b["Match ID"], b["Innings"], b["Bowler"])]
    b["Overs"] = b["Balls"].map(overs_str)
    b["Economy"] = (6 * b["Runs"] / b["Balls"]).round(2)
    b["Bowler Type"] = b["Bowler"].map(lambda n: _meta_val(meta, n, "type"))
    b = _workbook_order(b).reset_index(drop=True)
    for c in ("Date", "Season", "Match Type", "Stage", "Venue", "Host"):
        b[c] = b["Match ID"].map(mm[c])
    return b[["Match ID", "Date", "Season", "Match Type", "Stage", "Venue", "Host", "Innings", "Team", "Opposition",
              "Bowler", "Bowler Type", "Overs", "Balls", "Runs", "Wickets", "Dots", "Fours", "Sixes", "Wides",
              "No-balls", "Maidens", "Economy"]]


# ── partnerships, batter v bowler by season ──────────────────────────────────────────────────
def _partnerships(d: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    b = d[["match_id", "innings", "batting_team", "bowling_team", "striker", "non_striker", "bat_runs", "total",
           "faced", "player_dismissed"]].copy().reset_index(drop=True)
    b["out"] = b["player_dismissed"].notna().astype(int)
    b["pair"] = [" & ".join(sorted((s, n))) for s, n in zip(b["striker"], b["non_striker"])]
    key = b["match_id"].astype(str) + "|" + b["innings"].astype(str)
    new = (b["pair"] != b["pair"].shift()) | (key != key.shift())
    b["pid"] = new.cumsum()
    wk_before = b.groupby(key)["out"].transform(lambda s: s.shift(fill_value=0).cumsum())
    b["wkt_no"] = wk_before + 1
    g = b.groupby("pid")
    part = pd.DataFrame({
        "Match ID": g["match_id"].first(), "Innings": g["innings"].first(),
        "Batting Team": g["batting_team"].first(), "Bowling Team": g["bowling_team"].first(),
        "Wicket": g["wkt_no"].first().clip(upper=10), "Pair": g["pair"].first(),
        "Runs": g["total"].sum().astype(int), "Balls": g["faced"].sum().astype(int),
        "Unbroken": (g["out"].last() == 0).astype(int),
    })
    bat = b.groupby(["pid", "striker"])["bat_runs"].sum().unstack(fill_value=0)
    a_b = part["Pair"].str.split(" & ", expand=True)
    part["Batter 1"], part["Batter 2"] = a_b[0], a_b[1]
    part["Batter 1 Runs"] = [int(bat.at[i, p]) if p in bat.columns else 0 for i, p in zip(part.index, part["Batter 1"])]
    part["Batter 2 Runs"] = [int(bat.at[i, p]) if p in bat.columns else 0 for i, p in zip(part.index, part["Batter 2"])]
    mm = matches[["Match ID", "Season", "Date", "Venue"]]
    part = _workbook_order(part.merge(mm, on="Match ID", how="left")).reset_index(drop=True)
    part["Season"] = part["Season"].astype(int)
    return part


def _pair_seasons(ball: pd.DataFrame, min_balls: int = 12) -> pd.DataFrame:
    """Batter v bowler by season, for pairs that met for 12+ balls across all seasons."""
    b = ball.assign(_out=((ball["Bowler Wkt"] == 1) & (ball["Striker Out"] == 1)).astype(int))
    g = b.groupby(["Batter", "Bowler", "Season"])
    out = pd.DataFrame({"Balls": g["Ball Faced"].sum(), "Runs": g["Bat Runs"].sum(), "Outs": g["_out"].sum(),
                        "Dots": g["Bat Dot"].sum(), "Fours": g["Four"].sum(), "Sixes": g["Six"].sum()}).reset_index()
    total = out.groupby(["Batter", "Bowler"])["Balls"].transform("sum")
    out = out[total >= min_balls].sort_values(["Batter", "Bowler", "Season"]).reset_index(drop=True)
    return out
