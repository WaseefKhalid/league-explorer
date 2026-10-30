"""Read a Cricsheet CSV2 zip: every `<id>.csv` (deliveries) and `<id>_info.csv` (match info)."""
from __future__ import annotations

import csv
import io
import re
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


_MATCH = re.compile(r"^(\d+)\.csv$")
_INFO = re.compile(r"^(\d+)_info\.csv$")


def read_zip(src) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """Returns (deliveries, infos, people).

    deliveries: every delivery of every match, in file order (super overs included, innings > 2).
    infos: one dict per match with 'match_id' added.
    people: Player name → Cricsheet player_id, from the info registries.

    Only `<id>.csv` / `<id>_info.csv` are read, each match once: a combined file such as
    all_matches.csv, a second copy of the folder or Mac `__MACOSX` files would otherwise count
    every ball twice.
    """
    z = _open(src)
    names = [n for n in z.namelist() if "__MACOSX" not in n and not Path(n).name.startswith("._")]
    match_files, info_files = {}, {}
    for n in sorted(names):
        base = Path(n).name
        if (mm := _MATCH.match(base)):
            match_files.setdefault(int(mm.group(1)), n)
        elif (mi := _INFO.match(base)):
            info_files.setdefault(int(mi.group(1)), n)
    if not info_files:
        raise ValueError("This zip isn't in Cricsheet's CSV2 format (it may be the older \"CSV\" download). "
                         "On cricsheet.org download the league's CSV2 file instead: its name ends in _csv2.zip.")
    if not match_files:
        raise ValueError("No ball-by-ball files (<match id>.csv) found in this zip.")
    infos, frames = [], []
    for mid in sorted(set(match_files) & set(info_files)):
        d = _info(z.read(info_files[mid]).decode("utf-8"))
        d["match_id"] = mid
        infos.append(d)
        df = pd.read_csv(io.BytesIO(z.read(match_files[mid])), dtype={"season": str, "start_date": str})
        df["match_id"] = mid
        frames.append(df)
    if not frames:
        raise ValueError("The zip's ball-by-ball files and match-info files don't belong to the same matches.")
    deliveries = pd.concat(frames, ignore_index=True)
    for c, t in DELIVERY_DTYPES.items():
        if c in deliveries:
            deliveries[c] = deliveries[c].fillna(0).astype(t) if t == "float64" else deliveries[c].astype(t)
    _check_t20(deliveries)
    reg = {}
    for d in infos:
        reg.update(d["registry"])
    people = pd.DataFrame(sorted(reg.items()), columns=["Player", "player_id"])
    return deliveries, infos, people


def _check_t20(dl: pd.DataFrame) -> None:
    """Stop early on data that isn't 20-over cricket (or has repeated balls): every number would be wrong."""
    main = dl[dl["innings"] <= 2]
    legal = main[(main["wides"] == 0) & (main["noballs"] == 0)]
    per_inns = legal.groupby(["match_id", "innings"]).size()
    over = per_inns[per_inns > 126]
    if len(over):
        mid, inns = over.index[0]
        raise ValueError(f"{len(over)} innings have more than 20 overs of legal balls (e.g. match {mid}, innings "
                         f"{inns}: {over.iloc[0]} balls). The site is built for T20 leagues, and this usually means "
                         "the zip isn't a T20 competition or has the same balls in it twice.")
