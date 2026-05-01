# SAVAGE AGENT

Autonomous Solana memecoin trading agent. Monitors tracked wallets for convergent ape activity, scores tokens across four dimensions, and executes trades autonomously via Jupiter V6.

```
┌─────────────────────────────────────────────────────────────┐
│                      SAVAGE AGENT                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    PlaySignal    ┌───────────────┐       │
│  │   Wallet      │────────────────▶│   Token        │       │
│  │   Tracker     │                 │   Intelligence │       │
│  │  (Helius WS)  │                 │  (Score 0-100) │       │
│  └──────────────┘                  └───────┬───────┘       │
│                                            │               │
│  ┌──────────────┐                  ┌───────▼───────┐       │
│  │  Platform     │  bonus score    │   Execution    │       │
│  │  Crawlers     │────────────────▶│   Engine       │       │
│  │  (PumpFun...) │                 │  (Jupiter V6)  │       │
│  └──────────────┘                  └───────┬───────┘       │
│                                            │               │
│  ┌──────────────┐                  ┌───────▼───────┐       │
│  │  CT Motion    │  hold boost     │   Exit         │       │
│  │  Detector     │────────────────▶│   Manager      │       │
│  │  (Grok/xAI)   │                 │  (TP/SL/Nuke)  │       │
│  └──────────────┘                  └───────┬───────┘       │
│                                            │               │
│  ┌──────────────┐                  ┌───────▼───────┐       │
│  │  Learning     │◀────────────────│   Alert        │       │
│  │  Engine       │   trade results │   Manager      │       │
│  │  (Adaptation) │                 │  (Telegram)    │       │
│  └──────────────┘                  └───────────────┘       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  SQLite: trades.db + learning.db    Logs: JSON + rotating   │
└─────────────────────────────────────────────────────────────┘
```

**Core thesis:** If 2–5 solid tracked traders ape a call within seconds or minutes of each other, the agent auto-buys 1–10 SOL of it.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/maycry234/SAVAGE-AGENT.git
cd SAVAGE-AGENT

# 2. Configure
cp .env.example .env
# Fill in HELIUS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# DRY_RUN=true is the default — no wallet needed for paper trading

# 3. Add tracked wallets
# Edit data/wallets.json with wallet addresses to monitor

