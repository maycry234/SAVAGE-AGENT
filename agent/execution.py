import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import aiosqlite
import base58
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from config import settings
from db import get_db
from agent.token_intel import TokenScore
from agent.utils import RateLimiter, create_aiohttp_session, retry_with_backoff, shorten_address

logger = logging.getLogger("savage.execution")


@dataclass
class ExecutionResult:
    success: bool
    tx_signature: Optional[str] = None
    token_amount: float = 0
    sol_spent: float = 0
    entry_price: float = 0
    error: Optional[str] = None
    simulated: bool = False
    metadata: Optional[dict] = None


class ExecutionEngine:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._keypair: Optional[Keypair] = None
        self._jupiter_limiter = RateLimiter(settings.JUPITER_RATE_LIMIT)
        self._helius_limiter = RateLimiter(settings.HELIUS_RATE_LIMIT)
        self._dexscreener_limiter = RateLimiter(settings.DEXSCREENER_RATE_LIMIT)
        self.dry_run: bool = settings.DRY_RUN

    async def initialize(self):
        self._session = create_aiohttp_session(timeout_total=settings.RPC_TIMEOUT)

        if self.dry_run:
            logger.info("DRY RUN enabled — no live trades will be sent")
            if settings.ENCRYPTION_KEY and settings.TRADER_WALLET_KEY:
                try:
                    from cryptography.fernet import Fernet
                    f = Fernet(settings.ENCRYPTION_KEY.encode())
                    decrypted = f.decrypt(settings.TRADER_WALLET_KEY.encode())
                    self._keypair = Keypair.from_bytes(decrypted)
                    logger.info("wallet loaded (dry-run): %s", self._keypair.pubkey())
                except Exception:
                    logger.info("wallet key present but could not decrypt — continuing in dry-run without wallet")
            elif os.getenv("TRADER_WALLET_PRIVATE_KEY", ""):
                try:
                    self._keypair = Keypair.from_bytes(base58.b58decode(os.getenv("TRADER_WALLET_PRIVATE_KEY", "")))
                    logger.info("wallet loaded (dry-run): %s", self._keypair.pubkey())
                except Exception:
                    logger.info("raw wallet key present but invalid — continuing in dry-run without wallet")
            return

        if settings.ENCRYPTION_KEY and settings.TRADER_WALLET_KEY:
            from cryptography.fernet import Fernet
            f = Fernet(settings.ENCRYPTION_KEY.encode())
            decrypted = f.decrypt(settings.TRADER_WALLET_KEY.encode())
            self._keypair = Keypair.from_bytes(decrypted)
        else:
            raw = os.getenv("TRADER_WALLET_PRIVATE_KEY", "")
            if raw:
                self._keypair = Keypair.from_bytes(base58.b58decode(raw))

        if not self._keypair:
            raise ValueError("No trading wallet configured")

        logger.info("execution engine initialized, wallet=%s", self._keypair.pubkey())

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Position sizing ─────────────────────────────────────────────────

    def compute_position_size(self, score: TokenScore, ape_count: int) -> float:
        base = 0.0
        if score.total_score >= 90 and ape_count >= 5:
            base = 7.0
        elif score.total_score >= 80 and ape_count >= 4:
            base = 4.0
        elif score.total_score >= 70 and ape_count >= 3:
            base = 2.0
        elif score.total_score >= 60 and ape_count >= 2:
            base = 1.0
        else:
            return 0.0

        if score.volume_1h > settings.VOLUME_MULTIPLIER_THRESHOLD:
            base *= settings.VOLUME_MULTIPLIER

        return min(base, settings.MAX_POSITION_SOL)

    # ── Pre-flight checks ──────────────────────────────────────────────

    async def check_concurrent_positions(self) -> bool:
        try:
            db = await get_db()
            try:
                cursor = await db.execute("SELECT COUNT(*) as cnt FROM open_positions")
                row = await cursor.fetchone()
                count = row["cnt"] if row else 0
                return count < settings.MAX_CONCURRENT_POSITIONS
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.error("position count check failed: %s", exc)
            return False

    async def check_reentry_cooldown(self, token_address: str) -> bool:
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT cooldown_until FROM reentry_cooldowns WHERE token_address = ?",
                    (token_address,),
                )
                row = await cursor.fetchone()
                if not row:
                    return True
                cooldown_until = datetime.fromisoformat(row["cooldown_until"])
                return datetime.now(timezone.utc) > cooldown_until.replace(tzinfo=timezone.utc)
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.error("reentry cooldown check failed: %s", exc)
            return False

    # ── Honeypot check ──────────────────────────────────────────────────

    async def check_honeypot(self, token_address: str) -> tuple[bool, str]:
        try:
            await self._jupiter_limiter.acquire()
            test_amount = 1_000_000

            quote_url = (
                f"{settings.JUPITER_API_URL}/quote"
                f"?inputMint={token_address}"
                f"&outputMint={settings.WSOL_MINT}"
                f"&amount={test_amount}"
                f"&slippageBps={settings.SLIPPAGE_BPS}"
            )

            async with self._session.get(quote_url) as resp:
                if resp.status != 200:
                    return True, f"sell quote failed with status {resp.status}"
                quote = await resp.json()

            if quote.get("error"):
                return True, f"sell quote error: {quote['error']}"

            in_amount = int(quote.get("inAmount", 0))
            out_amount = int(quote.get("outAmount", 0))

            if in_amount <= 0 or out_amount <= 0:
                return True, "zero output on sell simulation"

            await self._jupiter_limiter.acquire()
            buy_quote_url = (
                f"{settings.JUPITER_API_URL}/quote"
                f"?inputMint={settings.WSOL_MINT}"
                f"&outputMint={token_address}"
                f"&amount={out_amount}"
                f"&slippageBps={settings.SLIPPAGE_BPS}"
            )

            async with self._session.get(buy_quote_url) as resp:
                if resp.status != 200:
                    return False, "could not verify tax ratio, proceeding cautiously"
                buy_quote = await resp.json()

            buy_out = int(buy_quote.get("outAmount", 0))
            if buy_out <= 0:
                return True, "reverse quote returned zero"

            implied_tax = 1.0 - (in_amount / buy_out) if buy_out > 0 else 1.0
            if implied_tax > settings.HONEYPOT_TAX_THRESHOLD:
                return True, f"implied sell tax {implied_tax:.1%} exceeds {settings.HONEYPOT_TAX_THRESHOLD:.0%}"

            return False, "sell simulation passed"

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("honeypot check failed: %s", exc)
            return True, f"honeypot check error: {exc}"

    # ── Paper balance helpers ───────────────────────────────────────────

    async def get_paper_balance(self) -> float:
        try:
            db = await get_db()
            try:
                cursor = await db.execute("SELECT COALESCE(SUM(sol_delta), 0) as total FROM paper_ledger")
                row = await cursor.fetchone()
                delta = row["total"] if row else 0.0
                return settings.DRY_RUN_STARTING_SOL + delta
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.error("paper balance query failed: %s", exc)
            return settings.DRY_RUN_STARTING_SOL

    async def reset_paper_balance(self, reason: str = "manual"):
        db = await get_db()
        try:
            cursor = await db.execute("SELECT COALESCE(SUM(sol_delta), 0) as total FROM paper_ledger")
            row = await cursor.fetchone()
            current_delta = row["total"] if row else 0.0
            if current_delta != 0:
                await self._record_paper_ledger(
                    db, event_type="RESET", sol_delta=-current_delta, reason=reason,
                )
            await db.commit()
        finally:
            await db.close()

    async def _record_paper_ledger(
        self,
        db,
        event_type: str,
        sol_delta: float,
        token_address: str = None,
        token_symbol: str = None,
        token_delta: float = 0,
        simulated_price: float = None,
        reason: str = None,
        metadata: dict = None,
    ):
        await db.execute(
            """INSERT INTO paper_ledger
               (event_type, token_address, token_symbol, sol_delta, token_delta,
                simulated_price, reason, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_type,
                token_address,
                token_symbol,
                sol_delta,
                token_delta,
                simulated_price,
                reason,
                json.dumps(metadata) if metadata else None,
            ),
        )

    # ── DexScreener price lookup ────────────────────────────────────────

    async def _get_dexscreener_price(self, token_address: str) -> Optional[float]:
        try:
            await self._dexscreener_limiter.acquire()
            url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{token_address}"
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            pairs = data.get("pairs") or []
            if not pairs:
                return None
            sol_pairs = [p for p in pairs if p.get("quoteToken", {}).get("symbol", "").upper() == "SOL"]
            target = sol_pairs[0] if sol_pairs else pairs[0]
            price_str = target.get("priceNative") or target.get("priceUsd")
            return float(price_str) if price_str else None
        except Exception as exc:
            logger.debug("dexscreener price lookup failed for %s: %s", shorten_address(token_address), exc)
            return None

    # ── Paper buy ───────────────────────────────────────────────────────

    async def _paper_buy_token(
        self, token_address: str, sol_amount: float, score: TokenScore,
    ) -> ExecutionResult:
        if settings.DRY_RUN_EXECUTION_DELAY_MS > 0:
            await asyncio.sleep(settings.DRY_RUN_EXECUTION_DELAY_MS / 1000.0)

        balance = await self.get_paper_balance()
        if sol_amount > balance:
            return ExecutionResult(
                success=False, simulated=True,
                error=f"paper balance insufficient: {balance:.4f} SOL < {sol_amount:.4f} SOL",
            )

        price = await self._get_dexscreener_price(token_address)
        if price and price > 0:
            token_amount = sol_amount / price
            entry_price = price
        else:
            token_amount = sol_amount * 1_000_000
            entry_price = sol_amount / token_amount

        ts = int(time.time())
        short_addr = token_address[:8]
        tx_sig = f"DRYRUN_BUY_{ts}_{short_addr}"

        db = await get_db()
        try:
            tp_price = entry_price * settings.INITIAL_TP_MULTIPLIER
            sl_price = entry_price * (1 - settings.INITIAL_SL_PERCENT)

            await db.execute(
                """INSERT OR REPLACE INTO open_positions
                   (token_address, token_symbol, entry_price, current_price,
                    amount_tokens, amount_sol, peak_price, tp_price, sl_price,
                    trail_percent, remaining_percent, dry_run, simulated_tx_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 1, ?)""",
                (
                    token_address, score.symbol, entry_price, entry_price,
                    token_amount, sol_amount, entry_price, tp_price, sl_price,
                    settings.TRAILING_TP_PERCENT, tx_sig,
                ),
            )

            await self._record_paper_ledger(
                db,
                event_type="BUY",
                token_address=token_address,
                token_symbol=score.symbol,
                sol_delta=-sol_amount,
                token_delta=token_amount,
                simulated_price=entry_price,
                reason=f"score={score.total_score}",
                metadata={"tx_sig": tx_sig, "ape_score": score.total_score},
            )

            await db.commit()
        finally:
            await db.close()

        logger.info(
            "PAPER BUY token=%s symbol=%s sol=%.4f tokens=%.2f entry=%.10f sig=%s",
            shorten_address(token_address), score.symbol, sol_amount,
            token_amount, entry_price, tx_sig,
        )

        return ExecutionResult(
            success=True,
            simulated=True,
            tx_signature=tx_sig,
            token_amount=token_amount,
            sol_spent=sol_amount,
            entry_price=entry_price,
            metadata={"dry_run": True, "paper_balance": balance - sol_amount},
        )

    # ── Paper sell ──────────────────────────────────────────────────────

    async def _paper_sell_token(
        self, token_address: str, token_amount: int, reason: str,
    ) -> ExecutionResult:
        if settings.DRY_RUN_EXECUTION_DELAY_MS > 0:
            await asyncio.sleep(settings.DRY_RUN_EXECUTION_DELAY_MS / 1000.0)

        price = await self._get_dexscreener_price(token_address)

        if not price or price <= 0:
            db = await get_db()
            try:
                cursor = await db.execute(
                    "SELECT entry_price FROM open_positions WHERE token_address = ?",
                    (token_address,),
                )
                row = await cursor.fetchone()
                price = row["entry_price"] if row else 0.000001
            finally:
                await db.close()

        sol_received = float(token_amount) * price if price else 0.0

        ts = int(time.time())
        short_addr = token_address[:8]
        tx_sig = f"DRYRUN_SELL_{ts}_{short_addr}"

        db = await get_db()
        try:
            symbol = None
            cursor = await db.execute(
                "SELECT token_symbol FROM open_positions WHERE token_address = ?",
                (token_address,),
            )
            row = await cursor.fetchone()
            if row:
                symbol = row["token_symbol"]

            await self._record_paper_ledger(
                db,
                event_type="SELL",
                token_address=token_address,
                token_symbol=symbol,
                sol_delta=sol_received,
                token_delta=-float(token_amount),
                simulated_price=price,
                reason=reason,
                metadata={"tx_sig": tx_sig},
            )
            await db.commit()
        finally:
            await db.close()

        logger.info(
            "PAPER SELL token=%s reason=%s sol_out=%.4f sig=%s",
            shorten_address(token_address), reason, sol_received, tx_sig,
        )

        return ExecutionResult(
            success=True,
            simulated=True,
            tx_signature=tx_sig,
            sol_spent=sol_received,
            metadata={"dry_run": True},
        )

    # ── Jupiter V6 buy ──────────────────────────────────────────────────

    async def buy_token(
        self, token_address: str, sol_amount: float, score: TokenScore
    ) -> ExecutionResult:
        can_buy = await self.check_concurrent_positions()
        if not can_buy:
            return ExecutionResult(
                success=False,
                error=f"max concurrent positions ({settings.MAX_CONCURRENT_POSITIONS}) reached",
            )

        can_reenter = await self.check_reentry_cooldown(token_address)
        if not can_reenter:
            return ExecutionResult(
                success=False,
                error=f"reentry cooldown active for {shorten_address(token_address)}",
            )

        if self.dry_run:
            return await self._paper_buy_token(token_address, sol_amount, score)

        is_honeypot, hp_reason = await self.check_honeypot(token_address)
        if is_honeypot:
            return ExecutionResult(success=False, error=f"honeypot: {hp_reason}")

        lamports = int((sol_amount - settings.SOL_FEE_RESERVE) * 1e9)
        if lamports <= 0:
            return ExecutionResult(success=False, error="insufficient sol after fee reserve")

        try:
            await self._jupiter_limiter.acquire()
            quote_url = (
                f"{settings.JUPITER_API_URL}/quote"
                f"?inputMint={settings.WSOL_MINT}"
                f"&outputMint={token_address}"
                f"&amount={lamports}"
                f"&slippageBps={settings.SLIPPAGE_BPS}"
            )
            async with self._session.get(quote_url) as resp:
                if resp.status != 200:
                    return ExecutionResult(success=False, error=f"quote failed: {resp.status}")
                quote = await resp.json()

            if quote.get("error"):
                return ExecutionResult(success=False, error=f"quote error: {quote['error']}")

            await self._jupiter_limiter.acquire()
            swap_payload = {
                "quoteResponse": quote,
                "userPublicKey": str(self._keypair.pubkey()),
                "wrapAndUnwrapSol": True,
            }
            async with self._session.post(
                f"{settings.JUPITER_API_URL}/swap", json=swap_payload
            ) as resp:
                if resp.status != 200:
                    return ExecutionResult(success=False, error=f"swap failed: {resp.status}")
                swap_data = await resp.json()

            swap_tx_b64 = swap_data.get("swapTransaction")
            if not swap_tx_b64:
                return ExecutionResult(success=False, error="no swap transaction returned")

            tx_bytes = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self._keypair])
            signed_bytes = bytes(signed_tx)

            tx_sig = await self._send_and_confirm(signed_bytes)
            if not tx_sig:
                return ExecutionResult(success=False, error="tx send/confirm failed")

            out_amount = int(quote.get("outAmount", 0))
            token_decimals = score.volume_1h  # placeholder; actual decimals from score metadata
            token_amount = out_amount / 1e6  # default 6 decimals, adjust as needed
            entry_price = sol_amount / token_amount if token_amount > 0 else 0

            await self._record_open_position(token_address, score, sol_amount, token_amount, entry_price)

            logger.info(
                "BUY SUCCESS token=%s symbol=%s sol=%.4f tokens=%.2f entry=%.10f sig=%s",
                shorten_address(token_address), score.symbol, sol_amount,
                token_amount, entry_price, tx_sig,
            )

            return ExecutionResult(
                success=True,
                tx_signature=tx_sig,
                token_amount=token_amount,
                sol_spent=sol_amount,
                entry_price=entry_price,
            )

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error("buy failed: %s", exc)
            return ExecutionResult(success=False, error=str(exc))

    # ── Jupiter V6 sell ─────────────────────────────────────────────────

    async def sell_token(
        self, token_address: str, token_amount: int, reason: str
    ) -> ExecutionResult:
        if self.dry_run:
            return await self._paper_sell_token(token_address, token_amount, reason)

        try:
            await self._jupiter_limiter.acquire()
            quote_url = (
                f"{settings.JUPITER_API_URL}/quote"
                f"?inputMint={token_address}"
                f"&outputMint={settings.WSOL_MINT}"
                f"&amount={token_amount}"
                f"&slippageBps={settings.SLIPPAGE_BPS}"
            )
            async with self._session.get(quote_url) as resp:
                if resp.status != 200:
                    return ExecutionResult(success=False, error=f"sell quote failed: {resp.status}")
                quote = await resp.json()

            if quote.get("error"):
                return ExecutionResult(success=False, error=f"sell quote error: {quote['error']}")

            await self._jupiter_limiter.acquire()
            swap_payload = {
                "quoteResponse": quote,
                "userPublicKey": str(self._keypair.pubkey()),
                "wrapAndUnwrapSol": True,
            }
            async with self._session.post(
                f"{settings.JUPITER_API_URL}/swap", json=swap_payload
            ) as resp:
                if resp.status != 200:
                    return ExecutionResult(success=False, error=f"sell swap failed: {resp.status}")
                swap_data = await resp.json()

            swap_tx_b64 = swap_data.get("swapTransaction")
            if not swap_tx_b64:
                return ExecutionResult(success=False, error="no sell swap transaction returned")

            tx_bytes = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self._keypair])
            signed_bytes = bytes(signed_tx)

            tx_sig = await self._send_and_confirm(signed_bytes)
            if not tx_sig:
                return ExecutionResult(success=False, error="sell tx send/confirm failed")

            sol_received = int(quote.get("outAmount", 0)) / 1e9

            logger.info(
                "SELL SUCCESS token=%s reason=%s sol_out=%.4f sig=%s",
                shorten_address(token_address), reason, sol_received, tx_sig,
            )

            return ExecutionResult(
                success=True,
                tx_signature=tx_sig,
                sol_spent=sol_received,
            )

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error("sell failed: %s", exc)
            return ExecutionResult(success=False, error=str(exc))

    # ── RPC send + confirm ──────────────────────────────────────────────

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def _send_and_confirm(self, signed_bytes: bytes) -> Optional[str]:
        await self._helius_limiter.acquire()
        encoded = base64.b64encode(signed_bytes).decode()

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                encoded,
                {"skipPreflight": True, "maxRetries": 3, "encoding": "base64"},
            ],
        }

        async with self._session.post(settings.HELIUS_RPC_URL, json=payload) as resp:
            result = await resp.json()
            if "error" in result:
                logger.error("sendTransaction error: %s", result["error"])
                return None
            tx_sig = result.get("result")

        if not tx_sig:
            return None

        for _ in range(30):
            await asyncio.sleep(1)
            await self._helius_limiter.acquire()
            status_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignatureStatuses",
                "params": [[tx_sig], {"searchTransactionHistory": False}],
            }
            async with self._session.post(settings.HELIUS_RPC_URL, json=status_payload) as resp:
                status_result = await resp.json()

            statuses = status_result.get("result", {}).get("value", [])
            if statuses and statuses[0]:
                confirmation = statuses[0].get("confirmationStatus")
                if confirmation in ("confirmed", "finalized"):
                    if statuses[0].get("err") is None:
                        return tx_sig
                    logger.error("tx confirmed with error: %s", statuses[0]["err"])
                    return None

        logger.warning("tx confirmation timeout: %s", tx_sig)
        return None

    # ── DB operations ───────────────────────────────────────────────────

    async def _record_open_position(
        self,
        token_address: str,
        score: TokenScore,
        sol_amount: float,
        token_amount: float,
        entry_price: float,
    ):
        tp_price = entry_price * settings.INITIAL_TP_MULTIPLIER
        sl_price = entry_price * (1 - settings.INITIAL_SL_PERCENT)

        try:
            db = await get_db()
            try:
                await db.execute(
                    """INSERT OR REPLACE INTO open_positions
                       (token_address, token_symbol, entry_price, current_price,
                        amount_tokens, amount_sol, peak_price, tp_price, sl_price,
                        trail_percent, remaining_percent)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0)""",
                    (token_address, score.symbol, entry_price, entry_price,
                     token_amount, sol_amount, entry_price, tp_price, sl_price,
                     settings.TRAILING_TP_PERCENT),
                )
                await db.commit()
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.error("failed to record open position: %s", exc)

    async def record_completed_trade(
        self,
        token_address: str,
        symbol: str,
        entry_price: float,
        exit_price: float,
        sol_in: float,
        sol_out: float,
        exit_reason: str,
        trigger_wallets: Optional[str] = None,
        buy_score: Optional[float] = None,
        opened_at: Optional[str] = None,
    ):
        pnl_sol = sol_out - sol_in
        pnl_percent = (pnl_sol / sol_in) * 100 if sol_in > 0 else 0

        duration = None
        if opened_at:
            try:
                opened_dt = datetime.fromisoformat(opened_at)
                duration = int((datetime.now(timezone.utc) - opened_dt.replace(tzinfo=timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass

        try:
            db = await get_db()
            try:
                await db.execute(
                    """INSERT INTO completed_trades
                       (token_address, token_symbol, entry_price, exit_price,
                        amount_sol_in, amount_sol_out, pnl_sol, pnl_percent,
                        exit_reason, trigger_wallets, buy_score, duration_seconds, opened_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (token_address, symbol, entry_price, exit_price,
                     sol_in, sol_out, pnl_sol, pnl_percent,
                     exit_reason, trigger_wallets, buy_score, duration, opened_at),
                )

                await db.execute("DELETE FROM open_positions WHERE token_address = ?", (token_address,))

                if exit_reason in ("stop_loss", "nuke_exit", "liquidity_collapse"):
                    cooldown_until = datetime.now(timezone.utc).isoformat()
                    await db.execute(
                        """INSERT OR REPLACE INTO reentry_cooldowns
                           (token_address, exit_reason, cooldown_until)
                           VALUES (?, ?, datetime('now', '+' || ? || ' seconds'))""",
                        (token_address, exit_reason, settings.REENTRY_COOLDOWN),
                    )

                await db.commit()
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.error("failed to record completed trade: %s", exc)
