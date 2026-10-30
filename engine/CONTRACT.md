# League Explorer engine — contract

Goal: turn ANY Cricsheet T20 league zip (CSV2 format, e.g. `psl_male_csv2.zip`,
`ilt20_male_csv2.zip`) into the exact data tables the website already uses for
the PSL, so every page works for every league.

The PSL is the answer key: `data/leagues/psl/*.parquet` (and `data/leagues/psl/mvp/*.parquet`)
are the validated outputs of the original PSL workbook. Building from
`raw/psl_male_csv2.zip` must reproduce them. Aim for exact equality; where a value
genuinely cannot be derived from the zip, say so in a comment and in your report.

Run Python from the repo root: `cd /home/claude/le-build && python3 ...`
Never modify files outside your own area (listed in your brief).

## Inputs available

- `raw/psl_male_csv2.zip`           — Cricsheet CSV2 zip: `<id>.csv` (deliveries) + `<id>_info.csv` (match info)
- `raw/PSL_All_Players_Impact_Performances.xlsx` — the MVP workbook (answer key for the MVP tables)
- `data/leagues/psl/*.parquet`      — answer key for core + player tables (from the PSL workbook)
- `data/leagues/psl/mvp/*.parquet`  — answer key for the MVP tables (`tools/build_mvp.py` output)
- `data/registry/players_meta.parquet` — player metadata keyed by Cricsheet `player_id`
  (Bat Hand, Bowling Style, Bowling Type, Country, Role (Cricinfo), Full Name). Known for PSL players only;
  other leagues get whatever overlaps, everyone else is "Unknown".

## Pipeline (engine/__init__.py exposes `build_league`)

```
engine/cricsheet.py  read_zip(src) -> deliveries DataFrame, infos list[dict], people DataFrame   [lead]
engine/core.py       build_core(...) -> ball (without impact cols), matches, team_matches,
                     bat_inns, bowl_inns, partnerships, pair_seasons                               [lead]
engine/impact.py     add_impact(ball, matches) -> ball + 5 impact columns                         [agent A]
engine/players.py    build_player_tables(tables, people, registry) -> player_seasons, players, lists  [agent C]
engine/mvp.py        build_mvp(tables, people) -> the MVP tables                                   [agent B]
engine/__init__.py   build_league(src, name, short, overrides=None) -> (tables: dict[str, DataFrame], meta: dict)  [lead]
```

`tables` keys = file names in `data/leagues/<slug>/` (`ball`, `matches`, `team_matches`, `bat_inns`,
`bowl_inns`, `partnerships`, `pair_seasons`, `player_seasons`, `players`, `lists`) plus `mvp/<name>` keys
for the MVP tables (`mvp/scoreboard`, `mvp/highlights`, ...).

`people`: DataFrame `Player` (name as used in deliveries), `player_id` (Cricsheet registry id).

## Conventions (all leagues)

- Season = calendar year of the match date's season label end: Cricsheet season `2016/17` → 2017,
  `2024` → 2024 (PSL: equals the calendar year of every match).
- Phases (T20): PP = overs 1–6, MO1 = 7–10, MO2 = 11–16, Death = 17–20 (Over is 1-based).
- Play-offs: matches without `match_number` in the info file. Per season, ordered by date:
  4 games → Qualifier, Eliminator 1, Eliminator 2, Final; 1 → Final; otherwise Playoff 1..n-1, Final.
  `Match Type` = "League" or "Playoff".
- Super overs are excluded from player and team stats; ties are "Tie (super over)".
- Metadata that Cricsheet does not have (bat hand, bowling type, overseas/local, host country,
  home grounds, fielding) is "Unknown" / NaN unless supplied by the registry or a league override.
  `meta.json` flags tell the site which analyses to show:
  `{"name", "short", "slug", "seasons": [..], "matches": n, "built": "YYYY-MM-DD",
    "has_hand_type": bool, "has_origin": bool, "has_host": bool, "has_home": bool, "has_fielding": bool}`

## Column schemas

Exactly the columns (names, order, dtypes) of the matching `data/leagues/psl/<table>.parquet`.
Read them with `pd.read_parquet(...).dtypes`.
