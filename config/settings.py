import os
from pathlib import Path


def _env(key: str, default, cast=str):
    val = os.getenv(key, default)
    if val is None:
        return None
    try:
        return cast(val) if not isinstance(val, cast) else val
    except (ValueError, TypeError):
        return cast(default) if default is not None else None


def _env_int(key, default):
    return _env(key, default, int)


def _env_float(key, default):
    return _env(key, default, float)


def _env_bool(key, default=False):
    val = os.getenv(key, str(default)).lower()
    return val in ('true', '1', 'yes')


# === Paths ===
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_DIR = BASE_DIR / "db"
LOG_DIR = BASE_DIR / "logs"

# === API Keys (from .env) ===
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL", "https://mainnet.helius-rpc.com/?api-key=") + HELIUS_API_KEY
HELIUS_WS_URL = os.getenv("HELIUS_WS_URL", "wss://mainnet.helius-rpc.com/?api-key=") + HELIUS_API_KEY
HELIUS_REST_URL = os.getenv("HELIUS_REST_URL", "https://api.helius.xyz")
JUPITER_API_URL = os.getenv("JUPITER_API_URL", "https://api.jup.ag/swap/v1")
DEXSCREENER_API_URL = os.getenv("DEXSCREENER_API_URL", "https://api.dexscreener.com/latest")
GROK_API_URL = os.getenv("GROK_API_URL", "https://api.x.ai/v1")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# === Wallet Tracker ===
WALLET_POLL_INTERVAL = _env_int("WALLET_POLL_INTERVAL", 10)
CONVERGENCE_WINDOW = _env_int("CONVERGENCE_WINDOW", 120)
MIN_APES = _env_int("MIN_APES", 2)
MAX_TRACKED_WALLETS = _env_int("MAX_TRACKED_WALLETS", 30)

# === Token Intelligence / Scoring ===
BUY_SCORE_THRESHOLD = _env_int("BUY_SCORE_THRESHOLD", 60)
MAX_HOLDER_CONCENTRATION = _env_float("MAX_HOLDER_CONCENTRATION", 0.60)
MAX_TOP3_CONCENTRATION = _env_float("MAX_TOP3_CONCENTRATION", 0.50)
LARGE_SELL_THRESHOLD = _env_float("LARGE_SELL_THRESHOLD", 0.05)
LARGE_SELL_WINDOW = _env_int("LARGE_SELL_WINDOW", 600)
SCORING_TIMEOUT = _env_float("SCORING_TIMEOUT", 5.0)

# === Position Sizing ===
MAX_POSITION_SOL = _env_float("MAX_POSITION_SOL", 10.0)
VOLUME_MULTIPLIER_THRESHOLD = _env_float("VOLUME_MULTIPLIER_THRESHOLD", 500000)
VOLUME_MULTIPLIER = _env_float("VOLUME_MULTIPLIER", 1.2)

# === Execution ===
SLIPPAGE_BPS = _env_int("SLIPPAGE_BPS", 1500)
SOL_FEE_RESERVE = _env_float("SOL_FEE_RESERVE", 0.01)
WSOL_MINT = "So11111111111111111111111111111111111111112"
RPC_TIMEOUT = _env_int("RPC_TIMEOUT", 30)
MAX_CONCURRENT_POSITIONS = _env_int("MAX_CONCURRENT_POSITIONS", 3)
HONEYPOT_TAX_THRESHOLD = _env_float("HONEYPOT_TAX_THRESHOLD", 0.15)

# === Take Profit / Stop Loss ===
INITIAL_TP_MULTIPLIER = _env_float("INITIAL_TP_MULTIPLIER", 2.0)
INITIAL_SL_PERCENT = _env_float("INITIAL_SL_PERCENT", 0.30)
TRAILING_TP_PERCENT = _env_float("TRAILING_TP_PERCENT", 0.15)
TIGHTENED_TRAIL_PERCENT = _env_float("TIGHTENED_TRAIL_PERCENT", 0.08)
PROFIT_LOCK_TIER1 = _env_float("PROFIT_LOCK_TIER1", 1.5)
PROFIT_LOCK_TIER2 = _env_float("PROFIT_LOCK_TIER2", 2.0)

# === CT Motion / Grok ===
CT_POLL_INTERVAL = _env_int("CT_POLL_INTERVAL", 180)
HOLD_BOOST_LOCK_PERCENT = _env_float("HOLD_BOOST_LOCK_PERCENT", 0.50)
HOLD_BOOST_ADD_MULTIPLIER = _env_float("HOLD_BOOST_ADD_MULTIPLIER", 1.5)
HOLD_BOOST_TP_MULTIPLIER = _env_float("HOLD_BOOST_TP_MULTIPLIER", 4.0)
VOLUME_GROWTH_THRESHOLD = _env_float("VOLUME_GROWTH_THRESHOLD", 0.20)

