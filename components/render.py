"""
Block → Streamlit. Every analysis on every page goes through render_block():
heading + PNG button, takeaway / note, then KPIs, chart and/or the tinted table.
"""
from __future__ import annotations

import functools
import importlib

import pandas as pd
import streamlit as st

from analytics import data as d
from analytics import flags
from analytics.blocks import Block
from components import theme as ui
from components.png import block_png
from components.styling import (display_strings, formats, normalize, numeric_cols, row_flags, sentence_case,
                                tint_matrix)

ROW_H, HEAD_H = 35, 38

_COLOR_TOKENS = {"amber": "AMBER", "sky": "SKY", "red": "RED", "violet": "VIOLET", "green": "GREEN"}


def _color(name: str | None) -> str:
    """A chart colour by name, in the current mode's palette."""
    t = ui.tokens()
    return t[_COLOR_TOKENS.get(name or "amber", "AMBER")]


# ── data ────────────────────────────────────────────────────────────────────
def blocks_for(module: str, span: tuple[int, int], filters: tuple = ()) -> list[Block]:
    """A page's Blocks for the current league, without what its data can't support."""
    lg = d.current()
    return _blocks(module, tuple(span), tuple(filters), lg.key, lg.flags(), lg)


@st.cache_data(show_spinner=False, max_entries=256)
def _blocks(module: str, span: tuple[int, int], filters: tuple, league_key: str, league_flags: tuple,
            _league: d.League) -> list[Block]:
    # league_key / league_flags are the cache key; _league (not hashed) is the league itself.
    mod = importlib.import_module(f"analytics.{module}")
    with d.using(_league):
        blocks = mod.build(span, **dict(filters)) if filters else mod.build(span)
        return flags.apply(blocks, _league)


def span_label(span, league: d.League | None = None) -> str:
    lo, hi = min(span), max(span)
    short = (league or d.current()).short
    return f"{short} {lo}" if lo == hi else f"{short} {lo}–{hi}"


# ── table ───────────────────────────────────────────────────────────────────
def _styler(block: Block, df: pd.DataFrame):
    palette = ui.TINT
    bg = tint_matrix(block, df, palette)
    muted, bold = row_flags(block, df)

    if block.labels is not None:
        shown = display_strings(block, df)
        sty = shown.style
    else:
        shown = df
        sty = df.style.format(formats(block, df), na_rep="—")

    css = pd.DataFrame("", index=df.index, columns=df.columns, dtype=object)
    for c in df.columns:
        col_bg = bg[c]
        css[c] = [f"background-color: {v};" if v else "" for v in col_bg.tolist()]
    for c in getattr(block, "muted_cols", []) or []:
        if c in css.columns:
            css[c] = f"color: {palette['muted_ink']}; background-color: {palette['muted_bg']};"
    for i in muted:
        css.loc[i, :] = f"color: {palette['muted_ink']}; background-color: {palette['muted_bg']};"
    for i in bold:
        css.loc[i, :] = css.loc[i, :].astype(str) + " font-weight: 700;"
    sty = sty.apply(lambda _: css, axis=None)
    return sty, shown


def _column_config(block: Block, df: pd.DataFrame, shown: pd.DataFrame) -> dict:
    cfg = {}
    if block.labels is None:
        for c in block.bars:
            if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
                s = pd.to_numeric(df[c], errors="coerce")
                f = (block.fmt.get(c) or "{:,.1f}")
                printf = "%.0f" if ".0f" in f else ("%.2f" if ".2f" in f else "%.1f")
                cfg[c] = st.column_config.ProgressColumn(
                    str(c), min_value=float(min(0, s.min() if s.notna().any() else 0)),
                    max_value=float(s.max() if s.notna().any() and s.max() > 0 else 1), format=printf)
    # Keep the row's name in view when the table scrolls sideways (phones, wide tables):
    # pin a leading "#"/rank column and the first text column among the first three.
    cols = list(df.columns)
    if len(cols) > 5:
        if str(cols[0]) in ("#", "Rank") and cols[0] not in cfg:
            cfg[cols[0]] = st.column_config.Column(str(cols[0]), pinned=True)
        for c in cols[:3]:
            if c not in cfg and not pd.api.types.is_numeric_dtype(df[c]):
                cfg[c] = st.column_config.Column(str(c), pinned=True)
                break
    return cfg


def render_table(block: Block):
    df = normalize(block.df)
    if df is None:
        return
    if df.empty:
        st.info("Nothing to show for this selection. Widen the season span or relax a filter.")
        return
    sty, shown = _styler(block, df)
    n = len(df)
    height = None
    if n > 10:
        height = block.height or (720 if n > 60 else HEAD_H + ROW_H * min(n, 15) + 3)
    kw = dict(width="stretch", hide_index=block.hide_index, column_config=_column_config(block, df, shown),
              placeholder="—")
    if height:
        kw["height"] = height
    st.dataframe(sty, **kw)


