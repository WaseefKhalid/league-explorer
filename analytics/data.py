"""
Data access for every analytics module, for any league.

Each league is a folder data/leagues/<slug>/ holding the tables as parquet
(ball, matches, team_matches, bat_inns, bowl_inns, partnerships,
pair_seasons, player_seasons, players, lists), the MVP tables in mvp/ and a
meta.json (name, short, seasons, matches and the has_* flags; see
engine/CONTRACT.md). A league built on the admin page lives only in that
visitor's session: League.tables holds its DataFrames.

Which league?
-------------
Streamlit serves several visitors at once, each script run in its own
thread, so the league is never a plain module global. app.py calls
set_current() at the top of every run (a threading.local); everything else
asks current(). Every cache is keyed by League.key (per_league below, and
the st.cache_data wrappers in components/ and views/ take the key as an
argument). Code that may run outside the script thread (deferred downloads)
passes the League explicitly: load(name, league) or `with using(league):`.

Rules for callers
-----------------
* Never mutate a frame returned by these loaders (they are cached and
  shared). Filter, then .copy() before adding columns.
* Seasons are calendar years (the year a season ends in); see seasons().
"""
from __future__ import annotations

import functools
import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEAGUES_DIR = ROOT / "data" / "leagues"
DEFAULT_SLUG = "psl"

# meta.json flags: which analyses a league's data can support
FLAGS = ("has_hand_type", "has_origin", "has_host", "has_home", "has_fielding")

PHASES = ["PP", "MO1", "MO2", "Death"]
PHASE_LABELS = {"PP": "PP (1–6)", "MO1": "MO1 (7–10)", "MO2": "MO2 (11–16)", "Death": "Death (17–20)"}
BOWL_TYPES = ["Right-arm pace", "Left-arm pace", "Off-spin", "Leg-spin",
              "Left-arm orthodox", "Left-arm wrist-spin"]
TYPE_SHORT = {"Right-arm pace": "RAP", "Left-arm pace": "LAP", "Off-spin": "OS",
              "Leg-spin": "LS", "Left-arm orthodox": "LAO", "Left-arm wrist-spin": "LWS"}
HANDS = ["RHB", "LHB"]

# Metadata Cricsheet doesn't carry is "Unknown" (or NaN) in a league's tables.
# Blanks become "Unknown" on load so the explorers' "All" (= any non-blank
# value, like the workbook's SUMIFS "*") still matches every ball. The PSL
# has no blanks in these columns, so its tables load unchanged.
_UNKNOWN_COLS = {
    "ball": ["Host", "Bat Hand", "Bowler Type", "Pace/Spin", "Batter Origin", "Bowler Origin", "Pair"],
    "bat_inns": ["Host", "Bat Hand"],
    "bowl_inns": ["Host", "Bowler Type"],
    "team_matches": ["Host", "Home Ground"],
    "matches": ["Host"],
    "player_seasons": ["Origin", "Hand", "Bowl Type"],
}


# ── leagues ─────────────────────────────────────────────────────────────────
@dataclass(eq=False)
class League:
    slug: str
    meta: dict
    tables: dict[str, pd.DataFrame] | None = None   # in memory (admin build); None = on disk
    token: str = ""                                  # tells in-memory builds (and disk versions) apart
    path: Path = field(default=None)                 # type: ignore[assignment]

    def __post_init__(self):
        if self.path is None:
            self.path = LEAGUES_DIR / self.slug

    @property
    def key(self) -> str:
        """Cache key: unique per league *and* per version of its data."""
        return f"{self.slug}@{self.token}" if self.tables is not None else f"{self.slug}#{self.token}"

    @property
    def in_memory(self) -> bool:
        return self.tables is not None

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.slug.upper())

    @property
    def short(self) -> str:
        return str(self.meta.get("short") or self.slug.upper())

    @property
    def has_mvp(self) -> bool:
        """The MVP tables exist (a build whose MVP step failed still gets every other page)."""
        if self.tables is not None:
            return "mvp/scoreboard" in self.tables
        return (self.path / "mvp" / "scoreboard.parquet").is_file()

    def has(self, flag: str) -> bool:
        """A missing flag counts as False: hide what the data may not support."""
        return bool(self.meta.get(flag, False))

    def flags(self) -> tuple[bool, ...]:
        return tuple(self.has(f) for f in FLAGS)


def _meta_files() -> tuple[tuple[str, int], ...]:
    """(folder name, meta.json mtime) for every league folder on disk."""
    out = []
    try:
        for p in sorted(LEAGUES_DIR.iterdir()):
            f = p / "meta.json"
            if p.is_dir() and f.is_file():
                out.append((p.name, f.stat().st_mtime_ns))
    except FileNotFoundError:
        pass
    return tuple(out)


@lru_cache(maxsize=64)
def _disk_league(slug: str, mtime: int) -> League:
    meta = json.loads((LEAGUES_DIR / slug / "meta.json").read_text(encoding="utf-8"))
    meta = dict(meta, slug=slug)          # the folder name is the slug
    return League(slug=slug, meta=meta, token=str(mtime))


