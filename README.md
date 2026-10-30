# League Explorer · The 18th Yard

Cricket analytics for any T20 league: every analysis of the PSL Analytics
Workbook, interactive, for the PSL and for any league built from a
[Cricsheet](https://cricsheet.org) zip. One League picker and one season-span
control for the whole site, green / amber / red highlighting and a PNG download
on every analysis.

## Pages

| Menu | Pages |
|---|---|
| Home | The league, headline numbers for the span, what's on the site, the MVP feature, definitions, data notes |
| Insights | Key Insights (up to 18 findings) · Impact · Player of the Match |
| Explorers | Batter · Bowler · Matchup (batter v bowler, team v team) · Team · Venue & Toss |
| League | Season by Season · Teams · Toss & Chasing · Venues · Phases |
| Players | Batting · Best Batting Seasons · Bowling · Best Bowling Seasons · Matchups · Player List |
| More | Records · Raw Data (admin) · Add a league (admin) |
| **MVP** | MVP Scoreboard · Impact Highlights · Knockout Matches · Close Finishes |

## Leagues

Each league is a folder:

```
data/leagues/<slug>/
    ball.parquet  matches.parquet  team_matches.parquet  bat_inns.parquet  bowl_inns.parquet
    partnerships.parquet  pair_seasons.parquet  player_seasons.parquet  players.parquet  lists.parquet
    mvp/*.parquet          the MVP tables
    meta.json              name, short, slug, seasons, matches, built, has_* flags
```

Every folder with a `meta.json` appears in the League picker (top of the sidebar).
The choice follows the visitor from page to page and is in the URL
(`?league=<slug>`), so links open the same league.

`meta.json` flags say what the league's data supports. When one is false, the
analyses that need it are left out (the full list is in `analytics/flags.py`):

| Flag | Needs | Hidden when false |
|---|---|---|
| `has_hand_type` | batting hand, bowling type | hand / type / pace-spin analyses, columns and explorer filters |
| `has_origin` | overseas / local | overseas analyses, country and overseas columns |
| `has_host` | host country | host filters and columns |
| `has_home` | home / away | home advantage |
| `has_fielding` | catches | the catches column |

### Add or refresh a league (admin)

1. Download the league's **CSV2** zip from cricsheet.org (e.g. `ilt20_male_csv2.zip`).
2. Sign in as admin, open **More → Add a league**, upload the zip, give the league a
   name and a short name (optionally its home country) and press **Build**. It opens
   straight away, for you only.
3. **Download data bundle**, unzip it and drag the `data/leagues/<slug>` folder into
   `data/leagues/` on GitHub. Commit: the league is then on the site for everyone.

To refresh a league (new season, corrections), build the newest zip with the same
short name and commit the bundle: it overwrites the old folder. On a computer,
`python tools/build_league.py <zip> "<name>" <SHORT>` does the same.

The PSL keeps its validated workbook data (`tools/build_data.py`,
`tools/build_mvp.py` → `data/leagues/psl/`); its editorial choices (grounds and teams
in Key Insights, season and data notes) are in `analytics/presets.py`.

## How it's built

```
app.py                  entry point: page config, League picker, season slider, top navigation
views/                  page layouts (Home, span pages, explorers, Records, Raw Data, Add a league)
analytics/              pure-pandas analyses, one module per workbook sheet
analytics/data.py       league-aware data access (current league per script thread, per-league caches)
analytics/flags.py      what each meta.json flag hides
analytics/presets.py    editorial choices for known leagues (the PSL)
engine/                 Cricsheet zip → a league's tables (see engine/CONTRACT.md)
components/leagues.py   the League picker (session state + ?league=)
components/theme.py     colours, fonts, CSS, chart helpers (Bright + Dark palettes)
components/theme_switch.py  the Bright / Dark switch in the top bar
components/auth.py      public (view + PNG) and admin (password) access
components/render.py    turns each analysis into heading + tinted table / chart + PNG button
components/png.py       PNG export (matplotlib, same tints as the site)
static/fonts/           self-hosted fonts (OFL)
```

Streamlit serves many visitors at once, each run in its own thread: the league is
set per thread at the top of every run (`analytics.data.set_current`), and every
cache is keyed by the league (`@d.per_league()`, and the league key in each
`st.cache_data` call). Every PSL number was checked cell-for-cell against the
workbook for 2016–2026.

## Theme

Every page has a **Bright / Dark** switch in the top-right corner. First-time
visitors get Bright; the switch remembers each visitor's choice for their next
visit. `.streamlit/config.toml` holds both looks; `components/theme.py` has the
two palettes.

## Access

- **Public** (everyone): every page and every analysis, plus a PNG download on
  each one. No CSV downloads, no Raw Data, no Add a league.
- **Admin**: sign in from **Admin** at the bottom of the sidebar. Adds Raw Data,
  CSV downloads on every table and Add a league. Closing the tab signs out.

The admin password is not in the code. Set it on Streamlit Community Cloud
under **App settings → Secrets**:

```toml
ADMIN_PASSWORD = "choose-a-long-password"
```

Without it, admin sign-in is switched off. Visitors never see tracebacks or code
(`showErrorDetails = "none"` in `.streamlit/config.toml`).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Ball-by-ball data: [Cricsheet](https://cricsheet.org). League Explorer · The 18th Yard ·
waseefkhalid481@gmail.com · [LinkedIn](https://www.linkedin.com/in/waseef-khalid-khan-366951237).
