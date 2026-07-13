# GEAR / BBOZ Bi-Weekly ML Allocator

A production dashboard for a bi-weekly, machine-learning trend-following allocation
strategy that routes between two leveraged ASX-listed Australian equities products:

- **GEAR.AX** — BetaShares Geared Australian Equity Fund, ~2x long geared exposure to the S&P/ASX 200
- **BBOZ.AX** — BetaShares Australian Strong Bear Hedge Fund, inverse/short geared exposure to the S&P/ASX 200

This is a direct port of a sibling strategy originally built for LNAS.AX / SNAS.AX
(leveraged/inverse-leveraged ASX-listed Nasdaq products), re-pointed at GEAR.AX /
BBOZ.AX with the reference index switched from the Nasdaq to the S&P/ASX 200
(`^AXJO`, falling back to the broader All Ordinaries `^AORD`). The model, filters,
thresholds, and volatility overrides described below are carried over unchanged from
that strategy's own real walk-forward validation rather than re-derived here; where
this document cites a specific real result, date, or price level as the evidence
behind a design choice, it's citing that sibling strategy's history, not a GEAR/BBOZ-
specific backtest.

The system decides on **Tuesdays and Fridays** which of GEAR, BBOZ, or cash to hold
for the next bi-weekly interval, using a Guppy Multiple Moving Average (GMMA) k-NN
classifier gated by four rule-based trend-continuation confirmations, seeded with a
~2-year training floor and walk-forward evaluated across several trailing 1-year
(52-week) windows so an apparent edge can be checked for stability rather than
trusted from a single window. It starts from a fixed **$500** seed with a
**zero-brokerage** friction assumption.

## Architecture

```
scripts/engine.py            Python pipeline: data -> features -> k-NN -> backtest -> JSON
.github/workflows/run_strategy.yml   Cron trigger (Tue/Fri) that runs the engine and commits the output
public/strategy_data.json    Flat JSON data bundle consumed directly by the frontend
app/page.tsx                 Client dashboard (Tailwind + lucide-react)
app/api/workflow-status/route.ts   Serverless proxy to the GitHub Actions REST API
```

### Backend: `scripts/engine.py`

1. **Data acquisition** — pulls ~10 years of daily history (yfinance returns whatever's
   actually available, gracefully degrading for newer listings) and 60-minute intraday
   bars for GEAR/BBOZ, plus daily history for a non-leveraged reference index
   (`^AXJO`, falling back to `^AORD`) used purely for feature engineering. Yahoo's own
   intraday retention is interval-dependent, not a yfinance-imposed limit: 1-minute
   bars retain ~7 days, {2m,5m,15m,30m,90m} retain ~60 days, and **60-minute bars
   retain ~2 years** — chosen deliberately for the ~2-year window at the cost of a
   coarser (nearest-hour, not nearest-half-hour) 2pm price, so far fewer walk-forward
   sessions fall back to the daily close.
2. **Timezone normalization** — all timestamps are interpreted in
   `Australia/Adelaide`. Daily bars (which yfinance labels at local midnight) are kept
   as date labels rather than tz-converted, since converting an instant across
   timezones would shift the calendar date. Intraday bars, which are real
   timestamped instants, are converted to Adelaide time so the **14:00** bar can be
   located precisely.
3. **Session price resolution** — for every Tuesday/Friday session the engine picks,
   in priority order: the 14:00 Adelaide intraday bar (the actionable signal ahead of
   the 16:00 AEST close) → the latest available intraday bar if it's a live session
   before 14:00 → the daily close as a fallback for sessions outside yfinance's ~2
   year intraday retention window. Each ledger/live-signal row records which source
   was used (`priceSource`).