# 4. Run (starts in paper-trading mode by default)
docker compose up -d
docker compose logs -f
```

---

## Environment Variables

| Variable | Description | Default | Required |
|---|---|---|---|
| `DRY_RUN` | Paper-trading mode (no real swaps) | `true` | No |
| `DRY_RUN_STARTING_SOL` | Starting paper balance (SOL) | `25.0` | No |
| `DRY_RUN_EXECUTION_DELAY_MS` | Simulated execution latency (ms) | `250` | No |
| `DRY_RUN_SLIPPAGE_BPS` | Simulated slippage (bps) | `SLIPPAGE_BPS` | No |
| `STARTUP_HEALTHCHECK_REQUIRED` | Run health checks on startup | `true` | No |
| `REQUIRE_TRADING_WALLET` | Require wallet even in dry-run | `false` | No |
| `REQUIRE_GROK` | Require Grok API key | `false` | No |
| `HEALTH_CHECK_TIMEOUT` | Health check timeout (seconds) | `8.0` | No |
| `HELIUS_API_KEY` | Helius API key for RPC + WebSocket | — | **Yes** |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for alerts | — | **Yes** |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for alerts | — | **Yes** |
| `ENCRYPTION_KEY` | Fernet key for wallet encryption | `""` | No* |
| `TRADER_WALLET_KEY` | Encrypted private key (Fernet) | `""` | No* |
| `TRADER_WALLET_PRIVATE_KEY` | Raw base58 private key (fallback) | `""` | No* |
| `HELIUS_RPC_URL` | Helius RPC endpoint | `https://mainnet.helius-rpc.com/?api-key=` | No |
| `HELIUS_WS_URL` | Helius WebSocket endpoint | `wss://mainnet.helius-rpc.com/?api-key=` | No |
| `HELIUS_REST_URL` | Helius REST API endpoint | `https://api.helius.xyz` | No |
| `JUPITER_API_URL` | Jupiter swap API endpoint | `https://api.jup.ag/swap/v1` | No |
| `DEXSCREENER_API_URL` | DexScreener API endpoint | `https://api.dexscreener.com/latest` | No |
| `GROK_API_URL` | Grok/xAI API endpoint | `https://api.x.ai/v1` | No |
| `GROK_API_KEY` | Grok API key for CT motion analysis | `""` | No |
| `GROK_MODEL` | Grok model name | `grok-3-mini` | No |
| `WALLET_POLL_INTERVAL` | REST poll interval (seconds) | `10` | No |
| `CONVERGENCE_WINDOW` | Window for ape convergence (seconds) | `120` | No |
| `MIN_APES` | Minimum wallets for convergence signal | `2` | No |
| `MAX_TRACKED_WALLETS` | Maximum wallets to track | `30` | No |
| `BUY_SCORE_THRESHOLD` | Minimum score to buy (0-100) | `60` | No |
| `MAX_HOLDER_CONCENTRATION` | Max top-10 holder concentration | `0.60` | No |
| `MAX_TOP3_CONCENTRATION` | Max top-3 holder concentration | `0.50` | No |
| `LARGE_SELL_THRESHOLD` | Large sell detection (% of supply) | `0.05` | No |
| `LARGE_SELL_WINDOW` | Large sell window (seconds) | `600` | No |
| `SCORING_TIMEOUT` | Token scoring timeout (seconds) | `5.0` | No |
| `MAX_POSITION_SOL` | Hard cap per position (SOL) | `10.0` | No |
| `VOLUME_MULTIPLIER_THRESHOLD` | Volume threshold for size boost ($) | `500000` | No |
| `VOLUME_MULTIPLIER` | Size multiplier when volume is high | `1.2` | No |
| `SLIPPAGE_BPS` | Jupiter swap slippage (basis points) | `1500` | No |
| `SOL_FEE_RESERVE` | SOL reserved for tx fees | `0.01` | No |
| `RPC_TIMEOUT` | RPC request timeout (seconds) | `30` | No |
| `MAX_CONCURRENT_POSITIONS` | Max simultaneous open positions | `3` | No |
| `HONEYPOT_TAX_THRESHOLD` | Max implied sell tax before abort | `0.15` | No |
| `INITIAL_TP_MULTIPLIER` | Initial take-profit target (x entry) | `2.0` | No |
| `INITIAL_SL_PERCENT` | Initial stop-loss (% below entry) | `0.30` | No |
| `TRAILING_TP_PERCENT` | Trailing stop distance (%) | `0.15` | No |
| `TIGHTENED_TRAIL_PERCENT` | Tightened trail on volume decay (%) | `0.08` | No |
| `PROFIT_LOCK_TIER1` | Tier 1 TP sell trigger (x entry) | `1.5` | No |
| `PROFIT_LOCK_TIER2` | Tier 2 TP sell trigger (x entry) | `2.0` | No |
| `CT_POLL_INTERVAL` | CT motion poll interval (seconds) | `180` | No |
| `HOLD_BOOST_LOCK_PERCENT` | % of position locked on CT boost | `0.50` | No |
| `HOLD_BOOST_ADD_MULTIPLIER` | Max add-on multiplier on CT boost | `1.5` | No |
| `HOLD_BOOST_TP_MULTIPLIER` | Boosted TP target (x entry) | `4.0` | No |
| `VOLUME_GROWTH_THRESHOLD` | Volume growth % to confirm CT motion | `0.20` | No |
| `CRAWLER_INTERVAL` | Crawler cycle interval (seconds) | `75` | No |
| `CRAWLER_BONUS_SCORE` | Bonus score for multi-source signal | `15` | No |
| `PUMPFUN_MC_SPIKE_THRESHOLD` | PumpFun MC spike ratio for signal | `2.0` | No |
| `PUMPFUN_SPIKE_WINDOW` | PumpFun new token age window (s) | `1800` | No |
| `EXIT_CHECK_INTERVAL` | Position monitor interval (seconds) | `60` | No |
| `NUKE_CHECK_INTERVAL` | Nuke detector interval (seconds) | `30` | No |
| `TOP_HOLDER_SELL_THRESHOLD` | Top holder sell % to trigger nuke | `0.10` | No |
| `NUKE_SELLER_COUNT` | Top holders selling to confirm nuke | `3` | No |
| `NUKE_WINDOW` | Nuke detection window (seconds) | `300` | No |
| `NUKE_SELL_PERCENT` | % of position to sell on nuke | `0.80` | No |
| `VOLUME_DECAY_THRESHOLD` | Volume decay % for trail tightening | `0.40` | No |
| `LIQUIDITY_COLLAPSE_THRESHOLD` | Liquidity drop % for emergency exit | `0.20` | No |
| `LIQUIDITY_COLLAPSE_WINDOW` | Liquidity collapse window (seconds) | `300` | No |
| `MIN_WALLET_SCORE` | Minimum wallet reputation score | `0.1` | No |
| `DEFAULT_WALLET_SCORE` | Starting wallet reputation score | `50.0` | No |
| `WIN_RATE_HIGH` | Win rate to loosen threshold | `0.65` | No |
| `WIN_RATE_LOW` | Win rate to tighten threshold | `0.40` | No |
| `THRESHOLD_RAISE` | Points to raise on poor performance | `5` | No |
| `THRESHOLD_LOWER` | Points to lower on good performance | `3` | No |
| `THRESHOLD_MIN` | Absolute minimum buy threshold | `55` | No |
| `THRESHOLD_LOOKBACK` | Trades to review for adaptation | `20` | No |
| `REENTRY_COOLDOWN` | Re-entry cooldown (seconds) | `86400` | No |
| `BEAR_BTC_DROP_THRESHOLD` | BTC 1h drop % for bear detection | `0.03` | No |
| `BEAR_THRESHOLD_BOOST` | Threshold increase in bear market | `10` | No |
| `HELIUS_RATE_LIMIT` | Helius API rate limit (req/s) | `10` | No |
| `DEXSCREENER_RATE_LIMIT` | DexScreener rate limit (req/s) | `5` | No |
| `JUPITER_RATE_LIMIT` | Jupiter API rate limit (req/s) | `10` | No |
| `GROK_RATE_LIMIT` | Grok API rate limit (req/s) | `2` | No |
| `LOG_LEVEL` | Logging level | `INFO` | No |
| `LOG_FORMAT_JSON` | Use JSON log format | `true` | No |
| `DAILY_SUMMARY_HOUR` | UTC hour for daily summary | `0` | No |