# ── chart ───────────────────────────────────────────────────────────────────
def chart_figure(spec: dict, df: pd.DataFrame | None):
    data = spec.get("data")
    data = df if data is None else data
    if data is None or len(data) == 0:
        return None
    kind = spec.get("type", "bar")
    x, y = spec.get("x"), spec.get("y")
    title = spec.get("title")
    labels = spec.get("labels")
    color = _color(spec.get("color"))
    if kind in ("bar", "hbar") and not isinstance(y, (list, tuple)):
        return ui.bar(data, x, y, title=title, color=color, horizontal=kind == "hbar", labels=labels,
                      colors=spec.get("bar_colors"))
    ys = list(y) if isinstance(y, (list, tuple)) else [y]
    # colour names ("amber", "sky", …) follow the current theme; hex values pass through
    colors = [_color(c) if c in _COLOR_TOKENS else c for c in spec["colors"]] if spec.get("colors") else None
    if kind == "line":
        return ui.multi_line(data, x, ys, title=title, labels=labels, colors=colors,
                             categorical_x=spec.get("categorical_x", True))
    if kind in ("grouped", "stacked", "bar", "hbar"):
        return ui.grouped_bar(data, x, ys, title=title, labels=labels, colors=colors,
                              horizontal=kind == "hbar", barmode="stack" if kind == "stacked" else "group")
    if kind == "heatmap":
        vals = data.set_index(x) if x and x in data.columns else data
        vals = vals.select_dtypes("number")
        return ui.heatmap(vals, title=title, good=spec.get("good", "high"), center=spec.get("center"))
    return None


# ── KPIs ────────────────────────────────────────────────────────────────────
def render_kpis(block: Block):
    if not block.kpis:
        return
    cells = "".join(
        f'<div class="wz-cell"><div class="wz-num wz-num-sm">{ui._e(v)}</div>'
        f'<div class="wz-lbl">{ui._e(sentence_case(l))}</div>'
        + (f'<div class="wz-sublbl">{ui._e(s)}</div>' if s else "") + "</div>"
        for l, v, s in block.kpis)
    grid = " wz-board-4" if len(block.kpis) == 8 else ""      # 8 numbers: two rows of four
    st.markdown(f'<div class="wz-board wz-board-kpi{grid}">{cells}</div>', unsafe_allow_html=True)


# ── block ───────────────────────────────────────────────────────────────────
def render_block(block: Block, span) -> None:
    with st.container(key=f"bh_{block.key}"):
        head, btn = st.columns([8, 1.3], vertical_alignment="bottom")
    with head:
        st.subheader(block.title, anchor=block.key)
    with btn:
        if block.kind != "text":
            st.download_button(
              "PNG", data=functools.partial(_png_bytes, block, span_label(span)),
              file_name=f"the-18th-yard-{d.current().slug}-{block.key}-{min(span)}-{max(span)}.png",
              mime="image/png",
              key=f"png_{block.key}", on_click="ignore", icon=":material/download:", width="stretch",
              help="Download this analysis as an image",
            )
    if block.finding:
        st.markdown(f'<p class="wz-finding">{block.finding}</p>', unsafe_allow_html=True)
    if block.note:
        st.caption(block.note)

    if block.kind == "text" and block.text:
        st.markdown(block.text)
    if block.kind == "kpis":
        render_kpis(block)

    fig = chart_figure(block.chart, block.df) if block.chart else None
    has_table = block.kind in ("table", "matrix") and block.df is not None
    small = has_table and len(block.df) <= 12 and len(block.df.columns) <= 7
    if fig is not None and has_table and small:
        left, right = st.columns([1, 1], gap="medium")
        with left:
            render_table(block)
        with right:
            ui.show(fig)
    else:
        if fig is not None:
            ui.show(fig)
        if has_table:
            render_table(block)


def _png_bytes(block: Block, label: str) -> bytes:
    return block_png(block, label)


def render_blocks(blocks: list[Block], span, toc: bool = True) -> None:
    if toc and len(blocks) > 3:
        links = " ".join(f'<a class="wz-toc" href="#{b.key}" target="_self">{ui._e(_short(b.title))}</a>'
                         for b in blocks)
        st.markdown(f'<nav class="wz-tocbar">{links}</nav>', unsafe_allow_html=True)
    for i, b in enumerate(blocks):
        if i:
            st.markdown('<div class="wz-gap"></div>', unsafe_allow_html=True)
        render_block(b, span)


def _short(t: str, n: int = 46) -> str:
    t = str(t)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"
