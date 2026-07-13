#!/usr/bin/env python3
"""
Parameter sweep for the GEAR/BBOZ engine's rule-based filter and volatility-override
thresholds, run against GEAR.AX/BBOZ.AX's own real history instead of the values
carried over unchanged from the sibling LNAS/SNAS strategy (see engine.py's config
comments). This is a deliberately pragmatic, greedy two-stage search, not a rigorous
academic optimization -- see the caveats printed in the report.

Stage A sweeps the four BBOZ-gate confirmation filters (ALIGNMENT_MARGIN_PCT,
RS_LOOKBACK_DAYS, LIQUIDITY_MIN_RATIO, PULLBACK_MAX_EXTENSION_PCT) with the
volatility/MA overrides held at their original values. Stage B then fixes the
winning filter thresholds and sweeps the volatility/MA override parameters
(VOL_SPIKE_MULTIPLIER, VOL_REGIME_MA_DAYS, SHORT_TERM_MA_DAYS, and the realized-vol
lookback/baseline windows). Two stages instead of one joint search keeps the grid
size (and runtime) tractable; it isn't guaranteed to find the joint optimum, but it
directly targets the two mechanisms identified as the actual drivers of
underperformance: a sub-50% raw win rate (Stage A: is the BBOZ entry bar calibrated
right for this instrument?) and BBOZ dominating the dollar losses via the
override-forced entries (Stage B: are the override thresholds forcing BBOZ too
often or too readily for the ASX 200's own volatility/trend regime?).

TRAIN/HOLDOUT SPLIT -- the key fix versus this script's first version. With only ~8
non-overlapping walk-forward windows of real history, fitting parameters to the same
windows the dashboard then reports on is genuine overfitting risk, not a hypothetical
one: given enough parameter combinations, *something* will look good on any fixed set
of 8 windows purely by chance. So every candidate is scored only on the older windows
(TUNING windows; the most recent HOLDOUT_WINDOW_COUNT windows are never touched during
the sweep), and the winning parameters are then evaluated once, cold, against the
holdout windows the search never saw. The holdout number is the one that actually
tells you whether this generalizes -- the tuning-set number only tells you the search
worked, which it always will.

The optimization objective is mean Sharpe ratio on the tuning windows (risk-adjusted),
not raw mean return -- a wilder but sometimes-lucky parameter set isn't an improvement,
and chasing raw return with no risk penalty is exactly how you end up with a curve-fit
strategy that looks great until the first regime it wasn't fit to.

Usage: python scripts/tune.py    (writes scripts/tuning_report.json)
"""

from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import engine  # noqa: E402

REPORT_PATH = SCRIPT_DIR / "tuning_report.json"

# The most recent N windows are held out of every sweep score -- never optimized
# against, only evaluated once at the end against the winning parameters. 2 of the
# real ~8 windows is a small holdout, but holding out more leaves too few tuning
# windows to search against at all; this is a real constraint of a young, short-
# history instrument pair, not a stylistic choice.
HOLDOUT_WINDOW_COUNT = 2


def run_backtest() -> list[dict]:
    """Run engine's own walk-forward backtest under whatever parameter values are
    currently patched onto the engine module; returns validation_windows, most
    recent first (index 0 is the most recent window)."""
    result = engine.walk_forward_backtest(
        SESSIONS, UNDERLYING_DAILY, GEAR_DAILY, BBOZ_DAILY
    )
    return result.validation_windows


