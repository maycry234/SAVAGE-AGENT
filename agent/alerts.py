import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from config import settings
from db import get_db
from agent.utils import shorten_address
from agent.exit_manager import ExitEvent

logger = logging.getLogger("savage.alerts")


class AlertManager:
    def __init__(self, exit_queue: asyncio.Queue):
        self.exit_queue = exit_queue
        self._bot: Optional[Bot] = None
        self._running = False

    async def start(self):
        self._bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        self._running = True
        asyncio.create_task(self._exit_listener())
        asyncio.create_task(self._daily_summary_loop())
        logger.info("alert manager started")

    async def stop(self):
        self._running = False

    # ── Alert formatters ────────────────────────────────────────────────

    async def send_play_alert(
        self, token_address: str, symbol: str, ape_count: int,
        window_secs: int, score: int, sol_size: float,
        vol_1h: float, liquidity: float, holders: int,
        holder_growth: float, dev_status: str, distro_score: int,
        entry_price: float, tp_price: float, sl_price: float,
        dry_run: bool = False,
    ):
        addr_short = shorten_address(token_address)
        dev_icon = "\u2705" if dev_status == "CLEAN" else "\u26a0\ufe0f"
        title_prefix = "\U0001f9ea DRY RUN \u2014 " if dry_run else ""
        text = (
            f"{title_prefix}\U0001f3af PLAY DETECTED \u2014 ${symbol}\n"
            f"`{addr_short}`\n\n"
            f"apes: {ape_count} wallets (\u26a1 within {window_secs}s)\n"
            f"score: {score}/100  \u2022  size: {sol_size} SOL\n"
            f"vol 1h: ${vol_1h:,.0f}  \u2022  liq: ${liquidity:,.0f}\n"
            f"holders: {holders:,} (+{holder_growth:.1f}/min)\n"
            f"dev: {dev_status} {dev_icon}  \u2022  distro: {distro_score}%\n\n"
            f"entry: {entry_price:.8f}  \u2022  tp: {tp_price:.8f}  \u2022  sl: {sl_price:.8f}"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("\U0001f50d Scan", callback_data=f"scan:{token_address}"),
                InlineKeyboardButton("\U0001f4ca Chart", url=f"https://dexscreener.com/solana/{token_address}"),
                InlineKeyboardButton("\u274c Abort", callback_data=f"abort:{token_address}"),
            ]
        ])
        await self._send(text, keyboard)

    async def send_motion_alert(
        self, symbol: str, locked_percent: float,
        add_sol: float, key_signals: list[str], tp_target: float,
    ):
        signals_str = ", ".join(key_signals[:3])
        text = (
            f"\U0001f525 CT MOTION DETECTED \u2014 ${symbol}\n"
            f"holding {int(locked_percent * 100)}% locked  \u2022  adding {add_sol:.1f} SOL\n"
            f"grok signals: {signals_str}\n"
            f"new tp target: {tp_target}x"
        )
        await self._send(text)

    async def send_exit_alert(self, event: ExitEvent):
        pnl_sign = "+" if event.pnl_sol >= 0 else ""
        text = (
            f"\U0001f6a8 EXIT \u2014 ${event.token_symbol}\n"
            f"reason: {event.exit_reason}\n"
            f"pnl: {pnl_sign}{event.pnl_sol:.2f} SOL ({pnl_sign}{event.pnl_percent:.1f}%)\n"
            f"held: {self._format_duration(event.duration_seconds)}"
        )
        await self._send(text)

    async def send_daily_summary(self):
        db = await get_db("trades.db")
        try:
            cursor = await db.execute("""
                SELECT token_symbol, pnl_sol, pnl_percent, exit_reason
                FROM completed_trades
                WHERE closed_at >= datetime('now', '-24 hours')
                ORDER BY closed_at DESC
            """)
            trades = await cursor.fetchall()

            if not trades:
                text = "\U0001f4ca daily wrap\nno trades today. watching."
                await self._send(text)
                return

            total_trades = len(trades)
            wins = sum(1 for t in trades if t["pnl_sol"] > 0)
            win_rate = (wins / total_trades * 100) if total_trades else 0
            total_pnl = sum(t["pnl_sol"] for t in trades)

            best = max(trades, key=lambda t: t["pnl_percent"])
            worst = min(trades, key=lambda t: t["pnl_percent"])

            ldb = await get_db("learning.db")
            try:
                tcursor = await ldb.execute(
                    "SELECT new_threshold FROM threshold_history ORDER BY changed_at DESC LIMIT 1"
                )
                trow = await tcursor.fetchone()
                threshold = trow["new_threshold"] if trow else settings.BUY_SCORE_THRESHOLD

                wcursor = await ldb.execute(
                    "SELECT wallet_address, score FROM wallet_scores ORDER BY score DESC LIMIT 1"
                )
                wrow = await wcursor.fetchone()
                top_wallet = shorten_address(wrow["wallet_address"]) if wrow else "n/a"
            finally:
                await ldb.close()

            pnl_sign = "+" if total_pnl >= 0 else ""
            text = (
                f"\U0001f4ca daily wrap\n"
                f"trades: {total_trades}  \u2022  win rate: {win_rate:.0f}%\n"
                f"total pnl: {pnl_sign}{total_pnl:.2f} SOL\n"
                f"best: ${best['token_symbol']} +{best['pnl_percent']:.0f}%  \u2022  worst: ${worst['token_symbol']} {worst['pnl_percent']:.0f}%\n"
                f"threshold: {threshold}  \u2022  top wallet: {top_wallet}"
            )
            await self._send(text)
        finally:
            await db.close()

    # ── Internal helpers ────────────────────────────────────────────────

    async def _send(self, text: str, reply_markup=None):
        try:
            await self._bot.send_message(
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error("telegram send failed: %s", e)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hours}h {mins}m"

    async def handle_callback(self, callback_data: str):
        parts = callback_data.split(":")
        action = parts[0]
        token = parts[1] if len(parts) > 1 else None

        if action == "scan":
            pass
        elif action == "abort":
            pass

    # ── Background loops ────────────────────────────────────────────────

    async def _exit_listener(self):
        while self._running:
            try:
                event = await asyncio.wait_for(self.exit_queue.get(), timeout=5.0)
                await self.send_exit_alert(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("exit listener error: %s", e)

    async def _daily_summary_loop(self):
        while self._running:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=settings.DAILY_SUMMARY_HOUR, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            try:
                await asyncio.sleep(wait_seconds)
                await self.send_daily_summary()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("daily summary error: %s", e)
