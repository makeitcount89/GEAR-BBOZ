#!/usr/bin/env python3
"""
GEAR/BBOZ bi-weekly ML trend-following allocation engine.

This engine is a direct port of a sibling strategy originally built for LNAS.AX /
SNAS.AX (leveraged/inverse-leveraged ASX-listed Nasdaq products), re-pointed at
GEAR.AX / BBOZ.AX (leveraged/inverse-leveraged ASX-listed Australian equities
products) with the reference index switched from the Nasdaq to the S&P/ASX 200. The
model, filters, thresholds, and volatility overrides below are carried over unchanged
from that strategy's own real walk-forward validation rather than re-derived here --
see the config comments further down for the reasoning behind each choice.

Pipeline:
  1. Pull RAW (unadjusted) daily price history (~5 years, or whatever's actually
     available) for GEAR.AX and BBOZ.AX, 60m intraday bars for both (~2 years of
     retention -- Yahoo's own per-interval limit, not a yfinance choice; 30m/15m/5m
     bars only retain ~60 days), Yahoo's recorded split ratios for both, and daily
     history for a non-leveraged reference S&P/ASX 200 index -- all via yfinance.
  2. Apply a precise, split-only price adjustment to GEAR/BBOZ using the recorded
     split ratios (not yfinance's opaque combined split+dividend auto_adjust, which
     was observed on the sibling strategy to still miss a very recent split and to
     introduce its own boundary artifact adjusting an older one). A residual safety
     net (desplit_session_prices) catches any remaining implausible single-interval
     move -- a split Yahoo hasn't recorded yet, or a genuinely unexplained data
     artifact.
  3. Normalize all timestamps to Australia/Adelaide and resolve a "session price"
     for every Tuesday/Friday: the 14:00 ACST/ACDT intraday bar when available
     (actionable signal ahead of the 16:00 AEST close), falling back to the daily
     close for sessions outside yfinance's ~2 year intraday retention window.
  4. Build a single Guppy Multiple Moving Average (GMMA) feature set from the
     reference index -- short ("trader") EMA group compression, long ("investor") EMA
     group separation, and price's position relative to the short group -- fed into a
     from-scratch k=3 Euclidean k-NN (the exact model family this project was
     specified with). A raw GMMA-only signal, and two other feature families tried in
     the sibling strategy's earlier iterations (lagged-return momentum, SMA50/200 +
     VIX regime), each landed within noise of a 50% win rate on their own -- so rather
     than picking a feature set on faith, the k-NN's directional call is gated by four
     classic rule-based GMMA trading-system confirmations before it's ever acted on:
       - **trend alignment**: the short and long EMA group *centers* must be ordered
         in the called direction by a small margin -- a genuine established trend,
         not a compression reading occurring mid-chop, without requiring the
         unrealistically strict bar of every single EMA in one group clearing every
         single EMA in the other with zero overlap.
       - **relative strength**: the underlying's own trailing 20-trading-day return
         must agree with the called direction -- confirms the trend on a slightly
         slower timescale than the GMMA pattern's own short group, without being so
         slow (an earlier 60-day version) that it's frequently out of phase with an
         otherwise-good GMMA setup.
       - **sufficient liquidity**: the candidate asset's (GEAR's or BBOZ's) own
         volume must be at least 80% of its trailing 20-day average -- a real,
         executable setup, not one on an unusually thin session.
       - **pullback, not an extended move**: price must currently be within 3.5% of
         the short EMA group rather than already stretched further away from it --
         buying the pullback/bounce, not chasing a move that already ran.
     All four filters must pass unanimously before a BBOZ (short) call is acted on --
     see the module-level comments above apply_gmma_filters for how this unanimous
     bar was arrived at (an intermediate any-3-of-4 majority gate, and a core/soft
     split of the four filters, were both tried and superseded on the sibling
     strategy's real history before settling here).
  4b. **GEAR is the default position; BBOZ is a tactical, high-conviction excursion,
      re-checked every session.** resolve_final_decision treats GEAR as the
      unconditional default/home position -- no filter gate is required to hold or
      return to it. The only way out of GEAR is a high-conviction BBOZ call: the raw
      k-NN prediction must itself call BBOZ *and* all 4 confirmation filters above
      must pass unanimously. Once holding BBOZ via that gate, the position is
      re-checked against those same 4 filters every session, independent of the raw
      k-NN's current prediction -- the moment any single filter fails, exit straight
      back to GEAR. There is no CASH resting state in this design -- every session
      holds either GEAR or BBOZ (subject to the fast MA-breakdown and volatility
      overrides below, which can force a switch regardless of the filter gate). Each
      decision's action (ENTER / HOLD / FLIP) is recorded on the ledger row and the
      live signal for transparency.
     ~2 years of history seeds the neighbor pool (the "dev" floor) before any decision
     is evaluated; every session after that is evaluated and chunked into trailing
     non-overlapping ~1-year (52-week) windows for reporting, so performance can be
     checked for stability across several windows rather than trusted from just the
     most recent one.
  5. Compute the trading ledger, portfolio equity curve, and win-rate metrics for the
     most recent window (the main dashboard), the same for each older validation
     window, and the current live/actionable signal (including the raw k-NN call,
     each filter's pass/fail state, and the final gated recommendation, for
     transparency into exactly why a call was taken).
  6. Write the result as flat JSON to public/strategy_data.json.

Zero-brokerage assumption: no fees or slippage are modelled anywhere in this file.
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date as date_cls
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

TICKER_LONG = "GEAR.AX"     # Long geared ASX 200 (~2x, BetaShares Geared Australian Equity Fund)
TICKER_SHORT = "BBOZ.AX"    # Short/inverse geared ASX 200 (BetaShares Australian Strong Bear Hedge Fund)
# Non-leveraged reference index used purely for feature engineering. A much cleaner
# signal than deriving it from the geared products' own leverage-decay/tracking-
# error-contaminated returns. Falls back to the broader All Ordinaries if the
# S&P/ASX 200 fetch fails.
UNDERLYING_TICKER = "^AXJO"
UNDERLYING_FALLBACK_TICKER = "^AORD"

ADELAIDE_TZ = ZoneInfo("Australia/Adelaide")

INITIAL_CAPITAL = 500.00
SESSIONS_PER_WEEK = 2          # Tuesday + Friday
# Minimum dev/training history before any decision is evaluated. Was 5 years on the
# sibling LNAS/SNAS strategy, but that product pair only had ~5.9 years of real
# history in total -- a 5y floor left just ~10 months (2 windows) to actually
# validate against, which isn't enough evidence to tell a real edge from luck. 2
# years is still a generous k=3 neighbor pool (~200 samples) and frees up most of
# the remaining history for validation windows instead.
# (This floor, and the window sizing below, were tuned against the sibling LNAS/SNAS
# strategy this engine is adapted from -- see that project's history for the real
# multi-year sample this traded off against. GEAR.AX/BBOZ.AX may have a different
# amount of real listed history; the runtime NOTE in main() flags it if the actual
# history available is materially shorter than this floor requests.)
TRAIN_WEEKS = 2 * 52
# Window size and count trade off directly against each other within a fixed multi-year
# span of real history. Went through two prior sizes: 26 weeks (the original setting,
# ~6-7 real windows on the sibling LNAS/SNAS strategy) and 13 weeks (shrunk to reach 15
# windows for a finer-grained stability read, at the cost of roughly doubling each
# window's own standard error with only ~26 trades apiece). Settled on 52 weeks/1 year
# per window instead -- a full year covers a much wider range of regimes per window
# (not just a single quarter's conditions) while still being small enough that several
# independent yearly windows fit within a several-year span of history.
HOLDOUT_WEEKS = 52              # ~1 year per reported window; the most recent window is the main dashboard
# How many trailing HOLDOUT_WEEKS-sized windows to evaluate and report, most recent
# first. A single window is too small a sample to trust on its own -- reporting
# several non-overlapping windows shows whether an edge is stable or just this
# window's luck. Set generously high (rather than tuned to a specific target count)
# so it's a non-binding ceiling -- chunk_into_windows already stops once real history
# runs out (dropping a leftover fragment shorter than half a window rather than
# reporting a misleadingly-small partial), so the actual number of windows shown is
# purely however many full 52-week periods the real data supports.
MAX_HOLDOUT_WINDOWS = 50
TOTAL_WEEKS = TRAIN_WEEKS + HOLDOUT_WEEKS * MAX_HOLDOUT_WINDOWS
MIN_TRAIN_SAMPLES = 20         # floor: don't start evaluating anything until the pool has this many samples

TRADING_WEEKDAYS = (1, 4)      # Python weekday(): Monday=0 ... Tuesday=1, Friday=4
DECISION_HOUR = 14             # 2:00 PM local (Adelaide) decision cutoff
K_NEIGHBORS = 3

# Daryl Guppy's classic Multiple Moving Average (GMMA) trend-continuation setup.
# Short ("trader") EMA group reacts to near-term price action; long ("investor") EMA
# group reflects the sustained trend. Three textbook conditions for a continuation
# entry -- price pulling back toward the short group, short EMAs compressing while
# long EMAs stay separated, and price bouncing from the short group -- are
# operationalized as group compression/separation and price's position relative to
# the short group; the k-NN neighbor match finds the "compression + bounce" pattern
# across historical sessions, rather than a hand-coded threshold rule.
GUPPY_SHORT_PERIODS = (3, 5, 8, 10, 12, 15)
GUPPY_LONG_PERIODS = (30, 35, 40, 45, 50, 60)
# Underlying interval return inside this band is treated as "no real trend" -> CASH,
# rather than forcing a directional GEAR/BBOZ call on noise.
FLAT_BAND_PCT = 0.5

# ----------------------------------------------------------------------------------
# Rule-based confirmation filters. The raw k-NN call above is a pure pattern match on
# the compression/separation/pullback shape; these four classic GMMA trading-system
# rules gate whether that call is actually acted on, downgrading to CASH otherwise.
# Each threshold below was already loosened once from an overly strict first pass.
# A 3-of-4 majority gate (any 3 of the 4, regardless of which) was then tried on the
# sibling LNAS/SNAS strategy this engine is adapted from, on the theory that unanimity
# itself -- not the thresholds -- was the dominant cash-driver (only ~24% of CASH
# sessions were a genuine raw FLAT call vs. ~59% a directional call vetoed by a
# filter). On that strategy's real history it backfired: trade count roughly doubled
# and win rate held up (~69% vs ~73%), but total-return variance nearly tripled
# (6-window return stddev +/-7.9 -> +/-22.0) for essentially the same mean return,
# because the extra trades let through were disproportionately the ones failing
# exactly one of trend-alignment/relative-strength -- the two filters that fail
# together ~67% of the time and are precisely what catches a setup about to reverse
# hard. A real HOLD later confirmed the same lesson directly: it rode into a sizeable
# single-session loss with liquidity and pullback both still green, only relative
# strength having flipped. So rather than treat all 4 filters as interchangeable
# votes, an intermediate design split them by role -- trend alignment and relative
# strength as CORE (both required, unanimous), liquidity and pullback as SOFT (only
# one of the two needed) -- before being superseded again below by requiring all 4
# unanimously. This engine carries the final (all-4-unanimous) design forward
# unchanged onto GEAR.AX/BBOZ.AX; see apply_gmma_filters.
# ----------------------------------------------------------------------------------
# Superseded by a long-biased redesign: on the sibling LNAS/SNAS strategy, real data
# showed buy-and-hold the long product beat a neutral-by-default, mostly-cash design
# in 5 of its 6 walk-forward windows (it sat in cash 58-81% of every window's
# sessions, which structurally caps upside during a genuine sustained uptrend).
# resolve_final_decision instead treats GEAR as the unconditional default/home
# position with no filter gate of its own; switching into BBOZ requires all 4 filters
# unanimous (the strictest bar, not just the 2 core ones) plus the raw k-NN call
# itself agreeing, and a held BBOZ position exits back to GEAR the moment any single
# one of those 4 filters fails, independent of the raw call. CASH no longer exists as
# a resting state at all. This long-biased design (validated on LNAS/SNAS) is what
# this engine runs for GEAR/BBOZ from the start, rather than re-deriving it.
# ----------------------------------------------------------------------------------
# Trend alignment: the short/long EMA group *means* must be ordered in the called
# direction by at least this margin. Originally required the entire short EMA range
# to sit above/below the entire long EMA range with zero overlap -- a much stricter
# bar than real GMMA setups usually clear, since the two groups' innermost members
# often brush against each other even in a clean trend. Comparing group centers (with
# a small required margin, rather than a hard zero-overlap requirement) still rejects
# noise-level crossings while tolerating a few EMAs overlapping between groups.
ALIGNMENT_MARGIN_PCT = 0.1
# Relative strength: the underlying's own trailing return must agree with the called
# direction. Shortened from 60 to 20 trading days -- 60 days is a much slower signal
# than the GMMA pattern itself (whose short EMA group reacts in ~3-15 days), so it was
# frequently out of phase with an otherwise-good GMMA setup; 20 days sits closer to
# the GMMA signal's own timescale.
RS_LOOKBACK_DAYS = 20
# Above-average liquidity: the candidate asset's own volume must be at least this
# fraction of its trailing 20-day average (computed on the prior 20 sessions, not
# including today) -- loosened from requiring it exceed the average outright (which a
# literal coin-flip of sessions fails by construction) to a "not unusually thin"
# threshold instead.
LIQUIDITY_LOOKBACK_DAYS = 20
LIQUIDITY_MIN_RATIO = 0.8
# Pullback, not an extended move: price must be within this band of the short EMA
# group (both directions) to count as "pulled back near the group" rather than
# already stretched away from it. Widened from 2.0% to give genuine pullback setups
# more room before being classed as an extended/chasing entry.
PULLBACK_MAX_EXTENSION_PCT = 3.5

# Volatility regime override, independent of the BBOZ gate above, applied regardless
# of what the trend/BBOZ signal says. Added after the long-biased (always-invested)
# redesign showed a much wider return spread across validation windows than the prior
# neutral-by-default design on the sibling LNAS/SNAS strategy (+-20.6 vs +-16.4
# stddev) -- being 100% invested in a leveraged product at all times means every
# window is fully exposed to whatever realized volatility that window happened to
# have. The volatility trigger is
# self-relative -- current short-window realized volatility vs. its own recent
# baseline, not a fixed absolute threshold -- so it transfers across different
# volatility regimes without retuning.
#
# All of the following was worked out against the sibling LNAS/SNAS strategy this
# engine is adapted from; GEAR/BBOZ inherits the resulting design unchanged rather
# than re-deriving it from its own history.
#
# First version simply forced CASH whenever volatility was elevated. Real data showed
# that's too blunt: one volatility spike occurred while price sat below its 50-day MA,
# and the long product went on to rally over the next two sessions -- cash sat out a
# real gain. Another spike occurred while price sat above its 50-day MA, and the long
# product fell over the next six sessions -- cash correctly avoided a real loss. The
# two spikes looked identical on volatility alone; only the price-vs-MA regime
# distinguished a bounce from a real breakdown. So the override is directional, not a
# flat de-risk: elevated volatility with price above its 50-day MA reads as a
# topping/reversal-from-strength pattern (switch to the short product); elevated
# volatility with price still below its 50-day MA reads as an oversold-bounce pattern
# (buy/stay in the long product). There is no CASH state produced by this override --
# it's a directional call, not a flight to safety.
#
# Two follow-up attempts tried to refine the "buy/stay long" half with a 200-day MA
# falling-knife check (first a 7-session lookback, then a same-day check, then a
# same-day check with a 20-day MA reversal confirmation) to keep it from buying a real
# breakdown. Real data showed neither the lookback nor the same-day 200-day MA check
# improved anything, so the 200-day MA approach was abandoned entirely.
#
# The real culprit the 200-day MA attempts were chasing was a *different* session: a
# sizeable single-session loss on the long product that happened during *normal* (not
# elevated) volatility, so it was never even in scope for the elevated_volatility
# branch above -- no amount of tuning the 200-day MA check inside that branch could
# have caught it. Around that date the 20-day MA had crossed below the 50-day MA (a
# short-term downtrend forming under the 50-day trend) shortly beforehand. That
# crossover became its own independent check, evaluated every session regardless of
# volatility regime and ahead of the elevated_volatility branch: 20-day MA below the
# 50-day MA -> short product, *unless* price has already reclaimed the 20-day MA,
# which reads as the reversal already underway -> long product.
#
# The elevated_volatility branch itself (only reached once the crossover above isn't
# active, i.e. the 20-day MA is still at or above the 50-day MA -- a broadly bullish
# MA structure) keys its topping/oversold-bounce call off price vs. the 50-day MA:
# above it during a vol spike reads as topping (-> short product), below it reads as
# an oversold bounce (-> long product). A since-reverted attempt keyed this off the
# 20-day MA instead (the same one the crossover check above uses), on the theory that
# the slower 50-day MA was misreading ordinary bull-market pullbacks as topping. Real
# data proved that wrong: the window the theory targeted came back bit-for-bit
# identical (meaning this branch was never even active during that window), and the
# live window's return regressed, missing a real short-product entry and eating a real
# loss from flipping out of the short product early that the 50-day MA version had
# avoided. Reverted back to the 50-day MA on that evidence.
#
# Real chart evidence for that same underperforming window then showed *why* neither
# override caught its real underperformance either: the long product crashed hard well
# before the window's boundary date, and price was already trading well below its own
# 20-day MA by that point -- but the slower 20-day-vs-50-day MA crossover hadn't
# triggered yet (the 20-day MA was still above the 50-day MA), so neither the
# crossover nor the elevated-volatility branch ever engaged, and the strategy just
# held the long product through the whole decline. Added a third, faster check ahead
# of both: price closing below its own 20-day MA forces the short product immediately,
# regardless of where the slower 50-day MA sits -- it reacts to the crash directly
# instead of waiting for a slower MA to confirm it. The 20/50 crossover above is now
# only reached for sessions where price has already reclaimed the 20-day MA (i.e. it
# can no longer itself force the short product -- only the reversal-underway long call
# survives from it).
REALIZED_VOL_LOOKBACK_DAYS = 10    # ~2 trading weeks: "current" volatility
VOL_BASELINE_LOOKBACK_DAYS = 60    # ~3 months: what's "normal" for this instrument lately
VOL_SPIKE_MULTIPLIER = 1.5         # override triggers once current vol exceeds 1.5x its own baseline
VOL_REGIME_MA_DAYS = 50            # price vs. this MA decides which direction the elevated-vol override takes
SHORT_TERM_MA_DAYS = 20            # crossed below VOL_REGIME_MA_DAYS -> bearish regime; price back above it -> reversal underway

DAILY_FETCH_PERIOD = "10y"      # generous; yfinance returns whatever's actually available
# Yahoo's own intraday retention is interval-dependent, not a yfinance-imposed limit:
# 1m ~7d, {2m,5m,15m,30m,90m} ~60d, {60m/1h} ~730d, 1d+ full history. 60-minute bars
# trade a coarser "at or before 14:00" price (nearest hourly bar, not half-hourly) for
# ~2 years of real intraday coverage instead of ~60 days -- far fewer walk-forward
# sessions fall back to the daily close. Request period must actually match what the
# interval allows, or Yahoo silently caps the response back down to the old window.
INTRADAY_FETCH_PERIOD = "730d"
INTRADAY_INTERVAL = "60m"

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "public" / "strategy_data.json"

CLASS_DOWN, CLASS_FLAT, CLASS_UP = 0, 1, 2
CLASS_TO_ASSET = {CLASS_DOWN: "BBOZ", CLASS_FLAT: "CASH", CLASS_UP: "GEAR"}
CLASS_TO_DIRECTION = {CLASS_DOWN: "DOWN", CLASS_FLAT: "FLAT", CLASS_UP: "UP"}


# --------------------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------------------

@dataclass
class SessionPrice:
    session_date: date_cls
    gear_price: float
    bboz_price: float
    price_source: str  # 'intraday_14:00' | 'intraday_latest_partial' | 'daily_close'
    as_of: datetime


@dataclass
class LedgerEntry:
    decision_date: str
    realization_date: str
    predicted_asset: str
    action: str  # ENTER | HOLD | FLIP | EXIT | CASH -- see resolve_final_decision
    raw_prediction: str
    raw_confidence: float
    filters: dict  # this session's 4 BBOZ-gate filter checks against the bearish direction
    volatility_guard: dict  # volatility regime override check (vol + 50-day MA), independent of the BBOZ gate
    actual_direction: str
    correct: bool
    gear_price: float
    bboz_price: float
    gear_price_at_decision: float  # GEAR price when this decision was made, before its own interval -- the buy-and-hold reference point
    axjo_price: float  # ^AXJO price at realization -- the unleveraged buy-and-hold reference point
    axjo_price_at_decision: float  # ^AXJO price when this decision was made, before its own interval
    interval_return_pct: float
    portfolio_value_before: float
    portfolio_value_after: float
    cumulative_return_pct: float
    price_source: str


# --------------------------------------------------------------------------------------
# Step 1: market data acquisition
# --------------------------------------------------------------------------------------

def fetch_daily(ticker: str, auto_adjust: bool = True) -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=DAILY_FETCH_PERIOD,
        interval="1d",
        auto_adjust=auto_adjust,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No daily data returned for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Daily bars are date labels for a trading session, not real timestamped instants
    # (yfinance reports them at local midnight). Converting that instant across timezones
    # would shift the calendar date backwards (Sydney is always 30/60min ahead of Adelaide),
    # silently dropping sessions -- so we strip tz info and keep the exchange-local date as-is.
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_underlying_daily() -> pd.DataFrame:
    """Reference (non-leveraged) S&P/ASX 200 index for momentum/RSI features. Indices
    don't split, so the default auto_adjust=True (dividend adjustment only, immaterial
    for an index) is fine as-is -- no need for the GEAR/BBOZ split-handling machinery
    here."""
    last_exc: Exception | None = None
    for ticker in (UNDERLYING_TICKER, UNDERLYING_FALLBACK_TICKER):
        try:
            return fetch_daily(ticker)
        except Exception as exc:  # noqa: BLE001
            print(f"[engine] underlying fetch failed for {ticker}: {exc}")
            last_exc = exc
    raise RuntimeError(f"Could not fetch underlying index data from any ticker: {last_exc}")


def fetch_splits(ticker: str) -> pd.Series:
    """Yahoo's recorded split ratios (ex-date -> ratio, e.g. 2.0 for a 2-for-1 split)
    for precise, surgical price adjustment -- see apply_split_adjustment."""
    try:
        splits = yf.Ticker(ticker).splits
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] splits fetch failed for {ticker}: {exc}")
        return pd.Series(dtype=float)
    if splits is None or splits.empty:
        return pd.Series(dtype=float)
    if splits.index.tz is not None:
        splits.index = splits.index.tz_localize(None)
    return splits


def apply_split_adjustment(df: pd.DataFrame, splits: pd.Series) -> pd.DataFrame:
    """Back-adjust a RAW (auto_adjust=False) close series using only Yahoo's recorded
    split ratios -- unlike auto_adjust's opaque combined split+dividend adjustment,
    this applies exactly the known ratio and nothing else, so it can't conflate a split
    with genuine price movement around the same date. Works for both a daily (tz-naive)
    and intraday (tz-aware Adelaide) index since it compares by calendar date."""
    if splits.empty or df.empty:
        return df
    bar_dates = df.index.date
    factor = np.ones(len(df))
    for split_ts, ratio in splits.items():
        split_date = pd.Timestamp(split_ts).date()
        factor[bar_dates < split_date] /= float(ratio)
    adjusted = df.copy()
    adjusted["Close"] = df["Close"].to_numpy() * factor
    return adjusted


def fetch_intraday(ticker: str, auto_adjust: bool = True) -> pd.DataFrame:
    try:
        df = yf.download(
            ticker,
            period=INTRADAY_FETCH_PERIOD,
            interval=INTRADAY_INTERVAL,
            auto_adjust=auto_adjust,
            progress=False,
            threads=False,
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ADELAIDE_TZ)
    return df


def build_session_dates(today: date_cls) -> list[date_cls]:
    start = today - timedelta(weeks=TOTAL_WEEKS)
    dates = []
    d = start
    while d <= today:
        if d.weekday() in TRADING_WEEKDAYS:
            dates.append(d)
        d += timedelta(days=1)
    return dates


def resolve_session_price(
    ticker_daily: pd.DataFrame,
    ticker_intraday: pd.DataFrame,
    session_date: date_cls,
    now_adelaide: datetime,
) -> tuple[float | None, str, datetime | None]:
    """Resolve the actionable price for a given ticker/session.

    Priority:
      1. If the session is today and we're at/after the 14:00 cutoff: the last
         intraday bar at or before 14:00 (the genuine "2pm actionable signal").
      2. If the session is today and we're before the 14:00 cutoff: the latest
         available intraday bar so far today (best-effort partial signal).
      3. If the session is a past date within intraday retention: the last
         intraday bar at or before 14:00 on that date.
      4. Fallback: the daily close for that date.
    """
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=ADELAIDE_TZ).replace(
        hour=DECISION_HOUR
    )
    is_today = session_date == now_adelaide.date()

    if not ticker_intraday.empty:
        day_mask = ticker_intraday.index.date == session_date
        day_bars = ticker_intraday.loc[day_mask]
        if not day_bars.empty:
            if is_today and now_adelaide < cutoff:
                bar = day_bars.iloc[-1]
                return float(bar["Close"]), "intraday_latest_partial", day_bars.index[-1].to_pydatetime()
            at_or_before_cutoff = day_bars.loc[day_bars.index <= cutoff]
            if not at_or_before_cutoff.empty:
                bar = at_or_before_cutoff.iloc[-1]
                return float(bar["Close"]), "intraday_14:00", at_or_before_cutoff.index[-1].to_pydatetime()

    if not ticker_daily.empty:
        day_mask = ticker_daily.index.date == session_date
        day_rows = ticker_daily.loc[day_mask]
        if not day_rows.empty:
            row = day_rows.iloc[-1]
            return float(row["Close"]), "daily_close", day_rows.index[-1].to_pydatetime()

    return None, "unavailable", None


def build_session_price_series(
    session_dates: list[date_cls],
    gear_daily: pd.DataFrame,
    gear_intraday: pd.DataFrame,
    bboz_daily: pd.DataFrame,
    bboz_intraday: pd.DataFrame,
    now_adelaide: datetime,
) -> list[SessionPrice]:
    out: list[SessionPrice] = []
    for sd in session_dates:
        gear_px, gear_src, gear_ts = resolve_session_price(gear_daily, gear_intraday, sd, now_adelaide)
        bboz_px, bboz_src, bboz_ts = resolve_session_price(bboz_daily, bboz_intraday, sd, now_adelaide)
        if gear_px is None or bboz_px is None:
            continue  # market holiday / no data for this session (or product not listed yet), skip
        source = gear_src if gear_src == bboz_src else f"{gear_src}+{bboz_src}"
        as_of = max([t for t in (gear_ts, bboz_ts) if t is not None])
        out.append(SessionPrice(sd, gear_px, bboz_px, source, as_of))
    return out


# --------------------------------------------------------------------------------------
# Step 2: feature engineering
# --------------------------------------------------------------------------------------

def compute_return_series(prices: list[float]) -> list[float]:
    """r[i] = prices[i]/prices[i-1] - 1, r[0] is undefined (NaN placeholder)."""
    returns = [float("nan")]
    for i in range(1, len(prices)):
        returns.append(prices[i] / prices[i - 1] - 1.0)
    return returns


# Largest single-interval (~3-4 trading day, Tue/Fri) move considered organic for a
# geared/inverse-geared ASX 200 product. Anything beyond this is treated as a scale discontinuity
# rather than a real return. Known splits are now handled precisely upstream via
# apply_split_adjustment(), so by the time a price series reaches this function, a
# trip over the threshold means either a split Yahoo hasn't recorded yet or a genuinely
# unexplained data artifact -- either way, letting it stand would corrupt both the k-NN
# training labels and the portfolio P&L, so it's rebased and flagged as residual/
# unexplained for a human to double check. Not applied to the underlying index, which
# doesn't split and where a genuine >30% move is real news.
MAX_PLAUSIBLE_INTERVAL_MOVE = 0.30


def desplit_session_prices(prices: list[float], ticker: str, threshold: float = MAX_PLAUSIBLE_INTERVAL_MOVE) -> list[float]:
    """Rebase any prefix of the series across an implausible single-interval jump so the
    whole series reads as one continuous scale. This is the residual fallback for jumps
    NOT explained by a known split (those are already handled by apply_split_adjustment
    before this runs) -- so every trip here is logged as unexplained and worth a look."""
    corrected = list(prices)
    for i in range(1, len(corrected)):
        if corrected[i - 1] == 0:
            continue
        ratio = corrected[i] / corrected[i - 1]
        if abs(ratio - 1.0) > threshold:
            print(
                f"[engine] WARNING: {ticker} unexplained interval move at session {i} "
                f"({corrected[i - 1]:.4f} -> {corrected[i]:.4f}, {(ratio - 1) * 100:+.1f}%) with no "
                f"matching recorded split; treating as a residual scale discontinuity and "
                f"rebasing {i} prior session(s)."
            )
            for j in range(i):
                corrected[j] *= ratio
    return corrected


def compute_daily_indicators(daily_df: pd.DataFrame) -> pd.DataFrame:
    """GMMA indicator series from a single daily close series (computed on the
    non-leveraged reference index): short/long EMA group compression, separation,
    price's position relative to the short group (the k-NN's 3 features), plus the
    two rule-based confirmation signals derived from the same EMA groups -- trend
    alignment and relative strength."""
    close = daily_df["Close"]

    short_emas = [close.ewm(span=p, min_periods=p, adjust=False).mean() for p in GUPPY_SHORT_PERIODS]
    long_emas = [close.ewm(span=p, min_periods=p, adjust=False).mean() for p in GUPPY_LONG_PERIODS]
    short_group = pd.concat(short_emas, axis=1)
    long_group = pd.concat(long_emas, axis=1)
    short_mean = short_group.mean(axis=1)
    long_mean = long_group.mean(axis=1)
    # Coefficient of variation within each group: low = the group's EMAs are bunched
    # together (compressed), high = they're fanned out (separated/trending).
    short_group_compression = short_group.std(axis=1) / short_mean * 100.0
    long_group_separation = long_group.std(axis=1) / long_mean * 100.0
    price_vs_short_group = (close - short_mean) / short_mean * 100.0

    # Trend alignment: the short ("trader") and long ("investor") group *centers* are
    # ordered in the called direction by at least ALIGNMENT_MARGIN_PCT -- a looser bar
    # than requiring every single short EMA to clear every single long EMA with zero
    # overlap, which real GMMA setups often don't clear even in a clean trend. Only
    # valid once every EMA in both groups has completed its own warmup.
    groups_ready = short_group.notna().all(axis=1) & long_group.notna().all(axis=1)
    center_gap_pct = (short_mean - long_mean) / long_mean * 100.0
    bullish_alignment = (center_gap_pct > ALIGNMENT_MARGIN_PCT).astype(float).where(groups_ready)
    bearish_alignment = (center_gap_pct < -ALIGNMENT_MARGIN_PCT).astype(float).where(groups_ready)

    # Relative strength: is the underlying itself actually trending in the candidate
    # direction over a slightly slower window than the GMMA pattern's own short group,
    # rather than just exhibiting a short-lived compression that could resolve either way.
    rs = (close / close.shift(RS_LOOKBACK_DAYS) - 1.0) * 100.0

    out = pd.DataFrame(
        {
            "short_group_compression": short_group_compression,
            "long_group_separation": long_group_separation,
            "price_vs_short_group": price_vs_short_group,
            "bullish_alignment": bullish_alignment,
            "bearish_alignment": bearish_alignment,
            "rs": rs,
        }
    )
    out.index = daily_df.index
    return out


def compute_liquidity_indicator(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Liquidity filter for one candidate asset (GEAR or BBOZ): today's volume vs.
    LIQUIDITY_MIN_RATIO of its own trailing LIQUIDITY_LOOKBACK_DAYS average, computed
    from the prior sessions only (shifted by 1) so it's a genuinely already-known-at-
    decision-time average rather than one contaminated by including today's own
    volume. Not-thin liquidity, not literally above average."""
    volume = daily_df["Volume"]
    avg_volume = volume.rolling(LIQUIDITY_LOOKBACK_DAYS).mean().shift(1)
    sufficient_liquidity = (volume >= avg_volume * LIQUIDITY_MIN_RATIO).astype(float).where(avg_volume.notna())
    out = pd.DataFrame({"sufficient_liquidity": sufficient_liquidity})
    out.index = daily_df.index
    return out