def split_windows(windows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(tuning_windows, holdout_windows) -- holdout is the most recent
    HOLDOUT_WINDOW_COUNT windows (index 0..N-1), tuning is everything older."""
    holdout = windows[:HOLDOUT_WINDOW_COUNT]
    tuning = windows[HOLDOUT_WINDOW_COUNT:]
    return tuning, holdout


def summarize(windows: list[dict]) -> dict:
    return engine.summarize_validation_windows(windows)


def score(tuning_summary: dict) -> float:
    """Risk-adjusted: mean Sharpe ratio on the tuning windows only. Ties broken by
    mean return so two candidates with a similar Sharpe don't get picked arbitrarily."""
    if tuning_summary.get("windowsEvaluated", 0) == 0:
        return float("-inf")
    sharpe = tuning_summary.get("meanSharpeRatio", 0.0)
    tie_break = tuning_summary.get("meanTotalReturnPct", 0.0) / 1000.0  # negligible vs sharpe
    return sharpe + tie_break


def apply_params(params: dict) -> None:
    for name, value in params.items():
        setattr(engine, name, value)


def sweep(param_grid: dict, fixed: dict, label: str) -> list[dict]:
    apply_params(fixed)
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"[tune] {label}: evaluating {len(combos)} combinations "
          f"over {keys} (scored on tuning windows only)", flush=True)
    results = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        if "SHORT_TERM_MA_DAYS" in params and "VOL_REGIME_MA_DAYS" in params:
            if params["SHORT_TERM_MA_DAYS"] >= params["VOL_REGIME_MA_DAYS"]:
                continue  # "short" MA must actually be shorter than the "regime" MA
        apply_params(params)
        try:
            windows = run_backtest()
        except Exception as exc:  # noqa: BLE001
            print(f"[tune]   combo {params} failed: {exc}")
            continue
        tuning_windows, holdout_windows = split_windows(windows)
        tuning_summary = summarize(tuning_windows)
        results.append({
            "params": params,
            "score": score(tuning_summary),
            "tuningSummary": tuning_summary,
        })
        if (i + 1) % 50 == 0:
            print(f"[tune]   ...{i + 1}/{len(combos)}", flush=True)
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def robustness_note(results: list[dict], winner: dict, keys: list[str]) -> str:
    """Crude neighbor-robustness check: among the top 10 scored candidates, how many
    share at least half their parameter values with the winner? A winner that looks
    nothing like anything else in the top 10 is more likely a lucky single grid
    point than a genuine regime the strategy responds to."""
    top = results[:10]
    similar = 0
    for r in top:
        matches = sum(1 for k in keys if r["params"].get(k) == winner["params"].get(k))
        if matches >= len(keys) / 2:
            similar += 1
    return f"{similar}/{len(top)} of the top-10 candidates share >=half the winner's parameter values"


