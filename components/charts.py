"""Reusable league charts, styled with the Floodlit theme (components/theme.py).

Function names and arguments are unchanged from the original module.
"""

import pandas as pd
import streamlit as st

from components import theme as ui


def _safe_merge_season(deliveries: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Merge deliveries with season info safely, avoiding duplicate columns."""
    match_cols = [c for c in ["match_id", "season"] if c in matches.columns]
    merged = deliveries.merge(matches[match_cols], on="match_id", how="left")
    if "season_x" in merged.columns:
        merged = merged.rename(columns={"season_x": "season"}).drop(columns=["season_y"], errors="ignore")
    return merged


def plot_runs_per_season(deliveries: pd.DataFrame, matches: pd.DataFrame):
    if deliveries.empty or matches.empty:
        st.info("No matches in your selection.")
        return
    try:
        merged = _safe_merge_season(deliveries, matches)
        if "season" not in merged.columns:
            st.info("This data has no season column.")
            return
        merged["total_ball_runs"] = merged["runs_off_bat"].fillna(0) + merged["extras"].fillna(0)
        runs = (
            merged.groupby("season")["total_ball_runs"]
            .sum()
            .reset_index()
            .rename(columns={"total_ball_runs": "total_runs"})
            .sort_values("season")
        )
        runs["total_runs"] = runs["total_runs"].astype(int)
        ui.show(ui.bar(runs, "season", "total_runs", title="Runs per season"))
    except Exception as e:
        st.warning(f"Couldn't draw the runs-per-season chart: {e}")


def plot_wickets_per_season(deliveries: pd.DataFrame, matches: pd.DataFrame):
    if deliveries.empty or matches.empty:
        st.info("No matches in your selection.")
        return
    try:
        merged = _safe_merge_season(deliveries, matches)
        if "season" not in merged.columns:
            st.info("This data has no season column.")
            return
        wickets_df = merged[
            merged["wicket_type"].notna() & (merged["wicket_type"].astype(str).str.strip() != "")
        ]
        wickets = (
            wickets_df.groupby("season").size()
            .reset_index(name="wickets")
            .sort_values("season")
        )
        ui.show(ui.line(wickets, "season", "wickets", title="Wickets per season",
                        color=ui.RED, categorical_x=True))
    except Exception as e:
        st.warning(f"Couldn't draw the wickets-per-season chart: {e}")


def plot_win_by_method(matches: pd.DataFrame):
    if matches.empty:
        st.info("No matches in your selection.")
        return
    try:
        df = matches.copy()
        df["method"] = "By runs"
        if "winner_wickets" in df.columns:
            df["winner_wickets"] = pd.to_numeric(df["winner_wickets"], errors="coerce")
            df.loc[df["winner_wickets"].notna() & (df["winner_wickets"] > 0), "method"] = "By wickets"
        if "winner" in df.columns:
            df.loc[df["winner"].isna() | (df["winner"].astype(str).str.strip() == ""), "method"] = "No result"
        counts = df["method"].value_counts().reset_index()
        counts.columns = ["method", "count"]
        ui.show(ui.donut(counts, "method", "count", title="How matches were won"))
    except Exception as e:
        st.warning(f"Couldn't draw the win-method chart: {e}")


def plot_toss_impact(matches: pd.DataFrame):
    if matches.empty or "toss_decision" not in matches.columns:
        st.info("No toss data in your selection.")
        return
    try:
        counts = matches["toss_decision"].dropna().value_counts().reset_index()
        counts.columns = ["decision", "count"]
        ui.show(ui.donut(counts, "decision", "count", title="Toss decisions", colors=[ui.AMBER, ui.SKY]))
    except Exception as e:
        st.warning(f"Couldn't draw the toss chart: {e}")


def plot_top_batsmen(df: pd.DataFrame, x: str, y: str, title: str):
    if df.empty:
        st.info("No batters in your selection.")
        return
    try:
        top = df.head(10).copy()
        top[y] = pd.to_numeric(top[y], errors="coerce").fillna(0)
        ui.show(ui.bar(top, x, y, title=title, horizontal=True))
    except Exception as e:
        st.warning(f"Couldn't draw the chart: {e}")


def plot_top_bowlers(df: pd.DataFrame):
    if df.empty:
        st.info("No bowlers in your selection.")
        return
    try:
        top = df.head(10).copy()
        ui.show(ui.bar(top, "player", "wickets", title="Top 10 wicket takers",
                       horizontal=True, color=ui.VIOLET))
    except Exception as e:
        st.warning(f"Couldn't draw the bowlers chart: {e}")