4. **Split adjustment** — GEAR/BBOZ are fetched RAW (`auto_adjust=False`) and adjusted
   using Yahoo's own recorded split ratios (`yf.Ticker(...).splits`), applying exactly
   the known ratio rather than trusting yfinance's opaque combined split+dividend
   `auto_adjust`, which was observed in practice to still miss a very recent split and
   to introduce its own boundary artifact adjusting an older one. A residual, model-free
   safety net (`desplit_session_prices`) catches anything still implausible for a
   geared/inverse-geared ASX 200 product (>30% in one interval) — a split Yahoo hasn't recorded
   yet, or a genuinely unexplained data artifact — and logs it explicitly as
   "unexplained" for a human to double check, since by this point a known split isn't
   the likely cause.
5. **Feature engineering — Guppy Multiple Moving Average (GMMA).** Three features,
   computed on the non-leveraged reference index: a short ("trader") EMA group
   (spans 3/5/8/10/12/15) and a long ("investor") EMA group (spans 30/35/40/45/50/60).
   The three textbook conditions for a trend-continuation entry are operationalized as
   the coefficient of variation within each group (compression vs. separation) and
   price's position relative to the short group's mean:
   - short-group **compression** (`std/mean` of the 6 short EMAs, low = bunched)
   - long-group **separation** (`std/mean` of the 6 long EMAs, high = still trending)
   - **price vs. short group** (`(close - short_mean)/short_mean`, tracks pullback and
     bounce)

   Two other feature sets — lagged-return momentum + RSI, and a slow SMA50/SMA200
   trend filter + RSI + VIX level — were each tried alone and, on their own, landed
   within noise of a 50% win rate across multi-window validation, same as GMMA alone.
   Rather than keep guessing at raw feature combinations, GMMA now gets four
   rule-based confirmation filters instead (see below) — a discretionary trading
   system's actual entry logic, not a fourth blind guess. An earlier 5-feature GMMA
   version (adding RSI + realized volatility + GEAR's own trading volume directly
   into the k-NN distance) measurably hurt walk-forward accuracy against a k=3
   neighbor pool (curse of dimensionality), so the k-NN itself deliberately stays at
   exactly 3 features; the extra confirmations below gate the call instead of being
   fed into the distance metric. Using the underlying index (rather than GEAR/BBOZ's
   own returns) avoids contaminating the signal with the geared products' own
   leverage decay and tracking error. Features are z-score standardized against the
   training pool available at each walk-forward step (no lookahead) before the
   Euclidean k-NN distance, since raw scales differ.
6. **Model** — a from-scratch k-NN (k=3, Euclidean distance, inverse-distance-weighted
   vote -- a closer neighbor counts for more than a barely-in-the-top-k one, rather
   than every one of the k neighbors getting an equal unweighted vote) so the exact
   rule is transparent; no external ML dependency required. Three classes for
   training/labeling purposes: the underlying's next-interval return **UP** (→ GEAR),
   **DOWN** (→ BBOZ), or inside a ±0.5% **FLAT** band. FLAT is only ever a training
   label — see point 8 below for why the actual position resolution never holds cash.