def disk_leagues() -> dict[str, League]:
    """Every folder in data/leagues/ with a meta.json, by slug."""
    out = {}
    for slug, mtime in _meta_files():
        try:
            out[slug] = _disk_league(slug, mtime)
        except (OSError, ValueError):     # unreadable / half-written meta.json: skip it
            continue
    return out


def memory_league(tables: dict[str, pd.DataFrame], meta: dict) -> League:
    """A league built in this session (admin page): the engine's tables stay in memory, as built."""
    slug = str(meta.get("slug") or meta.get("short") or "league").lower()
    return League(slug=slug, meta=dict(meta, slug=slug), tables=dict(tables), token=uuid.uuid4().hex[:12])


def default_league() -> League:
    leagues = disk_leagues()
    if DEFAULT_SLUG in leagues:
        return leagues[DEFAULT_SLUG]
    if leagues:
        return next(iter(leagues.values()))
    raise FileNotFoundError(f"No league found in {LEAGUES_DIR} (each league needs a meta.json).")


# ── the current league (per thread) ─────────────────────────────────────────
_local = threading.local()


def current() -> League:
    lg = getattr(_local, "league", None)
    return lg if lg is not None else default_league()


def set_current(league: League) -> None:
    _local.league = league


@contextmanager
def using(league: League):
    prev = getattr(_local, "league", None)
    _local.league = league
    try:
        yield league
    finally:
        _local.league = prev


def meta() -> dict:
    return current().meta


def has(flag: str) -> bool:
    return current().has(flag)


def short() -> str:
    return current().short


def per_league(maxsize: int = 16):
    """lru_cache whose key starts with the current league's key."""
    def deco(fn):
        @lru_cache(maxsize=maxsize)
        def _cached(key, args, kwargs):
            return fn(*args, **dict(kwargs))

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return _cached(current().key, args, tuple(sorted(kwargs.items())))

        wrapper.cache_clear = _cached.cache_clear
        return wrapper
    return deco


# ── tables ──────────────────────────────────────────────────────────────────
def _normalise(name: str, df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in _UNKNOWN_COLS.get(name, []) if c in df.columns and df[c].isna().any()]
    if not cols:
        return df
    df = df.copy()
    for c in cols:
        df[c] = df[c].astype(object).where(df[c].notna(), "Unknown")
    return df


@lru_cache(maxsize=None)            # bounded by leagues on disk x tables
def _read(key: str, path: str, name: str) -> pd.DataFrame:
    return _normalise(name, pd.read_parquet(path))


@lru_cache(maxsize=64)              # keyed by the League object itself (in-memory leagues)
def _memory_table(league: League, name: str) -> pd.DataFrame:
    return _normalise(name, league.tables[name])


def load(name: str, league: League | None = None) -> pd.DataFrame:
    """name: ball | matches | team_matches | bat_inns | bowl_inns | partnerships |
    player_seasons | pair_seasons | players | lists | mvp/<table>"""
    lg = league or current()
    if lg.tables is not None:
        if name not in lg.tables:
            raise FileNotFoundError(f"{lg.slug}: no table {name!r}")
        return _memory_table(lg, name)
    return _read(lg.key, str(lg.path / f"{name}.parquet"), name)


def ball() -> pd.DataFrame:            return load("ball")
def matches() -> pd.DataFrame:         return load("matches")
def team_matches() -> pd.DataFrame:    return load("team_matches")
def bat_inns() -> pd.DataFrame:        return load("bat_inns")
def bowl_inns() -> pd.DataFrame:       return load("bowl_inns")
def player_seasons() -> pd.DataFrame:  return load("player_seasons")
def pair_seasons() -> pd.DataFrame:    return load("pair_seasons")
def players() -> pd.DataFrame:         return load("players")
def lists() -> pd.DataFrame:           return load("lists")


@per_league()
def seasons() -> tuple[int, ...]:
    return tuple(sorted(int(s) for s in matches()["Season"].dropna().unique()))


def full_span() -> tuple[int, int]:
    s = seasons()
    return (s[0], s[-1])


def edition(season: int) -> int:
    """1 for the league's first season, 2 for the next one in the data, …"""
    s = seasons()
    return s.index(season) + 1 if season in s else 0


def in_span(df: pd.DataFrame, span: tuple[int, int], col: str = "Season") -> pd.DataFrame:
    lo, hi = min(span), max(span)
    return df[(df[col] >= lo) & (df[col] <= hi)]


def safe_div(a, b, scale: float = 1.0):
    """a/b*scale, NaN where b == 0 (works on scalars and Series)."""
    if isinstance(b, pd.Series) or isinstance(a, pd.Series):
        b = pd.Series(b) if not isinstance(b, pd.Series) else b
        return (a * scale) / b.where(b != 0)
    return (a * scale / b) if b else float("nan")
