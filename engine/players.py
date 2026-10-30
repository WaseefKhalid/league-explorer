"""Player tables: player_seasons, players and lists (the site's dropdown lists).

    build_player_tables(tables, people, registry, home_country=None, infos=None, team_abbr=None)
        -> {"player_seasons": ..., "players": ..., "lists": ...}

home_country None -> tables["_home_country"] if present (else Origin is "Unknown");
people None -> tables["_people"]. team_abbr: {team name: code} overrides for the "Team"/"Teams" codes.

Everything is derived from the core tables (ball incl. the five impact columns, matches,
team_matches, bat_inns, bowl_inns) plus two optional extras:

* the playing XIs.  Cricsheet's info files list every player of each side; the core tables only
  know who batted or bowled.  `Mat` (and which player-seasons exist at all) needs the XIs, so pass
  either `infos` (read_zip's list of info dicts; names are mapped to `people` through the per-match
  registry ids) or a ready-made `tables["playing_xi"]` (Match ID, Team, Player).  Without them a
  player's matches are the ones in which he batted (incl. at the non-striker's end) or bowled.
* `registry` (player_id -> Full Name, Country, Role, Bat Hand, Bowling Style, Bowling Type).
  Hand / bowling type / country / origin exist only for players found there; everyone else is
  "Unknown" ("—" is the workbook's mark for a registered player with no bowling type).

Not derivable from Cricsheet CSV2 (no fielder names): Catches, Stumpings, Run-outs -> NaN.
Caught-and-bowled could credit the bowler with a catch, but that is a lower bound of a player's
catches, not the column's meaning, so it is not used.  The players table's "Hand Source" /
"Style Source" record where the workbook author got each value ("Cricinfo", "You", "Web check");
the registry carries no provenance, so known values are attributed to its documented source,
"Cricinfo", unless the registry supplies those columns itself.

Impact columns are sums of the ball table's impact columns, rounded to 3 dp like the workbook.
They are exact only when the ball impacts are unrounded; summing 3-dp ball values drifts by up to
~0.1 over a season.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

PHASES = ["PP", "MO1", "MO2", "Death"]
BOWL_TYPES = ["Right-arm pace", "Left-arm pace", "Off-spin", "Leg-spin", "Left-arm orthodox", "Left-arm wrist-spin"]
TYPE_SHORT = {"Right-arm pace": "RAP", "Left-arm pace": "LAP", "Off-spin": "OS", "Leg-spin": "LS",
              "Left-arm orthodox": "LAO", "Left-arm wrist-spin": "LWS"}
HANDS = ["RHB", "LHB"]
PACE_SPIN = ["Pace", "Spin"]
MATCH_TYPES = ["League", "Playoff"]
UNKNOWN = "Unknown"
NO_TYPE = "—"            # registered player without a bowling type (workbook convention)
SET_BATTER_BALLS = 20     # "set-batter wickets (20+ balls)"
TOP_ORDER = 3             # "top-order wickets (1–3)"

# Abbreviations that no rule can guess (single-word franchise names). Extend via `team_abbr`.
KNOWN_TEAM_ABBR = {"Rawalpindiz": "RP"}

PS_COLUMNS = [
    "Player", "Season", "Team", "Origin", "Hand", "Bowl Type", "Mat", "Inns", "NO", "Runs", "Balls", "Outs",
    "4s", "6s", "Bat Dots", "30s", "50s", "100s", "HS Key", "Runs in Wins", "Inns in Wins", "50+ in Wins",
    "Chase Runs", "Chase Balls",
    *[f"R {p}" for p in PHASES], *[f"B {p}" for p in PHASES],
    "R v Pace", "R v Spin", "B v Pace", "B v Spin",
    *[f"R v {s}" for s in TYPE_SHORT.values()], *[f"B v {s}" for s in TYPE_SHORT.values()],
    "R b1-10", "R b21+", "B b1-10", "B b21+", "R O20", "B O20", "6s O20",
    "Outs to Bowlers", "Outs v Pace", "Outs v Spin", "Outs Death", "Outs O20", "Bat Run Impact",
    "Bowl Inns", "Bowl Balls", "Bowl Runs", "Wkts", "Bowl Dots", "4s Conc", "6s Conc", "Wides", "No-balls",
    "Maidens", "3w", "4w+", "Best Key",
    *[f"BB {p}" for p in PHASES], *[f"BR {p}" for p in PHASES], *[f"BW {p}" for p in PHASES],
    "BB v RHB", "BB v LHB", "BR v RHB", "BR v LHB", "BW v RHB", "BW v LHB", "BB O20", "BR O20", "BW O20",
    "Bowl Run Impact", "Bowl Wkt Impact", "Wicket Value", "Top-order Wkts", "Set-batter Wkts",
    "Catches", "Stumpings", "Run-outs", "POTM", "Bat Out Impact", "player_id",
]
PS_TEXT = {"Player", "Team", "Origin", "Hand", "Bowl Type", "player_id"}
PS_FLOAT = {"HS Key", "Best Key", "Bat Run Impact", "Bowl Run Impact", "Bowl Wkt Impact", "Wicket Value",
            "Bat Out Impact"}
FIELDING = ["Catches", "Stumpings", "Run-outs"]          # not in Cricsheet CSV2 -> NaN

PLAYERS_COLUMNS = ["Player", "Full Name", "Country", "Overseas/Local", "Role (Cricinfo)", "Bat Hand",
                   "Bowling Style", "Bowling Type", "Teams", "Seasons (career)", "Matches", "Runs", "Wickets",
                   "POTM", "Batting impact", "Bowling impact", "Catches", "Hand Source", "Style Source",
                   "Still Missing"]

LISTS_COLUMNS = ["Batters", "Bowlers", "Teams+All", "Venues+All", "Phases+All", "Types+All", "Seasons",
                 "Hands+All", "PaceSpin+All", "MatchType+All", "Host+All", "Innings", "Toss", "Order", "Teams",
                 "FinishKey", "FinishLabel", "Batters+All", "Bowlers+All"]

KEY = ["Player", "Season"]


# ── helpers ────────────────────────────────────────────────────────────────────────────────────
def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip())


def team_abbreviations(teams, overrides: dict | None = None) -> dict[str, str]:
    """Short team codes: initials of each word ("Lahore Qalandars" -> "LQ"; short all-caps words are kept
    whole, "Kings XI Punjab" -> "KXIP"); one-word names take their first two letters. Known/override
    codes win; clashes get the next letter of the last word, then a number."""
    fixed = {**KNOWN_TEAM_ABBR, **(overrides or {})}
    names = sorted({t for t in teams if isinstance(t, str)})
    out: dict[str, str] = {t: fixed[t] for t in names if t in fixed}
    used = set(out.values())
    for t in names:
        if t in out:
            continue
        words = re.findall(r"[^\W_]+", t)
        if len(words) >= 2:
            code = "".join(w if (w.isupper() and len(w) <= 3) else w[0].upper() for w in words)
        elif words:
            code = words[0][:2].upper()
        else:
            code = t[:2].upper()
        last = words[-1] if words else t
        cand, i = code, 1
        while cand in used:
            cand = code + last[i].upper() if i < len(last) else f"{code}{i - len(last) + 2}"
            i += 1
        out[t] = cand
        used.add(cand)
    return out


def _span_label(seasons: pd.Series) -> str:
    lo, hi = int(seasons.min()), int(seasons.max())
    return str(lo) if lo == hi else f"{lo}–{hi}"


def _origin(country, home_country, keep_mark: bool) -> str:
    """Local / Overseas from the registry country. A trailing '*' marks an assumed country (no
    Cricinfo profile, e.g. Pakistani domestic players); only the players table keeps the mark."""
    if _blank(country) or country == UNKNOWN or _blank(home_country):
        return UNKNOWN
    base = country.rstrip("*").strip()
    mark = "*" if (keep_mark and country.endswith("*")) else ""
    return ("Local" if base == home_country else "Overseas") + mark


def _mark_assumed(country, full_name, has_full_name: bool):
    """The workbook writes "Pakistan*" for a country that did not come from a Cricinfo profile.
    Registries that still carry the '*' are used as they are; otherwise a registered player with a
    country but no profile (no Full Name) gets the mark."""
    if _blank(country) or country == UNKNOWN or country.endswith("*"):
        return country
    return f"{country}*" if (has_full_name and _blank(full_name)) else country


def playing_xi(infos: list[dict], people: pd.DataFrame) -> pd.DataFrame:
    """Match ID, Team, Player for every listed player of every match. Cricsheet names are mapped to the
    names used in the ball table through the per-match registry id (`people`: Player, player_id)."""
    id2name = {}
    for name, pid in zip(people["Player"], people["player_id"]):
        if isinstance(pid, str) and pid not in id2name:
            id2name[pid] = name
    rows = []
    for d in infos:
        reg = d.get("registry") or {}
        for team, names in (d.get("players") or {}).items():
            for n in names:
                rows.append((int(d["match_id"]), team, id2name.get(reg.get(n), n)))
    return pd.DataFrame(rows, columns=["Match ID", "Team", "Player"]).drop_duplicates()


# ── main ───────────────────────────────────────────────────────────────────────────────────────
def build_player_tables(tables: dict[str, pd.DataFrame], people: pd.DataFrame, registry: pd.DataFrame | None,
                        home_country: str | None = None, infos: list[dict] | None = None,
                        team_abbr: dict | None = None) -> dict[str, pd.DataFrame]:
    if home_country is None:
        home_country = tables.get("_home_country")
    if people is None:
        people = tables.get("_people", pd.DataFrame(columns=["Player", "player_id"]))
    ball = tables["ball"]
    if "Innings" in ball:
        ball = ball[ball["Innings"] <= 2]                       # never count super overs
    matches, tm = tables["matches"], tables["team_matches"]
    bi, bo = tables["bat_inns"], tables["bowl_inns"]
    season_of = matches.set_index("Match ID")["Season"]
    date_of = matches.set_index("Match ID")["Date"] if "Date" in matches else None

    # ── who played: (Match ID, Team, Player) ──
    app = [bi[["Match ID", "Team", "Batter"]].rename(columns={"Batter": "Player"}),
           bo[["Match ID", "Team", "Bowler"]].rename(columns={"Bowler": "Player"})]
    xi = tables.get("playing_xi")
    if xi is None and infos:
        xi = playing_xi(infos, people)
    if xi is not None:
        app.insert(0, xi[["Match ID", "Team", "Player"]])
    app = pd.concat(app, ignore_index=True).drop_duplicates(["Match ID", "Player"])
    app = app[app["Match ID"].isin(season_of.index)].copy()
    app["Season"] = app["Match ID"].map(season_of).astype("int64")
    app["_d"] = app["Match ID"].map(date_of) if date_of is not None else 0
    app = app.sort_values(["_d", "Match ID"], kind="stable")

    teams_all = pd.concat([matches["Team 1"], matches["Team 2"]]).dropna().unique()
    abbr = team_abbreviations(list(teams_all) + list(app["Team"].dropna().unique()), team_abbr)
    app["Abbr"] = app["Team"].map(abbr)

    base = app.groupby(KEY, sort=False).agg(
        Team=("Abbr", lambda s: "/".join(pd.unique(s.dropna()))),
        Mat=("Match ID", "nunique"))
    base = base.reset_index().sort_values(KEY, kind="stable").set_index(KEY)    # Player (code-point order), Season
    idx = base.index
    out: dict = {}                     # column -> values aligned on idx; one DataFrame at the end

    def put(name, s, kind="int"):
        s = s.reindex(idx)
        out[name] = s.fillna(0).round().astype("int64") if kind == "int" else s.astype(float)

    # ── metadata from the registry ──
    pid = people.drop_duplicates("Player").set_index("Player")["player_id"]
    reg = (registry.drop_duplicates("player_id").set_index("player_id")
           if registry is not None and len(registry) else pd.DataFrame(columns=["Country", "Bat Hand", "Bowling Type"]))
    players_idx = idx.get_level_values(0)
    p_id = players_idx.map(pid)
    in_reg = pd.Series(p_id, index=idx).isin(reg.index).to_numpy()

    def reg_col(col, ids):
        if col not in reg:
            return pd.Series([np.nan] * len(ids))
        return pd.Series([reg.at[i, col] if (isinstance(i, str) and i in reg.index) else np.nan for i in ids])

    country = reg_col("Country", p_id)
    hand = reg_col("Bat Hand", p_id)
    btype = reg_col("Bowling Type", p_id)

    out["Team"] = base["Team"]
    out["Origin"] = [_origin(c, home_country, keep_mark=False) for c in country]
    out["Hand"] = [h if h in HANDS else UNKNOWN for h in hand]
    out["Bowl Type"] = [t if not _blank(t) else (NO_TYPE if r else UNKNOWN) for t, r in zip(btype, in_reg)]
    out["Mat"] = base["Mat"].astype("int64")

    # ── batting: innings ──
    winner = matches.set_index("Match ID")["Winner"]
    x = bi.copy()
    x["Season"] = x["Match ID"].map(season_of)
    win = (x["Match ID"].map(winner) == x["Team"]).astype(int)
    r = x["Runs"]
    x = x.assign(_inn=1, _no=(x["Out"] == 0).astype(int),
                 _30=((r >= 30) & (r < 50)).astype(int), _50=((r >= 50) & (r < 100)).astype(int),
                 _100=(r >= 100).astype(int), _hs=r + 0.1 * (x["Out"] == 0),
                 _rw=r * win, _iw=win, _fw=((r >= 50) & (win == 1)).astype(int),
                 _cr=r * (x["Innings"] == 2), _cb=x["Balls"] * (x["Innings"] == 2))
    g = x.groupby(["Batter", "Season"])
    for name, col in [("Inns", "_inn"), ("NO", "_no"), ("Runs", "Runs"), ("Balls", "Balls"), ("Outs", "Out"),
                      ("4s", "Fours"), ("6s", "Sixes"), ("Bat Dots", "Dots"), ("30s", "_30"), ("50s", "_50"),
                      ("100s", "_100")]:
        put(name, g[col].sum())
    put("HS Key", g["_hs"].max().round(1), "float")
    for name, col in [("Runs in Wins", "_rw"), ("Inns in Wins", "_iw"), ("50+ in Wins", "_fw"),
                      ("Chase Runs", "_cr"), ("Chase Balls", "_cb")]:
        put(name, g[col].sum())

    # ── batting: ball splits ──
    def bsum(mask, col, by="Batter"):
        d = ball if mask is None else ball[mask]
        return d.groupby([by, "Season"])[col].sum()

    for p in PHASES:
        put(f"R {p}", bsum(ball["Phase"] == p, "Bat Runs"))
    for p in PHASES:
        put(f"B {p}", bsum(ball["Phase"] == p, "Ball Faced"))
    for v in PACE_SPIN:
        put(f"R v {v}", bsum(ball["Pace/Spin"] == v, "Bat Runs"))
    for v in PACE_SPIN:
        put(f"B v {v}", bsum(ball["Pace/Spin"] == v, "Ball Faced"))
    for t, s in TYPE_SHORT.items():
        put(f"R v {s}", bsum(ball["Bowler Type"] == t, "Bat Runs"))
    for t, s in TYPE_SHORT.items():
        put(f"B v {s}", bsum(ball["Bowler Type"] == t, "Ball Faced"))
    bno, o20 = ball["Batter Ball No"], ball["Over"] == 20
    put("R b1-10", bsum(bno <= 10, "Bat Runs"))
    put("R b21+", bsum(bno >= 21, "Bat Runs"))
    put("B b1-10", bsum(bno <= 10, "Ball Faced"))
    put("B b21+", bsum(bno >= 21, "Ball Faced"))
    put("R O20", bsum(o20, "Bat Runs"))
    put("B O20", bsum(o20, "Ball Faced"))
    put("6s O20", bsum(o20, "Six"))
    bw = ball["Bowler Wkt"] == 1
    put("Outs to Bowlers", bsum(bw, "Bowler Wkt", "Player Out"))
    put("Outs v Pace", bsum(bw & (ball["Pace/Spin"] == "Pace"), "Bowler Wkt", "Player Out"))
    put("Outs v Spin", bsum(bw & (ball["Pace/Spin"] == "Spin"), "Bowler Wkt", "Player Out"))
    put("Outs Death", bsum(ball["Phase"] == "Death", "Striker Out"))      # any dismissal of the striker
    put("Outs O20", bsum(o20, "Striker Out"))

    has_imp = all(c in ball for c in ["Bat Run Impact", "Exp Out Cost", "Out Impact", "Bowl Run Impact",
                                      "Bowl Wkt Impact"])

    def isum(s):
        return s.reindex(idx).fillna(0.0).round(3) if has_imp else pd.Series(np.nan, index=idx)

    out["Bat Run Impact"] = isum(bsum(None, "Bat Run Impact") if has_imp else None)

    # ── bowling: innings ──
    y = bo.copy()
    y["Season"] = y["Match ID"].map(season_of)
    y = y.assign(_inn=1, _3w=(y["Wickets"] == 3).astype(int), _4w=(y["Wickets"] >= 4).astype(int),
                 _best=y["Wickets"] * 1000 - y["Runs"])
    g = y.groupby(["Bowler", "Season"])
    for name, col in [("Bowl Inns", "_inn"), ("Bowl Balls", "Balls"), ("Bowl Runs", "Runs"), ("Wkts", "Wickets"),
                      ("Bowl Dots", "Dots"), ("4s Conc", "Fours"), ("6s Conc", "Sixes"), ("Wides", "Wides"),
                      ("No-balls", "No-balls"), ("Maidens", "Maidens"), ("3w", "_3w"), ("4w+", "_4w")]:
        put(name, g[col].sum())
    put("Best Key", g["_best"].max(), "float")

    # ── bowling: ball splits ──
    for p in PHASES:
        put(f"BB {p}", bsum(ball["Phase"] == p, "Legal Ball", "Bowler"))
    for p in PHASES:
        put(f"BR {p}", bsum(ball["Phase"] == p, "Bowler Runs", "Bowler"))
    for p in PHASES:
        put(f"BW {p}", bsum(ball["Phase"] == p, "Bowler Wkt", "Bowler"))
    for h in HANDS:
        put(f"BB v {h}", bsum(ball["Bat Hand"] == h, "Legal Ball", "Bowler"))
    for h in HANDS:
        put(f"BR v {h}", bsum(ball["Bat Hand"] == h, "Bowler Runs", "Bowler"))
    for h in HANDS:
        put(f"BW v {h}", bsum(ball["Bat Hand"] == h, "Bowler Wkt", "Bowler"))
    put("BB O20", bsum(o20, "Legal Ball", "Bowler"))
    put("BR O20", bsum(o20, "Bowler Runs", "Bowler"))
    put("BW O20", bsum(o20, "Bowler Wkt", "Bowler"))
    out["Bowl Run Impact"] = isum(bsum(None, "Bowl Run Impact", "Bowler") if has_imp else None)
    out["Bowl Wkt Impact"] = isum(bsum(None, "Bowl Wkt Impact", "Bowler") if has_imp else None)

    # wickets: value (runs the dismissal cost the batting side), top order (1–3), set batter (20+ balls)
    w = ball[bw].copy()
    pos = bi.drop_duplicates(["Match ID", "Innings", "Batter"]).set_index(["Match ID", "Innings", "Batter"])["Position"]
    w["_pos"] = pd.MultiIndex.from_arrays([w["Match ID"], w["Innings"], w["Player Out"]]).map(pos)
    w["_top"] = (w["_pos"] <= TOP_ORDER).astype(int)
    w["_set"] = (w["Batter Ball No"] >= SET_BATTER_BALLS).astype(int)
    gw = w.groupby(["Bowler", "Season"])
    out["Wicket Value"] = isum(-gw["Out Impact"].sum() if has_imp else None)
    put("Top-order Wkts", gw["_top"].sum())
    put("Set-batter Wkts", gw["_set"].sum())

    for c in FIELDING:
        out[c] = np.nan

    # Player of the match (joint awards may arrive as "A, B" / "A & B")
    known = set(players_idx)
    potm = []
    for mid, s in zip(matches["Match ID"], matches["Player of Match"]):
        if _blank(s):
            continue
        names = [s] if s in known else [n.strip() for n in re.split(r",|&|;", s) if n.strip() in known]
        potm += [(n, season_of[mid]) for n in names]
    potm = pd.DataFrame(potm, columns=KEY)
    put("POTM", potm.groupby(KEY).size() if len(potm) else pd.Series(dtype=float))

    if has_imp:
        out_imp = ball.groupby(["Player Out", "Season"])["Out Impact"].sum()
        exp = ball.groupby(["Batter", "Season"])["Exp Out Cost"].sum()
        out["Bat Out Impact"] = (out_imp.reindex(idx).fillna(0.0) - exp.reindex(idx).fillna(0.0)).round(3)
    else:
        out["Bat Out Impact"] = np.nan
    out["player_id"] = np.asarray(p_id, dtype=object)

    ps = pd.DataFrame(out, index=idx).reset_index()
    ps["Season"] = ps["Season"].astype("int64")
    ps = ps[PS_COLUMNS]
    for c in PS_TEXT:
        ps[c] = ps[c].astype("str").where(ps[c].notna())

    players = _players(ps, app, abbr, registry_frame=reg, people_id=pid, ball=ball, home_country=home_country)
    lists = _lists(ball, matches, tm, bo)
    return {"player_seasons": ps, "players": players, "lists": lists}


def _players(ps: pd.DataFrame, app: pd.DataFrame, abbr: dict, registry_frame: pd.DataFrame,
             people_id: pd.Series, ball: pd.DataFrame, home_country) -> pd.DataFrame:
    names = sorted(ps["Player"].unique())
    reg = registry_frame
    ids = pd.Index(names).map(people_id)

    def rc(col):
        if col not in reg:
            return [np.nan] * len(names)
        return [reg.at[i, col] if (isinstance(i, str) and i in reg.index) else np.nan for i in ids]

    df = pd.DataFrame({"Player": names})
    df["Full Name"] = rc("Full Name")
    country = [_mark_assumed(c, f, "Full Name" in reg) if r else c
               for c, f, r in zip(rc("Country"), df["Full Name"], [isinstance(i, str) and i in reg.index for i in ids])]
    df["Country"] = [UNKNOWN if _blank(c) else c for c in country]
    df["Overseas/Local"] = [_origin(c, home_country, keep_mark=True) for c in country]
    df["Role (Cricinfo)"] = rc("Role (Cricinfo)")
    df["Bat Hand"] = [h if h in HANDS else UNKNOWN for h in rc("Bat Hand")]
    df["Bowling Style"] = rc("Bowling Style")
    in_reg = [isinstance(i, str) and i in reg.index for i in ids]
    df["Bowling Type"] = [t if not _blank(t) else (np.nan if r else UNKNOWN) for t, r in zip(rc("Bowling Type"), in_reg)]

    teams = app.groupby("Player", sort=False)["Abbr"].agg(lambda s: "/".join(pd.unique(s.dropna())))
    df["Teams"] = df["Player"].map(teams)
    df["Seasons (career)"] = df["Player"].map(ps.groupby("Player")["Season"].agg(_span_label))

    g = ps.groupby("Player")
    s = g[["Mat", "Runs", "Wkts", "POTM", "Balls", "Bowl Balls"]].sum()
    imp = g[["Bat Run Impact", "Bat Out Impact", "Bowl Run Impact", "Bowl Wkt Impact"]].sum(min_count=1)
    df["Matches"] = df["Player"].map(s["Mat"]).astype(float)
    df["Runs"] = df["Player"].map(s["Runs"]).astype(float)
    df["Wickets"] = df["Player"].map(s["Wkts"]).astype(float)
    df["POTM"] = df["Player"].map(s["POTM"]).astype(float)
    bat = (imp["Bat Run Impact"] + imp["Bat Out Impact"]).where(s["Balls"] > 0)
    bowl = (imp["Bowl Run Impact"] + imp["Bowl Wkt Impact"]).where(s["Bowl Balls"] > 0)
    df["Batting impact"] = df["Player"].map(bat).astype(float)
    df["Bowling impact"] = df["Player"].map(bowl).astype(float)
    df["Catches"] = df["Player"].map(g["Catches"].sum(min_count=1)).astype(float)

    # data source: the registry's own provenance columns if it has them, else its documented source
    known_hand = df["Bat Hand"].isin(HANDS)
    known_style = df["Bowling Style"].map(lambda v: not _blank(v))
    df["Hand Source"] = rc("Hand Source") if "Hand Source" in reg else np.where(known_hand, "Cricinfo", None)
    df["Style Source"] = rc("Style Source") if "Style Source" in reg else np.where(known_style, "Cricinfo", None)
    df.loc[~known_hand, "Hand Source"] = np.nan
    df.loc[~known_style, "Style Source"] = np.nan
    batted, bowled = set(ball["Batter"]), set(ball["Bowler"])
    miss = []
    for p, h, st in zip(df["Player"], known_hand, known_style):
        parts = (["batting hand"] if (not h and p in batted) else []) + \
                (["bowling style"] if (not st and p in bowled) else [])
        miss.append(" + ".join(parts) if parts else np.nan)
    df["Still Missing"] = miss

    df = df[PLAYERS_COLUMNS]
    for c in df.columns:
        if c not in ("Matches", "Runs", "Wickets", "POTM", "Batting impact", "Bowling impact", "Catches"):
            df[c] = df[c].astype(object).where(df[c].notna()).astype("str").where(df[c].notna())
    return df


def _present(values, canonical: list[str]) -> list[str]:
    """Canonical values that occur, in canonical order, then any other known values sorted."""
    have = {v for v in pd.unique(values) if isinstance(v, str) and v and v != UNKNOWN}
    return [v for v in canonical if v in have] + sorted(have - set(canonical))


def _lists(ball: pd.DataFrame, matches: pd.DataFrame, tm: pd.DataFrame, bo: pd.DataFrame) -> pd.DataFrame:
    batters = sorted(ball["Batter"].dropna().unique())
    bowlers = sorted(ball["Bowler"].dropna().unique())
    teams = sorted(pd.concat([matches["Team 1"], matches["Team 2"]]).dropna().unique())
    venues = sorted(matches["Venue"].dropna().unique())
    hosts = sorted(h for h in matches["Host"].dropna().unique() if h != UNKNOWN)
    seasons = sorted(int(s) for s in matches["Season"].dropna().unique())

    # season finish per team: Champion / Runner-up (the Final), Playoffs, League
    ts = tm[["Team", "Season"]].drop_duplicates()
    po = set(zip(tm.loc[tm["Match Type"] == "Playoff", "Team"], tm.loc[tm["Match Type"] == "Playoff", "Season"]))
    fin = matches[matches["Stage"] == "Final"]
    champ, runner = set(), set()
    for _, r in fin.iterrows():
        if isinstance(r["Winner"], str):
            champ.add((r["Winner"], r["Season"]))
            if isinstance(r["Loser"], str):
                runner.add((r["Loser"], r["Season"]))
        else:                                       # final without a result: title shared
            champ.update({(r["Team 1"], r["Season"]), (r["Team 2"], r["Season"])})

    def label(t, s):
        return ("Champion" if (t, s) in champ else "Runner-up" if (t, s) in runner
                else "Playoffs" if (t, s) in po else "League")
    fk = sorted((f"{t}|{int(s)}", label(t, s)) for t, s in zip(ts["Team"], ts["Season"]))

    cols = {
        "Batters": batters, "Bowlers": bowlers, "Teams+All": ["All"] + teams, "Venues+All": ["All"] + venues,
        "Phases+All": ["All"] + PHASES,
        "Types+All": ["All"] + _present(ball["Bowler Type"], BOWL_TYPES),
        "Seasons": [float(s) for s in seasons],
        "Hands+All": ["All"] + _present(ball["Bat Hand"], HANDS),
        "PaceSpin+All": ["All"] + _present(ball["Pace/Spin"], PACE_SPIN),
        "MatchType+All": ["All"] + _present(matches["Match Type"], MATCH_TYPES),
        "Host+All": ["All"] + hosts,
        "Innings": ["All", "1st innings", "2nd innings"],
        "Toss": ["All", "Won toss", "Lost toss"],
        "Order": ["All", "Bat first", "Chasing"],
        "Teams": teams,
        "FinishKey": [k for k, _ in fk], "FinishLabel": [lab for _, lab in fk],
        "Batters+All": ["All"] + batters, "Bowlers+All": ["All"] + bowlers,
    }
    n = max(len(v) for v in cols.values())
    out = pd.DataFrame(index=range(n))
    for c in LISTS_COLUMNS:
        v = cols[c]
        if c == "Seasons":
            out[c] = pd.Series(v + [np.nan] * (n - len(v)), dtype="float64")
        else:
            out[c] = pd.Series(v + [None] * (n - len(v)), dtype="str")
    return out
