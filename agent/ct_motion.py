import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import settings
from db import get_db
from agent.utils import RateLimiter, create_aiohttp_session, retry_with_backoff

logger = logging.getLogger("savage.ct_motion")


@dataclass
class MotionSignal:
    token_address: str
    token_symbol: str
    trending: bool
    sentiment: str
    velocity: str
    key_signals: list[str]
    action: str


class CTMotionDetector:
    def __init__(self, exit_queue: asyncio.Queue):
        self.exit_queue = exit_queue
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._grok_limiter = RateLimiter(settings.GROK_RATE_LIMIT)
        self._dex_limiter = RateLimiter(settings.DEXSCREENER_RATE_LIMIT)
        self._volume_history: dict[str, list[tuple[float, float]]] = {}
        self._consecutive_failures = 0
        self._fallback_until: float = 0

    async def start(self):
        self._running = True
        self._session = create_aiohttp_session()
        logger.info("ct motion detector started")
        while self._running:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ct motion cycle error: %s", e)
            await asyncio.sleep(settings.CT_POLL_INTERVAL)

    async def stop(self):
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()

    async def _poll_cycle(self):
        db = await get_db("trades.db")
        try:
            cursor = await db.execute("SELECT * FROM open_positions")
            positions = [dict(row) for row in await cursor.fetchall()]
        finally:
            await db.close()

        for pos in positions:
            try:
                signal = await self._analyze_token(pos)
                if signal:
                    await self._process_signal(pos, signal)
            except Exception as e:
                logger.error("ct motion analysis failed for %s: %s", pos["token_address"][:8], e)

    async def _analyze_token(self, pos: dict) -> Optional[MotionSignal]:
        token_address = pos["token_address"]
        token_symbol = pos["token_symbol"] or ""

        use_fallback = time.monotonic() < self._fallback_until

        if not use_fallback and settings.GROK_API_KEY:
            grok_result = await self._query_grok(token_symbol, token_address)
            if grok_result:
                self._consecutive_failures = 0
                return MotionSignal(
                    token_address=token_address,
                    token_symbol=token_symbol,
                    trending=grok_result.get("trending", False),
                    sentiment=grok_result.get("sentiment", "neutral"),
                    velocity=grok_result.get("velocity", "low"),
                    key_signals=grok_result.get("key_signals", []),
                    action="NONE",
                )
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= 5:
                    self._fallback_until = time.monotonic() + 600
                    logger.warning("grok failed %d times, switching to fallback for 10 minutes", self._consecutive_failures)
                elif self._consecutive_failures >= 3:
                    logger.warning("grok failed %d times, backing off 60s", self._consecutive_failures)
                    await asyncio.sleep(60)

        return await self._dexscreener_fallback(token_address, token_symbol)

    async def _query_grok(self, token_symbol: str, token_address: str) -> Optional[dict]:
        try:
            personality = (settings.DATA_DIR / "PERSONALITY.md").read_text()
        except FileNotFoundError:
            personality = ""
        try:
            soul = (settings.DATA_DIR / "SOUL.md").read_text()
        except FileNotFoundError:
            soul = ""

        system_prompt = f"""You are an AI analyzing crypto twitter sentiment.

{personality}

{soul}

Respond ONLY with valid JSON."""

        user_prompt = f"""Is ${token_symbol} ({token_address}) gaining traction on CT right now?

Return JSON: {{"trending": bool, "sentiment": "positive"|"neutral"|"negative", "velocity": "low"|"medium"|"high", "key_signals": [...]}}"""

        await self._grok_limiter.acquire()
        try:
            async with self._session.post(
                f"{settings.GROK_API_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.GROK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": settings.GROK_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    logger.warning("grok rate limited")
                    return None
                if resp.status != 200:
                    logger.warning("grok returned status %d", resp.status)
                    return None
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            logger.warning("grok API error for %s: %s", token_symbol, e)
            return None

    async def _dexscreener_fallback(self, token_address: str, token_symbol: str) -> Optional[MotionSignal]:
        logger.debug("using dexscreener fallback for %s (grok unavailable)", token_symbol)
        await self._dex_limiter.acquire()
        try:
            url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{token_address}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except Exception as e:
            logger.warning("dexscreener fallback failed for %s: %s", token_symbol, e)
            return None

        pairs = data.get("pairs") or []
        if not pairs:
            return None

        pair = pairs[0]
        price_change_1h = float(pair.get("priceChange", {}).get("h1", 0) or 0)
        has_socials = bool(pair.get("info", {}).get("socials", []) if pair.get("info") else [])

        trending = has_socials and price_change_1h > 10
        sentiment = "positive" if price_change_1h > 5 else ("negative" if price_change_1h < -10 else "neutral")
        velocity = "high" if price_change_1h > 30 else ("medium" if price_change_1h > 10 else "low")

        signals = []
        if has_socials:
            signals.append("has_social_links")
        if price_change_1h > 10:
            signals.append(f"price_up_{price_change_1h:.0f}%_1h")

        return MotionSignal(
            token_address=token_address,
            token_symbol=token_symbol,
            trending=trending,
            sentiment=sentiment,
            velocity=velocity,
            key_signals=signals,
            action="NONE",
        )

    async def _process_signal(self, pos: dict, signal: MotionSignal):
        token_address = pos["token_address"]
        token_symbol = pos["token_symbol"] or ""
        was_boosted = bool(pos["hold_boost_locked"])

        if signal.trending and signal.sentiment == "positive" and signal.velocity == "high":
            signal.action = "HOLD_BOOST"
            await self._apply_hold_boost(pos, signal)
        elif was_boosted and signal.sentiment == "negative":
            signal.action = "RELEASE_LOCK"
            await self._release_boost(pos)
        else:
            signal.action = "NONE"

        db = await get_db("learning.db")
        try:
            await db.execute("""
                INSERT INTO ct_motion_events (token_address, token_symbol, trending, sentiment, velocity, key_signals, action_taken)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                token_address, token_symbol,
                1 if signal.trending else 0,
                signal.sentiment, signal.velocity,
                json.dumps(signal.key_signals),
                signal.action,
            ))
            await db.commit()
        finally:
            await db.close()

        logger.info(
            "ct motion: %s trending=%s sentiment=%s velocity=%s action=%s",
            token_symbol, signal.trending, signal.sentiment, signal.velocity, signal.action,
        )

    async def _apply_hold_boost(self, pos: dict, signal: MotionSignal):
        token_address = pos["token_address"]
        token_symbol = pos["token_symbol"] or ""
        amount_tokens = pos["amount_tokens"]
        entry_price = pos["entry_price"]

        if pos["hold_boost_locked"]:
            await self._check_volume_growth(pos)
            return

        locked_amount = amount_tokens * settings.HOLD_BOOST_LOCK_PERCENT
        boost_tp = entry_price * settings.HOLD_BOOST_TP_MULTIPLIER

        db = await get_db("trades.db")
        try:
            await db.execute(
                "UPDATE open_positions SET hold_boost_locked = 1, locked_amount_tokens = ?, boost_tp_price = ? WHERE token_address = ?",
                (locked_amount, boost_tp, token_address),
            )
            await db.commit()
        finally:
            await db.close()

        await self._check_volume_growth(pos)

        logger.info(
            "hold boost activated for %s: locked %.0f%%, boost TP at %.2fx",
            token_symbol, settings.HOLD_BOOST_LOCK_PERCENT * 100, settings.HOLD_BOOST_TP_MULTIPLIER,
        )

    async def _check_volume_growth(self, pos: dict):
        token_address = pos["token_address"]

        await self._dex_limiter.acquire()
        try:
            url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{token_address}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
        except Exception:
            return

        pairs = data.get("pairs") or []
        if not pairs:
            return

        volume_1h = float(pairs[0].get("volume", {}).get("h1", 0) or 0)
        now = time.monotonic()

        history = self._volume_history.setdefault(token_address, [])
        history.append((now, volume_1h))
        history[:] = [(t, v) for t, v in history if now - t < 1800]

        if len(history) >= 2:
            oldest_vol = history[0][1]
            if oldest_vol > 0:
                growth = (volume_1h - oldest_vol) / oldest_vol
                if growth > settings.VOLUME_GROWTH_THRESHOLD:
                    logger.info(
                        "volume growing %.1f%% for %s, CT motion confirmed",
                        growth * 100, pos["token_symbol"] or token_address[:8],
                    )

    async def _release_boost(self, pos: dict):
        token_address = pos["token_address"]
        token_symbol = pos["token_symbol"] or ""

        db = await get_db("trades.db")
        try:
            await db.execute(
                "UPDATE open_positions SET hold_boost_locked = 0, locked_amount_tokens = 0, boost_tp_price = NULL WHERE token_address = ?",
                (token_address,),
            )
            await db.commit()
        finally:
            await db.close()

        self._volume_history.pop(token_address, None)
        logger.info("hold boost released for %s, sentiment flipped negative", token_symbol)
