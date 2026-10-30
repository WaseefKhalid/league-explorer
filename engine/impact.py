"""Ball-by-ball impact (runs added / saved compared with an average player).

`add_impact(ball, matches)` returns `ball` with five columns appended:
'Bat Run Impact', 'Exp Out Cost', 'Out Impact', 'Bowl Run Impact', 'Bowl Wkt Impact'.

The original PSL script is lost; this module was reverse-engineered from the
answer key (data/leagues/psl/ball.parquet) and reproduces it to 3 decimals on
>99.97% of rows (max abs difference 0.001; see tests/check_engine_impact.py).

Model
-----
1. Expected runs ER(u, w): u = legal balls left (of 120), w = wickets lost.
   For every first innings with 'Full 1st Inns' == 1, each LEGAL ball gives one
   observation: state before the ball (u, w) -> runs still to come in the
   innings (total minus runs before the ball, i.e. including this ball).
   Cells (w, u) with fewer than 3 observations are dropped.  For each w = 0..9
   a curve  ER_w(u) = Z_w * (1 - exp(-k_w * u))  is fitted by least squares on
   the remaining observations (the exact optimum, see `_fit_curve`).
   The table is made non-increasing in wickets (cumulative minimum over w),
   ER(u, 10) = 0 and u < 0 (7-ball overs) is treated as u = 0.
2. Season scaling: fac_s = mean first-innings total of the season / mean over
   all seasons (both over 'Full 1st Inns' == 1 matches).  Every ER value used
   for season s is multiplied by fac_s.
3. Per ball (u before, u' after the ball, w wickets before):
      run value  M  = fac_s * (ER(u, w) - ER(u - 1, w))     legal balls; 0 otherwise
      wicket value V = fac_s * (ER(u', w) - ER(u', w + 1))
4. Centring per (Season, Phase) over the included balls:
      Bat Run Impact  = Ball Faced * (Bat Runs - M - k_bat)
                        k_bat = sum(Ball Faced * (Bat Runs - M)) / sum(Ball Faced)
      Bowl Run Impact = Legal * (M + k_bowl) - Bowler Runs
                        k_bowl = (sum(Bowler Runs) - sum(M)) / sum(Legal)
      Out Impact      = -V on every Wicket row (run-outs included)
      Exp Out Cost    = -Ball Faced * sum(V * Wicket) / sum(Ball Faced)
      Bowl Wkt Impact = V * Bowler Wkt - Legal * sum(V * Bowler Wkt) / sum(Legal)
   (wides: only Bowl Run Impact = -Bowler Runs, plus a bowler wicket off a wide;
    no-balls: faced by the batter, M = 0, no par for the bowler.)
   A batter's dismissal impact = sum(Out Impact where he is out) - sum(Exp Out Cost
   over balls he faced); a bowler's wicket impact = sum(Bowl Wkt Impact).
5. Matches with a rain-rule method (Method not empty: D/L, DLS ...) or
   Result == 'No result' get 0 in all five columns and are left out of the
   centring.  Ties (super over) are included.
6. Each column is rounded to 3 decimals (decimals=None keeps full precision,
   which is what the workbook summed into player_seasons).

Pure pandas / numpy; nothing league-specific is hard-coded (T20 = 120 balls).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

IMPACT_COLS = ["Bat Run Impact", "Exp Out Cost", "Out Impact", "Bowl Run Impact", "Bowl Wkt Impact"]

BALLS = 120          # T20 innings length in legal balls
MAX_WKTS = 10
MIN_CELL = 3         # (wickets, balls-left) cells with fewer observations are not fitted


# ── expected-runs curve fit ─────────────────────────────────────────────────────
def _fit_curve(u: np.ndarray, y: np.ndarray, n: np.ndarray) -> tuple[float, float] | None:
    """Weighted least squares of y ~ Z * (1 - exp(-k u)) (weights n = cell counts,
    y = cell means; identical to least squares on the raw observations).

    Z is linear given k, so the problem is profiled to one dimension and the
    optimum is found as the root of d/dk of the profiled fit (precise to machine
    accuracy rather than to an optimiser's stopping tolerance).
    Returns (Z, k) or None when the curve cannot be fitted."""
    u = np.asarray(u, float)
    y = np.asarray(y, float)
    n = np.asarray(n, float)
    if len(u) < 2 or np.ptp(u) == 0:
        return None

    def parts(k):
        e = np.exp(-k * u)
        g = 1.0 - e
        a = (n * y * g).sum()            # A(k)
        bb = (n * g * g).sum()           # B(k)
        da = (n * y * u * e).sum()       # A'(k)
        dbh = (n * g * u * e).sum()      # B'(k) / 2
        return a, bb, da, dbh

    def sse(k):
        a, bb, _, _ = parts(k)
        return (n * y * y).sum() - a * a / bb if bb > 0 else np.inf

    def h(k):                            # sign of dF/dk, F = A^2 / B (maximised)
        a, bb, da, dbh = parts(k)
        return da * bb - a * dbh

    grid = np.exp(np.linspace(np.log(1e-6), np.log(5.0), 400))
    vals = np.array([sse(k) for k in grid])
    i = int(np.nanargmin(vals))
    if i == 0 or i == len(grid) - 1:      # optimum on the edge of the range
        k = float(grid[i])
    else:
        lo, hi = grid[i - 1], grid[i + 1]
        hlo, hhi = h(lo), h(hi)
        if not (hlo > 0 > hhi):          # no clean bracket: refine on the grid value
            k = float(grid[i])
        else:
            for _ in range(200):         # bisection on the first-order condition
                mid = 0.5 * (lo + hi)
                if mid <= lo or mid >= hi:
                    break
                hm = h(mid)
                if hm > 0:
                    lo = mid
                elif hm < 0:
                    hi = mid
                else:
                    lo = hi = mid
                    break
            k = 0.5 * (lo + hi)
    a, bb, _, _ = parts(k)
    if not np.isfinite(a) or bb <= 0:
        return None
    return a / bb, k


def _er_table(u: np.ndarray, w: np.ndarray, y: np.ndarray) -> np.ndarray:
    """ER[u, w] for u = 0..BALLS, w = 0..MAX_WKTS (unscaled, cumulative-min in w)."""
    obs = pd.DataFrame({"u": u, "w": w, "y": y})
    cells = obs.groupby(["w", "u"])["y"].agg(["mean", "count"]).reset_index()
    cells = cells[cells["count"] >= MIN_CELL]
    uu = np.arange(BALLS + 1, dtype=float)
    er = np.zeros((BALLS + 1, MAX_WKTS + 1))
    for wk in range(MAX_WKTS):
        c = cells[cells["w"] == wk]
        p = _fit_curve(c["u"].to_numpy(), c["mean"].to_numpy(), c["count"].to_numpy())
        if p is not None:
            er[:, wk] = p[0] * (1.0 - np.exp(-p[1] * uu))
        elif wk > 0:                     # too little data: no extra value for this wicket
            er[:, wk] = er[:, wk - 1]
        else:                            # degenerate league: flat scoring rate
            rate = (obs["y"] / obs["u"].clip(lower=1)).mean() if len(obs) else 0.0
            er[:, wk] = rate * uu
    er[:, :MAX_WKTS] = np.minimum.accumulate(er[:, :MAX_WKTS], axis=1)
    er[:, MAX_WKTS] = 0.0
    return er


# ── main ───────────────────────────────────────────────────────────────────────
def add_impact(ball: pd.DataFrame, matches: pd.DataFrame, decimals: int | None = 3) -> pd.DataFrame:
    """Return `ball` (rows in delivery order within each Match ID + Innings)
    with the five impact columns appended in IMPACT_COLS order.

    decimals=3 reproduces the stored ball table.  The workbook's player-season
    sums ('Bat Run Impact', 'Bat Out Impact', 'Bowl Run Impact', 'Bowl Wkt Impact',
    'Wicket Value' in player_seasons) were summed from the UNROUNDED per-ball
    values: pass decimals=None to get those (summing the rounded columns drifts
    by up to ~0.2 per player-season)."""
    out = ball.drop(columns=[c for c in IMPACT_COLS if c in ball.columns]).copy()
    if len(ball) == 0:
        for c in IMPACT_COLS:
            out[c] = pd.Series(dtype="float64")
        return out

    b = ball.reset_index(drop=True)
    mm = matches.drop_duplicates("Match ID").set_index("Match ID")

    # matches left out of impact: rain-rule result or no result (ties stay in)
    method = mm["Method"] if "Method" in mm else pd.Series(np.nan, index=mm.index)
    has_method = method.notna() & method.astype(str).str.strip().ne("")
    excl = mm["Result"].astype(str).eq("No result") | has_method
    incl = ~b["Match ID"].map(excl).fillna(False).astype(bool).to_numpy()

    legal = b["Legal Ball"].to_numpy(float)
    faced = b["Ball Faced"].to_numpy(float)
    wkt = b["Wicket"].to_numpy(float)
    bwkt = b["Bowler Wkt"].to_numpy(float)
    bat_runs = b["Bat Runs"].to_numpy(float)
    bowl_runs = b["Bowler Runs"].to_numpy(float)

    # match state before each delivery (rows are in delivery order)
    g = b.groupby(["Match ID", "Innings"], sort=False)
    wk_before = (g["Wicket"].cumsum() - b["Wicket"]).to_numpy()
    lb_before = (g["Legal Ball"].cumsum() - b["Legal Ball"]).to_numpy()
    runs_before = (g["Total Runs"].cumsum() - b["Total Runs"]).to_numpy(float)
    inns_total = g["Total Runs"].transform("sum").to_numpy(float)
    u_before = BALLS - lb_before
    u_after = u_before - legal.astype(int)

    # expected-runs model from complete first innings
    full_ids = mm.index[mm["Full 1st Inns"].fillna(0).astype(int) == 1]
    fit_rows = (b["Innings"].to_numpy() == 1) & b["Match ID"].isin(full_ids).to_numpy() & (legal == 1)
    er = _er_table(u_before[fit_rows], wk_before[fit_rows], (inns_total - runs_before)[fit_rows])

    # season scaling
    full = mm.loc[full_ids]
    if len(full):
        fac_by_season = full.groupby("Season")["1st Inns Runs"].mean() / full["1st Inns Runs"].mean()
    else:
        fac_by_season = pd.Series(dtype=float)
    fac = b["Season"].map(fac_by_season).fillna(1.0).to_numpy(float)

    def er_at(uu, ww):
        return er[np.clip(uu, 0, BALLS), np.clip(ww, 0, MAX_WKTS)]

    w0 = np.clip(wk_before, 0, MAX_WKTS)
    run_val = np.where(legal == 1, fac * (er_at(u_before, w0) - er_at(u_before - 1, w0)), 0.0)
    wkt_val = fac * (er_at(u_after, w0) - er_at(u_after, w0 + 1))

    # centring per season and phase over included balls
    key = pd.MultiIndex.from_arrays([b["Season"].to_numpy(), b["Phase"].astype(str).to_numpy()])
    inc = incl.astype(float)

    def gsum(x):
        return pd.Series(np.asarray(x, float) * inc).groupby(key).transform("sum").to_numpy()

    def ratio(num, den):
        num, den = gsum(num), gsum(den)
        return np.divide(num, den, out=np.zeros_like(num), where=den != 0)

    k_bat = ratio(faced * (bat_runs - run_val), faced)
    k_bowl = ratio(bowl_runs - run_val, legal)
    out_val = wkt_val * wkt
    bowl_wkt_val = wkt_val * bwkt

    res = {
        "Bat Run Impact": faced * (bat_runs - run_val - k_bat),
        "Exp Out Cost": -faced * ratio(out_val, faced),
        "Out Impact": -out_val,
        "Bowl Run Impact": legal * (run_val + k_bowl) - bowl_runs,
        "Bowl Wkt Impact": bowl_wkt_val - legal * ratio(bowl_wkt_val, legal),
    }
    for c in IMPACT_COLS:
        v = np.where(incl, res[c], 0.0)
        if decimals is not None:
            v = np.round(v, decimals)
        out[c] = v + 0.0                    # + 0.0 turns -0.0 into 0.0
    return out
