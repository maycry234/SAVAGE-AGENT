import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import settings
from db import get_db
from agent.utils import RateLimiter, create_aiohttp_session

logger = logging.getLogger("savage.crawlers")


@dataclass
class CrawlerSignal:
    source: str
    token_address: Optional[str]
    token_symbol: Optional[str]
    signal_type: str
    data: dict


class PlatformCrawlers:
    def __init__(self):
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._signals: dict[str, list[CrawlerSignal]] = {}
        self._dex_limiter = RateLimiter(settings.DEXSCREENER_RATE_LIMIT)
        self._prev_pumpfun: dict[str, float] = {}

    async def start(self):
        self._running = True
        self._session = create_aiohttp_session(timeout_total=20)
        logger.info("platform crawlers started")
        while self._running:
            try:
                results = await asyncio.gather(
                    self._crawl_pumpfun(),
                    self._crawl_memescope(),
                    self._crawl_printr(),
                    return_exceptions=True,
                )
                await self._process_signals(results)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("crawler cycle error: %s", e)
            await asyncio.sleep(settings.CRAWLER_INTERVAL)

    async def stop(self):
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()

    # ── PumpFun crawler ─────────────────────────────────────────────────

    async def _crawl_pumpfun(self) -> list[CrawlerSignal]:
        signals: list[CrawlerSignal] = []
        try:
            url = "https://frontend-api-v3.pump.fun/coins?sort=market_cap&order=DESC&limit=50&includeNsfw=false"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("pumpfun returned status %d", resp.status)
                    return signals
                data = await resp.json()
        except Exception as e:
            logger.warning("pumpfun crawl failed: %s", e)
            return signals

        if not isinstance(data, list):
            data = data.get("coins", data.get("data", []))
            if not isinstance(data, list):
                return signals

        now = time.time()
        current_mc: dict[str, float] = {}

        for coin in data:
            mint = coin.get("mint", "")
            symbol = coin.get("symbol", "")
            market_cap = float(coin.get("market_cap", 0) or coin.get("usd_market_cap", 0) or 0)
            created_ts = coin.get("created_timestamp")

            if not mint:
                continue

            current_mc[mint] = market_cap

            if mint in self._prev_pumpfun:
                old_mc = self._prev_pumpfun[mint]
                if old_mc > 0:
                    spike = market_cap / old_mc
                    if spike >= settings.PUMPFUN_MC_SPIKE_THRESHOLD:
                        sig = CrawlerSignal(
                            source="pumpfun",
                            token_address=mint,
                            token_symbol=symbol,
                            signal_type="mc_spike",
                            data={"market_cap": market_cap, "spike_ratio": spike, "prev_mc": old_mc},
                        )
                        signals.append(sig)
                        logger.info("pumpfun mc spike: %s %.1fx (%s)", symbol, spike, mint[:8])

            if created_ts:
                try:
                    age_seconds = now - (created_ts / 1000 if created_ts > 1e12 else created_ts)
                    if 0 < age_seconds < settings.PUMPFUN_SPIKE_WINDOW and market_cap > 50000:
                        sig = CrawlerSignal(
                            source="pumpfun",
                            token_address=mint,
                            token_symbol=symbol,
                            signal_type="trending",
                            data={"market_cap": market_cap, "age_seconds": age_seconds},
                        )
                        signals.append(sig)
                except (TypeError, ValueError):
                    pass

        self._prev_pumpfun = current_mc
        if signals:
            logger.info("pumpfun crawl found %d signals", len(signals))
        return signals

    # ── Memescope / FOMO crawler ────────────────────────────────────────

    async def _crawl_memescope(self) -> list[CrawlerSignal]:
        signals: list[CrawlerSignal] = []
        endpoints = [
            "https://api.memescope.io/v1/trending",
            "https://memescope.io/api/trending",
        ]

        for url in endpoints:
            try:
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tokens = data if isinstance(data, list) else data.get("tokens", data.get("data", []))
                        for token in tokens[:20]:
                            addr = token.get("address", token.get("mint", token.get("token_address", "")))
                            sym = token.get("symbol", "")
                            if addr:
                                signals.append(CrawlerSignal(
                                    source="memescope",
                                    token_address=addr,
                                    token_symbol=sym,
                                    signal_type="trending",
                                    data={"raw": {k: v for k, v in token.items() if isinstance(v, (str, int, float, bool))}},
                                ))
                        if signals:
                            logger.info("memescope crawl found %d signals", len(signals))
                        return signals
            except Exception as e:
                logger.debug("memescope endpoint %s unavailable: %s", url, e)
                continue

        logger.debug("memescope: no API endpoints available, playwright scraping would be needed")
        return signals

    # ── Printr crawler ──────────────────────────────────────────────────

    async def _crawl_printr(self) -> list[CrawlerSignal]:
        signals: list[CrawlerSignal] = []
        endpoints = [
            "https://api.printr.io/v1/trending",
            "https://printr.io/api/trending",
        ]

        for url in endpoints:
            try:
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tokens = data if isinstance(data, list) else data.get("tokens", data.get("data", []))
                        for token in tokens[:20]:
                            addr = token.get("address", token.get("mint", token.get("token_address", "")))
                            sym = token.get("symbol", "")
                            if addr:
                                signals.append(CrawlerSignal(
                                    source="printr",
                                    token_address=addr,
                                    token_symbol=sym,
                                    signal_type="trending",
                                    data={"raw": {k: v for k, v in token.items() if isinstance(v, (str, int, float, bool))}},
                                ))
                        if signals:
                            logger.info("printr crawl found %d signals", len(signals))
                        return signals
            except Exception as e:
                logger.debug("printr endpoint %s unavailable: %s", url, e)
                continue

        logger.debug("printr: no API endpoints available, graceful degradation")
        return signals

    # ── Signal processing ───────────────────────────────────────────────

    async def _process_signals(self, results: list):
        all_signals: list[CrawlerSignal] = []
        for result in results:
            if isinstance(result, list):
                all_signals.extend(result)
            elif isinstance(result, Exception):
                logger.warning("crawler returned exception: %s", result)

        if not all_signals:
            return

        for sig in all_signals:
            if sig.token_address:
                self._signals.setdefault(sig.token_address, []).append(sig)

        now = time.time()
        for token, sigs in list(self._signals.items()):
            self._signals[token] = sigs[-50:]

        db = await get_db("trades.db")
        try:
            for sig in all_signals:
                if sig.token_address:
                    import json
                    await db.execute(
                        "INSERT INTO crawler_signals (source, token_address, token_symbol, signal_type, data) VALUES (?, ?, ?, ?, ?)",
                        (sig.source, sig.token_address, sig.token_symbol, sig.signal_type, json.dumps(sig.data)),
                    )
            await db.commit()
        finally:
            await db.close()

        logger.info("processed %d crawler signals from %d sources", len(all_signals), len({s.source for s in all_signals}))

    # ── Cross-reference scoring ─────────────────────────────────────────

    async def get_bonus_score(self, token_address: str) -> int:
        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT DISTINCT source FROM crawler_signals WHERE token_address = ? AND detected_at > datetime('now', '-5 minutes')",
                (token_address,),
            )
            sources = await cursor.fetchall()
            if len(sources) >= 2:
                return settings.CRAWLER_BONUS_SCORE
            return 0
        finally:
            await db.close()

    def get_cached_signals(self, token_address: str) -> list[CrawlerSignal]:
        return self._signals.get(token_address, [])
