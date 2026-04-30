import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone

from config import settings
from db import init_all, get_db
from agent.wallet_tracker import WalletTracker, PlaySignal
from agent.token_intel import TokenIntel
from agent.execution import ExecutionEngine
from agent.exit_manager import ExitManager
from agent.ct_motion import CTMotionDetector
from agent.crawlers import PlatformCrawlers
from agent.learning import LearningEngine
from agent.alerts import AlertManager
from agent.utils import setup_logging

logger = logging.getLogger("savage.main")


class SavageAgent:
    def __init__(self):
        self.signal_queue = asyncio.Queue()
        self.exit_queue = asyncio.Queue()

        self.wallet_tracker = WalletTracker(self.signal_queue)
        self.token_intel = TokenIntel()
        self.execution = ExecutionEngine()
        self.exit_manager = ExitManager(self.execution, self.exit_queue)
        self.ct_motion = CTMotionDetector(self.exit_queue)
        self.crawlers = PlatformCrawlers()
        self.learning = LearningEngine()
        self.alerts = AlertManager(self.exit_queue)

        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self):
        logger.info("SAVAGE AGENT starting up...")

        settings.validate()

        await init_all()
        logger.info("databases initialized")

        await self.execution.initialize()
        logger.info("trading wallet loaded: %s", self.execution._keypair.pubkey())

        await self.token_intel.initialize()

        await self.alerts.start()

        self._running = True

        self._tasks = [
            asyncio.create_task(self.wallet_tracker.start(), name="wallet_tracker"),
            asyncio.create_task(self._signal_processor(), name="signal_processor"),
            asyncio.create_task(self.exit_manager.start(), name="exit_manager"),
            asyncio.create_task(self.ct_motion.start(), name="ct_motion"),
            asyncio.create_task(self.crawlers.start(), name="crawlers"),
            asyncio.create_task(self._learning_loop(), name="learning_loop"),
        ]

        logger.info(
            "all systems online. tracking %d wallets. buy threshold: %d, max positions: %d",
            len(self.wallet_tracker.tracked_wallets),
            settings.BUY_SCORE_THRESHOLD,
            settings.MAX_CONCURRENT_POSITIONS,
        )

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("agent shutting down...")

    async def _signal_processor(self):
        while self._running:
            try:
                play: PlaySignal = await asyncio.wait_for(
                    self.signal_queue.get(), timeout=5.0
                )
                logger.info(
                    "play signal received: %s (%d apes in %ds)",
                    play.token_address, play.ape_count, play.window_seconds,
                )
                await self._process_play(play)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("signal processing error: %s", e, exc_info=True)

    async def _process_play(self, play: PlaySignal):
        token = play.token_address

        db = await get_db("trades.db")
        try:
            cursor = await db.execute(
                "SELECT cooldown_until FROM reentry_cooldowns WHERE token_address = ?",
                (token,),
            )
            row = await cursor.fetchone()
            if row:
                cooldown_until = datetime.fromisoformat(row["cooldown_until"])
                if datetime.now(timezone.utc) < cooldown_until.replace(tzinfo=timezone.utc):
                    logger.info("skipping %s — re-entry cooldown active until %s", token[:8], row["cooldown_until"])
                    return
        finally:
            await db.close()

        db = await get_db("trades.db")
        try:
            cursor = await db.execute("SELECT COUNT(*) as cnt FROM open_positions")
            count = (await cursor.fetchone())["cnt"]
            if count >= settings.MAX_CONCURRENT_POSITIONS:
                logger.info("skipping %s — max concurrent positions (%d/%d)", token[:8], count, settings.MAX_CONCURRENT_POSITIONS)
                return
        finally:
            await db.close()

        score = await self.token_intel.score_token(token)
        if not score.passed:
            logger.info("token %s failed scoring: %s (score: %d)", token[:8], score.abort_reason, score.total_score)
            return

        crawler_bonus = await self.crawlers.get_bonus_score(token)
        effective_score = score.total_score + crawler_bonus
        if crawler_bonus > 0:
            logger.info("crawler bonus +%d applied for %s", crawler_bonus, score.symbol)

        threshold = await self.learning.get_effective_threshold()
        if effective_score < threshold:
            logger.info("token %s score %d below threshold %d", score.symbol, effective_score, threshold)
            return

        sol_size = self.execution.compute_position_size(score, play.ape_count)
        if sol_size <= 0:
            logger.info("position size 0 for %s — ape count too low for score bracket", score.symbol)
            return

        is_honeypot, hp_reason = await self.execution.check_honeypot(token)
        if is_honeypot:
            logger.warning("honeypot detected for %s: %s — aborting", score.symbol, hp_reason)
            return

        logger.info(
            "executing buy: %s — %.1f SOL (score: %d, apes: %d)",
            score.symbol, sol_size, effective_score, play.ape_count,
        )
        result = await self.execution.buy_token(token, sol_size, score)

        if result.success:
            db = await get_db("trades.db")
            try:
                await db.execute(
                    "INSERT INTO convergence_events (token_address, wallet_count, wallets, buy_score, position_size_sol) VALUES (?, ?, ?, ?, ?)",
                    (token, play.ape_count, json.dumps(play.wallets), effective_score, sol_size),
                )
                await db.commit()
            finally:
                await db.close()

            holder_growth = 0
            dev_status = "CLEAN" if score.dev_safety_score >= 20 else "FLAG"

            await self.alerts.send_play_alert(
                token_address=token,
                symbol=score.symbol,
                ape_count=play.ape_count,
                window_secs=play.window_seconds,
                score=effective_score,
                sol_size=sol_size,
                vol_1h=score.volume_1h,
                liquidity=score.liquidity_usd,
                holders=score.holder_count,
                holder_growth=holder_growth,
                dev_status=dev_status,
                distro_score=score.distribution_score,
                entry_price=result.entry_price,
                tp_price=result.entry_price * settings.INITIAL_TP_MULTIPLIER,
                sl_price=result.entry_price * (1 - settings.INITIAL_SL_PERCENT),
            )
            logger.info("position opened: %s @ %s — %.1f SOL", score.symbol, result.entry_price, sol_size)
        else:
            logger.error("buy failed for %s: %s", score.symbol, result.error)

    async def _learning_loop(self):
        while self._running:
            try:
                await self.learning.adapt_threshold()
            except Exception as e:
                logger.error("learning loop error: %s", e)
            await asyncio.sleep(300)

    async def shutdown(self):
        logger.info("initiating graceful shutdown...")
        self._running = False

        await self.wallet_tracker.stop()
        await self.exit_manager.stop()
        await self.ct_motion.stop()
        await self.crawlers.stop()

        for task in self._tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("all tasks cancelled")

        await self.token_intel.close()
        await self.execution.close()
        await self.alerts.stop()

        logger.info("SAVAGE AGENT shut down cleanly")


def main():
    setup_logging()

    agent = SavageAgent()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(agent.shutdown()))

    try:
        loop.run_until_complete(agent.start())
    except KeyboardInterrupt:
        loop.run_until_complete(agent.shutdown())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
