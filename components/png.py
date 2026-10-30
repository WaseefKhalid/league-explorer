"""
Block → PNG (for the "Download PNG" button on every analysis).

Rendered with matplotlib on a white card in the site's fonts and the same
green / amber / red tints as the web table. Runs only when the button is
clicked (Streamlit's deferred download), so pages stay fast.
"""
from __future__ import annotations

import dataclasses
import html
import io
import logging
import re
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, to_rgba  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analytics.blocks import Block  # noqa: E402
from components.styling import LIGHT, display_strings, normalize, numeric_cols, row_flags, sentence_case, tint_matrix  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
FONT_DIR = Path(__file__).resolve().parents[1] / "static" / "fonts" / "ttf"
for _f in sorted(FONT_DIR.glob("*.ttf")):
    try:
        fm.fontManager.addfont(str(_f))
    except Exception:
        pass
# Family lists give per-glyph fallback (± † → ≤ ≥ come from DejaVu Sans).
_BODY_FAM = ["Instrument Sans", "DejaVu Sans"]
_DISP_FAM = ["Big Shoulders Display", "DejaVu Sans"]
BODY = fm.FontProperties(family=_BODY_FAM, weight=400)
BODY_B = fm.FontProperties(family=_BODY_FAM, weight=600)
DISPLAY = fm.FontProperties(family=_DISP_FAM, weight=800)
DISPLAY7 = fm.FontProperties(family=_DISP_FAM, weight=700)

INK, INK2, MUTED, LINE, PANEL = "#0E1528", "#3D4761", "#667089", "#DFE4EC", "#F6F8FB"
ACCENT_INK, RED_BALL = "#A85A08", "#D6404B"
SERIES = {"amber": "#C47510", "sky": "#2A78D6", "red": "#D6404B", "violet": "#6E56CF", "green": "#1F8C4E"}
ORDER = ["#C47510", "#2A78D6", "#D6404B", "#6E56CF"]
EMAIL = "waseefkhalid481@gmail.com"
PRODUCT = "League Explorer"     # sub-label next to THE 18TH YARD (same as components/theme.PRODUCT)

W = 12.0            # inches
DPI = 170
PAD = 0.45
MAX_ROWS = 30
MAX_COLS = 16


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", "", str(text)))     # findings are HTML
    return text.replace("**", "").replace("__", "").replace("`", "")


def _wrap(text: str, width_in: float, size: float) -> list[str]:
    chars = max(20, int(width_in * 72 / (size * 0.52)))
    lines = []
    for para in _clean(text).split("\n"):
        lines.extend(textwrap.wrap(para, chars) or [""])
    return lines


# ── table geometry ──────────────────────────────────────────────────────────
def _table_layout(block: Block):
    df = normalize(block.df)
    if df is None or df.empty:
        return None
    cols = list(df.columns)
    extra_cols = max(0, len(cols) - MAX_COLS)
    cols = cols[:MAX_COLS]
    sub = df[cols]
    extra_rows = max(0, len(sub) - MAX_ROWS)
    sub = sub.iloc[:MAX_ROWS]
    shown = dataclasses.replace(
        block, df=sub,
        labels=block.labels.reindex(index=sub.index, columns=cols) if block.labels is not None else None)
    text = display_strings(shown, sub)
    tints = tint_matrix(shown, sub, LIGHT)
    muted, bold = row_flags(shown, sub)
    nums = set(numeric_cols(sub))
    # column widths from content length
    lens = []
    for c in cols:
        body = max((len(str(v)) for v in text[c].tolist()), default=1)
        lens.append(max(min(len(str(c)), 22), min(body, 34), 3))
    mcols = set(getattr(block, "muted_cols", []) or [])
    return dict(sub=sub, cols=cols, text=text, tints=tints, muted=muted, bold=bold, mcols=mcols,
                nums=nums, lens=lens, extra_rows=extra_rows, extra_cols=extra_cols, total=len(df))


def _table_height(lay, row_h):
    if lay is None:
        return 0
    return 0.42 + row_h * len(lay["sub"]) + (0.32 if lay["extra_rows"] or lay["extra_cols"] else 0.08)


