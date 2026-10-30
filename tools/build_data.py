"""
Convert the PSL Analytics Workbook into the app's data files.

    python tools/build_data.py path/to/PSL_Analytics_Workbook.xlsx

Writes data/leagues/psl/*.parquet. The app only reads these files, so when the
workbook is refreshed (new season, corrections) re-run this script and
commit the new parquet files (update "matches" / "seasons" / "built" in
data/leagues/psl/meta.json too). Any other league is built from its Cricsheet
zip instead: Admin → Add a league, or tools/build_league.py.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "leagues" / "psl"

# sheet name -> (output file, header row index (0-based), first column letter, last column letter)
SHEETS = {
    "Ball Data":       ("ball",          0, None),
    "Match Data":      ("matches",       0, None),
    "Team Match Data": ("team_matches",  0, None),
    "Batting Innings": ("bat_inns",      0, None),
    "Bowling Innings": ("bowl_inns",     0, None),
    "Player Seasons":  ("player_seasons", 0, None),
    "Pair Seasons":    ("pair_seasons",  0, None),
    "Lists":           ("lists",         0, None),
    "Players":         ("players",      12, "B:U"),
}


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, [c for c in df.columns if not c.startswith("Unnamed")]]
    for c in df.columns:
        if df[c].dtype == object:
            kinds = set(type(v) for v in df[c].dropna())
            if kinds - {str}:
                # mixed text/number columns: keep numbers numeric when the column is mostly numeric
                num = pd.to_numeric(df[c], errors="coerce")
                text_vals = df[c].dropna().map(lambda v: isinstance(v, str) and v.strip() != "")
                if text_vals.sum() == 0:
                    df[c] = num
                else:
                    df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
            else:
                df[c] = df[c].replace({"": None})
    return df


def build_partnerships(zip_path: Path) -> None:
    """Batting partnerships from the raw Cricsheet zip (the workbook's ball
    data has no non-striker column). Super overs are excluded."""
    import zipfile
    frames = []
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.endswith(".csv") and not n.endswith("_info.csv"):
                frames.append(pd.read_csv(z.open(n), dtype={"ball": str},
                                          usecols=["match_id", "innings", "ball", "batting_team", "bowling_team",
                                                   "striker", "non_striker", "runs_off_bat", "extras", "wides",
                                                   "noballs", "player_dismissed"]))
    b = pd.concat(frames, ignore_index=True)
    b = b[b["innings"].isin([1, 2])].copy()
    b["wides"] = b["wides"].fillna(0)
    b["noballs"] = b["noballs"].fillna(0)
    b["legal_faced"] = (b["wides"] == 0).astype(int)        # batters face no-balls, not wides
    b["runs"] = b["runs_off_bat"].fillna(0) + b["extras"].fillna(0)
    b["out"] = b["player_dismissed"].notna().astype(int)
    b["pair"] = [" & ".join(sorted((s, n))) for s, n in zip(b["striker"], b["non_striker"])]
    b = b.reset_index(drop=True)
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
        "Runs": g["runs"].sum().astype(int), "Balls": g["legal_faced"].sum().astype(int),
        "Unbroken": (g["out"].last() == 0).astype(int),
    })
    bat = b.groupby(["pid", "striker"])["runs_off_bat"].sum().unstack(fill_value=0)
    a_b = part["Pair"].str.split(" & ", expand=True)
    part["Batter 1"], part["Batter 2"] = a_b[0], a_b[1]
    part["Batter 1 Runs"] = [int(bat.at[i, p]) if p in bat.columns else 0 for i, p in zip(part.index, part["Batter 1"])]
    part["Batter 2 Runs"] = [int(bat.at[i, p]) if p in bat.columns else 0 for i, p in zip(part.index, part["Batter 2"])]
    m = pd.read_parquet(OUT / "matches.parquet")[["Match ID", "Season", "Date", "Venue"]]
    part = part.merge(m, on="Match ID", how="left")
    part = part[part["Season"].notna()].reset_index(drop=True)
    part["Season"] = part["Season"].astype(int)
    part.to_parquet(OUT / "partnerships.parquet", index=False, compression="zstd")
    print(f"partnerships     -> partnerships.parquet  {part.shape}")


def main(path: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sheet, (name, header, cols) in SHEETS.items():
        df = pd.read_excel(path, sheet_name=sheet, header=header, usecols=cols, engine="openpyxl")
        df = _clean(df)
        if name == "players":
            df = df[df["Player"].notna() & ~df["Player"].astype(str).str.startswith("PSL Analytics")]
        df.to_parquet(OUT / f"{name}.parquet", index=False, compression="zstd")
        print(f"{sheet:16s} -> {name}.parquet  {df.shape}")
    zips = sorted((ROOT / "raw").glob("psl_male_csv2*.zip")) + sorted((ROOT / "data").glob("psl_male_csv2*.zip"))
    if zips:
        build_partnerships(zips[-1])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "PSL_Analytics_Workbook.xlsx")
