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

Every candidate is scored on the exact same walk-forward validation windows the
dashboard itself reports (no separate held-out test set -- with only ~8 non-
overlapping windows of real history, carving out a further split would leave too
little of either to trust). That means this sweep is *fitting* to the same windows
whose scores it reports, a real overfitting risk flagged here rather than hidden:
the report includes each candidate's return-vs-stddev trade-off and how many windows
it beats buy-and-hold, and prefers candidates whose immediate neighbors in the grid
also perform reasonably (a crude but real robustness check against picking a single
lucky grid point), but the final choice still deserves a skeptical read against
future live sessions, not blind trust.

Usage: python scripts/tune.py    (writes scripts/tuning_report.json)
"""

from __future__ import annotations

import itertools
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import engine  # noqa: E402

REPORT_PATH = SCRIPT_DIR / "tuning_report.json"


def evaluate() -> dict:
    """Run engine's own walk-forward backtest under whatever parameter values are
    currently patched onto the engine module, and return its validation summary
    plus the full per-window breakdown."""
    result = engine.walk_forward_backtest(
        SESSIONS, UNDERLYING_DAILY, GEAR_DAILY, BBOZ_DAILY
    )
    summary = engine.summarize_validation_windows(result.validation_windows)
    return {
        "summary": summary,
        "windows": [
            {
                "windowIndex": w["windowIndex"],
                "totalReturnPct": w["totalReturnPct"],
                "winRatePct": w["winRatePct"],
                "beatBuyHoldGear": w["beatBuyHoldGear"],
            }
            for w in result.validation_windows
        ],
    }


def score(evaluation: dict) -> float:
    """Prefer high mean return, penalize instability across windows -- a simple
    risk-adjusted objective rather than raw mean return alone, since a wilder
    but-sometimes-lucky parameter set isn't actually what "improve the model"
    should mean with only 8 windows of evidence."""
    s = evaluation["summary"]
    if s.get("windowsEvaluated", 0) == 0:
        return float("-inf")
    return s.get("meanTotalReturnPct", 0.0) - 0.5 * s.get("stdDevTotalReturnPct", 0.0)


def apply_params(params: dict) -> None:
    for name, value in params.items():
        setattr(engine, name, value)


def sweep(param_grid: dict, fixed: dict, label: str) -> list[dict]:
    apply_params(fixed)
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"[tune] {label}: evaluating {len(combos)} combinations "
          f"over {keys}", flush=True)
    results = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        if "SHORT_TERM_MA_DAYS" in params and "VOL_REGIME_MA_DAYS" in params:
            if params["SHORT_TERM_MA_DAYS"] >= params["VOL_REGIME_MA_DAYS"]:
                continue  # "short" MA must actually be shorter than the "regime" MA
        apply_params(params)
        try:
            ev = evaluate()
        except Exception as exc:  # noqa: BLE001
            print(f"[tune]   combo {params} failed: {exc}")
            continue
        results.append({"params": params, "score": score(ev), **ev})
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
    print("[tune] baseline (LNAS/SNAS-carried-over) parameters:", baseline_params)
    apply_params(baseline_params)
    baseline_eval = evaluate()
    print("[tune] baseline summary:", baseline_eval["summary"])

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
          f"score={stage_a_winner['score']:.2f} summary={stage_a_winner['summary']}")

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
          f"score={stage_b_winner['score']:.2f} summary={stage_b_winner['summary']}")

    final_params = {**stage_a_winner["params"], **stage_b_winner["params"]}
    apply_params(final_params)
    final_eval = evaluate()
    print(f"[tune] FINAL combined parameters: {final_params}")
    print(f"[tune] FINAL summary: {final_eval['summary']}")

    report = {
        "generatedAt": now_adelaide.isoformat(),
        "caveats": (
            "Greedy two-stage search (filters, then volatility/MA overrides), scored "
            "on the same ~8 walk-forward windows the dashboard reports (no separate "
            "holdout was available). Treat as a directionally-informed re-calibration "
            "against GEAR/BBOZ's own history, not a guaranteed-optimal or "
            "out-of-sample-validated result."
        ),
        "baseline": {"params": baseline_params, **baseline_eval},
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
        "final": {"params": final_params, **final_eval},
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"[tune] wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