# ── drawing helpers ─────────────────────────────────────────────────────────
def _draw_table(ax, lay, y0, width, row_h, fs):
    x0 = PAD
    total = sum(lay["lens"])
    widths = [width * l / total for l in lay["lens"]]
    # header
    ax.add_patch(Rectangle((x0, y0), width, 0.42, color=PANEL, lw=0))
    x = x0
    for c, w in zip(lay["cols"], widths):
        num = c in lay["nums"]
        label = str(c)
        max_chars = max(4, int(w * 72 / (fs * 0.55)))
        if len(label) > max_chars:
            label = label[: max_chars - 1] + "…"
        ax.text(x + (w - 0.08 if num else 0.08), y0 + 0.21, label, ha="right" if num else "left",
                va="center", fontproperties=BODY_B, fontsize=fs, color=INK2)
        x += w
    y = y0 + 0.42
    for i, idx in enumerate(lay["sub"].index):
        muted = idx in lay["muted"]
        bold = idx in lay["bold"]
        if muted:
            ax.add_patch(Rectangle((x0, y), width, row_h, color=LIGHT["muted_bg"], lw=0))
        x = x0
        for c, w in zip(lay["cols"], widths):
            bg = lay["tints"].at[idx, c]
            if c in lay["mcols"] and not muted:
                ax.add_patch(Rectangle((x, y), w, row_h, color=LIGHT["muted_bg"], lw=0))
                bg = ""
            if bg and not muted:
                ax.add_patch(Rectangle((x + 0.02, y + 0.03), w - 0.04, row_h - 0.06,
                                       color=to_rgba(_css_to_mpl(bg)), lw=0))
            txt = str(lay["text"].at[idx, c])
            num = c in lay["nums"]
            max_chars = max(4, int(w * 72 / (fs * 0.53)))
            if len(txt) > max_chars:
                txt = txt[: max_chars - 1] + "…"
            ax.text(x + (w - 0.08 if num else 0.08), y + row_h / 2, txt,
                    ha="right" if num else "left", va="center",
                    fontproperties=BODY_B if bold else BODY, fontsize=fs,
                    color=LIGHT["muted_ink"] if (muted or c in lay["mcols"]) else INK)
            x += w
        ax.plot([x0, x0 + width], [y + row_h, y + row_h], color=LINE, lw=0.6)
        y += row_h
    notes = []
    if lay["extra_rows"]:
        notes.append(f"Showing the first {MAX_ROWS} of {lay['total']:,} rows")
    if lay["extra_cols"]:
        notes.append(f"{lay['extra_cols']} more columns on the site")
    if notes:
        ax.text(x0, y + 0.2, ". ".join(notes) + ".", fontproperties=BODY, fontsize=fs - 0.5, color=MUTED, va="center")
    return y


def _css_to_mpl(css: str):
    m = re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", css.replace(" ", ""))
    if m:
        r, g, b, a = m.groups()
        return (int(r) / 255, int(g) / 255, int(b) / 255, float(a))
    return css