def compute_volatility_indicator(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Volatility/regime override inputs (see VOL_*/SHORT_TERM_MA_DAYS constants
    above), computed on the same non-leveraged underlying series used for the
    GMMA/RS features. Current REALIZED_VOL_LOOKBACK_DAYS realized volatility is
    compared against its own trailing VOL_BASELINE_LOOKBACK_DAYS baseline (shifted
    by 1 so the current spike can't inflate its own reference baseline) --
    self-relative rather than a fixed absolute threshold, so it holds up across
    different volatility regimes without retuning. price_above_ma decides which
    direction the elevated-volatility override takes; ma20_below_ma50 and
    above_short_ma together drive the independent 20/50-day MA crossover check
    (see resolve_final_decision). All MA checks are same-day, not a lookback
    window -- an earlier version of a since-abandoned 200-day MA check used a
    7-session lookback, but real data showed that kept a bear-regime call
    "sticky" for up to a week after a single dip even once price had already
    recovered."""
    close = daily_df["Close"]
    daily_returns = close.pct_change()
    realized_vol = daily_returns.rolling(REALIZED_VOL_LOOKBACK_DAYS).std() * 100.0
    baseline_vol = realized_vol.rolling(VOL_BASELINE_LOOKBACK_DAYS).mean().shift(1)
    elevated = (realized_vol > baseline_vol * VOL_SPIKE_MULTIPLIER).astype(float).where(baseline_vol.notna())
    ma = close.rolling(VOL_REGIME_MA_DAYS).mean()
    above_ma = (close > ma).astype(float).where(ma.notna())
    short_ma = close.rolling(SHORT_TERM_MA_DAYS).mean()
    above_short_ma = (close > short_ma).astype(float).where(short_ma.notna())
    ma20_below_ma50 = (short_ma < ma).astype(float).where(ma.notna() & short_ma.notna())
    out = pd.DataFrame(
        {
            "realized_vol_pct": realized_vol,
            "elevated_volatility": elevated,
            "price_above_ma": above_ma,
            "ma20_below_ma50": ma20_below_ma50,
            "above_short_ma": above_short_ma,
        }
    )
    out.index = daily_df.index
    return out


def asof_value(dates: np.ndarray, values: np.ndarray, target_date: date_cls) -> float | None:
    """Most recent value at or before target_date; None if not yet available."""
    idx = int(np.searchsorted(dates, target_date, side="right")) - 1
    if idx < 0 or idx >= len(values) or np.isnan(values[idx]):
        return None
    return float(values[idx])


def standardize(train_x: list[list[float]], query_x: list[float]) -> tuple[list[list[float]], list[float]]:
    """Z-score standardize using only the training pool available at this walk-forward
    step (no lookahead), so heterogeneous feature scales (return % vs RSI 0-100 vs
    log-volume) don't dominate the Euclidean distance."""
    if not train_x:
        return [], list(query_x)
    arr = np.array(train_x, dtype=float)
    mean = arr.mean(axis=0)
    std = arr.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    train_scaled = ((arr - mean) / std).tolist()
    query_scaled = ((np.array(query_x, dtype=float) - mean) / std).tolist()
    return train_scaled, query_scaled


def knn_predict(x_train: list[list[float]], y_train: list[int], x_query: list[float], k: int) -> tuple[int, float]:
    """Manual Euclidean k-NN over 3 classes, inverse-distance-weighted so a very close
    neighbor counts for more than a barely-in-the-top-k one, rather than every one of
    the k neighbors getting an equal, unweighted vote. Transparent and
    dependency-light -- no external ML library needed."""
    if len(x_train) == 0:
        return CLASS_FLAT, 1 / 3  # no history yet: default to no exposure rather than guessing a direction
    k_eff = min(k, len(x_train))
    dists = []
    for xt, yt in zip(x_train, y_train):
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(xt, x_query)))
        dists.append((d, yt))
    dists.sort(key=lambda t: t[0])
    neighbors = dists[:k_eff]

    weights: dict[int, float] = {}
    total_weight = 0.0
    for d, yt in neighbors:
        w = 1.0 / (d + 1e-9)  # epsilon guards an exact-duplicate (zero-distance) neighbor
        weights[yt] = weights.get(yt, 0.0) + w
        total_weight += w

    prediction = max(weights, key=weights.get)
    confidence = weights[prediction] / total_weight if total_weight > 0 else 1 / k_eff
    return prediction, confidence