# === Crawlers ===
CRAWLER_INTERVAL = _env_int("CRAWLER_INTERVAL", 75)
CRAWLER_BONUS_SCORE = _env_int("CRAWLER_BONUS_SCORE", 15)
PUMPFUN_MC_SPIKE_THRESHOLD = _env_float("PUMPFUN_MC_SPIKE_THRESHOLD", 2.0)
PUMPFUN_SPIKE_WINDOW = _env_int("PUMPFUN_SPIKE_WINDOW", 1800)

# === Exit Manager ===
EXIT_CHECK_INTERVAL = _env_int("EXIT_CHECK_INTERVAL", 60)
NUKE_CHECK_INTERVAL = _env_int("NUKE_CHECK_INTERVAL", 30)
TOP_HOLDER_SELL_THRESHOLD = _env_float("TOP_HOLDER_SELL_THRESHOLD", 0.10)
NUKE_SELLER_COUNT = _env_int("NUKE_SELLER_COUNT", 3)
NUKE_WINDOW = _env_int("NUKE_WINDOW", 300)
NUKE_SELL_PERCENT = _env_float("NUKE_SELL_PERCENT", 0.80)
VOLUME_DECAY_THRESHOLD = _env_float("VOLUME_DECAY_THRESHOLD", 0.40)
LIQUIDITY_COLLAPSE_THRESHOLD = _env_float("LIQUIDITY_COLLAPSE_THRESHOLD", 0.20)
LIQUIDITY_COLLAPSE_WINDOW = _env_int("LIQUIDITY_COLLAPSE_WINDOW", 300)

# === Learning ===
MIN_WALLET_SCORE = _env_float("MIN_WALLET_SCORE", 0.1)
DEFAULT_WALLET_SCORE = _env_float("DEFAULT_WALLET_SCORE", 50.0)
WIN_RATE_HIGH = _env_float("WIN_RATE_HIGH", 0.65)
WIN_RATE_LOW = _env_float("WIN_RATE_LOW", 0.40)
THRESHOLD_RAISE = _env_int("THRESHOLD_RAISE", 5)
THRESHOLD_LOWER = _env_int("THRESHOLD_LOWER", 3)
THRESHOLD_MIN = _env_int("THRESHOLD_MIN", 55)
THRESHOLD_LOOKBACK = _env_int("THRESHOLD_LOOKBACK", 20)

# === Re-entry Cooldown ===
REENTRY_COOLDOWN = _env_int("REENTRY_COOLDOWN", 86400)

# === Bear Market Detection ===
BEAR_BTC_DROP_THRESHOLD = _env_float("BEAR_BTC_DROP_THRESHOLD", 0.03)
BEAR_THRESHOLD_BOOST = _env_int("BEAR_THRESHOLD_BOOST", 10)

# === Rate Limiting (token bucket) ===
HELIUS_RATE_LIMIT = _env_int("HELIUS_RATE_LIMIT", 10)
DEXSCREENER_RATE_LIMIT = _env_int("DEXSCREENER_RATE_LIMIT", 5)
JUPITER_RATE_LIMIT = _env_int("JUPITER_RATE_LIMIT", 10)
GROK_RATE_LIMIT = _env_int("GROK_RATE_LIMIT", 2)

# === Logging ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT_JSON = _env_bool("LOG_FORMAT_JSON", True)

# === Wallet Encryption ===
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
TRADER_WALLET_KEY = os.getenv("TRADER_WALLET_KEY", "")

# === Daily Summary ===
DAILY_SUMMARY_HOUR = _env_int("DAILY_SUMMARY_HOUR", 0)


def validate():
    errors = []
    if not HELIUS_API_KEY:
        errors.append("HELIUS_API_KEY is required")
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is required")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID is required")
    if MIN_APES < 2 or MIN_APES > 5:
        errors.append("MIN_APES must be between 2 and 5")
    if MAX_POSITION_SOL <= 0:
        errors.append("MAX_POSITION_SOL must be positive")
    if BUY_SCORE_THRESHOLD < THRESHOLD_MIN:
        errors.append(f"BUY_SCORE_THRESHOLD must be >= {THRESHOLD_MIN}")
    if errors:
        raise ValueError(f"Config validation failed: {'; '.join(errors)}")
