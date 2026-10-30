"""
Shared table logic for the web view and the PNG export: how each cell is
written (number formats) and coloured (green / amber / red tints).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from analytics.blocks import Block

# Light (workbook) tints — used for PNGs always, and on the site in light mode.
LIGHT = dict(good="#CDEBD6", mid="#FFEFC1", bad="#F8D5DC",
             good_rgb=(31, 140, 78), bad_rgb=(200, 54, 70),
             muted_bg="#F6F7F7", muted_ink="#B4BAC2")

_ID_LIKE = re.compile(r"(season|year|match id|id$|^#$|^no\.?$|rank|position|pos$|over$)", re.I)


_ACRONYMS = {"SR", "RHB", "LHB", "PP", "MO1", "MO2", "POTM", "DLS", "NR", "HS", "LBW", "RAP", "LAP", "OS",
             "LS", "LAO", "LWS", "PSL", "UAE", "4S", "6S", "50S", "100S", "V"}


def sentence_case(label: str) -> str:
    """'BALLS PER DISMISSAL' -> 'Balls per dismissal'; keeps SR, PP, RHB… ; leaves mixed-case labels alone."""
    s = str(label)
    if not s.isupper():
        return s
    words = s.split(" ")
    out = []
    for i, w in enumerate(words):
        core = w.strip("()†*·,:")
        if core in _ACRONYMS and core not in {"V", "4S", "6S", "50S", "100S"}:
            out.append(w)
        elif core in {"4S", "6S", "50S", "100S"}:
            out.append(w.lower())
        elif core == "V":
            out.append(w.lower())
        else:
            out.append(w.lower() if i else w[:1] + w[1:].lower())
    return " ".join(out)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Object columns that only hold numbers (and blanks) become numeric, so blanks show as '—'."""
    if df is None:
        return df
    fixed = None
    for c in df.columns:
        if df[c].dtype == object:
            vals = df[c].dropna()
            is_num = [isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in vals]
            if len(vals) and all(is_num):
                fixed = df.copy() if fixed is None else fixed
                fixed[c] = pd.to_numeric(df[c], errors="coerce")
            elif any(is_num):
                # Numbers mixed with labels ("2016" … "Selected span"): show all as text,
                # which is what the table would do anyway, without the Arrow retry.
                fixed = df.copy() if fixed is None else fixed
                fixed[c] = df[c].map(lambda v: v if pd.isna(v) else str(v)).astype(object)
    return df if fixed is None else fixed


def numeric_cols(df: pd.DataFrame) -> list:
    return [c for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def auto_fmt(df: pd.DataFrame, col) -> str:
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if _ID_LIKE.search(str(col)):
        return "{:.0f}"
    if s.empty or (s % 1 == 0).all():
        return "{:,.0f}"
    return "{:,.2f}"


def _fmt_date(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    t = pd.Timestamp(v)
    return f"{t.day} {t.strftime('%b %Y')}"


def formats(block: Block, df: pd.DataFrame) -> dict:
    out = {}
    for c in numeric_cols(df):
        out[c] = block.fmt.get(c) or auto_fmt(df, c)
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            out[c] = _fmt_date
    return out


def fmt_value(v, f) -> str:
    if callable(f):
        return f(v)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if isinstance(v, pd.Timestamp):
        return _fmt_date(v)
    if f is None or not isinstance(v, (int, float, np.integer, np.floating)):
        return str(v)
    try:
        return f.format(v)
    except (ValueError, TypeError):
        return str(v)


def display_strings(block: Block, df: pd.DataFrame) -> pd.DataFrame:
    """Every cell as the text the reader sees."""
    fm = formats(block, df)
    out = pd.DataFrame(index=df.index, columns=df.columns, dtype=object)
    for c in df.columns:
        f = fm.get(c)
        out[c] = [fmt_value(v, f) for v in df[c].tolist()]
    if block.labels is not None:
        lab = block.labels.reindex(index=df.index, columns=df.columns)
        out = lab.where(lab.notna() & (lab.astype(str) != ""), out)
    return out


def _compare(s: pd.Series, cond) -> pd.Series:
    op, thr = cond
    if isinstance(thr, pd.Series):
        thr = pd.to_numeric(thr.reindex(s.index), errors="coerce")
    s = pd.to_numeric(s, errors="coerce")
    if op == ">=":
        m = s >= thr
    elif op == ">":
        m = s > thr
    elif op == "<=":
        m = s <= thr
    elif op == "<":
        m = s < thr
    elif op in ("==", "="):
        m = s == thr
    else:
        raise ValueError(op)
    return m.fillna(False).astype(bool)


def _rgba(rgb, a):
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a:.3f})"


def tint_matrix(block: Block, df: pd.DataFrame, palette: dict) -> pd.DataFrame:
    """Background colour per cell ('' = none)."""
    bg = pd.DataFrame("", index=df.index, columns=df.columns, dtype=object)
    nums = set(numeric_cols(df))
    rules = block.rules or {}
    for col in df.columns:
        rule = rules.get(col)
        if rule is None and "*" in rules and col in nums:
            rule = rules["*"]
        if rule and col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            has = s.notna()
            # Optional boolean mask: the rule only applies where True
            if isinstance(rule.get("where"), pd.Series):
                has &= rule["where"].reindex(s.index).fillna(False).astype(bool)
            # A per-row threshold of NaN means "this rule doesn't apply to the row" → no tint at all
            for part in ("good", "bad"):
                cond = rule.get(part)
                if cond and isinstance(cond[1], pd.Series):
                    has &= pd.to_numeric(cond[1].reindex(s.index), errors="coerce").notna()
            good = (_compare(s, rule["good"]) & has) if rule.get("good") else pd.Series(False, index=s.index)
            bad = (_compare(s, rule["bad"]) & ~good & has) if rule.get("bad") else pd.Series(False, index=s.index)
            mid = has & ~good & ~bad if rule.get("mid", True) and rule.get("good") and rule.get("bad") else \
                pd.Series(False, index=s.index)
            bg.loc[good, col] = palette["good"]
            bg.loc[bad, col] = palette["bad"]
            bg.loc[mid, col] = palette["mid"]
            continue
        if col in block.good_high or col in block.good_low:
            s = pd.to_numeric(df[col], errors="coerce")
            if s.notna().sum() < 2:
                continue
            c = block.center.get(col, float(s.median()))
            spread = float((s.quantile(.9) - s.quantile(.1)) / 2) or float((s - c).abs().max()) or 1.0
            z = ((s - c) / spread).clip(-1, 1)
            if col in block.good_low:
                z = -z
            for i in s.index[s.notna()]:
                zi = float(z.loc[i])
                if abs(zi) < .08:
                    continue
                rgb = palette["good_rgb"] if zi > 0 else palette["bad_rgb"]
                bg.at[i, col] = _rgba(rgb, .10 + .30 * abs(zi))
    cells = getattr(block, "cell_tints", None)
    if cells is not None:
        cells = cells.reindex(index=df.index, columns=df.columns)
        for key in ("good", "mid", "bad"):
            bg = bg.mask(cells.eq(key), palette[key])
    return bg


def row_flags(block: Block, df: pd.DataFrame) -> tuple[set, set]:
    idx = set(df.index)
    return ({i for i in block.muted_rows if i in idx}, {i for i in block.bold_rows if i in idx})
