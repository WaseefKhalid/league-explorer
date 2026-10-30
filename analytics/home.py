"""Home sheet: headline numbers for the span (row 7–8 of the workbook's Home sheet)."""
from __future__ import annotations

from analytics import data as d


def headline(span: tuple[int, int]) -> list[tuple[str, int]]:
    lo, hi = min(span), max(span)
    m = d.in_span(d.matches(), span)
    b = d.in_span(d.ball(), span)
    ps = d.in_span(d.player_seasons(), span)
    bi = d.in_span(d.bat_inns(), span)
    players = ps.groupby("Player")["Mat"].sum()
    return [
        ("Matches", int((m["Season"] > 0).sum())),
        ("Seasons", sum(lo <= s <= hi for s in d.seasons())),     # seasons in the data (a league may skip a year)
        ("Players", int((players > 0).sum())),
        ("Balls (legal)", int(b.loc[b["Legal Ball"] == 1, "Legal Ball"].sum())),
        ("Runs", int(b["Total Runs"].sum())),
        ("Wickets", int(b["Wicket"].sum())),
        ("Sixes", int(b["Six"].sum())),
        ("Centuries", int((bi["Runs"] >= 100).sum())),
    ]
