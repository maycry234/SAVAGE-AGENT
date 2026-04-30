import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
import aiosqlite

from config import settings
from db import get_db
from agent.execution import ExecutionEngine
from agent.utils import RateLimiter, create_aiohttp_session

logger = logging.getLogger("savage.exit_manager")


@dataclass
class ExitEvent:
    token_address: str
    token_symbol: str
    exit_reason: str
    pnl_sol: float
    pnl_percent: float
    duration_seconds: int
    amount_sold_percent: float


class ExitManager:
    def __init__(self, execution_engine: ExecutionEngine, exit_queue: asyncio.Queue):
        self.engine = execution_engine
        self.exit_queue = exit_queue
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._helius_limiter = RateLimiter(settings.HELIUS_RATE_LIMIT)
        self._dex_limiter = RateLimiter(settings.DEXSCREENER_RATE_LIMIT)

    async def start(self):
        self._running = True
        self._session = create_aiohttp_session()
        logger.info("exit manager started")
        tasks = [
            asyncio.create_task(self._position_monitor_loop(), name="position_monitor"),
            asyncio.create_task(self._nuke_detector_loop(), name="nuke_detector"),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("exit manager shutting down")
        finally:
            await self.stop()

    async def stop(self):
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Position monitor loop ───────────────────────────────────────────

    async def _position_monitor_loop(self):
        while self._running:
            try:
                positions = await self._fetch_open_positions()
                for pos in positions:
                    try:
                        await self._check_position(pos)
                    except Exception as e:
                        logger.error("position check failed token=%s: %s", pos["token_address"][:8], e)
            except Exception as e:
                logger.error("position monitor cycle error: %s", e)
            await asyncio.sleep(settings.EXIT_CHECK_INTERVAL)

    async def _check_position(self, pos: dict):
        token_address = pos["token_address"]
        token_symbol = pos["token_symbol"] or ""
        entry_price = pos["entry_price"]
        current_peak = pos["peak_price"] or entry_price
        tp_price = pos["tp_price"]
        sl_price = pos["sl_price"]
        trailing_activated = bool(pos["trailing_activated"])
        trail_percent = pos["trail_percent"] or settings.TRAILING_TP_PERCENT
        tier1_sold = bool(pos["tier1_sold"])
        tier2_sold = bool(pos["tier2_sold"])
        remaining_percent = pos["remaining_percent"] or 1.0
        amount_tokens = pos["amount_tokens"]
        amount_sol = pos["amount_sol"]
        hold_boost_locked = bool(pos["hold_boost_locked"])
        boost_tp_price = pos["boost_tp_price"]
        locked_amount_tokens = pos["locked_amount_tokens"] or 0
        opened_at = pos["opened_at"]

        current_price = await self._get_current_price(token_address)
        if current_price is None:
            return

        peak_price = max(current_peak, current_price)
        await self._update_position_prices(token_address, current_price, peak_price)

        multiplier = current_price / entry_price if entry_price > 0 else 0

        if await self._check_dev_sell(pos, multiplier):
            return

        if current_price <= sl_price:
            await self._execute_exit(
                pos, current_price, peak_price,
                exit_reason="SL_HIT",
                sell_percent=remaining_percent,
            )
            return

        if not tier1_sold and multiplier >= settings.PROFIT_LOCK_TIER1:
            sell_pct = 0.25
            sell_tokens = int(amount_tokens * sell_pct)
            result = await self.engine.sell_token(token_address, sell_tokens, "PROFIT_LOCK_TIER1")
            if result.success:
                new_remaining = remaining_percent - sell_pct
                db = await get_db("trades.db")
                try:
                    await db.execute(
                        "UPDATE open_positions SET tier1_sold = 1, remaining_percent = ? WHERE token_address = ?",
                        (new_remaining, token_address),
                    )
                    await db.commit()
                finally:
                    await db.close()
                await self._emit_partial_exit(pos, current_price, "PROFIT_LOCK_TIER1", sell_pct)
                logger.info("tier1 profit lock: sold 25%% of %s at %.2fx", token_symbol, multiplier)

        if not tier2_sold and multiplier >= settings.PROFIT_LOCK_TIER2:
            sell_pct = 0.25
            sell_tokens = int(amount_tokens * sell_pct)
            result = await self.engine.sell_token(token_address, sell_tokens, "PROFIT_LOCK_TIER2")
            if result.success:
                new_remaining = (remaining_percent if tier1_sold else remaining_percent) - sell_pct
                db = await get_db("trades.db")
                try:
                    await db.execute(
                        "UPDATE open_positions SET tier2_sold = 1, trailing_activated = 1, remaining_percent = ? WHERE token_address = ?",
                        (new_remaining, token_address),
                    )
                    await db.commit()
                finally:
                    await db.close()
                await self._emit_partial_exit(pos, current_price, "PROFIT_LOCK_TIER2", sell_pct)
                logger.info("tier2 profit lock: sold 25%% of %s at %.2fx, trailing activated", token_symbol, multiplier)
                trailing_activated = True

        if trailing_activated:
            drop_from_peak = (peak_price - current_price) / peak_price if peak_price > 0 else 0
            if drop_from_peak > trail_percent:
                sell_pct = remaining_percent
                if hold_boost_locked and locked_amount_tokens > 0:
                    unlocked_tokens = amount_tokens * remaining_percent - locked_amount_tokens
                    sell_pct = unlocked_tokens / amount_tokens if amount_tokens > 0 else remaining_percent
                    sell_pct = max(0, sell_pct)
                if sell_pct > 0:
                    await self._execute_exit(
                        pos, current_price, peak_price,
                        exit_reason="TRAILING_TP",
                        sell_percent=sell_pct,
                    )
                    return

        if hold_boost_locked and boost_tp_price and current_price >= boost_tp_price:
            locked_pct = locked_amount_tokens / amount_tokens if amount_tokens > 0 else 0
            if locked_pct > 0:
                sell_tokens = int(locked_amount_tokens)
                result = await self.engine.sell_token(token_address, sell_tokens, "HOLD_BOOST_TP")
                if result.success:
                    new_remaining = remaining_percent - locked_pct
                    db = await get_db("trades.db")
                    try:
                        await db.execute(
                            "UPDATE open_positions SET hold_boost_locked = 0, locked_amount_tokens = 0, remaining_percent = ? WHERE token_address = ?",
                            (new_remaining, token_address),
                        )
                        await db.commit()
                    finally:
                        await db.close()
                    await self._emit_partial_exit(pos, current_price, "HOLD_BOOST_TP", locked_pct)
                    logger.info("hold boost TP hit for %s, sold locked portion", token_symbol)

        await self._check_volume_decay(token_address, trail_percent)

    async def _check_dev_sell(self, pos: dict, multiplier: float) -> bool:
        if multiplier >= settings.PROFIT_LOCK_TIER2:
            return False

        token_address = pos["token_address"]
        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT raw_data FROM token_scores WHERE token_address = ?",
                (token_address,),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()

        if not row or not row["raw_data"]:
            return False

        try:
            raw = json.loads(row["raw_data"])
            dev_wallet = raw.get("dev_wallet") or raw.get("mint_authority")
        except (json.JSONDecodeError, TypeError):
            return False

        if not dev_wallet:
            return False

        try:
            await self._helius_limiter.acquire()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [dev_wallet, {"limit": 10}],
            }
            async with self._session.post(settings.HELIUS_RPC_URL, json=payload) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()

            sigs = data.get("result", [])
            opened_at = pos["opened_at"]
            for sig_info in sigs:
                block_time = sig_info.get("blockTime", 0)
                if block_time and datetime.fromtimestamp(block_time, tz=timezone.utc) > datetime.fromisoformat(opened_at).replace(tzinfo=timezone.utc):
                    memo = sig_info.get("memo", "") or ""
                    if sig_info.get("err") is None:
                        await self._execute_exit(
                            pos, pos.get("current_price", pos["entry_price"]),
                            pos.get("peak_price", pos["entry_price"]),
                            exit_reason="DEV_SELL",
                            sell_percent=pos["remaining_percent"] or 1.0,
                        )
                        logger.warning("dev sell detected for %s, emergency exit", pos["token_symbol"])
                        return True
        except Exception as e:
            logger.warning("dev sell check failed for %s: %s", pos["token_address"][:8], e)

        return False

    async def _check_volume_decay(self, token_address: str, current_trail: float):
        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT volume_1h FROM liquidity_snapshots WHERE token_address = ? ORDER BY snapshot_at DESC LIMIT 10",
                (token_address,),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()

        if len(rows) < 2:
            return

        volumes = [r["volume_1h"] for r in rows if r["volume_1h"] is not None]
        if not volumes:
            return

        peak_vol = max(volumes)
        current_vol = volumes[0]
        if peak_vol > 0 and (peak_vol - current_vol) / peak_vol > settings.VOLUME_DECAY_THRESHOLD:
            if current_trail > settings.TIGHTENED_TRAIL_PERCENT:
                db = await get_db("trades.db")
                try:
                    await db.execute(
                        "UPDATE open_positions SET trail_percent = ? WHERE token_address = ?",
                        (settings.TIGHTENED_TRAIL_PERCENT, token_address),
                    )
                    await db.commit()
                finally:
                    await db.close()
                logger.info("volume decay detected for %s, tightened trail to %.0f%%", token_address[:8], settings.TIGHTENED_TRAIL_PERCENT * 100)

    # ── Nuke detector loop ──────────────────────────────────────────────

    async def _nuke_detector_loop(self):
        while self._running:
            try:
                positions = await self._fetch_open_positions()
                for pos in positions:
                    try:
                        await self._check_nuke(pos)
                        await self._check_liquidity_collapse(pos)
                    except Exception as e:
                        logger.error("nuke check failed token=%s: %s", pos["token_address"][:8], e)
            except Exception as e:
                logger.error("nuke detector cycle error: %s", e)
            await asyncio.sleep(settings.NUKE_CHECK_INTERVAL)

    async def _check_nuke(self, pos: dict):
        token_address = pos["token_address"]

        await self._helius_limiter.acquire()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [token_address],
        }
        try:
            async with self._session.post(settings.HELIUS_RPC_URL, json=payload) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
        except Exception as e:
            logger.warning("holder fetch failed for %s: %s", token_address[:8], e)
            return

        holders = data.get("result", {}).get("value", [])[:20]
        if not holders:
            return

        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT holder_address, balance FROM holder_snapshots WHERE token_address = ? AND snapshot_at = (SELECT MAX(snapshot_at) FROM holder_snapshots WHERE token_address = ?)",
                (token_address, token_address),
            )
            prev_snapshot = {row["holder_address"]: row["balance"] for row in await cursor.fetchall()}

            flagged = 0
            now_str = datetime.now(timezone.utc).isoformat()
            for h in holders:
                addr = h.get("address", "")
                balance = float(h.get("uiAmount", 0) or 0)

                await db.execute(
                    "INSERT INTO holder_snapshots (token_address, holder_address, balance, percent_of_supply, snapshot_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    (token_address, addr, balance, float(h.get("uiAmount", 0) or 0)),
                )

                if addr in prev_snapshot:
                    old_balance = prev_snapshot[addr]
                    if old_balance > 0:
                        sell_pct = (old_balance - balance) / old_balance
                        if sell_pct > settings.TOP_HOLDER_SELL_THRESHOLD:
                            flagged += 1
                            logger.warning(
                                "top holder %s sold %.1f%% of %s",
                                addr[:8], sell_pct * 100, pos["token_symbol"] or token_address[:8],
                            )

            await db.commit()
        finally:
            await db.close()

        if flagged >= settings.NUKE_SELLER_COUNT:
            logger.warning(
                "NUKE DETECTED: %d top holders selling %s, emergency exit",
                flagged, pos["token_symbol"] or token_address[:8],
            )
            sell_pct = settings.NUKE_SELL_PERCENT
            sell_tokens = int(pos["amount_tokens"] * sell_pct)
            result = await self.engine.sell_token(token_address, sell_tokens, "TOP_HOLDER_NUKE")
            if result.success:
                current_price = await self._get_current_price(token_address) or pos.get("current_price", pos["entry_price"])
                new_remaining = (pos["remaining_percent"] or 1.0) - sell_pct
                if new_remaining <= 0.01:
                    await self._close_position(pos, current_price, "TOP_HOLDER_NUKE", sell_pct)
                else:
                    db = await get_db("trades.db")
                    try:
                        await db.execute(
                            "UPDATE open_positions SET remaining_percent = ? WHERE token_address = ?",
                            (new_remaining, token_address),
                        )
                        await db.commit()
                    finally:
                        await db.close()
                    await self._emit_partial_exit(pos, current_price, "TOP_HOLDER_NUKE", sell_pct)

    async def _check_liquidity_collapse(self, pos: dict):
        token_address = pos["token_address"]

        await self._dex_limiter.acquire()
        try:
            url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{token_address}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
        except Exception as e:
            logger.warning("liquidity fetch failed for %s: %s", token_address[:8], e)
            return

        pairs = data.get("pairs") or []
        if not pairs:
            return

        pair = pairs[0]
        liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
        volume_1h = float(pair.get("volume", {}).get("h1", 0) or 0)

        db = await get_db("trades.db")
        try:
            await db.execute(
                "INSERT INTO liquidity_snapshots (token_address, liquidity_usd, volume_1h) VALUES (?, ?, ?)",
                (token_address, liquidity, volume_1h),
            )
            await db.commit()

            window_seconds = settings.LIQUIDITY_COLLAPSE_WINDOW
            cursor = await db.execute(
                "SELECT liquidity_usd FROM liquidity_snapshots WHERE token_address = ? AND snapshot_at >= datetime('now', ?) ORDER BY snapshot_at ASC LIMIT 1",
                (token_address, f"-{window_seconds} seconds"),
            )
            old_row = await cursor.fetchone()
        finally:
            await db.close()

        if old_row and old_row["liquidity_usd"] > 0:
            old_liq = old_row["liquidity_usd"]
            drop = (old_liq - liquidity) / old_liq
            if drop > settings.LIQUIDITY_COLLAPSE_THRESHOLD:
                logger.warning(
                    "LIQUIDITY COLLAPSE: %s dropped %.1f%% in %ds",
                    pos["token_symbol"] or token_address[:8], drop * 100, window_seconds,
                )
                await self._execute_exit(
                    pos,
                    pos.get("current_price", pos["entry_price"]),
                    pos.get("peak_price", pos["entry_price"]),
                    exit_reason="LIQUIDITY_COLLAPSE",
                    sell_percent=pos["remaining_percent"] or 1.0,
                )

    # ── Execution helpers ───────────────────────────────────────────────

    async def _execute_exit(self, pos: dict, current_price: float, peak_price: float, exit_reason: str, sell_percent: float):
        token_address = pos["token_address"]
        amount_tokens = pos["amount_tokens"]
        sell_tokens = int(amount_tokens * sell_percent)

        result = await self.engine.sell_token(token_address, sell_tokens, exit_reason)
        if not result.success:
            logger.error("exit sell failed for %s: %s", token_address[:8], result.error)
            return

        await self._close_position(pos, current_price, exit_reason, sell_percent)

    async def _close_position(self, pos: dict, current_price: float, exit_reason: str, sell_percent: float):
        token_address = pos["token_address"]
        token_symbol = pos["token_symbol"] or ""
        entry_price = pos["entry_price"]
        amount_sol = pos["amount_sol"]
        opened_at = pos["opened_at"]

        pnl_percent = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        pnl_sol = amount_sol * (pnl_percent / 100) * sell_percent

        try:
            opened_dt = datetime.fromisoformat(opened_at).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            opened_dt = datetime.now(timezone.utc)
        duration = int((datetime.now(timezone.utc) - opened_dt).total_seconds())

        trigger_wallets = ""
        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT wallets FROM convergence_events WHERE token_address = ? ORDER BY triggered_at DESC LIMIT 1",
                (token_address,),
            )
            row = await cursor.fetchone()
            if row:
                trigger_wallets = row["wallets"]
        finally:
            await db.close()

        db = await get_db("trades.db")
        try:
            await db.execute("""
                INSERT INTO completed_trades (token_address, token_symbol, entry_price, exit_price, amount_sol_in, amount_sol_out, pnl_sol, pnl_percent, exit_reason, trigger_wallets, buy_score, duration_seconds, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                token_address, token_symbol, entry_price, current_price,
                amount_sol, amount_sol + pnl_sol, pnl_sol, pnl_percent,
                exit_reason, trigger_wallets, pos.get("buy_score"),
                duration, opened_at,
            ))

            await db.execute("DELETE FROM open_positions WHERE token_address = ?", (token_address,))

            cooldown_until = (datetime.now(timezone.utc) + timedelta(seconds=settings.REENTRY_COOLDOWN)).isoformat()
            await db.execute(
                "INSERT OR REPLACE INTO reentry_cooldowns (token_address, exit_reason, cooldown_until) VALUES (?, ?, ?)",
                (token_address, exit_reason, cooldown_until),
            )

            await db.commit()
        finally:
            await db.close()

        event = ExitEvent(
            token_address=token_address,
            token_symbol=token_symbol,
            exit_reason=exit_reason,
            pnl_sol=pnl_sol,
            pnl_percent=pnl_percent,
            duration_seconds=duration,
            amount_sold_percent=sell_percent * 100,
        )
        await self.exit_queue.put(event)

        logger.info(
            "EXIT %s reason=%s pnl=%.2f SOL (%.1f%%) held=%ds",
            token_symbol, exit_reason, pnl_sol, pnl_percent, duration,
        )

    async def _emit_partial_exit(self, pos: dict, current_price: float, reason: str, sell_percent: float):
        entry_price = pos["entry_price"]
        pnl_percent = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        pnl_sol = pos["amount_sol"] * (pnl_percent / 100) * sell_percent

        try:
            opened_dt = datetime.fromisoformat(pos["opened_at"]).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            opened_dt = datetime.now(timezone.utc)
        duration = int((datetime.now(timezone.utc) - opened_dt).total_seconds())

        event = ExitEvent(
            token_address=pos["token_address"],
            token_symbol=pos["token_symbol"] or "",
            exit_reason=reason,
            pnl_sol=pnl_sol,
            pnl_percent=pnl_percent,
            duration_seconds=duration,
            amount_sold_percent=sell_percent * 100,
        )
        await self.exit_queue.put(event)

    # ── Data fetching helpers ───────────────────────────────────────────

    async def _fetch_open_positions(self) -> list[dict]:
        db = await get_db("trades.db")
        try:
            cursor = await db.execute("SELECT * FROM open_positions")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await db.close()

    async def _get_current_price(self, token_address: str) -> Optional[float]:
        await self._dex_limiter.acquire()
        try:
            url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{token_address}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            pairs = data.get("pairs") or []
            if pairs:
                return float(pairs[0].get("priceUsd", 0) or 0)
        except Exception as e:
            logger.warning("price fetch failed for %s: %s", token_address[:8], e)
        return None

    async def _update_position_prices(self, token_address: str, current_price: float, peak_price: float):
        db = await get_db("trades.db")
        try:
            await db.execute(
                "UPDATE open_positions SET current_price = ?, peak_price = ?, last_updated = datetime('now') WHERE token_address = ?",
                (current_price, peak_price, token_address),
            )
            await db.commit()
        finally:
            await db.close()
