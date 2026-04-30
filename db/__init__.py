import aiosqlite
from config import settings
import os


async def get_db(db_name: str = "trades.db") -> aiosqlite.Connection:
    os.makedirs(settings.DB_DIR, exist_ok=True)
    db_path = settings.DB_DIR / db_name
    db = await aiosqlite.connect(str(db_path))
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = aiosqlite.Row
    return db


async def init_trades_db():
    db = await get_db("trades.db")
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallet_swaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                token_address TEXT NOT NULL,
                tx_signature TEXT UNIQUE NOT NULL,
                amount_sol REAL,
                timestamp INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_swaps_token_ts "
            "ON wallet_swaps(token_address, timestamp)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_swaps_wallet "
            "ON wallet_swaps(wallet_address)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS convergence_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                wallet_count INTEGER NOT NULL,
                wallets TEXT NOT NULL,
                buy_score REAL,
                position_size_sol REAL,
                triggered_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS open_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT UNIQUE NOT NULL,
                token_symbol TEXT,
                entry_price REAL NOT NULL,
                current_price REAL,
                amount_tokens REAL NOT NULL,
                amount_sol REAL NOT NULL,
                peak_price REAL,
                tp_price REAL,
                sl_price REAL,
                trailing_activated INTEGER DEFAULT 0,
                trail_percent REAL,
                hold_boost_locked INTEGER DEFAULT 0,
                locked_amount_tokens REAL DEFAULT 0,
                boost_tp_price REAL,
                tier1_sold INTEGER DEFAULT 0,
                tier2_sold INTEGER DEFAULT 0,
                remaining_percent REAL DEFAULT 1.0,
                opened_at TEXT DEFAULT (datetime('now')),
                last_updated TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS completed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                token_symbol TEXT,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                amount_sol_in REAL NOT NULL,
                amount_sol_out REAL NOT NULL,
                pnl_sol REAL NOT NULL,
                pnl_percent REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                trigger_wallets TEXT,
                buy_score REAL,
                duration_seconds INTEGER,
                opened_at TEXT NOT NULL,
                closed_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_completed_trades_closed "
            "ON completed_trades(closed_at)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS token_scores (
                token_address TEXT PRIMARY KEY,
                buy_score REAL NOT NULL,
                volume_score REAL,
                holder_score REAL,
                distribution_score REAL,
                dev_safety_score REAL,
                raw_data TEXT,
                scored_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS holder_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                holder_address TEXT NOT NULL,
                balance REAL NOT NULL,
                percent_of_supply REAL NOT NULL,
                snapshot_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_holder_snap_token "
            "ON holder_snapshots(token_address, snapshot_at)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS liquidity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                liquidity_usd REAL NOT NULL,
                volume_1h REAL,
                snapshot_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_liq_snap_token "
            "ON liquidity_snapshots(token_address, snapshot_at)"
        )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reentry_cooldowns (
                token_address TEXT PRIMARY KEY,
                exit_reason TEXT NOT NULL,
                cooldown_until TEXT NOT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS crawler_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                token_address TEXT,
                token_symbol TEXT,
                signal_type TEXT NOT NULL,
                data TEXT,
                detected_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_crawler_token "
            "ON crawler_signals(token_address, detected_at)"
        )

        await db.commit()
    finally:
        await db.close()


async def init_learning_db():
    db = await get_db("learning.db")
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallet_scores (
                wallet_address TEXT PRIMARY KEY,
                score REAL NOT NULL DEFAULT 50.0,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                total_pnl_sol REAL DEFAULT 0.0,
                last_updated TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS score_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                old_score REAL NOT NULL,
                new_score REAL NOT NULL,
                reason TEXT NOT NULL,
                trade_id INTEGER,
                changed_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS threshold_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_threshold INTEGER NOT NULL,
                new_threshold INTEGER NOT NULL,
                win_rate REAL NOT NULL,
                lookback_trades INTEGER NOT NULL,
                reason TEXT NOT NULL,
                changed_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ct_motion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                token_symbol TEXT,
                trending INTEGER,
                sentiment TEXT,
                velocity TEXT,
                key_signals TEXT,
                action_taken TEXT,
                detected_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.commit()
    finally:
        await db.close()


async def init_all():
    await init_trades_db()
    await init_learning_db()