\* Either `ENCRYPTION_KEY` + `TRADER_WALLET_KEY` or `TRADER_WALLET_PRIVATE_KEY` is required for live trading (`DRY_RUN=false`).

---

## VPS Burn-in (Paper Trading)

Before funding a VPS with real SOL, run the agent in paper-trading mode for 24–72 hours to validate configuration, signal quality, and system stability.

### How it works

1. **Default safe**: `DRY_RUN=true` is the default. No private key, encryption key, or wallet config needed.
2. **Full pipeline**: All signal ingestion (wallet tracking, crawlers, Helius WS), token scoring, and alerting work identically to live mode.
3. **Paper ledger**: Buys and sells are recorded in `paper_ledger` (SQLite) with simulated tx signatures (`DRYRUN_BUY_<ts>_<addr>`, `DRYRUN_SELL_<ts>_<addr>`). Open positions use `dry_run=1` and `simulated_tx_signature` columns.
4. **Paper balance**: Starts at `DRY_RUN_STARTING_SOL` (default 25 SOL). Each paper buy deducts SOL; each paper sell credits SOL. Query with `ExecutionEngine.get_paper_balance()`.
5. **Telegram alerts**: Play alerts include a `🧪 DRY RUN` prefix so you can distinguish paper trades from live ones.
6. **Startup health checks**: Before any trading loop starts, the agent verifies connectivity to Helius RPC, Helius REST, DexScreener, Jupiter, Telegram, and optionally Grok. Required checks must pass or the agent refuses to start.

### Health checks

| Check | What it verifies | Required? |
|---|---|---|
| `helius_rpc` | JSON-RPC `getHealth` call | Yes |
| `helius_rest` | REST API reachable | Yes |
| `dexscreener` | Token data endpoint returns pairs | Yes |
| `jupiter` | WSOL→USDC quote succeeds | Yes |
| `telegram` | Bot `getMe` call | Yes |
| `grok` | `/models` endpoint | Only if `REQUIRE_GROK=true` |
| `wallet` | Key material exists | Only if `DRY_RUN=false` or `REQUIRE_TRADING_WALLET=true` |

### Going live

After a successful burn-in:

```bash
# 1. Stop the agent
docker compose down

# 2. Update .env
DRY_RUN=false
ENCRYPTION_KEY=your_fernet_key
TRADER_WALLET_KEY=your_encrypted_private_key
# OR: TRADER_WALLET_PRIVATE_KEY=your_base58_key

# 3. Restart
docker compose up -d
```

The agent will run startup health checks (including wallet verification) and begin live trading.

---

## Modules