7. **Rule-based confirmation filters — the BBOZ gate, all 4 unanimous.** The raw k-NN
   call is a pure pattern match on the compression/separation/pullback shape; these
   four classic GMMA trading-system rules, evaluated in the BBOZ/bearish direction,
   gate whether the strategy ever leaves its GEAR default (see point 8):
   - **GMMA trend alignment** — the short and long EMA group *centers* (not every
     single EMA) must be ordered bearishly by a small margin (>0.1%) — the
     difference between a genuine, established downtrend and a compression reading
     that just happens to occur mid-chop, without demanding the unrealistic
     zero-overlap bar of every short EMA clearing every long EMA.
   - **Relative strength** — the underlying's own trailing 20-trading-day return
     must be negative, confirming the trend on a timescale closer to the GMMA
     pattern's own short group (shortened from an initial 60-day version, which was
     frequently out of phase with an otherwise-good GMMA setup).
   - **Sufficient liquidity** — BBOZ's own volume must be at least 80% of its
     trailing 20-day average, so the setup is genuinely tradeable without requiring
     literally above-average volume on every session.
   - **Pullback, not an extended move** — price must be within 3.5% of the short EMA
     group (either side) to count as having pulled back near the group rather than
     already stretched away from it — buying the pullback/bounce, not chasing a move
     that already ran.

   All four must pass, unanimously, before switching into BBOZ. Earlier iterations
   split these into CORE (trend alignment + relative strength, mandatory) and SOFT
   (liquidity + pullback, either one) roles for *both* GEAR and BBOZ entries, each
   backed by evidence: an initial pass requiring all four unanimously vetoed the vast
   majority of raw calls to cash (windows down to 1-9 trades); loosening thresholds
   (values above) helped only a little; a 3-of-4 majority gate backfired on real data
   (trade count roughly doubled, win rate held ~69% vs ~73%, but 6-window return
   stddev nearly tripled ±7.9 → ±22.0, since the extra trades let through were
   disproportionately the ones failing trend alignment/relative strength — the two
   filters that catch a setup about to reverse hard); the core/soft split then
   recovered some of that lost trade count without loosening either proven-protective
   filter. That whole line of design was superseded, not because the filters
   themselves were wrong, but because being neutral-by-default (mostly cash) is a
   structural drag against a leveraged product riding a real uptrend — see point 8.
   The live signal still reports the raw k-NN call and each filter's own pass/fail
   state, so it's visible exactly why GEAR was kept or BBOZ was taken.