def _style_axes(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontproperties(BODY)
        lab.set_fontsize(8.5)
    ax.grid(axis="y", color="#E7EBF2", lw=0.7)
    ax.set_axisbelow(True)


def _draw_chart(fig, spec, df, rect):
    data = spec.get("data")
    data = df if data is None else data
    if data is None or len(data) == 0:
        return
    ax = fig.add_axes(rect)
    kind = spec.get("type", "bar")
    x = spec.get("x")
    ys = spec.get("y")
    ys = ys if isinstance(ys, (list, tuple)) else [ys]
    labels = spec.get("labels") or {}
    color = SERIES.get(spec.get("color", "amber"), ORDER[0])
    colors = [SERIES.get(c, c) for c in spec["colors"]] if spec.get("colors") else ORDER
    if kind == "heatmap":
        vals = data.select_dtypes("number")
        cmap = LinearSegmentedColormap.from_list("rag", ["#C83646", "#F7E3B0", "#1F8C4E"])
        if spec.get("good", "high") == "low":
            cmap = cmap.reversed()
        ax.imshow(vals.values.astype(float), aspect="auto", cmap=cmap)
        ax.set_xticks(range(vals.shape[1]), [str(c) for c in vals.columns])
        ax.set_yticks(range(vals.shape[0]), [str(i) for i in vals.index])
        for (i, j), v in np.ndenumerate(vals.values):
            if pd.notna(v):
                ax.text(j, i, f"{v:.0f}" if abs(v) >= 10 else f"{v:.2f}", ha="center", va="center",
                        fontproperties=BODY, fontsize=7.5, color=INK)
        _style_axes(ax)
        ax.grid(False)
        return
    xs = data[x].astype(str).tolist() if x in data.columns else [str(i) for i in data.index]
    if kind in ("bar", "hbar") and len(ys) == 1:
        y = ys[0]
        vals = pd.to_numeric(data[y], errors="coerce").fillna(0).tolist()
        cols = spec.get("bar_colors") or [color] * len(vals)
        if kind == "hbar":
            ax.barh(xs[::-1], vals[::-1], color=cols[::-1], height=0.62)
            for i, v in enumerate(vals[::-1]):
                ax.text(v, i, f" {v:,.0f}" if abs(v) >= 100 else f" {v:,.1f}", va="center",
                        fontproperties=BODY, fontsize=8, color=INK2)
            ax.grid(axis="x", color="#E7EBF2", lw=0.7)
        else:
            ax.bar(xs, vals, color=cols, width=0.62)
            for i, v in enumerate(vals):
                ax.text(i, v, f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}", ha="center", va="bottom",
                        fontproperties=BODY, fontsize=8, color=INK2)
    elif kind in ("grouped", "stacked", "bar", "hbar"):
        n = len(ys)
        base = np.zeros(len(xs))
        pos = np.arange(len(xs))
        width = 0.8 / (1 if kind == "stacked" else n)
        for k, y in enumerate(ys):
            vals = pd.to_numeric(data[y], errors="coerce").fillna(0).values
            if kind == "stacked":
                ax.bar(pos, vals, bottom=base, color=colors[k % len(colors)], width=0.62, label=labels.get(y, y))
                base = base + vals
            else:
                ax.bar(pos - 0.4 + width * (k + .5), vals, width=width * 0.92, color=colors[k % len(colors)],
                       label=labels.get(y, y))
        ax.set_xticks(pos, xs)
        ax.legend(frameon=False, prop=BODY, fontsize=8, loc="upper left", ncol=min(n, 4))
    else:  # line
        for k, y in enumerate(ys):
            vals = pd.to_numeric(data[y], errors="coerce").values
            c = colors[k % len(colors)] if len(ys) > 1 else color
            ax.plot(xs, vals, color=c, lw=2, marker="o", ms=4.5, label=labels.get(y, y))
        if len(ys) > 1:
            leg = ax.legend(frameon=False, prop=BODY, fontsize=8, loc="best", ncol=min(len(ys), 4))
    if len(xs) > 8 and kind != "hbar" and max(len(s) for s in xs) > 4:
        plt.setp(ax.get_xticklabels(), rotation=40, ha="right")
    _style_axes(ax)
    if spec.get("title"):
        ax.set_title(_clean(spec["title"]), loc="left", fontproperties=BODY_B, fontsize=10.5, color=INK, pad=8)
    _fit_left_labels(fig, ax, rect)


def _fit_left_labels(fig, ax, rect) -> None:
    """Move the plot right far enough that long y labels (team names on
    sideways bars) are not cut off at the image's left edge."""
    renderer = fig.canvas.get_renderer()
    widths = [t.get_window_extent(renderer=renderer).width for t in ax.get_yticklabels() if t.get_text()]
    if not widths:
        return
    need = (max(widths) + 10) / fig.bbox.width      # label + tick padding, as a share of the image width
    left = max(rect[0], PAD / W + need)
    if left > rect[0]:
        ax.set_position([left, rect[1], rect[0] + rect[2] - left, rect[3]])