def apply_gmma_filters(
    prediction: int,
    price_vs_short_group: float,
    bullish_alignment: bool,
    bearish_alignment: bool,
    rs: float,
    gear_sufficient_liquidity: bool,
    bboz_sufficient_liquidity: bool,
) -> dict[str, dict]:
    """Evaluate the four classic GMMA trading-system confirmation rules against a
    given direction (always CLASS_DOWN/BBOZ in the current long-biased design --
    see resolve_final_decision) and return each filter's own pass/fail state with
    detail, for both gating the BBOZ decision and transparency in the live signal
    and ledger."""
    not_extended = abs(price_vs_short_group) <= PULLBACK_MAX_EXTENSION_PCT

    if prediction == CLASS_UP:
        return {
            "trendAlignment": {"pass": bullish_alignment, "detail": "bullish"},
            "relativeStrength": {"pass": rs > 0, "detail": f"{rs:+.2f}% vs required > 0%"},
            "liquidity": {"pass": gear_sufficient_liquidity, "detail": f"GEAR.AX volume vs {LIQUIDITY_MIN_RATIO:.0%} of its {LIQUIDITY_LOOKBACK_DAYS}-day average"},
            "pullbackNotExtended": {"pass": not_extended, "detail": f"{price_vs_short_group:+.2f}% vs short EMA group"},
        }
    if prediction == CLASS_DOWN:
        return {
            "trendAlignment": {"pass": bearish_alignment, "detail": "bearish"},
            "relativeStrength": {"pass": rs < 0, "detail": f"{rs:+.2f}% vs required < 0%"},
            "liquidity": {"pass": bboz_sufficient_liquidity, "detail": f"BBOZ.AX volume vs {LIQUIDITY_MIN_RATIO:.0%} of its {LIQUIDITY_LOOKBACK_DAYS}-day average"},
            "pullbackNotExtended": {"pass": not_extended, "detail": f"{price_vs_short_group:+.2f}% vs short EMA group"},
        }
    # FLAT: filters don't apply to sitting out.
    return {
        "trendAlignment": {"pass": True, "detail": "n/a (flat)"},
        "relativeStrength": {"pass": True, "detail": "n/a (flat)"},
        "liquidity": {"pass": True, "detail": "n/a (flat)"},
        "pullbackNotExtended": {"pass": True, "detail": "n/a (flat)"},
    }


