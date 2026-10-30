"""
The one output format every analytics function returns.

A page is a list of Blocks. The UI (components/render.py) turns each Block
into a heading, a colour-tinted table and/or chart, and a "Download PNG"
button. Analytics code never formats numbers as strings unless the cell is
genuinely text (e.g. "67% (12)" in a grid) — give numbers + `fmt` instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class Block:
    key: str                          # unique per page, e.g. "ki_01"
    title: str                        # section title as in the workbook
    df: pd.DataFrame | None = None    # the table (numbers stay numeric)
    note: str | None = None           # the grey subtitle / how-to-read line
    finding: str | None = None        # one-sentence takeaway (Key Insights etc.)
    kind: str = "table"               # "table" | "matrix" | "kpis" | "text"

    # ── Tinting: green = good, amber = in between, red = bad ─────────────────
    # 1) Exact traffic-light rules, mirroring the workbook's conditional
    #    formatting. Thresholds are absolute numbers (work out "league
    #    average x 1.03" etc. yourself and pass the number):
    #        rules={"Win %": {"good": (">=", 0.60), "bad": ("<=", 0.45)}}
    #    Cells matching neither get the amber "middle" tint. Use the key
    #    "*" to apply one rule to every numeric cell (grids/matrices).
    #    Per-row thresholds (e.g. "vs the League row"): pass a Series
    #    indexed like df instead of a number.
    rules: dict[str, dict] = field(default_factory=dict)
    # 2) Columns the workbook doesn't tint but where direction is obvious:
    #    soft green/red gradient around the column median (or `center`).
    good_high: list[str] = field(default_factory=list)   # higher is better
    good_low: list[str] = field(default_factory=list)    # lower is better
    center: dict[str, float] = field(default_factory=dict)
    # 3) In-cell bars (the workbook's data bars), e.g. ["Impact"].
    bars: list[str] = field(default_factory=list)
    # 4) Cell-by-cell tints copied from a workbook's own fills: same shape as df,
    #    values "good" | "bad" | "mid" | "" (applied after 1 and 2).
    cell_tints: pd.DataFrame | None = None

    # Display
    fmt: dict[str, str] = field(default_factory=dict)    # column -> Python format, e.g. "{:,.0f}", "{:.1f}", "{:.1%}"
    labels: pd.DataFrame | None = None  # same shape as df: text to show instead of the number (e.g. "67% (12)")
    hide_index: bool = True
    muted_rows: list[Any] = field(default_factory=list)   # index labels shown greyed (e.g. seasons outside span)
    bold_rows: list[Any] = field(default_factory=list)    # index labels shown bold (e.g. "Selected span", "League")
    muted_cols: list[Any] = field(default_factory=list)   # column names shown greyed (e.g. seasons outside span)
    height: int | None = None         # preferred table height in px for long tables

    # kind="kpis": [(label, value, sublabel_or_None), ...] value already a display string
    kpis: list[tuple[str, str, str | None]] = field(default_factory=list)
    text: str | None = None           # kind="text": markdown paragraph(s)

    # Optional chart, rendered with the site's Plotly helpers.
    # {"type": "bar"|"hbar"|"line"|"stacked"|"grouped"|"heatmap",
    #  "x": col, "y": col or [cols], "title": str, "labels": {col: label},
    #  "color": "amber"|"sky"|"red"|"violet"|"green", "data": optional DataFrame (defaults to df)}
    chart: dict | None = None
