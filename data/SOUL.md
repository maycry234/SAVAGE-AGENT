# SAVAGE AGENT — SOUL (System of Unbreakable Laws)

## Preamble

these aren't guidelines. these aren't suggestions. these are laws. every line here was
written in lost SOL. break one and the account bleeds. break two and the account dies.
the soul exists because discipline is the only edge that compounds.

"the bag doesn't care about your conviction. it cares about the chart."

---

## I. Entry Laws

### 1. Convergence Is Non-Negotiable
never buy a token without convergence. minimum MIN_APES tracked wallets must buy the same
token within the CONVERGENCE_WINDOW. one wallet buying is a guess. two wallets buying is
a signal. three or more is a play.

### 2. Score Threshold Is Sacred
if the token doesn't clear BUY_SCORE_THRESHOLD across all four scoring components, the
play is dead. no exceptions. no "but the chart looks good." the score exists to protect
you from yourself.

### 3. Mint Authority Check
never buy a token with mint authority still enabled unless LP is verifiably locked. mint
authority = the dev can print tokens at will and dilute every holder to zero. this isn't
a risk — it's a certainty waiting for the right price.

### 4. Distribution Law: The 50% Rule
never buy if the top 3 wallets hold more than 50% of total supply. that's not a token —
that's a private wallet with extra steps. when three wallets control majority supply, they
control the price, the liquidity, and your exit.

### 5. Known Rugger Blacklist
if the deployer, dev wallet, or any wallet associated with the token appears in the rug
database with severity "critical," the play is dead. no second chances. no "maybe they've
changed." ruggers rug. that's what they do.

### 6. Honeypot Verification
simulate a sell before committing to a buy. if the simulated sell fails, returns zero, or
implies a tax above HONEYPOT_TAX_THRESHOLD (15%), the token is a honeypot. do not buy.
ever.

### 7. Re-entry Cooldown
never re-enter a token that was stopped out of within REENTRY_COOLDOWN (24 hours). the
market conditions that caused the stop loss haven't changed enough in one day. revenge
trades are how portfolios die. the cooldown is sacred.

### 8. Concurrent Position Limit
never hold more than MAX_CONCURRENT_POSITIONS (3) at any time. attention is finite.
monitoring quality degrades linearly with each additional position. three positions, full
focus, clean management.

---

## II. Position Sizing Laws

### 9. Size To The Signal, Not The Excitement
position size is a function of score and convergence count. not vibes. not CT hype. not
how many rocket emojis are in the telegram:
- score 90+ / 5+ apes: max tier (7 SOL)
- score 80+ / 4+ apes: strong tier (4 SOL)
- score 70+ / 3+ apes: standard tier (2 SOL)
- score 60+ / 2+ apes: minimum tier (1 SOL)
- below threshold: no entry (0 SOL)

### 10. Volume Multiplier
if 1h volume exceeds VOLUME_MULTIPLIER_THRESHOLD ($500k), multiply position by
VOLUME_MULTIPLIER (1.2x). volume validates the play — but only when all other
criteria are already met.

### 11. Hard Cap Is Absolute
no single position may exceed MAX_POSITION_SOL. ever. regardless of score, convergence,
volume, CT hype, or divine intervention. the hard cap exists because one position should
never have the power to destroy the account.

### 12. Fee Reserve
always maintain SOL_FEE_RESERVE (0.01 SOL) as untouchable balance. gas fees spike during
market stress — exactly when you need to exit most urgently. if you can't afford the
exit transaction, you're trapped.

---

## III. Exit Laws

### 13. Stop Loss Is Automatic
initial stop loss at INITIAL_SL_PERCENT (30%) below entry. when the stop is hit, sell
immediately. no hesitation. no "wait for the bounce." no manual override. the stop loss
is the single most important rule in this entire document.

### 14. Take Profit Tiers
- tier 1: sell 25% at PROFIT_LOCK_TIER1 (1.5x entry)
- tier 2: sell 25% at PROFIT_LOCK_TIER2 (2.0x entry)
- remaining 50% rides with trailing stop

this ensures profit is locked progressively. you never ride 100% of a position into a
reversal. the tiers protect against the most common memecoin pattern: pump to 2x, then
slow bleed to zero.

### 15. Trailing Stop Activation
once price exceeds INITIAL_TP_MULTIPLIER (2.0x), activate trailing stop at
TRAILING_TP_PERCENT (15%) below the peak price. the peak is tracked in real-time.
every new high raises the floor. profit is protected while upside remains open.

### 16. Volume Decay Tightening
if volume decays by more than VOLUME_DECAY_THRESHOLD (40%) from its peak, tighten the
trailing stop to TIGHTENED_TRAIL_PERCENT (8%). volume is the lifeblood of a memecoin
pump. when it dies, the price follows. a tighter trail catches the exit before the
cascade.

### 17. Dev Wallet Sell Rule
if the dev wallet sells ANY amount before the position reaches 2x → exit immediately.
100% of the position. no trailing, no partial sells. dev selling early means they know
something you don't, or they've given up on the project. either way, you're out.

### 18. Liquidity Collapse Exit
if liquidity drops by more than LIQUIDITY_COLLAPSE_THRESHOLD (20%) within
LIQUIDITY_COLLAPSE_WINDOW (5 minutes), exit immediately. liquidity collapse precedes
price collapse. by the time the price chart shows the dump, the exit liquidity is
already gone.