# ── public ──────────────────────────────────────────────────────────────────
def block_png(block: Block, span_label: str) -> bytes:
    width = W - 2 * PAD
    title_lines = _wrap(block.title, width, 20)
    sub = " ".join(t for t in [_clean(block.finding), _clean(block.note)] if t)
    sub_lines = _wrap(sub, width, 10) if sub else []
    head_h = 0.95 + 0.38 * len(title_lines) + 0.21 * len(sub_lines) + 0.2

    chart_h = 3.6 if block.chart else 0.0
    lay = _table_layout(block) if block.kind in ("table", "matrix") else None
    n_cols = len(lay["cols"]) if lay else 0
    fs = 9.0 if n_cols <= 8 else (8.0 if n_cols <= 12 else 7.0)
    row_h = 0.30 if fs >= 9 else 0.27
    table_h = _table_height(lay, row_h)
    kpi_h = 1.25 * int(np.ceil(len(block.kpis) / 5)) if block.kind == "kpis" and block.kpis else 0
    text_lines = _wrap(block.text, width, 10.5) if block.kind == "text" and block.text else []
    text_h = 0.22 * len(text_lines) + (0.2 if text_lines else 0)
    foot_h = 0.6
    H = head_h + chart_h + (0.25 if chart_h and table_h else 0) + table_h + kpi_h + text_h + foot_h + 0.2

    fig = plt.figure(figsize=(W, H), dpi=DPI)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    # brand row
    ax.add_patch(Circle((PAD + 0.12, 0.42), 0.12, color=RED_BALL, lw=0))
    for dx in (-0.035, 0.012):   # the stitched seam
        ts = np.linspace(-1, 1, 30)
        ax.plot(PAD + 0.12 + dx - 0.035 * (1 - ts ** 2), 0.42 + 0.115 * ts, color="#F4E9D8", lw=0.9,
                ls=(0, (1.2, 1.4)), solid_capstyle="round")
    # THE 18TH YARD, number in the accent colour; each word placed after the last one's measured width
    renderer = fig.canvas.get_renderer()
    x = PAD + 0.32
    for word, colour in (("THE", INK), ("18TH", ACCENT_INK), ("YARD", INK)):
        t = ax.text(x, 0.43, word, fontproperties=DISPLAY, fontsize=15, color=colour, va="center")
        x += t.get_window_extent(renderer=renderer).width / DPI + 0.07
    ax.text(x + 0.1, 0.44, PRODUCT, fontproperties=BODY, fontsize=9.5, color=MUTED, va="center")
    ax.text(W - PAD, 0.44, span_label, fontproperties=BODY_B, fontsize=9.5, color=ACCENT_INK, va="center", ha="right")
    y = 0.95
    for line in title_lines:
        ax.text(PAD, y, line, fontproperties=DISPLAY7, fontsize=20, color=INK, va="top")
        y += 0.38
    y += 0.06
    for line in sub_lines:
        ax.text(PAD, y, line, fontproperties=BODY, fontsize=10, color=INK2, va="top")
        y += 0.21
    y = head_h

    if block.chart:
        top = y
        rect = [PAD / W + 0.035, 1 - (top + chart_h - 0.15) / H, (width / W) - 0.05, (chart_h - 0.45) / H]
        try:
            _draw_chart(fig, block.chart, block.df, rect)
        except Exception:  # never fail a download because of a chart
            pass
        y += chart_h + (0.25 if table_h else 0)

    if lay:
        _draw_table(ax, lay, y, width, row_h, fs)
        y += table_h

    if kpi_h:
        per_row = 5
        tile_w = (width - 0.15 * (per_row - 1)) / per_row
        for i, (label, value, sub_lab) in enumerate(block.kpis):
            r, c = divmod(i, per_row)
            x0 = PAD + c * (tile_w + 0.15)
            y0 = y + r * 1.25
            ax.add_patch(FancyBboxPatch((x0, y0 + 0.05), tile_w, 1.05, boxstyle="round,pad=0,rounding_size=0.08",
                                        fc=PANEL, ec=LINE, lw=0.8))
            ax.text(x0 + 0.15, y0 + 0.55, _clean(value), fontproperties=DISPLAY7, fontsize=22, color=ACCENT_INK,
                    va="center")
            ax.text(x0 + 0.15, y0 + 0.92, sentence_case(_clean(label))[:34], fontproperties=BODY, fontsize=8.5, color=INK2,
                    va="center")
        y += kpi_h

    for line in text_lines:
        ax.text(PAD, y, line, fontproperties=BODY, fontsize=10.5, color=INK, va="top")
        y += 0.22

    # footer
    fy = H - 0.36
    ax.plot([PAD, W - PAD], [fy - 0.2, fy - 0.2], color=LINE, lw=0.8)
    ax.text(PAD, fy, EMAIL, fontproperties=BODY_B, fontsize=8.5, color=INK2, va="center")
    ax.text(W - PAD, fy, "Ball-by-ball data: Cricsheet", fontproperties=BODY, fontsize=8.5, color=MUTED,
            va="center", ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor="white")
    plt.close(fig)
    return buf.getvalue()
