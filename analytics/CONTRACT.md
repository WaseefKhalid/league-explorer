# Analytics contract

The Streamlit site rebuilds every analysis in the **PSL Analytics Workbook**
(the spec) from the workbook's own data, so every number matches Excel.

## Files you can use

| What | Where |
|---|---|
| Data tables (parquet, workbook column headers as column names) | `analytics/data.py` → `ball()`, `matches()`, `team_matches()`, `bat_inns()`, `bowl_inns()`, `player_seasons()`, `pair_seasons()`, `players()`, `lists()`; helpers `in_span()`, `safe_div()`, constants `PHASES`, `BOWL_TYPES`, `TYPE_SHORT`, `HANDS` |
| Output type | `analytics/blocks.py` → `Block` (read its comments carefully) |
| Workbook cell values / formulas / number formats (instant) | `tools/xlcheck.py` → `grid(sheet, "B10:X20")`, `grid(..., formulas=True)`, `grid(..., formulas="numfmt")`, `cell(sheet, "C8")` |
| Text dump of every sheet (values + formulas, one line per row) | `/tmp/claude-0/-home-claude/f73a253e-1e80-5731-b966-e39e9f460305/scratchpad/xl/sheets/<Sheet_Name>.txt` (grep it) |
| Named ranges → sheet columns (+ header) | `analytics/NAMED_RANGES.txt` (e.g. `ps_runs` = Player Seasons "Runs", `bd_*` = Ball Data, `md_*` = Match Data, `tm_*` = Team Match Data) |
| Conditional formatting rules (tints) | `analytics/CF_RULES.txt` — green fill FFCDEBD6 = good, red FFF8D5DC = bad, yellow FFFFEFC1 = middle, grey font = muted (outside span) |
| Workbook charts | Seasons: "Average first-innings score" (line, J10:J20) and "Run rate by phase" (lines L:O rows 10–20); Teams: "Win % in the selected span" (bar H9:H16); Venues: "Average first-innings score — selected span" (bar G10:G16); Phases: "Runs per over, over by over" (lines I26:I45 v D26:D45) |
| Calc helper sheet (span-aware per-player sums, keys) | `grid("Calc", ...)` and the dump `Calc.txt` |

Run Python from the repo root: `cd /home/claude/waseefkhalid/cricsheet && python3 ...`
(`sys.path` must include the repo root; `import analytics.data as d`).

## What to write

One module per workbook sheet, `analytics/<module>.py`:

```python
def build(span: tuple[int, int]) -> list[Block]: ...
```

Explorer sheets (they have extra dropdowns) also expose:

```python
FILTERS: list[str]                      # keyword names in dropdown order
def filter_options(span) -> dict[str, list]   # choices per filter; "All" first where the workbook has "All"
DEFAULTS: dict[str, object]             # the values selected in the saved workbook (used for validation)
def build(span, **filters) -> list[Block]
```

Rules:

1. **Same to same.** Every section of the sheet becomes one Block (two if a
   section really holds two separate tables). Keep the workbook's section
   titles, subtitles/how-to-read notes, column headers, row order, sort
   order, tie-breaks, top-N limits, minimum-ball thresholds and footnotes.
   Static "finding" headlines (Key Insights) go in `finding` or `title`.
   Text that a workbook formula builds dynamically must be built
   dynamically too.
2. **Span.** `span` replaces the sheet's Seasons box (C5/E5). Everything the
   workbook recalculates for the span must recalculate. Rows the workbook
   greys out for seasons outside the span → `muted_rows`; "Selected span" /
   "League" style summary rows → `bold_rows`.
3. **Numbers stay numbers** in `df`; set `fmt` for every numeric column from
   the workbook's number format (`grid(..., formulas="numfmt")`):
   `0` → `"{:,.0f}"`, `0.0` → `"{:,.1f}"`, `0.00` → `"{:,.2f}"`,
   `0%` → `"{:.0%}"`, `0.0%` → `"{:.1%}"` (store fractions for %).
   Grid cells that Excel shows as text like `"67% (12)"` → put the number in
   `df` (for tinting) and the text in `labels`.
4. **Colours.** Mirror the sheet's conditional formatting with `rules`
   (absolute thresholds; compute relative ones such as
   `AVERAGE(col)*1.03` or `League row*1.05` yourself; a pandas Series
   indexed like `df` is allowed for per-row thresholds). Data bars → `bars`.
   Where the workbook has no rule but the direction is obvious and useful
   (strike rate, economy, win %, impact), add `good_high` / `good_low`.
   Never tint identifiers, counts of balls/matches, or neutral shares.
5. **Index:** use a plain RangeIndex and keep rank/"#" columns as normal
   columns when the workbook shows them (`hide_index=True` is the default).
   Use `muted_rows` / `bold_rows` with the **index labels** of those rows.
6. **Charts:** where the workbook has a chart, add `chart` (see Block). You
   may add one chart to a block where a trend or ranking is clearly easier
   to read as a picture; don't add charts that just repeat a tiny table.
7. **Pure pandas, fast.** No Streamlit imports. Vectorised groupbys only (no
   Python loops over balls). Target: `build()` < 300 ms for the full span
   (< 500 ms for explorers) after data is loaded. Never mutate frames from
   `analytics.data` (filter, then `.copy()`).
8. **Robust.** `build()` must work for any span (single season, e.g.
   `(2026, 2026)`, early spans like `(2016, 2017)`) and any filter combo,
   including ones that leave no data — return the Block with an empty `df`
   (same columns) rather than raising.
9. **Validate.** Write `tests/check_<module>.py` that runs `build((2016, 2026))`
   (explorers: with `DEFAULTS`) and compares **every cell** of every table
   with the workbook range (`tools/xlcheck.grid`): text exact, numbers equal
   after rounding to the displayed precision. Print a per-block PASS/FAIL
   summary and the first few mismatches. Fix your code until everything
   passes. If something genuinely cannot match (a workbook quirk), keep the
   workbook's behaviour where possible; otherwise document it.
   Also run `build()` for `(2016, 2016)`, `(2020, 2022)`, `(2026, 2026)`
   (and several filter combos for explorers) to prove no exceptions.
10. Only create/edit your own `analytics/<module>.py` and
    `tests/check_<module>.py` files. Don't edit `data.py`, `blocks.py`,
    `tools/`, or other agents' modules. Copy small helpers into your module
    if you need them.

## Leagues (League Explorer)

The same modules now serve every league in `data/leagues/<slug>/`. Rules for any new code:

* Read data only through `analytics.data` (`d.ball()`, `d.load(name)`, `d.seasons()`, …): they
  return the **current league's** tables. Never read parquet paths yourself.
* Never cache with `functools.lru_cache` on module-level helpers: use `@d.per_league()` (an
  lru_cache keyed by the current league). Streamlit caches go in `components/` / `views/`
  with the league key as an argument (see `render.blocks_for`).
* No hard-coded seasons, teams, grounds or players. League-wide spans come from
  `d.seasons()` / `d.full_span()`; seasons may have gaps (index by position, not `year - first`).
  Editorial choices for a known league go in `analytics/presets.py` with a data-driven default.
* Analyses that need batting hand / bowling type, overseas / local, host country, home / away or
  fielding are listed in `analytics/flags.py` (by Block key, column or KPI label). Add new ones
  there; `render.blocks_for` hides them for leagues whose `meta.json` flag is false.
* `span` defaults: `build(span=None, …)` → `span = span or d.full_span()`.