**Wallet Tracker** (`agent/wallet_tracker.py`) — Monitors tracked wallets via Helius WebSocket (primary) and REST polling (fallback). Detects convergence when MIN_APES wallets buy the same token within CONVERGENCE_WINDOW seconds and emits a `PlaySignal`.

**Token Intelligence** (`agent/token_intel.py`) — Scores tokens 0-100 across four dimensions using Helius on-chain data and DexScreener market data. Checks against a rug database and enforces hard abort rules.

**Execution Engine** (`agent/execution.py`) — Executes swaps via Jupiter V6 API. Handles position sizing, honeypot simulation, transaction signing with `solders`, and send+confirm with retry.

**Exit Manager** (`agent/exit_manager.py`) — Monitors open positions for TP/SL triggers, trailing stop activation, volume decay tightening, dev wallet sells, liquidity collapse, and coordinated nuke exits.

**CT Motion Detector** (`agent/ct_motion.py`) — Queries Grok/xAI for crypto Twitter sentiment on open positions. Applies hold boosts (lock position + raise TP) when CT momentum is strong positive. Falls back to DexScreener heuristics when Grok is unavailable.

**Platform Crawlers** (`agent/crawlers.py`) — Crawls PumpFun, Memescope, and Printr for trending tokens and market-cap spikes. Awards a bonus score when a token appears across multiple sources.

**Learning Engine** (`agent/learning.py`) — Adjusts wallet reputation scores based on trade outcomes and adapts the buy threshold based on rolling win rate. Detects bear market conditions via BTC price monitoring.

**Alert Manager** (`agent/alerts.py`) — Sends formatted Telegram alerts for play detection, CT motion boosts, exits, and daily performance summaries.

**Crypto Utils** (`agent/crypto_utils.py`) — Fernet-based encryption/decryption for wallet private key storage.

**Operator CLI** (`agent/cli.py`) — Production operator CLI for VPS management over SSH. Supports wallet encryption, health checks, position/trade inspection, paper ledger management, and manual position control.

---

## Operator CLI

Manage your VPS deployment over SSH without editing SQLite by hand.

```bash
# Generate a Fernet encryption key
python -m agent.cli generate-key

# Encrypt a wallet private key (from file or inline)
python -m agent.cli encrypt-wallet --private-key ./wallet.txt --key "$ENCRYPTION_KEY"
python -m agent.cli encrypt-wallet --private-key <base58_key>

# Run health checks (nonzero exit if required checks fail)
python -m agent.cli health

# Inspect open positions
python -m agent.cli positions
python -m agent.cli positions --json

# View recent completed trades
python -m agent.cli trades --limit 10
python -m agent.cli trades --json

# Paper-trading balance and stats
python -m agent.cli paper-balance

# Reset paper ledger (requires confirmation)
python -m agent.cli reset-paper --confirm RESET

# Force-close a position
python -m agent.cli force-close --token <mint> --percent 100 --reason manual_exit
python -m agent.cli force-close --token <mint> --percent 50 --reason partial_exit --live

# Tail the learning log
python -m agent.cli tail-learning --lines 100
```

**Docker one-shot usage:**

```bash
docker compose run --rm savage-agent python -m agent.cli health
docker compose run --rm savage-agent python -m agent.cli positions
docker compose run --rm savage-agent python -m agent.cli paper-balance
```

**Safety:**
- `force-close` on live positions requires both `--live` flag and `DRY_RUN=false`.
- `encrypt-wallet` never prints the plaintext private key.
- `reset-paper` requires `--confirm RESET` and never touches real trade history.

---

## Scoring Engine

Tokens are scored 0-100 across four equally-weighted components:

| Component | Range | What it measures |
|---|---|---|
| **Volume Velocity** | 0-25 | 1h volume vs 24h average ratio |
| **Holder Health** | 0-25 | Holder count + top-10 concentration penalty |
| **Distribution** | 0-25 | Top-3 wallet concentration (lower = better) |
| **Dev Safety** | 0-25 | Mint authority, rug DB cross-reference |

**Hard abort rules** (score = 0, no buy):
- Top-3 holders > 50% of supply
- Mint authority enabled with < $10k liquidity
- Dev/holder in rug_db with `critical` severity

**Position sizing tiers:**

| Score | Apes | Size |
|---|---|---|
| 90+ | 5+ | 7 SOL |
| 80+ | 4+ | 4 SOL |
| 70+ | 3+ | 2 SOL |
| 60+ | 2+ | 1 SOL |
| Below threshold | — | No entry |

Volume multiplier: if 1h volume > $500k, size × 1.2. Hard cap: MAX_POSITION_SOL (10 SOL).