def resolve_final_decision(
    raw_prediction: int,
    bear_checks: dict,
    current_holding_class: int,
    elevated_volatility: bool,
    price_above_ma: bool,
    ma20_below_ma50: bool,
    above_short_ma: bool,
) -> tuple[int, str]:
    """Long-biased position resolution. GEAR is the unconditional default/home
    position -- entering or staying in it requires no filter gate of its own.
    One exception is a high-conviction BBOZ call: switching out of GEAR requires
    the raw k-NN prediction to itself call BBOZ (DOWN) *and* all 4 rule-based
    confirmation filters, evaluated in the BBOZ/bearish direction, to pass
    unanimously -- the strictest bar available, since shorting a leveraged
    product via BBOZ should be a high-conviction decision, not a marginal one
    ("meets our criteria perfectly").

    Once holding BBOZ via that gate, the position is re-checked against those
    same 4 filters every session, independent of what the raw k-NN currently
    predicts -- the moment any single one of them fails, exit straight back to
    GEAR ("doesn't remain solid").

    Three further exceptions override the GEAR-default/BBOZ-gate logic above,
    checked in this order. All three were worked out against the sibling
    LNAS/SNAS strategy this engine is adapted from and are carried over
    unchanged rather than re-derived from GEAR/BBOZ's own history:

    1. The fast 20-day MA breakdown: whenever price closes below its own
    20-day MA, force BBOZ immediately, regardless of volatility regime or
    where the slower 50-day MA sits. Real chart evidence from the sibling
    strategy's own underperforming window showed why this is needed: the long
    product crashed hard well before that window's boundary date, and price
    was already trading well below its 20-day MA by that boundary -- but the
    slower 20/50 MA crossover below hadn't triggered yet (the 20-day MA was
    still above the 50-day MA at that point), so nothing caught the crash and
    the strategy held the long product through the whole decline. This check
    reacts to price directly instead of waiting for a slower MA to confirm.

    2. The 20/50-day MA crossover, checked every session regardless of
    volatility regime, for sessions where price has already reclaimed the
    20-day MA (so exception 1 above doesn't apply): 20-day MA still below the
    50-day MA reads as the medium-term trend not yet confirming the reversal
    -> stay in BBOZ is *not* forced here, since price is back above the fast
    MA -- GEAR instead. This runs ahead of (and independent of) the volatility
    override below because the sizeable real loss it originally targeted (on
    the sibling strategy) happened during *normal*, not elevated, volatility --
    gating it behind elevated_volatility would never have caught it.

    3. The volatility regime override: whenever realized volatility is elevated
    (see VOL_* constants) and neither exception above is already active, the
    position is forced directionally rather than left to the trend/BBOZ signal,
    since neither reliably predicts a volatility spike in advance. Elevated
    volatility with price above its 50-day MA reads as a
    topping/reversal-from-strength pattern -> BBOZ. Elevated volatility with
    price below its 50-day MA reads as an oversold-bounce pattern -> GEAR. A
    since-reverted version keyed this off the 20-day MA instead, on the theory
    that the slower 50-day MA was misreading ordinary bull-market pullbacks as
    topping. Real data on the sibling strategy proved that wrong: the window
    the theory targeted came back bit-for-bit identical (meaning this branch
    was never even active during that window), and the live window's return
    regressed, missing a real BBOZ-equivalent entry and eating a real loss from
    flipping out of that position early that the 50-day MA version had avoided.

    There is no CASH state in this design -- once none of the three exceptions
    apply, the next decision falls back to the ordinary GEAR-default/BBOZ-gate
    logic above."""
    if not above_short_ma:
        final = CLASS_DOWN
    elif ma20_below_ma50:
        final = CLASS_UP
    elif elevated_volatility:
        final = CLASS_DOWN if price_above_ma else CLASS_UP
    else:
        bboz_all_pass = all(c["pass"] for c in bear_checks.values())
        if current_holding_class == CLASS_DOWN:
            final = CLASS_DOWN if bboz_all_pass else CLASS_UP
        else:
            final = CLASS_DOWN if (raw_prediction == CLASS_DOWN and bboz_all_pass) else CLASS_UP

    if final == current_holding_class:
        action = "HOLD"
    elif current_holding_class == CLASS_FLAT:
        action = "ENTER"
    else:
        action = "FLIP"
    return final, action


