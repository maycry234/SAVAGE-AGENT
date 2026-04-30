import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import aiosqlite

from config import settings
from db import get_db

logger = logging.getLogger("savage.learning")


class LearningEngine:
    def __init__(self):
        self._current_threshold = settings.BUY_SCORE_THRESHOLD
        self._learning_log_path = settings.LOG_DIR / "learning.log"

    async def update_wallet_scores(self, trade_id: int, trigger_wallets: list[str], pnl_sol: float, pnl_percent: float):
        db = await get_db("learning.db")
        try:
            for wallet in trigger_wallets:
                cursor = await db.execute(
                    "SELECT score, total_trades, winning_trades, total_pnl_sol FROM wallet_scores WHERE wallet_address = ?",
                    (wallet,),
                )
                row = await cursor.fetchone()
                if row:
                    old_score = row["score"]
                    total = row["total_trades"] + 1
                    wins = row["winning_trades"] + (1 if pnl_sol > 0 else 0)
                    total_pnl = row["total_pnl_sol"] + pnl_sol
                else:
                    old_score = settings.DEFAULT_WALLET_SCORE
                    total = 1
                    wins = 1 if pnl_sol > 0 else 0
                    total_pnl = pnl_sol

                if pnl_sol > 0:
                    bonus = min(pnl_percent * 0.1, 5.0)
                    new_score = min(100.0, old_score + bonus)
                else:
                    penalty = min(abs(pnl_percent) * 0.15, 8.0)
                    new_score = max(settings.MIN_WALLET_SCORE, old_score - penalty)

                await db.execute("""
                    INSERT INTO wallet_scores (wallet_address, score, total_trades, winning_trades, total_pnl_sol, last_updated)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(wallet_address) DO UPDATE SET
                        score = ?, total_trades = ?, winning_trades = ?, total_pnl_sol = ?, last_updated = datetime('now')
                """, (wallet, new_score, total, wins, total_pnl, new_score, total, wins, total_pnl))

                await db.execute("""
                    INSERT INTO score_history (wallet_address, old_score, new_score, reason, trade_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (wallet, old_score, new_score, f"{'profit' if pnl_sol > 0 else 'loss'}: {pnl_percent:.1f}%", trade_id))

                self._write_learning_log(
                    f"WALLET_SCORE: {wallet[:8]}... {old_score:.1f} → {new_score:.1f} (trade #{trade_id}, pnl: {pnl_percent:+.1f}%)"
                )

            await db.commit()
        finally:
            await db.close()

    async def adapt_threshold(self) -> Optional[int]:
        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT pnl_sol FROM completed_trades ORDER BY closed_at DESC LIMIT ?",
                (settings.THRESHOLD_LOOKBACK,),
            )
            trades = await cursor.fetchall()
            if len(trades) < settings.THRESHOLD_LOOKBACK:
                return None

            wins = sum(1 for t in trades if t["pnl_sol"] > 0)
            win_rate = wins / len(trades)
            old_threshold = self._current_threshold

            if win_rate < settings.WIN_RATE_LOW:
                self._current_threshold = min(100, old_threshold + settings.THRESHOLD_RAISE)
                reason = f"win rate {win_rate:.1%} < {settings.WIN_RATE_LOW:.0%}, raising threshold"
            elif win_rate > settings.WIN_RATE_HIGH:
                self._current_threshold = max(settings.THRESHOLD_MIN, old_threshold - settings.THRESHOLD_LOWER)
                reason = f"win rate {win_rate:.1%} > {settings.WIN_RATE_HIGH:.0%}, lowering threshold"
            else:
                return self._current_threshold

            if old_threshold != self._current_threshold:
                ldb = await get_db("learning.db")
                try:
                    await ldb.execute("""
                        INSERT INTO threshold_history (old_threshold, new_threshold, win_rate, lookback_trades, reason)
                        VALUES (?, ?, ?, ?, ?)
                    """, (old_threshold, self._current_threshold, win_rate, len(trades), reason))
                    await ldb.commit()
                finally:
                    await ldb.close()

                self._write_learning_log(f"THRESHOLD: {old_threshold} → {self._current_threshold} ({reason})")
        finally:
            await db.close()

        return self._current_threshold

    def _write_learning_log(self, message: str):
        os.makedirs(settings.LOG_DIR, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(self._learning_log_path, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
        logger.info(message)

    async def check_bear_market(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{settings.DEXSCREENER_API_URL}/dex/tokens/{settings.WSOL_MINT}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get("pairs"):
                        price_change_1h = float(data["pairs"][0].get("priceChange", {}).get("h1", 0) or 0)
                        if price_change_1h < -(settings.BEAR_BTC_DROP_THRESHOLD * 100):
                            return True
        except Exception as e:
            logger.warning("bear market check failed: %s", e)
        return False

    async def get_effective_threshold(self) -> int:
        is_bear = await self.check_bear_market()
        threshold = self._current_threshold
        if is_bear:
            threshold += settings.BEAR_THRESHOLD_BOOST
            logger.info("bear market detected, effective threshold: %d", threshold)
        return threshold

    async def get_wallet_score(self, wallet_address: str) -> float:
        db = await get_db("learning.db")
        try:
            cursor = await db.execute(
                "SELECT score FROM wallet_scores WHERE wallet_address = ?",
                (wallet_address,),
            )
            row = await cursor.fetchone()
            return row["score"] if row else settings.DEFAULT_WALLET_SCORE
        finally:
            await db.close()

    @property
    def current_threshold(self) -> int:
        return self._current_threshold