---

## Alert Formats

**Play Detected:**
```
🎯 PLAY DETECTED — $TOKEN
`Abcd...wxyz`

apes: 3 wallets (⚡ within 45s)
score: 78/100  •  size: 2.0 SOL
vol 1h: $125,000  •  liq: $85,000
holders: 1,250 (+0.0/min)
dev: CLEAN ✅  •  distro: 20%

entry: 0.00000150  •  tp: 0.00000300  •  sl: 0.00000105
[🔍 Scan] [📊 Chart] [❌ Abort]
```

**CT Motion:**
```
🔥 CT MOTION DETECTED — $TOKEN
holding 50% locked  •  adding 1.5 SOL
grok signals: trending, high velocity, kol mentions
new tp target: 4.0x
```

**Exit:**
```
🚨 EXIT — $TOKEN
reason: trailing_stop
pnl: +1.25 SOL (+62.5%)
held: 2h 15m
```

**Daily Summary:**
```
📊 daily wrap
trades: 5  •  win rate: 60%
total pnl: +3.50 SOL
best: $MOON +120%  •  worst: $RUG -30%
threshold: 60  •  top wallet: 7xBf...3kPq
```

---

## Safety Rules (SOUL.md)

The SOUL (System of Unbreakable Laws) enforces 33 rules across 8 categories. Key rules:

**Entry:**
1. Convergence is non-negotiable — minimum MIN_APES wallets must buy the same token within CONVERGENCE_WINDOW
2. Score threshold is sacred — no buy below BUY_SCORE_THRESHOLD
3. Mint authority check — never buy if mint authority enabled without LP lock
4. Distribution law — never buy if top-3 wallets hold > 50% supply
5. Known rugger blacklist — critical severity ruggers = instant abort
6. Honeypot verification — simulate sell before buying
7. Re-entry cooldown — 24h cooldown after stop-loss exit
8. Concurrent position limit — max 3 positions at once

**Exit:**
- Stop loss at 30% below entry, automatic and immediate
- Take profit tiers: 25% at 1.5x, 25% at 2.0x, 50% trailing
- Trailing stop at 15% below peak (tightens to 8% on volume decay)
- Dev wallet sell = immediate full exit
- Liquidity collapse (20% in 5min) = immediate exit

**Nuke Detection:**
- 3+ top holders selling 10%+ in 5 minutes = sell 80% immediately
- Single wallet selling 5%+ of supply = evaluate as nuke

**Market Regime:**
- Bear market (BTC -3% 1h) raises all thresholds by 10 points
- Low liquidity hours (02:00-06:00 UTC) = 50% size reduction

See `data/SOUL.md` for the complete rule set.

---

## Learning System

**Wallet Reputation:**
- Every tracked wallet starts at score 50.0
- Profitable trades triggered by a wallet increase its score (up to +5.0 per trade)
- Losing trades decrease score (up to -8.0 per trade)
- Score never drops below 0.1 — even bad wallets get second chances
- Wallet scores persist in `learning.db` and are loaded at startup

**Threshold Adaptation:**
- Reviews the last 20 completed trades
- Win rate > 65% → lower buy threshold by 3 (more aggressive)
- Win rate < 40% → raise buy threshold by 5 (more conservative)
- Threshold never drops below 55
- All adjustments logged to `logs/learning.log` and `learning.db`

**Bear Market Detection:**
- Monitors BTC/SOL price via DexScreener
- If BTC drops > 3% in 1 hour, adds +10 to effective threshold
- Automatically reverts when conditions normalize

---

## Deployment

### Docker Compose (recommended)

```bash
cp .env.example .env
# Edit .env with your API keys and wallet config
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

State persists in mounted volumes: `db/`, `logs/`, `data/`.

### Railway

1. Create a new project on [Railway](https://railway.app)
2. Connect the GitHub repo
3. Set all required environment variables in the Railway dashboard
4. Railway auto-detects the Dockerfile and deploys
5. Ensure `db/`, `logs/`, and `data/` are configured as persistent volumes

### Manual

```bash
pip install -r requirements.txt
# Ensure .env is configured or export env vars
python -m agent.main
```

Requires Python 3.11+.

---

## Data Files

- `data/wallets.json` — Tracked wallet addresses and metadata
- `data/rug_db.json` — Known rugger addresses and flagged patterns
- `data/SOUL.md` — System of Unbreakable Laws (safety rules)
- `data/PERSONALITY.md` — Agent personality for Grok prompts

---

## License

MIT
