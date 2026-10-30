"""
Convert the PSL Players — Impact Performances workbook into the MVP pages' data.

    python tools/build_mvp.py path/to/PSL_All_Players_Impact_Performances.xlsx

Writes data/leagues/psl/mvp/*.parquet. Re-run and commit the files when the workbook is
refreshed. The pages only read these files.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "leagues" / "psl" / "mvp"
DASH = {"–", "-", "—", ""}


def _num(v):
    """Workbook dashes and blanks → NaN; numbers stay numbers."""
    if v is None or (isinstance(v, str) and v.strip() in DASH):
        return np.nan
    return v


def _table(ws, header_row: int, last_row: int | None = None, stop_at_blank: bool = True) -> pd.DataFrame:
    """Rows under a header row, using only the columns that have a header."""
    heads = [(c.column, str(c.value).strip()) for c in ws[header_row] if c.value is not None]
    rows = []
    r = header_row + 1
    end = last_row or ws.max_row
    while r <= end:
        vals = [ws.cell(r, col).value for col, _ in heads]
        if all(v is None for v in vals):
            if stop_at_blank:
                break
        else:
            rows.append(vals)
        r += 1
    return pd.DataFrame(rows, columns=[h for _, h in heads])


def _find(ws, text: str) -> int:
    for row in ws.iter_rows(min_col=1, max_col=1):
        v = row[0].value
        if isinstance(v, str) and v.startswith(text):
            return row[0].row
    raise KeyError(text)


def _to_num(df: pd.DataFrame, cols) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c].map(_num), errors="coerce")
    return df


def _text(df: pd.DataFrame, cols) -> pd.DataFrame:
    def clean(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and v.strip() in DASH):
            return None
        return str(v)
    for c in cols:
        df[c] = df[c].astype(object).map(clean)
    return df


def summary(wb) -> dict[str, pd.DataFrame]:
    ws = wb["Summary"]
    # Definitions (A = what, C = rule)
    defs = []
    for r in range(_find(ws, "WHAT COUNTS") + 1, _find(ws, "AT A GLANCE")):
        a, c = ws.cell(r, 1).value, ws.cell(r, 3).value
        if a:
            defs.append((a, c))
    glance = []
    for r in range(_find(ws, "AT A GLANCE") + 1, _find(ws, "PLAYER SCOREBOARD")):
        for lc, vc in ((1, 4), (7, 10)):
            if ws.cell(r, lc).value:
                glance.append((ws.cell(r, lc).value, ws.cell(r, vc).value))
    board = _table(ws, _find(ws, "PLAYER SCOREBOARD") + 2)
    board = _text(board, ["Highest", "Best"])
    board = _to_num(board, [c for c in board.columns
                            if c not in ("Player", "Team(s) · latest first", "Role", "Seasons", "Highest", "Best")])
    board = board.rename(columns={"Team(s) · latest first": "Team(s)"})
    return {"definitions": pd.DataFrame(defs, columns=["What", "Counts when"]),
            "glance": pd.DataFrame(glance, columns=["Label", "Value"]),
            "scoreboard": board}


def highlights(wb) -> dict[str, pd.DataFrame]:
    ws = wb["Impact Highlights"]
    note = ws.cell(_find(ws, "Spells with 3+"), 1).value
    df = _table(ws, _find(ws, "ALL IMPACT PERFORMANCES") + 2)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Season"] = df["Season"].astype(int)
    df["Rank"] = df["Rank"].astype(int)
    df["Close finish"] = df["Close finish"].fillna("").eq("Close")
    return {"highlights": df, "highlights_note": pd.DataFrame({"note": [note]})}


_HEAD = re.compile(r"^(\d{1,2} \w{3} \d{4}) · (\d{4}) (.+?) · (.+?) v (.+?) · (.+)$")


def knockouts(wb) -> dict[str, pd.DataFrame]:
    ws = wb["Knockout Matches"]
    matches = _table(ws, _find(ws, "THE MATCHES") + 1)
    matches = matches.rename(columns={"Match · batting first v second": "Match"})
    matches["Date"] = pd.to_datetime(matches["Date"])
    matches["Season"] = matches["Stage"].str.slice(0, 4).astype(int)
    matches["Stage only"] = matches["Stage"].str.split(" · ").str[1]

    players = _table(ws, _find(ws, "PLAYER SUMMARY") + 2)
    players = _text(players, ["Runs (balls)", "Highest", "Best", "In the finals"])
    players = _to_num(players, ["Matches", "Strike rate", "Fifties", "Wickets", "Overs", "Runs conceded", "Economy",
                                "Impact innings"])

    # Match by match: a banner row per match, then one row per player
    start = _find(ws, "MATCH BY MATCH") + 2
    heads = [(c.column, str(c.value).strip()) for c in ws[start] if c.value is not None]
    rows, current = [], None
    for r in range(start + 1, ws.max_row + 1):
        a = ws.cell(r, 1).value
        vals = [ws.cell(r, col).value for col, _ in heads]
        if a is None and all(v is None for v in vals):
            continue
        m = _HEAD.match(str(a)) if isinstance(a, str) else None
        if m and all(v is None for v in vals[1:]):
            current = str(a)
            continue
        rows.append([current] + vals)
    cards = pd.DataFrame(rows, columns=["Match"] + [h for _, h in heads])
    cards["Date"] = pd.to_datetime(cards["Match"].str.extract(r"^(\d{1,2} \w{3} \d{4})")[0], format="%d %b %Y")
    cards["Season"] = cards["Match"].str.extract(r" · (\d{4}) ")[0].astype(int)
    cards = _text(cards, ["Runs", "4s / 6s", "Impact"])
    cards = _to_num(cards, ["Balls", "SR", "Overs", "Runs conc.", "Wickets", "Economy"])
    return {"ko_matches": matches, "ko_players": players, "ko_cards": cards}


def close(wb) -> dict[str, pd.DataFrame]:
    ws = wb["Close Finishes"]
    defs = []
    for r in range(_find(ws, "WHAT COUNTS") + 1, _find(ws, "AT A GLANCE")):
        if ws.cell(r, 1).value:
            defs.append((ws.cell(r, 1).value, ws.cell(r, 4).value))
    defs_note = ws.cell(_find(ws, "WHAT COUNTS") + 1, 7).value
    glance = []
    for r in range(_find(ws, "AT A GLANCE") + 1, _find(ws, "TEAM RECORD")):
        if ws.cell(r, 1).value:
            glance.append((ws.cell(r, 1).value, ws.cell(r, 4).value))
    teams = _table(ws, _find(ws, "TEAM RECORD") + 1)
    teams = _to_num(teams, [c for c in teams.columns if c != "Team"])

    prow = _find(ws, "PLAYER SUMMARY")
    players = _table(ws, prow + 2)
    players = _to_num(players, [c for c in players.columns if c not in ("Player", "Team(s)")])
    # The workbook's own green / red cells, kept to check our rule against
    fills = []
    first = prow + 3
    for i in range(len(players)):
        rec = {}
        for col, name in ((6, "Strike rate"), (11, "Economy")):
            f = ws.cell(first + i, col).fill
            rgb = f.fgColor.rgb if f is not None and f.fill_type == "solid" else None
            rec[name] = {"00D7EFE1": "good", "00F6DCD5": "bad"}.get(rgb, "")
        fills.append(rec)
    wb_tints = pd.DataFrame(fills, index=players.index)

    lrow = _find(ws, "THE CLOSE FINISHES")
    matches = _table(ws, lrow + 2)
    matches = matches.rename(columns={"Match · batting first v second": "Match"})
    matches["Date"] = pd.to_datetime(matches["Date"])
    matches["Season"] = matches["Date"].dt.year
    return {"close_definitions": pd.DataFrame(defs, columns=["What", "Close when"]),
            "close_note": pd.DataFrame({"note": [defs_note, ws.cell(prow + 1, 1).value, ws.cell(lrow + 1, 1).value]}),
            "close_glance": pd.DataFrame(glance, columns=["Label", "Value"]).astype({"Value": str}),
            "close_teams": teams, "close_players": players, "close_players_wb_tints": wb_tints,
            "close_matches": matches}


def main(path: str) -> None:
    wb = openpyxl.load_workbook(path, data_only=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {}
    for part in (summary, highlights, knockouts, close):
        tables.update(part(wb))
    for name, df in tables.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        print(f"{name:26s} {len(df):5d} rows  {len(df.columns):2d} cols")
    (OUT / "SOURCE.txt").write_text(f"Built from {Path(path).name} on {datetime.now():%d %b %Y}.\n")


if __name__ == "__main__":
    main(sys.argv[1])