@dataclass
class RawDecision:
    """A single walk-forward decision before portfolio simulation is applied. Kept
    separate from LedgerEntry so the same decision stream can be re-simulated
    independently per validation window (each window gets its own fresh $500 seed,
    rather than one continuous multi-year compounding run)."""
    decision_date: date_cls
    realization_date: date_cls
    predicted_asset: str
    action: str
    raw_prediction: str
    raw_confidence: float
    filters: dict
    volatility_guard: dict
    actual_direction: str
    correct: bool
    gear_price: float
    bboz_price: float
    gear_price_at_decision: float
    axjo_price: float
    axjo_price_at_decision: float
    applied_return: float
    price_source: str


def simulate_window(decisions: list[RawDecision]) -> list[LedgerEntry]:
    """Independent $500-seeded portfolio simulation over one window's decisions."""
    ledger: list[LedgerEntry] = []
    portfolio_value = INITIAL_CAPITAL
    for d in decisions:
        value_before = portfolio_value
        portfolio_value = portfolio_value * (1.0 + d.applied_return)
        cumulative_return_pct = (portfolio_value / INITIAL_CAPITAL - 1.0) * 100.0
        ledger.append(
            LedgerEntry(
                decision_date=d.decision_date.isoformat(),
                realization_date=d.realization_date.isoformat(),
                predicted_asset=d.predicted_asset,
                action=d.action,
                raw_prediction=d.raw_prediction,
                raw_confidence=d.raw_confidence,
                filters=d.filters,
                volatility_guard=d.volatility_guard,
                actual_direction=d.actual_direction,
                correct=d.correct,
                gear_price=round(d.gear_price, 4),
                bboz_price=round(d.bboz_price, 4),
                gear_price_at_decision=round(d.gear_price_at_decision, 4),
                axjo_price=round(d.axjo_price, 4),
                axjo_price_at_decision=round(d.axjo_price_at_decision, 4),
                interval_return_pct=round(d.applied_return * 100.0, 4),
                portfolio_value_before=round(value_before, 4),
                portfolio_value_after=round(portfolio_value, 4),
                cumulative_return_pct=round(cumulative_return_pct, 4),
                price_source=d.price_source,
            )
        )
    return ledger


def chunk_into_windows(decisions: list[RawDecision]) -> list[list[RawDecision]]:
    """Split a chronological decision stream into up to MAX_HOLDOUT_WINDOWS trailing
    non-overlapping windows of HOLDOUT_WEEKS each, most recent first. A leftover
    fragment shorter than half a window at the oldest end is dropped rather than
    reported as a partial, misleadingly-small window."""
    window_size = HOLDOUT_WEEKS * SESSIONS_PER_WEEK
    windows: list[list[RawDecision]] = []
    end = len(decisions)
    while end > 0 and len(windows) < MAX_HOLDOUT_WINDOWS:
        start = max(0, end - window_size)
        chunk = decisions[start:end]
        if len(chunk) < window_size // 2:
            break
        windows.append(chunk)
        end = start
    return windows


@dataclass
class WalkForwardResult:
    ledger: list[LedgerEntry] = field(default_factory=list)
    live_signal: dict | None = None
    validation_windows: list[dict] = field(default_factory=list)