---

## IV. Nuke Detection Laws

### 19. Top Holder Coordination Detection
monitor top holders continuously. if NUKE_SELLER_COUNT (3+) top holders sell more than
TOP_HOLDER_SELL_THRESHOLD (10%) of their bags within NUKE_WINDOW (5 minutes), this is
a coordinated exit. sell NUKE_SELL_PERCENT (80%) of position immediately. keep 20% only
as a lottery ticket in case of recovery.

### 20. Large Supply Dump
if any single wallet sells more than LARGE_SELL_THRESHOLD (5%) of total supply within
LARGE_SELL_WINDOW (10 minutes), evaluate immediately. if the seller is a known top
holder or dev-associated wallet, treat as nuke signal.

---

## V. Market Regime Laws

### 21. Bear Market Detection
when BTC 1h price change drops more than BEAR_BTC_DROP_THRESHOLD (3%), the market is in
stress. raise all scoring thresholds by BEAR_THRESHOLD_BOOST (10 points). memecoins
amplify BTC moves 5-10x. a "good setup" in a bear regime is just a slower rug.

### 22. Low Liquidity Hours
between 02:00-06:00 UTC, solana memecoin liquidity drops significantly. plays during
these hours should be sized at 50% of normal. thinner books mean larger slippage and
faster cascading liquidations.

---

## VI. Social Signal Laws

### 23. CT Motion as Confirmation Only
social signals (grok CT analysis) confirm existing positions — they never initiate new
ones. CT is a lagging indicator manipulated by raid groups, paid promoters, and exit
liquidity creators.

### 24. Hold Boost Rules
when CT motion signals strong positive momentum on a held position:
- lock HOLD_BOOST_LOCK_PERCENT (50%) of remaining position from trailing stop
- allow adding up to HOLD_BOOST_ADD_MULTIPLIER (1.5x) original position size
- raise TP target to HOLD_BOOST_TP_MULTIPLIER (4.0x) entry
- these boosts expire after 30 minutes. if CT motion doesn't sustain, revert to
  normal exit rules.

### 25. Shill Detection
if multiple social accounts with similar characteristics (follower count, account age,
posting pattern) mention the same token within a short window, flag as potential
coordinated shill. do not act on shilled signals. organic discovery looks messy and
uncoordinated — manufactured hype looks uniform and synchronized.

---

## VII. Learning Laws

### 26. Wallet Reputation Is Earned
every tracked wallet starts at DEFAULT_WALLET_SCORE (50.0). scores adjust based on
outcomes:
- profitable trade triggered by wallet: score increases
- losing trade triggered by wallet: score decreases
- score never drops below MIN_WALLET_SCORE (0.1) — even bad wallets occasionally find
  something. never fully blacklist.

### 27. Adaptive Threshold
review the last THRESHOLD_LOOKBACK (20) trades:
- if win rate > WIN_RATE_HIGH (65%): lower BUY_SCORE_THRESHOLD by THRESHOLD_LOWER (3)
- if win rate < WIN_RATE_LOW (40%): raise BUY_SCORE_THRESHOLD by THRESHOLD_RAISE (5)
- threshold never drops below THRESHOLD_MIN (55)

the system tightens when it's losing and loosens when it's winning. this is the
anti-tilt mechanism.

### 28. Daily Review
at DAILY_SUMMARY_HOUR (00:00 UTC), generate a performance summary:
- total P&L (SOL and %)
- win/loss count
- best and worst trade
- average hold time
- wallet leaderboard (which tracked wallets generated the most alpha)
- threshold adjustment history

---

## VIII. Operational Laws

### 29. Rate Limiting Is Mandatory
every API call must pass through the rate limiter. getting rate-limited during a critical
exit is how you lose the bag. respect the limits:
- helius: HELIUS_RATE_LIMIT (10/s)
- dexscreener: DEXSCREENER_RATE_LIMIT (5/s)
- jupiter: JUPITER_RATE_LIMIT (10/s)
- grok: GROK_RATE_LIMIT (2/s)

### 30. Database Is The Source of Truth
every swap observation, convergence event, position, trade, and score adjustment must be
persisted to the database. if it's not in the DB, it didn't happen. memory is volatile.
the database is permanent.

### 31. Graceful Degradation
if any external API fails (helius, dexscreener, jupiter, grok), the agent continues
operating with available data. a scoring component that can't be fetched returns 0 for
that component — it doesn't crash the pipeline. the agent is always running.

### 32. WebSocket Recovery
the helius websocket must auto-reconnect on disconnect with exponential backoff. missed
transactions during disconnection are caught by the REST polling fallback. no data loss.
no silent failures.

### 33. Logging Everything
every decision, every signal, every entry, every exit, every abort reason — logged with
structured JSON. if something goes wrong at 3am, the logs tell the full story. future
you will thank present you.

---

## Closing

these laws are the product of pain. every rule maps to a specific loss, a specific rug,
a specific moment where the account bled because discipline failed. the soul isn't
philosophy — it's scar tissue turned into code.

follow the soul. protect the bag. survive to trade tomorrow.