8. **GEAR is the default position; BBOZ is a tactical, high-conviction excursion.**
   On the sibling LNAS/SNAS strategy this engine is adapted from, 6-window validation
   showed an earlier neutral-by-default design (sitting in cash 58-81% of every
   window's sessions) lost to simple buy-and-hold of the long product in 5 of its 6
   windows — being mostly in cash structurally caps upside during a genuine, sustained
   uptrend, which is what a ~2x geared equity-index tracker like GEAR.AX spends most
   of a bull market in. `resolve_final_decision` instead treats GEAR as the
   unconditional default/home position: no filter gate is required to hold or return
   to it. The only way out of GEAR is a high-conviction BBOZ call — the raw k-NN
   prediction must itself call BBOZ *and* all 4 confirmation filters above must pass
   unanimously ("meets our criteria perfectly"). Once in BBOZ, the position is
   re-checked against those same 4 filters every session, independent of whatever the
   raw k-NN currently predicts — the moment any single one of them fails, exit
   straight back to GEAR, not to cash ("leave BBOZ if it doesn't remain solid"). There
   is no CASH resting state in this design: every session holds either GEAR or BBOZ.
   Each decision's action — `ENTER` (the very first position ever taken), `HOLD`
   (continuing the same position), or `FLIP` (switching between GEAR and BBOZ) — is
   recorded on the ledger row and the live signal for transparency; ledger rows expand
   on click in the dashboard to show the raw call and full filter detail behind it.
   `CASH`/`EXIT` remain valid action values only so pre-redesign ledger rows still
   render correctly. This long-biased design (validated on the sibling LNAS/SNAS
   strategy) is what this engine runs for GEAR/BBOZ from the start, rather than the
   earlier neutral/cash-default design (core+soft filters gating both sides, HOLD via
   relative-strength-gated cash fallback).
9. **Volatility regime override — directional, not a flight to cash.** On the sibling
   strategy, being permanently invested in a leveraged product (point 8) improved mean
   return across the 6 validation windows but also widened the spread of outcomes
   between them (±20.6 stddev, up from ±16.4 under the prior neutral/cash-default
   design) — every window is now fully exposed to whatever realized volatility
   that window happened to have. A first version simply forced CASH whenever
   `REALIZED_VOL_LOOKBACK_DAYS`-day (10) realized volatility exceeded
   `VOL_SPIKE_MULTIPLIER` (1.5x) its own trailing `VOL_BASELINE_LOOKBACK_DAYS`-day (60)
   baseline (self-relative, not a fixed absolute threshold, so it transfers across
   volatility regimes without retuning). But real data on the sibling strategy showed a
   flat de-risk is too blunt: one volatility spike occurred while price sat below its
   `VOL_REGIME_MA_DAYS`-day (50) MA, and the long product went on to rally over the
   next two sessions — cash sat out a real gain. Another spike occurred while price sat
   above that same MA, and the long product fell over the next six sessions — cash
   correctly avoided a real loss. The two spikes looked identical on volatility alone;
   only the price-vs-MA regime told them apart. So the override is directional:
   elevated volatility with price above its 50-day MA reads as a
   topping/reversal-from-strength pattern (switch to BBOZ); elevated volatility with
   price still below its 50-day MA reads as an oversold-bounce pattern (buy/stay in
   GEAR) — no CASH state is produced.

   The "buy/stay in GEAR" half was then refined on the sibling strategy, targeting the
   idea that the 50-day MA alone can't tell a pullback within an intact longer-term
   uptrend (a real dip worth buying) apart from a breakdown within an established
   downtrend (catching a falling knife with a leveraged long product). Two attempts
   added a 200-day MA falling-knife check (a 7-session lookback, then a same-day
   version, then a same-day version with a 20-day MA reversal confirmation on top);
   real data showed neither improved anything, so the 200-day MA approach was
   abandoned entirely.

   What the 200-day MA attempts were actually chasing turned out to be a different
   kind of session: a sizeable loss on the long product that happened during *normal*,
   not elevated, volatility — outside the volatility-override branch altogether, so no
   amount of tuning the 200-day MA check inside that branch could ever have caught it.
   Real data showed the `SHORT_TERM_MA_DAYS`-day (20) MA had crossed below the
   `VOL_REGIME_MA_DAYS`-day (50) MA shortly before that loss — a short-term downtrend
   forming under the medium-term trend. That crossover is now its own independent
   check, evaluated every session ahead of (and regardless of) the elevated-volatility
   branch above: 20-day MA below the 50-day MA -> BBOZ, *unless* price has already
   reclaimed the 20-day MA, which reads as the reversal already underway -> GEAR
   instead. Both MAs are same-day, not a lookback window. Every ledger row and the
   live signal report the `volatilityGuard` check (pass/fail plus a detail covering
   both the 20/50-day MA crossover and the realized-vol-vs-baseline state) alongside
   the 4 BBOZ-gate filters, so it's visible whenever either override — not the BBOZ
   gate — drove the call, and which of the two fired.

   The elevated-volatility branch itself (only reached once the crossover above isn't
   active — the 20-day MA is still at or above the 50-day MA, a broadly bullish MA
   structure) uses the 50-day MA for its own topping/oversold-bounce call: above it
   during a vol spike reads as topping (-> BBOZ), below it reads as an oversold bounce
   (-> GEAR). A since-reverted attempt keyed this off the 20-day MA instead (the same
   one the crossover check above uses), on the theory that the slower 50-day MA was
   misreading ordinary bull-market pullbacks as topping — real data on the sibling
   strategy proved that wrong: the window the theory targeted came back bit-for-bit
   identical (meaning this branch was never even active during that window), and the
   live window it was actually tested against regressed, missing a real BBOZ-side
   entry that the 50-day MA version had caught and eating a real loss from flipping
   out of BBOZ early that the 50-day MA version had avoided. Reverted back to the
   50-day MA on that evidence.

   Real chart evidence from the sibling strategy's own underperforming window then
   showed *why* neither override caught its real underperformance either: the long
   product crashed hard well before that window's boundary date, and price was already
   trading well below its own 20-day MA by that point. But the 20/50-day MA crossover
   above hadn't triggered yet: the 20-day MA was still *above* the 50-day MA at that
   point (a slower MA takes longer to roll over), so neither it nor the
   elevated-volatility branch ever engaged, and the strategy just held the long
   product through the entire decline. A third, faster check was added ahead of both:
   price closing below its own 20-day MA now forces BBOZ immediately, regardless of
   volatility regime or where the 50-day MA sits — it reacts to a breakdown directly
   instead of waiting for a slower MA to confirm it. The 20/50 crossover above is now
   only reached for sessions where price has already reclaimed the 20-day MA (so it
   can no longer itself force BBOZ — only the reversal-underway GEAR call survives
   from it).
10. **Train floor + multi-window holdout** — ~2 years of history is a minimum floor
   before any decision is evaluated (the "dev" pool) -- deliberately short: on the
   sibling LNAS/SNAS strategy, the two products only had ~5.9 years of real history in
   total, and a longer floor left too little left over to validate against (a 5-year
   floor left only ~10 months / 2 windows). GEAR.AX/BBOZ.AX may have a different
   amount of real listed history; the engine logs a NOTE at runtime if the actual
   history available is materially shorter than this floor requests. Every session
   after the floor is evaluated and chunked into trailing non-overlapping ~52-week
   (104-session) windows, most recent first, up to `MAX_HOLDOUT_WINDOWS` (50 -- a
   deliberately non-binding ceiling; the actual count shown is purely whatever real
   history supports).
   Window size went through two prior sizes on the sibling strategy -- 26 weeks
   (~6-7 real windows) and then 13 weeks (shrunk to reach 15 windows for a
   finer-grained stability read, at the cost of roughly doubling each window's own
   standard error with only ~26 trades apiece) -- before settling on 52 weeks: a full
   year covers a much wider range of regimes per window than a single quarter, while
   still being small enough that several independent yearly windows fit within a
   several-year span of history. The most recent
   window is the main dashboard (backward compatible with the single-window design);
   every window, including older ones, gets reported in `validation.windows` with a
   mean/stddev summary -- a single small window is too small a sample to trust on its
   own (a 62% win rate over 42 trades has a binomial standard error of roughly ±7.5
   points, and it only gets worse with fewer trades), so this is how the dashboard
   shows whether an apparent edge is stable or one window's luck. Each window is
   simulated independently from a fresh $500 seed (not one
   continuous multi-year compounding run), so no window's result depends on an
   earlier one's outcome. Every step still only ever trains on strictly prior
   sessions (no look-ahead), and the pool keeps growing through the whole evaluated
   range, so later windows get a richer training pool than the dev floor alone. The
   realized return applied is the *actual* return of whichever asset was selected
   (GEAR's own return, BBOZ's own return, or 0% for cash) — not a synthetic negation
   — so real product decay/tracking error is reflected. Win rate and streaks are
   computed only over traded (non-cash) sessions, since a 0%-by-construction cash
   interval isn't a win or a loss.
11. **Buy-and-hold benchmarks, per window — GEAR and the unleveraged ^AXJO.** An
   active strategy that merely matches a naive always-in-GEAR investor isn't earning
   its complexity, so every window (and the main portfolio) reports
   `buyHoldGearReturnPct` — what $500 would have returned buying GEAR at the first
   decision of the window and holding, untouched, to the window's last realized
   price, using the same split-adjusted price series the strategy itself trades on —
   alongside `beatBuyHoldGear`, a direct comparison against the strategy's own
   `totalReturnPct` over the identical date range. The same comparison is repeated
   against the unleveraged underlying index itself (`buyHoldAxjoReturnPct` /
   `beatBuyHoldAxjo`, using ^AXJO's own daily close series, already fetched for the
   GMMA/RS features) — since GEAR/BBOZ are leveraged products, beating buy-and-hold
   GEAR isn't the same question as beating buy-and-hold on the plain index; the
   strategy needs to answer both to show it's earning its leverage and complexity,
   not just riding amplified beta. `summarizeValidationWindows` rolls both up across
   all windows into `meanBuyHoldGearReturnPct`/`windowsBeatingBuyHoldGear` and
   `meanBuyHoldAxjoReturnPct`/`windowsBeatingBuyHoldAxjo`, so the validation table and
   dashboard both show, window by window, whether the strategy is actually
   outperforming either passive alternative or just adding trading complexity (and,
   for BBOZ, leveraged short exposure) for a similar or worse outcome.
12. **Output** — `public/strategy_data.json`: live signal, portfolio metrics, the full
   ledger, a chart-ready equity series, and the multi-window validation summary.

### Pipeline: `.github/workflows/run_strategy.yml`

Runs on a cron trigger for Tuesday/Friday, roughly 15 minutes after 14:00 in whichever
of ACST (UTC+9:30) or ACDT (UTC+10:30) is currently in effect (two cron lines cover
both DST states — `engine.py` resolves the real local time itself via `zoneinfo`, so
the "wrong season" firing is a harmless re-check that falls back to the latest
available intraday bar). It installs `scripts/requirements.txt`, runs the engine, and
commits `public/strategy_data.json` back to the repo with `[skip ci]` to avoid a
recursive build loop. `workflow_dispatch` is enabled for manual runs.

### Frontend: `app/page.tsx`

A lightweight client dashboard (no heavy chart library — the equity curve is a
hand-built SVG component) that:

- Fetches `/strategy_data.json` directly from the public folder (same-origin static
  file — no CORS, no API round trip). The **Query Live Signal Now** button re-fetches
  with a cache-busting query param.
- Shows the live actionable signal (GEAR, BBOZ, or CASH), the resulting **action**
  (Entering / Holding / Flipping / Exiting to cash / Staying in cash), the raw GMMA
  k-NN call and its confidence, the three GMMA feature values, and a pass/fail
  checklist for each of the four rule-based confirmation filters that can veto a
  fresh call.
- Polls `app/api/workflow-status/route.ts` — a serverless proxy to the GitHub Actions
  REST API — for the cron pipeline's last run status, timestamps, and logs link.
- Renders the full 52-week holdout **Trading Ledger Diary** — including each row's
  action (Enter/Hold/Flip/Exit/Cash) — a cumulative-profit equity curve with hover
  tooltips, and a **Validation Across Historical Windows** table showing win
  rate/return per trailing window plus the mean/stddev summary.
- Shows a **GEAR vs BBOZ accuracy & profit contribution** breakdown: trades/wins/
  losses and win rate per asset, plus each asset's exact dollar contribution to
  total profit (computed from each trade's own portfolio-value delta along the
  same compounding path, so GEAR + BBOZ contribution always sums to the total).
  The same breakdown is also reported per validation window, so it's visible
  whether one asset direction is consistently carrying (or dragging) performance
  rather than just looking at an aggregate win rate.

### Trading Diary: `app/diary/page.tsx`

A separate page (opens in a new tab from a link in the main dashboard's header) for
tracking real trades by hand, entirely independent of the ML backtest engine —
nothing here is generated by `engine.py` or written to `strategy_data.json`:

- Log a trade with ticker, buy date, buy price, and dollar amount invested; shares
  are derived (`$ invested / buy price`). Enter a sell date and sell price whenever a
  position is closed and profit ($) and return (%) compute automatically — every
  field remains editable inline afterward for corrections.
- A running summary (`lib/diary.ts`): portfolio value, cumulative return % (relative
  to an editable starting capital, default $500 to match the backtest's own seed),
  realized P&L, unrealized P&L (for open GEAR/BBOZ positions, using the same live
  prices already published in `strategy_data.json` — the only place this page reads
  engine output, purely for display), win rate, and a win/loss streak over closed
  trades.
- Persisted entirely in the browser's `localStorage` (`gear-bboz-trading-diary-v1`)
  — there's no backend/database in this app, and these are the user's own real
  trades, not something the engine should generate or a server should store.

## Local development

```bash
npm install
npm run dev            # http://localhost:3000

python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/engine.py    # writes public/strategy_data.json
```

## Deployment

- **Frontend**: deploy to Vercel (zero config — standard Next.js App Router build).
- **Backend**: the GitHub Actions workflow needs `contents: write` permission (already
  set) to commit the refreshed data file. No secrets are required for the engine
  itself; `app/api/workflow-status` will work unauthenticated against the public
  GitHub API at a lower rate limit, or you can set a `GITHUB_TOKEN` env var on Vercel
  for higher limits.

## Disclaimer

Zero-brokerage backtest for research purposes only. Not financial advice.