def walk_forward_backtest(
    sessions: list[SessionPrice],
    underlying_daily: pd.DataFrame,
    gear_daily: pd.DataFrame,
    bboz_daily: pd.DataFrame,
) -> WalkForwardResult:
    n = len(sessions)
    session_dates = [s.session_date for s in sessions]
    gear_prices = desplit_session_prices([s.gear_price for s in sessions], "GEAR.AX")
    bboz_prices = desplit_session_prices([s.bboz_price for s in sessions], "BBOZ.AX")
    r_gear = compute_return_series(gear_prices)
    r_bboz = compute_return_series(bboz_prices)

    underlying_dates = underlying_daily.index.date
    underlying_close = underlying_daily["Close"].to_numpy()
    indicators = compute_daily_indicators(underlying_daily)
    underlying_short_compression = indicators["short_group_compression"].to_numpy()
    underlying_long_separation = indicators["long_group_separation"].to_numpy()
    underlying_price_vs_short = indicators["price_vs_short_group"].to_numpy()
    underlying_bullish_alignment = indicators["bullish_alignment"].to_numpy()
    underlying_bearish_alignment = indicators["bearish_alignment"].to_numpy()
    underlying_rs = indicators["rs"].to_numpy()

    gear_liquidity = compute_liquidity_indicator(gear_daily)
    bboz_liquidity = compute_liquidity_indicator(bboz_daily)
    gear_liq_dates = gear_liquidity.index.date
    bboz_liq_dates = bboz_liquidity.index.date
    gear_liq_values = gear_liquidity["sufficient_liquidity"].to_numpy()
    bboz_liq_values = bboz_liquidity["sufficient_liquidity"].to_numpy()

    volatility = compute_volatility_indicator(underlying_daily)
    underlying_realized_vol = volatility["realized_vol_pct"].to_numpy()
    underlying_elevated_vol = volatility["elevated_volatility"].to_numpy()
    underlying_price_above_ma = volatility["price_above_ma"].to_numpy()
    underlying_ma20_below_ma50 = volatility["ma20_below_ma50"].to_numpy()
    underlying_above_short_ma = volatility["above_short_ma"].to_numpy()

    underlying_session_prices = []
    for sd in session_dates:
        px = asof_value(underlying_dates, underlying_close, sd)
        if px is None:
            raise RuntimeError(f"No underlying index price available as of {sd}")
        underlying_session_prices.append(px)
    # Needed only for the label (next-interval underlying direction).
    r_underlying = compute_return_series(underlying_session_prices)

    short_compression_at_session = [asof_value(underlying_dates, underlying_short_compression, sd) for sd in session_dates]
    long_separation_at_session = [asof_value(underlying_dates, underlying_long_separation, sd) for sd in session_dates]
    price_vs_short_at_session = [asof_value(underlying_dates, underlying_price_vs_short, sd) for sd in session_dates]
    bullish_alignment_at_session = [asof_value(underlying_dates, underlying_bullish_alignment, sd) for sd in session_dates]
    bearish_alignment_at_session = [asof_value(underlying_dates, underlying_bearish_alignment, sd) for sd in session_dates]
    rs_at_session = [asof_value(underlying_dates, underlying_rs, sd) for sd in session_dates]
    gear_liq_at_session = [asof_value(gear_liq_dates, gear_liq_values, sd) for sd in session_dates]
    bboz_liq_at_session = [asof_value(bboz_liq_dates, bboz_liq_values, sd) for sd in session_dates]
    realized_vol_at_session = [asof_value(underlying_dates, underlying_realized_vol, sd) for sd in session_dates]
    elevated_vol_at_session = [asof_value(underlying_dates, underlying_elevated_vol, sd) for sd in session_dates]
    price_above_ma_at_session = [asof_value(underlying_dates, underlying_price_above_ma, sd) for sd in session_dates]
    ma20_below_ma50_at_session = [asof_value(underlying_dates, underlying_ma20_below_ma50, sd) for sd in session_dates]
    above_short_ma_at_session = [asof_value(underlying_dates, underlying_above_short_ma, sd) for sd in session_dates]

    def features_at(i: int) -> list[float] | None:
        short_v = short_compression_at_session[i]
        long_v = long_separation_at_session[i]
        pos_v = price_vs_short_at_session[i]
        if any(v is None for v in (short_v, long_v, pos_v)):
            return None  # GMMA EMA warm-up not yet complete (earliest dev history only)
        return [short_v, long_v, pos_v]

    def filter_inputs_at(i: int) -> tuple[bool, bool, float, bool, bool] | None:
        bull_v = bullish_alignment_at_session[i]
        bear_v = bearish_alignment_at_session[i]
        rs_v = rs_at_session[i]
        gear_liq_v = gear_liq_at_session[i]
        bboz_liq_v = bboz_liq_at_session[i]
        if any(v is None for v in (bull_v, bear_v, rs_v, gear_liq_v, bboz_liq_v)):
            return None  # filter warm-up not yet complete (RS lookback / liquidity lookback / EMA warmup)
        return bool(bull_v), bool(bear_v), rs_v, bool(gear_liq_v), bool(bboz_liq_v)

    def volatility_at(i: int) -> tuple[bool, float, bool, bool, bool] | None:
        elevated_v = elevated_vol_at_session[i]
        vol_v = realized_vol_at_session[i]
        above_ma_v = price_above_ma_at_session[i]
        ma20_below_ma50_v = ma20_below_ma50_at_session[i]
        above_short_v = above_short_ma_at_session[i]
        if elevated_v is None or vol_v is None or above_ma_v is None or ma20_below_ma50_v is None or above_short_v is None:
            return None  # volatility warm-up not yet complete (needs the 60-day baseline / 20-day / 50-day MA)
        return bool(elevated_v), vol_v, bool(above_ma_v), bool(ma20_below_ma50_v), bool(above_short_v)

    def label_at(i: int) -> int:
        r = r_underlying[i + 1]
        band = FLAT_BAND_PCT / 100.0
        if r > band:
            return CLASS_UP
        if r < -band:
            return CLASS_DOWN
        return CLASS_FLAT

    samples_x: list[list[float]] = []
    samples_y: list[int] = []
    raw_decisions: list[RawDecision] = []
    # Tracks the position actually held going into each decision -- GEAR is the
    # default/home position, only CLASS_FLAT before the very first decision ever
    # made; see resolve_final_decision for the long-biased GEAR/BBOZ resolution.
    current_holding_class = CLASS_FLAT

    result = WalkForwardResult()

    # Evaluate every session once the training pool has at least TRAIN_WEEKS of
    # history seeded (the "dev" floor), rather than only the trailing HOLDOUT_WEEKS --
    # this is what lets chunk_into_windows() report multiple non-overlapping windows
    # when enough history exists, instead of just the single most recent one. Each
    # decision still only ever trains on strictly prior sessions (no look-ahead); the
    # pool keeps growing through the whole evaluated range, so later windows benefit
    # from richer training data than the dev floor alone, exactly as genuine
    # walk-forward should work.
    dev_sessions = min(TRAIN_WEEKS * SESSIONS_PER_WEEK, max(n - 3, 0))
    test_start = max(dev_sessions, 2)

    skipped_warmup = 0

    for i in range(2, n - 1):
        feats_i = features_at(i)
        filters_i = filter_inputs_at(i)
        vol_i = volatility_at(i)
        if feats_i is None or filters_i is None or vol_i is None:
            skipped_warmup += 1
            continue
        y_i = label_at(i)

        if i >= test_start and len(samples_y) >= MIN_TRAIN_SAMPLES:
            train_x, query_x = standardize(samples_x, feats_i)
            raw_prediction, confidence = knn_predict(train_x, samples_y, query_x, K_NEIGHBORS)
            checks = apply_gmma_filters(CLASS_DOWN, feats_i[2], *filters_i)
            elevated_vol, realized_vol_pct, above_ma, ma20_below_ma50, above_short_ma = vol_i
            volatility_check = {
                "pass": above_short_ma and not ma20_below_ma50 and not elevated_vol,
                "detail": f"price {'above' if above_short_ma else 'below'} its {SHORT_TERM_MA_DAYS}-day MA;"
                f" {SHORT_TERM_MA_DAYS}-day MA {'below' if ma20_below_ma50 else 'above'} its {VOL_REGIME_MA_DAYS}-day MA;"
                f" {realized_vol_pct:.2f}% realized {REALIZED_VOL_LOOKBACK_DAYS}-day vol"
                f" ({'elevated' if elevated_vol else 'normal'} vs its own {VOL_BASELINE_LOOKBACK_DAYS}-day baseline);"
                f" price {'above' if above_ma else 'below'} its {VOL_REGIME_MA_DAYS}-day MA",
            }
            final_prediction, action = resolve_final_decision(
                raw_prediction, checks, current_holding_class, elevated_vol, above_ma, ma20_below_ma50, above_short_ma
            )
            predicted_asset = CLASS_TO_ASSET[final_prediction]
            if predicted_asset == "GEAR":
                applied_return = r_gear[i + 1]
            elif predicted_asset == "BBOZ":
                applied_return = r_bboz[i + 1]
            else:
                applied_return = 0.0  # CASH: zero brokerage, so genuinely flat

            raw_decisions.append(
                RawDecision(
                    decision_date=sessions[i].session_date,
                    realization_date=sessions[i + 1].session_date,
                    predicted_asset=predicted_asset,
                    action=action,
                    raw_prediction=CLASS_TO_ASSET[raw_prediction],
                    raw_confidence=round(confidence, 4),
                    filters=checks,
                    volatility_guard=volatility_check,
                    actual_direction=CLASS_TO_DIRECTION[y_i],
                    correct=(final_prediction == y_i),
                    gear_price=gear_prices[i + 1],
                    bboz_price=bboz_prices[i + 1],
                    gear_price_at_decision=gear_prices[i],
                    axjo_price=underlying_session_prices[i + 1],
                    axjo_price_at_decision=underlying_session_prices[i],
                    applied_return=applied_return,
                    price_source=sessions[i + 1].price_source,
                )
            )
            current_holding_class = final_prediction

        # this session's outcome is now known -> add it to the training set
        samples_x.append(feats_i)
        samples_y.append(y_i)

    if skipped_warmup:
        print(f"[engine] skipped {skipped_warmup} early session(s) while GMMA indicators/filters warmed up")

    windows = chunk_into_windows(raw_decisions)
    if not windows:
        raise RuntimeError("Not enough post-warmup session history to evaluate even one holdout window")
    print(f"[engine] evaluated {len(raw_decisions)} decisions across {len(windows)} trailing {HOLDOUT_WEEKS}-week window(s)")

    for idx, window in enumerate(windows):
        window_ledger = simulate_window(window)
        window_metrics = compute_metrics(window_ledger)
        entry = {
            "windowIndex": idx,
            "startDate": window_ledger[0].decision_date,
            "endDate": window_ledger[-1].realization_date,
            **window_metrics,
        }
        result.validation_windows.append(entry)
        if idx == 0:
            # The most recent window is the one the main dashboard (ledger/portfolio/
            # chart) reports, matching prior behaviour.
            result.ledger = window_ledger

    # live/actionable signal: decision made at the most recent session for the upcoming interval
    live_i = n - 1
    feats_live = features_at(live_i)
    filters_live = filter_inputs_at(live_i)
    vol_live = volatility_at(live_i)
    if feats_live is None or filters_live is None or vol_live is None:
        raise RuntimeError("GMMA indicators/filters/volatility not available for the most recent session")
    train_x, query_x = standardize(samples_x, feats_live)
    raw_prediction, confidence = knn_predict(train_x, samples_y, query_x, K_NEIGHBORS)
    checks = apply_gmma_filters(CLASS_DOWN, feats_live[2], *filters_live)
    elevated_vol_live, realized_vol_pct_live, above_ma_live, ma20_below_ma50_live, above_short_ma_live = vol_live
    volatility_check_live = {
        "pass": above_short_ma_live and not ma20_below_ma50_live and not elevated_vol_live,
        "detail": f"price {'above' if above_short_ma_live else 'below'} its {SHORT_TERM_MA_DAYS}-day MA;"
        f" {SHORT_TERM_MA_DAYS}-day MA {'below' if ma20_below_ma50_live else 'above'} its {VOL_REGIME_MA_DAYS}-day MA;"
        f" {realized_vol_pct_live:.2f}% realized {REALIZED_VOL_LOOKBACK_DAYS}-day vol"
        f" ({'elevated' if elevated_vol_live else 'normal'} vs its own {VOL_BASELINE_LOOKBACK_DAYS}-day baseline);"
        f" price {'above' if above_ma_live else 'below'} its {VOL_REGIME_MA_DAYS}-day MA",
    }
    final_prediction, live_action = resolve_final_decision(
        raw_prediction, checks, current_holding_class, elevated_vol_live, above_ma_live, ma20_below_ma50_live, above_short_ma_live
    )
    predicted_asset = CLASS_TO_ASSET[final_prediction]
    latest = sessions[live_i]
    current_window_streak = result.validation_windows[0]["currentStreak"]
    result.live_signal = {
        "asOfSessionDate": latest.session_date.isoformat(),
        "asOfTimestamp": latest.as_of.isoformat(),
        "priceSource": latest.price_source,
        "rawPrediction": CLASS_TO_ASSET[raw_prediction],
        "recommendedAsset": predicted_asset,
        "action": live_action,
        "currentlyHolding": CLASS_TO_ASSET[current_holding_class],
        "confidence": round(confidence, 4),
        "features": {
            "shortGroupCompressionPct": round(feats_live[0], 4),
            "longGroupSeparationPct": round(feats_live[1], 4),
            "priceVsShortGroupPct": round(feats_live[2], 4),
        },
        "filters": checks,
        "volatilityGuard": volatility_check_live,
        "lastPrices": {
            "GEAR": round(gear_prices[live_i], 4),
            "BBOZ": round(bboz_prices[live_i], 4),
        },
        "trainingSamples": len(samples_y),
        "currentStreak": current_window_streak,
    }
    return result


