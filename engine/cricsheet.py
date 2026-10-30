"""Read a Cricsheet CSV2 zip: every `<id>.csv` (deliveries) and `<id>_info.csv` (match info)."""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pandas as pd

DELIVERY_DTYPES = {
    "match_id": "int64", "innings": "int64", "runs_off_bat": "int64", "extras": "int64",
    "wides": "float64", "noballs": "float64", "byes": "float64", "legbyes": "float64", "penalty": "float64",
}


def _open(src) -> zipfile.ZipFile:
    if isinstance(src, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(src))
    if hasattr(src, "read"):
        return zipfile.ZipFile(io.BytesIO(src.read()))
    return zipfile.ZipFile(Path(src))


def _info(text: str) -> dict:
    """One `_info.csv` → dict. Repeated keys become lists; players / registry kept structured."""
    out: dict = {"teams": [], "players": {}, "registry": {}}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[0] != "info":
            continue
        key, vals = row[1], row[2:]
        if key == "team":
            out["teams"].append(vals[0])
        elif key == "player":
            out["players"].setdefault(vals[0], []).append(vals[1])
        elif key == "registry":
            if len(vals) >= 3 and vals[0] == "people":
                out["registry"][vals[1]] = vals[2]
        elif key in ("umpire", "reserve_umpire", "tv_umpire", "match_referee"):
            out.setdefault(key, []).append(vals[0] if vals else None)
        else:
            out[key] = vals[0] if len(vals) == 1 else (vals or None)
    return out


def read_zip(src) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """Returns (deliveries, infos, people).

    deliveries: every delivery of every match, in file order (super overs included, innings > 2).
    infos: one dict per match with 'match_id' added.
    people: Player name → Cricsheet player_id, from the info registries.
    """
    z = _open(src)
    names = z.namelist()
    if not any(Path(n).name.endswith("_info.csv") for n in names):
        raise ValueError("This zip isn't in Cricsheet's CSV2 format (it may be the older \"CSV\" download). "
                         "On cricsheet.org download the league's CSV2 file instead: its name ends in _csv2.zip.")
    infos, frames = [], []
    for n in sorted(names):
        if not n.endswith(".csv"):
            continue
        base = Path(n).name
        if base.endswith("_info.csv"):
            d = _info(z.read(n).decode("utf-8"))
            d["match_id"] = int(base.split("_")[0])
            infos.append(d)
        else:
            df = pd.read_csv(io.BytesIO(z.read(n)), dtype={"season": str, "start_date": str})
            frames.append(df)
    if not frames:
        raise ValueError("No Cricsheet CSV2 delivery files found in this zip.")
    deliveries = pd.concat(frames, ignore_index=True)
    for c, t in DELIVERY_DTYPES.items():
        if c in deliveries:
            deliveries[c] = deliveries[c].fillna(0).astype(t) if t == "float64" else deliveries[c].astype(t)
    reg = {}
    for d in infos:
        reg.update(d["registry"])
    people = pd.DataFrame(sorted(reg.items()), columns=["Player", "player_id"])
    return deliveries, infos, people