def main() -> None:
    global SESSIONS, UNDERLYING_DAILY, GEAR_DAILY, BBOZ_DAILY

    now_adelaide = datetime.now(engine.ADELAIDE_TZ)
    today = now_adelaide.date()
    print(f"[tune] fetching GEAR.AX/BBOZ.AX/^AXJO history at {now_adelaide.isoformat()}")

    gear_daily_raw = engine.fetch_daily(engine.TICKER_LONG, auto_adjust=False)
    bboz_daily_raw = engine.fetch_daily(engine.TICKER_SHORT, auto_adjust=False)
    gear_intraday_raw = engine.fetch_intraday(engine.TICKER_LONG, auto_adjust=False)
    bboz_intraday_raw = engine.fetch_intraday(engine.TICKER_SHORT, auto_adjust=False)
    gear_splits = engine.fetch_splits(engine.TICKER_LONG)
    bboz_splits = engine.fetch_splits(engine.TICKER_SHORT)

    GEAR_DAILY = engine.apply_split_adjustment(gear_daily_raw, gear_splits)
    BBOZ_DAILY = engine.apply_split_adjustment(bboz_daily_raw, bboz_splits)
    gear_intraday = engine.apply_split_adjustment(gear_intraday_raw, gear_splits)
    bboz_intraday = engine.apply_split_adjustment(bboz_intraday_raw, bboz_splits)
    UNDERLYING_DAILY = engine.fetch_underlying_daily()

    session_dates = engine.build_session_dates(today)
    SESSIONS = engine.build_session_price_series(
        session_dates, GEAR_DAILY, gear_intraday, BBOZ_DAILY, bboz_intraday, now_adelaide
    )
    print(f"[tune] resolved {len(SESSIONS)} sessions")

    baseline_params = {
        "ALIGNMENT_MARGIN_PCT": engine.ALIGNMENT_MARGIN_PCT,
        "RS_LOOKBACK_DAYS": engine.RS_LOOKBACK_DAYS,
        "LIQUIDITY_MIN_RATIO": engine.LIQUIDITY_MIN_RATIO,
        "PULLBACK_MAX_EXTENSION_PCT": engine.PULLBACK_MAX_EXTENSION_PCT,
        "REALIZED_VOL_LOOKBACK_DAYS": engine.REALIZED_VOL_LOOKBACK_DAYS,
        "VOL_BASELINE_LOOKBACK_DAYS": engine.VOL_BASELINE_LOOKBACK_DAYS,
        "VOL_SPIKE_MULTIPLIER": engine.VOL_SPIKE_MULTIPLIER,
        "VOL_REGIME_MA_DAYS": engine.VOL_REGIME_MA_DAYS,
        "SHORT_TERM_MA_DAYS": engine.SHORT_TERM_MA_DAYS,
    }
    print("[tune] baseline (current engine.py) parameters:", baseline_params)
    apply_params(baseline_params)
    baseline_windows = run_backtest()
    baseline_tuning, baseline_holdout = split_windows(baseline_windows)
    baseline_tuning_summary = summarize(baseline_tuning)
    baseline_holdout_summary = summarize(baseline_holdout)
    print("[tune] baseline tuning-set summary:", baseline_tuning_summary)
    print("[tune] baseline holdout summary:", baseline_holdout_summary)

    # ---- Stage A: BBOZ-gate confirmation filters -----------------------------
    stage_a_grid = {
        "ALIGNMENT_MARGIN_PCT": [0.0, 0.05, 0.1, 0.2, 0.35],
        "RS_LOOKBACK_DAYS": [10, 15, 20, 30, 40],
        "LIQUIDITY_MIN_RATIO": [0.5, 0.6, 0.7, 0.8, 1.0],
        "PULLBACK_MAX_EXTENSION_PCT": [1.5, 2.0, 3.5, 5.0, 7.0],
    }
    stage_a_fixed = {
        "REALIZED_VOL_LOOKBACK_DAYS": baseline_params["REALIZED_VOL_LOOKBACK_DAYS"],
        "VOL_BASELINE_LOOKBACK_DAYS": baseline_params["VOL_BASELINE_LOOKBACK_DAYS"],
        "VOL_SPIKE_MULTIPLIER": baseline_params["VOL_SPIKE_MULTIPLIER"],
        "VOL_REGIME_MA_DAYS": baseline_params["VOL_REGIME_MA_DAYS"],
        "SHORT_TERM_MA_DAYS": baseline_params["SHORT_TERM_MA_DAYS"],
    }
    stage_a_results = sweep(stage_a_grid, stage_a_fixed, "Stage A (BBOZ-gate filters)")
    stage_a_winner = stage_a_results[0]
    print(f"[tune] Stage A winner: {stage_a_winner['params']} "
          f"score={stage_a_winner['score']:.3f} tuningSummary={stage_a_winner['tuningSummary']}")

    # ---- Stage B: volatility / MA override thresholds ------------------------
    stage_b_grid = {
        "REALIZED_VOL_LOOKBACK_DAYS": [5, 10, 15],
        "VOL_BASELINE_LOOKBACK_DAYS": [45, 60, 90],
        "VOL_SPIKE_MULTIPLIER": [1.3, 1.5, 2.0, 3.0],
        "VOL_REGIME_MA_DAYS": [30, 50, 100, 150],
        "SHORT_TERM_MA_DAYS": [10, 20, 30],
    }
    stage_b_fixed = dict(stage_a_winner["params"])
    stage_b_results = sweep(stage_b_grid, stage_b_fixed, "Stage B (volatility/MA overrides)")
    stage_b_winner = stage_b_results[0]
    print(f"[tune] Stage B winner: {stage_b_winner['params']} "
          f"score={stage_b_winner['score']:.3f} tuningSummary={stage_b_winner['tuningSummary']}")

    final_params = {**stage_a_winner["params"], **stage_b_winner["params"]}
    apply_params(final_params)
    final_windows = run_backtest()
    final_tuning, final_holdout = split_windows(final_windows)
    final_tuning_summary = summarize(final_tuning)
    final_holdout_summary = summarize(final_holdout)
    print(f"[tune] FINAL combined parameters: {final_params}")
    print(f"[tune] FINAL tuning-set summary: {final_tuning_summary}")
    print(f"[tune] FINAL holdout summary (never optimized against): {final_holdout_summary}")

    report = {
        "generatedAt": now_adelaide.isoformat(),
        "methodology": (
            f"Greedy two-stage search (filters, then volatility/MA overrides), scored "
            f"by mean Sharpe ratio on the oldest windows only ('tuning'); the most "
            f"recent {HOLDOUT_WINDOW_COUNT} windows ('holdout') were never touched "
            f"during the sweep and are evaluated once at the end against the winning "
            f"parameters. The holdout numbers are the honest read on whether this "
            f"generalizes; the tuning numbers mainly confirm the search worked."
        ),
        "caveats": (
            "Still a small-sample re-calibration (a handful of tuning windows, "
            f"{HOLDOUT_WINDOW_COUNT} holdout windows) on a young instrument pair -- "
            "informative, not a guarantee. Backtest includes an estimated bid-ask "
            "spread cost (SPREAD_COST_PCT in engine.py) but still assumes zero "
            "brokerage and perfect fills at the resolved session price."
        ),
        "baseline": {
            "params": baseline_params,
            "tuningSummary": baseline_tuning_summary,
            "holdoutSummary": baseline_holdout_summary,
        },
        "stageA": {
            "grid": stage_a_grid,
            "fixed": stage_a_fixed,
            "top10": stage_a_results[:10],
            "robustness": robustness_note(stage_a_results, stage_a_winner, list(stage_a_grid.keys())),
        },
        "stageB": {
            "grid": stage_b_grid,
            "fixed": stage_b_fixed,
            "top10": stage_b_results[:10],
            "robustness": robustness_note(stage_b_results, stage_b_winner, list(stage_b_grid.keys())),
        },
        "final": {
            "params": final_params,
            "tuningSummary": final_tuning_summary,
            "holdoutSummary": final_holdout_summary,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"[tune] wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