# --------------------------------------------------------------------------------------
# Step 3: metrics + JSON assembly
# --------------------------------------------------------------------------------------

def compute_asset_breakdown(ledger: list[LedgerEntry]) -> dict:
    """Per-asset (GEAR vs BBOZ) accuracy and profit-contribution breakdown -- how many
    of each asset's calls won vs lost, and how much of the total dollar profit each
    asset's trades actually contributed. The dollar figure is exact, not an estimate:
    each trade's own portfolio_value_after - portfolio_value_before already reflects
    its place in the same chronological compounding path used for the portfolio
    total, so summing it per asset partitions the total profit exactly (GEAR + BBOZ +
    CASH's always-zero contribution == final_value - initial_capital)."""
    total_profit = (ledger[-1].portfolio_value_after - INITIAL_CAPITAL) if ledger else 0.0
    out = {}
    for asset in ("GEAR", "BBOZ"):
        rows = [e for e in ledger if e.predicted_asset == asset]
        wins = sum(1 for e in rows if e.interval_return_pct > 0)
        losses = sum(1 for e in rows if e.interval_return_pct <= 0)
        dollar_pnl = sum(e.portfolio_value_after - e.portfolio_value_before for e in rows)
        out[asset] = {
            "trades": len(rows),
            "wins": wins,
            "losses": losses,
            "winRatePct": round(wins / (wins + losses) * 100.0, 2) if (wins + losses) else 0.0,
            "dollarPnl": round(dollar_pnl, 4),
            "contributionPct": round(dollar_pnl / total_profit * 100.0, 2) if total_profit else 0.0,
        }
    return out


def compute_metrics(ledger: list[LedgerEntry]) -> dict:
    if not ledger:
        return {
            "initialCapital": INITIAL_CAPITAL,
            "currentValue": INITIAL_CAPITAL,
            "totalReturnPct": 0.0,
            "totalTrades": 0,
            "wins": 0,
            "losses": 0,
            "cashSessions": 0,
            "winRatePct": 0.0,
            "currentStreak": None,
            "assetBreakdown": {
                "GEAR": {"trades": 0, "wins": 0, "losses": 0, "winRatePct": 0.0, "dollarPnl": 0.0, "contributionPct": 0.0},
                "BBOZ": {"trades": 0, "wins": 0, "losses": 0, "winRatePct": 0.0, "dollarPnl": 0.0, "contributionPct": 0.0},
            },
            "buyHoldGearReturnPct": 0.0,
            "beatBuyHoldGear": False,
            "buyHoldAxjoReturnPct": 0.0,
            "beatBuyHoldAxjo": False,
        }

    # Cash sessions are a deliberate sit-out (0% by construction), not a trade outcome --
    # they're excluded from the win/loss tally and its denominator.
    traded = [e for e in ledger if e.predicted_asset != "CASH"]
    wins = sum(1 for e in traded if e.interval_return_pct > 0)
    losses = sum(1 for e in traded if e.interval_return_pct <= 0)
    cash_sessions = len(ledger) - len(traded)
    total_trades = len(ledger)
    final_value = ledger[-1].portfolio_value_after

    streak_type = None
    streak_len = 0
    for e in reversed(ledger):
        if e.predicted_asset == "CASH":
            continue
        this_type = "W" if e.interval_return_pct > 0 else "L"
        if streak_type is None:
            streak_type = this_type
            streak_len = 1
        elif this_type == streak_type:
            streak_len += 1
        else:
            break

    # Buy-and-hold GEAR benchmark: what a naive, always-in-GEAR investor would have
    # returned over the identical decision-to-realization date range, using the same
    # split-adjusted price series the strategy itself trades on -- the natural passive
    # baseline an active strategy needs to actually beat to be worth using.
    total_return_pct = round((final_value / INITIAL_CAPITAL - 1.0) * 100.0, 4)
    buy_hold_return_pct = round(
        (ledger[-1].gear_price / ledger[0].gear_price_at_decision - 1.0) * 100.0, 4
    )
    # Buy-and-hold ^AXJO benchmark: the same comparison against the unleveraged
    # underlying index, so it's visible whether the strategy (and its leveraged
    # GEAR/BBOZ products) is actually earning its extra complexity and volatility
    # over simply holding the index itself, not just over the leveraged product.
    buy_hold_axjo_return_pct = round(
        (ledger[-1].axjo_price / ledger[0].axjo_price_at_decision - 1.0) * 100.0, 4
    )

    return {
        "initialCapital": INITIAL_CAPITAL,
        "currentValue": round(final_value, 2),
        "totalReturnPct": total_return_pct,
        "totalTrades": total_trades,
        "wins": wins,
        "losses": losses,
        "cashSessions": cash_sessions,
        "winRatePct": round(wins / (wins + losses) * 100.0, 2) if (wins + losses) else 0.0,
        "currentStreak": {"type": streak_type, "length": streak_len} if streak_type else None,
        "assetBreakdown": compute_asset_breakdown(ledger),
        "buyHoldGearReturnPct": buy_hold_return_pct,
        "beatBuyHoldGear": total_return_pct > buy_hold_return_pct,
        "buyHoldAxjoReturnPct": buy_hold_axjo_return_pct,
        "beatBuyHoldAxjo": total_return_pct > buy_hold_axjo_return_pct,
    }


