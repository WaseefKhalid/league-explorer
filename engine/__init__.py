"""
League Explorer engine: a Cricsheet CSV2 zip → every table the site uses.

    tables, meta = build_league(zip_bytes_or_path, name="International League T20", short="ILT20")

`tables` keys are file names under data/leagues/<slug>/ (MVP tables under "mvp/<name>"); `meta` is
data/leagues/<slug>/meta.json. See engine/CONTRACT.md.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "registry" / "players_meta.parquet"
OVERRIDES = Path(__file__).resolve().parent / "overrides"

CORE = ["ball", "matches", "team_matches", "bat_inns", "bowl_inns", "partnerships", "pair_seasons"]


def slugify(short: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(short).lower()).strip("-")
    return s or "league"


def league_overrides(name: str, short: str) -> dict:
    """Built-in settings for a known league (e.g. the PSL's workbook names and home grounds)."""
    for f in OVERRIDES.glob("*.json"):
        ov = json.loads(f.read_text())
        if slugify(ov.get("short", "")) == slugify(short) or ov.get("name", "").lower() == str(name).lower():
            return ov
    return {}


def _share_known(s: pd.Series) -> float:
    s = s.astype("string")
    return float((s.notna() & (s != "Unknown")).mean()) if len(s) else 0.0


def build_league(src, name: str, short: str, overrides: dict | None = None,
                 progress=None) -> tuple[dict[str, pd.DataFrame], dict]:
    """Build every table for one league. `progress(fraction, text)` is called as steps finish."""
    from engine.cricsheet import read_zip
    from engine.core import build_core
    from engine.impact import add_impact
    from engine.players import build_player_tables

    def step(f, text):
        if progress:
            progress(f, text)

    ov = {**league_overrides(name, short), **(overrides or {})}
    step(0.05, "Reading the zip")
    dl, infos, _people = read_zip(src)
    registry = pd.read_parquet(REGISTRY) if REGISTRY.exists() else None
    step(0.15, "Matches, balls and innings")
    core = build_core(dl, infos, registry=registry, overrides=ov)
    people, home_country = core.pop("_people"), core.pop("_home_country")
    core.pop("_deliveries", None)
    step(0.45, "Impact model")
    # player totals add up the unrounded impacts (as the workbook did); the ball table keeps 3 decimals
    core["ball"] = add_impact(core["ball"], core["matches"], decimals=None)
    step(0.6, "Player seasons")
    players = build_player_tables(core, people, registry, home_country=home_country, infos=infos)
    impact_cols = ["Bat Run Impact", "Exp Out Cost", "Out Impact", "Bowl Run Impact", "Bowl Wkt Impact"]
    core["ball"][impact_cols] = core["ball"][impact_cols].round(3)
    for t in ("players", "player_seasons"):        # sums of unrounded impacts: store 3 decimals
        df = players[t]
        cols = [c for c in df.columns if "impact" in c.lower() and pd.api.types.is_float_dtype(df[c])]
        df[cols] = df[cols].round(3)
    tables = {**core, **players}
    step(0.8, "MVP · impact performances")
    mvp_error = None
    try:
        from engine.mvp import build_mvp
        mvp = build_mvp(tables, people, infos=infos)   # team sheets: every XI appearance counts
    except Exception as e:      # noqa: BLE001 — an odd league still gets every other page
        mvp, mvp_error = {}, f"{type(e).__name__}: {e}"
    for k, v in mvp.items():
        tables[k if k.startswith("mvp/") else f"mvp/{k}"] = v

    m, b = tables["matches"], tables["ball"]
    teams = pd.unique(m[["Team 1", "Team 2"]].values.ravel())
    homes = tables["team_matches"].groupby("Team")["Home Ground"].agg(lambda s: (s == "Home").any())
    meta = {
        "name": name, "short": short, "slug": slugify(short),
        "seasons": sorted(int(s) for s in m["Season"].unique()),
        "matches": int(len(m)), "first_match": str(m["Date"].min().date()), "last_match": str(m["Date"].max().date()),
        "teams": int(len(teams)), "home_country": home_country,
        "built": date.today().isoformat(),
        "has_hand_type": _share_known(b["Bat Hand"]) >= 0.9 and _share_known(b["Bowler Type"]) >= 0.9,
        "has_origin": _share_known(b["Batter Origin"]) >= 0.9,
        "has_host": _share_known(m["Host"]) >= 0.9 and m["Host"][m["Host"] != "Unknown"].nunique() >= 2,
        "has_home": bool(homes.mean() >= 0.5) if len(homes) else False,
        "has_fielding": bool("Catches" in tables["player_seasons"] and tables["player_seasons"]["Catches"].notna().any()),
    }
    if mvp_error:
        meta["mvp_error"] = mvp_error
    step(1.0, "Done")
    return tables, meta


def bundle(tables: dict[str, pd.DataFrame], meta: dict) -> bytes:
    """A zip with data/leagues/<slug>/... ready to drop into the GitHub repo."""
    slug = meta["slug"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, df in tables.items():
            pb = io.BytesIO()
            df.to_parquet(pb, index=False)
            z.writestr(f"data/leagues/{slug}/{k}.parquet", pb.getvalue())
        z.writestr(f"data/leagues/{slug}/meta.json", json.dumps(meta, indent=1))
    return buf.getvalue()


def save(tables: dict[str, pd.DataFrame], meta: dict, root: Path | None = None) -> Path:
    """Write a built league to data/leagues/<slug>/ (used by tools/build_league.py)."""
    out = (root or ROOT / "data" / "leagues") / meta["slug"]
    (out / "mvp").mkdir(parents=True, exist_ok=True)
    for k, df in tables.items():
        df.to_parquet(out / f"{k}.parquet", index=False)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return out