def summarize_validation_windows(windows: list[dict]) -> dict:
    """Mean/stddev of win rate and return across the trailing validation windows, so
    it's visible at a glance whether an edge looks stable or was one window's luck."""
    if not windows:
        return {"windowsEvaluated": 0}

    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    def stdev(xs: list[float]) -> float:
        if len(xs) < 2:
            return 0.0
        m = mean(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    return_pcts = [w["totalReturnPct"] for w in windows]
    # Exclude windows with zero trades from the win-rate average (winRatePct is a
    # meaningless 0.0 placeholder there, not a real result) -- return is still
    # meaningful even for an all-cash window, so it stays in that average.
    win_rate_pcts = [w["winRatePct"] for w in windows if (w["wins"] + w["losses"]) > 0]
    buy_hold_return_pcts = [w["buyHoldGearReturnPct"] for w in windows]
    windows_beating_buy_hold = sum(1 for w in windows if w["beatBuyHoldGear"])
    buy_hold_axjo_return_pcts = [w["buyHoldAxjoReturnPct"] for w in windows]
    windows_beating_buy_hold_axjo = sum(1 for w in windows if w["beatBuyHoldAxjo"])

    return {
        "windowsEvaluated": len(windows),
        "meanWinRatePct": round(mean(win_rate_pcts), 2),
        "stdDevWinRatePct": round(stdev(win_rate_pcts), 2),
        "meanTotalReturnPct": round(mean(return_pcts), 2),
        "stdDevTotalReturnPct": round(stdev(return_pcts), 2),
        "meanBuyHoldGearReturnPct": round(mean(buy_hold_return_pcts), 2),
        "windowsBeatingBuyHoldGear": windows_beating_buy_hold,
        "meanBuyHoldAxjoReturnPct": round(mean(buy_hold_axjo_return_pcts), 2),
        "windowsBeatingBuyHoldAxjo": windows_beating_buy_hold_axjo,
    }


def build_chart_series(ledger: list[LedgerEntry]) -> list[dict]:
    series = [{"date": None, "portfolioValue": INITIAL_CAPITAL, "cumulativeProfit": 0.0}]
    for e in ledger:
        series.append(
            {
                "date": e.realization_date,
                "portfolioValue": e.portfolio_value_after,
                "cumulativeProfit": round(e.portfolio_value_after - INITIAL_CAPITAL, 4),
            }
        )
    # drop the placeholder null-date seed row for chart consumption, keep it only as origin marker
    series[0]["date"] = ledger[0].decision_date if ledger else None
    return series


def ledger_to_dicts(ledger: list[LedgerEntry]) -> list[dict]:
    out = []
    for e in ledger:
        out.append(
            {
                "decisionDate": e.decision_date,
                "realizationDate": e.realization_date,
                "allocatedAsset": e.predicted_asset,
                "action": e.action,
                "rawPrediction": e.raw_prediction,
                "rawConfidence": e.raw_confidence,
                "filters": e.filters,
                "volatilityGuard": e.volatility_guard,
                "actualDirection": e.actual_direction,
                "predictionCorrect": e.correct,
                "gearPrice": e.gear_price,
                "bbozPrice": e.bboz_price,
                "intervalReturnPct": e.interval_return_pct,
                "portfolioValueBefore": e.portfolio_value_before,
                "portfolioValueAfter": e.portfolio_value_after,
                "cumulativeReturnPct": e.cumulative_return_pct,
                "priceSource": e.price_source,
            }
        )
    return out


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main() -> None:
    now_adelaide = datetime.now(ADELAIDE_TZ)
    today = now_adelaide.date()

    print(f"[engine] run started at {now_adelaide.isoformat()} (Australia/Adelaide)")

    # Fetch RAW (unadjusted) prices for the geared products and apply our own precise
    # split-only adjustment, rather than trusting yfinance's opaque combined
    # split+dividend auto_adjust -- which was observed to still miss a very recent split
    # and to introduce its own boundary artifact when adjusting an older one.
    gear_daily_raw = fetch_daily(TICKER_LONG, auto_adjust=False)
    bboz_daily_raw = fetch_daily(TICKER_SHORT, auto_adjust=False)
    gear_intraday_raw = fetch_intraday(TICKER_LONG, auto_adjust=False)
    bboz_intraday_raw = fetch_intraday(TICKER_SHORT, auto_adjust=False)
    gear_splits = fetch_splits(TICKER_LONG)
    bboz_splits = fetch_splits(TICKER_SHORT)
    if not gear_splits.empty:
        print(f"[engine] {TICKER_LONG} known splits: {gear_splits.to_dict()}")
    if not bboz_splits.empty:
        print(f"[engine] {TICKER_SHORT} known splits: {bboz_splits.to_dict()}")

    gear_daily = apply_split_adjustment(gear_daily_raw, gear_splits)
    bboz_daily = apply_split_adjustment(bboz_daily_raw, bboz_splits)
    gear_intraday = apply_split_adjustment(gear_intraday_raw, gear_splits)
    bboz_intraday = apply_split_adjustment(bboz_intraday_raw, bboz_splits)
    underlying_daily = fetch_underlying_daily()

    session_dates = build_session_dates(today)
    sessions = build_session_price_series(
        session_dates, gear_daily, gear_intraday, bboz_daily, bboz_intraday, now_adelaide
    )
    print(f"[engine] resolved {len(sessions)} sessions from {len(session_dates)} candidate Tue/Fri dates")

    if len(sessions) < 10:
        raise RuntimeError(f"Insufficient resolved sessions ({len(sessions)}) to run the strategy")

    actual_years = (sessions[-1].session_date - sessions[0].session_date).days / 365.25
    requested_years = TRAIN_WEEKS / 52
    if actual_years < requested_years * 0.5:
        print(
            f"[engine] NOTE: only {actual_years:.1f} years of {TICKER_LONG} history available "
            f"(requested ~{requested_years:.0f}y dev window) -- likely a newer listing; "
            f"proceeding with whatever history exists."
        )

    result = walk_forward_backtest(sessions, underlying_daily, gear_daily, bboz_daily)
    metrics = compute_metrics(result.ledger)
    chart_series = build_chart_series(result.ledger)
    validation_summary = summarize_validation_windows(result.validation_windows)
    print(
        f"[engine] validation across {validation_summary['windowsEvaluated']} window(s): "
        f"mean win rate {validation_summary.get('meanWinRatePct', 'n/a')}% "
        f"(stddev {validation_summary.get('stdDevWinRatePct', 'n/a')}), "
        f"mean return {validation_summary.get('meanTotalReturnPct', 'n/a')}% "
        f"(stddev {validation_summary.get('stdDevTotalReturnPct', 'n/a')})"
    )

    output = {
        "generatedAt": now_adelaide.isoformat(),
        "meta": {
            "strategy": "Bi-weekly rolling GMMA k-NN (GEAR/BBOZ) with rule-based confirmation filters",
            "tickers": {
                "long": TICKER_LONG,
                "short": TICKER_SHORT,
                "underlying": UNDERLYING_TICKER,
            },
            "model": {
                "type": "k-NN",
                "k": K_NEIGHBORS,
                "distance": "euclidean (z-score standardized, inverse-distance-weighted vote)",
                "classes": ["DOWN -> BBOZ", "FLAT -> CASH", "UP -> GEAR"],
                "flatBandPct": FLAT_BAND_PCT,
                "signalSetup": "Guppy Multiple Moving Average (GMMA) trend-continuation",
                "features": [
                    "short EMA group (3,5,8,10,12,15) compression %",
                    "long EMA group (30,35,40,45,50,60) separation %",
                    "price vs short EMA group %",
                ],
                "filterGate": "GEAR is the default position; BBOZ is entered either via all 4 filters unanimous, or via the volatility regime override",
                "filters": [
                    f"[BBOZ gate] GMMA trend alignment (short/long EMA group centers ordered by >{ALIGNMENT_MARGIN_PCT}% bearish)",
                    f"[BBOZ gate] {RS_LOOKBACK_DAYS}-day relative strength of the underlying is negative",
                    f"[BBOZ gate] BBOZ.AX volume at least {LIQUIDITY_MIN_RATIO:.0%} of its trailing {LIQUIDITY_LOOKBACK_DAYS}-day average",
                    f"[BBOZ gate] pullback entry: price within {PULLBACK_MAX_EXTENSION_PCT}% of the short EMA group, not an extended move",
                ],
                "volatilityGuard": (
                    f"three overrides, independent of the BBOZ gate, checked every session in this order: "
                    f"(1) fast breakdown -- forces BBOZ immediately whenever price closes below its own "
                    f"{SHORT_TERM_MA_DAYS}-day MA, regardless of volatility regime or the {VOL_REGIME_MA_DAYS}-day MA; "
                    f"(2) failing that, {SHORT_TERM_MA_DAYS}-day MA vs {VOL_REGIME_MA_DAYS}-day MA crossover -- forces "
                    f"GEAR if the {SHORT_TERM_MA_DAYS}-day MA is still below the {VOL_REGIME_MA_DAYS}-day MA (price has "
                    f"reclaimed the {SHORT_TERM_MA_DAYS}-day MA, or (1) above would have fired instead); (3) failing "
                    f"that, whenever {REALIZED_VOL_LOOKBACK_DAYS}-day realized volatility exceeds "
                    f"{VOL_SPIKE_MULTIPLIER:.1f}x its own trailing {VOL_BASELINE_LOOKBACK_DAYS}-day baseline, forces "
                    f"BBOZ if price is above its {VOL_REGIME_MA_DAYS}-day MA (topping pattern), else forces GEAR "
                    f"(oversold bounce) -- no CASH state produced"
                ),
            },
            "rebalanceSchedule": "Tuesday & Friday",
            "decisionCutoffLocal": "14:00 Australia/Adelaide",
            "trainWindowWeeks": TRAIN_WEEKS,
            "holdoutWindowWeeks": HOLDOUT_WEEKS,
            "backtestWindowWeeks": HOLDOUT_WEEKS,  # legacy alias kept for the frontend
            "brokerageFees": 0.0,
            "timezone": "Australia/Adelaide",
            "knownSplits": {
                TICKER_LONG: {str(k.date()): float(v) for k, v in gear_splits.items()},
                TICKER_SHORT: {str(k.date()): float(v) for k, v in bboz_splits.items()},
            },
        },
        "liveSignal": result.live_signal,
        "portfolio": metrics,
        "ledger": ledger_to_dicts(result.ledger),
        "chartSeries": chart_series,
        "validation": {
            "windows": result.validation_windows,
            "summary": validation_summary,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"[engine] wrote {OUTPUT_PATH} ({len(result.ledger)} ledger rows)")
    print(f"[engine] live signal: {result.live_signal['recommendedAsset']} "
          f"(confidence {result.live_signal['confidence']:.2f}, source {result.live_signal['priceSource']})")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] FATAL: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
