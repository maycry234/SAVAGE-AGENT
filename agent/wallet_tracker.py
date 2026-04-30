import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import aiosqlite

from config import settings
from db import get_db
from agent.utils import RateLimiter, create_aiohttp_session, retry_with_backoff, shorten_address

logger = logging.getLogger("savage.wallet_tracker")

WSOL_MINT = settings.WSOL_MINT
IGNORED_MINTS = {WSOL_MINT, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}


@dataclass
class SwapEvent:
    wallet_address: str
    token_address: str
    amount_sol: float
    tx_signature: str
    timestamp: int


@dataclass
class PlaySignal:
    token_address: str
    wallets: list[str]
    ape_count: int
    first_swap_ts: int
    last_swap_ts: int
    window_seconds: int


class WalletTracker:
    def __init__(self, signal_queue: asyncio.Queue):
        self.signal_queue = signal_queue
        self.tracked_wallets: dict[str, dict] = {}
        self.recent_swaps: defaultdict[str, list[SwapEvent]] = defaultdict(list)
        self._ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._seen_signatures: set[str] = set()
        self._emitted_plays: dict[str, float] = {}
        self._rate_limiter = RateLimiter(settings.HELIUS_RATE_LIMIT)
        self._last_rest_signature: dict[str, str] = {}
        self._ws_reconnect_delay = 1.0

    async def load_wallets(self):
        wallets_path = settings.DATA_DIR / "wallets.json"
        with open(wallets_path) as f:
            data = json.load(f)

        db = await get_db("learning.db")
        try:
            for w in data["tracked_wallets"]:
                addr = w["address"]
                row = await db.execute(
                    "SELECT score FROM wallet_scores WHERE wallet_address = ?", (addr,)
                )
                score_row = await row.fetchone()
                w["score"] = score_row["score"] if score_row else settings.DEFAULT_WALLET_SCORE
                self.tracked_wallets[addr] = w
        finally:
            await db.close()

        logger.info("loaded %d tracked wallets", len(self.tracked_wallets))

    async def start(self):
        await self.load_wallets()
        self._session = create_aiohttp_session(timeout_total=settings.RPC_TIMEOUT)
        self._running = True

        tasks = [
            asyncio.create_task(self._ws_stream(), name="ws_stream"),
            asyncio.create_task(self._rest_poll_loop(), name="rest_poll"),
            asyncio.create_task(self._convergence_checker(), name="convergence"),
            asyncio.create_task(self._cleanup_loop(), name="cleanup"),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("wallet tracker shutting down")
        finally:
            await self.stop()

    async def stop(self):
        self._running = False
        if self._ws_connection and not self._ws_connection.closed:
            await self._ws_connection.close()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── WebSocket streaming ─────────────────────────────────────────────

    async def _ws_stream(self):
        while self._running:
            try:
                await self._ws_connect_and_listen()
            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as exc:
                logger.warning("ws disconnected: %s, reconnecting in %.1fs", exc, self._ws_reconnect_delay)
                await asyncio.sleep(self._ws_reconnect_delay)
                self._ws_reconnect_delay = min(self._ws_reconnect_delay * 2, 60.0)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("unexpected ws error")
                await asyncio.sleep(self._ws_reconnect_delay)

    async def _ws_connect_and_listen(self):
        if not settings.HELIUS_API_KEY:
            logger.warning("no HELIUS_API_KEY, ws stream disabled")
            await asyncio.sleep(3600)
            return

        async with self._session.ws_connect(settings.HELIUS_WS_URL) as ws:
            self._ws_connection = ws
            self._ws_reconnect_delay = 1.0
            logger.info("ws connected to helius")

            for addr in self.tracked_wallets:
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "transactionSubscribe",
                    "params": [
                        {"accountInclude": [addr]},
                        {
                            "commitment": "confirmed",
                            "encoding": "jsonParsed",
                            "transactionDetails": "full",
                            "maxSupportedTransactionVersion": 0,
                        },
                    ],
                }
                await ws.send_json(subscribe_msg)

            logger.info("subscribed to %d wallets via ws", len(self.tracked_wallets))

            async for msg in ws:
                if not self._running:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_ws_message(data)
                    except json.JSONDecodeError:
                        logger.warning("malformed ws message")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    async def _handle_ws_message(self, data: dict):
        if "method" not in data or data["method"] != "transactionNotification":
            return

        params = data.get("params", {})
        result = params.get("result", {})
        tx = result.get("transaction", {})
        signature = result.get("signature", "")

        if not signature or signature in self._seen_signatures:
            return

        swap = self._parse_transaction_for_swap(tx, signature)
        if swap:
            self._seen_signatures.add(signature)
            await self._process_swap(swap)

    def _parse_transaction_for_swap(self, tx: dict, signature: str) -> Optional[SwapEvent]:
        meta = tx.get("meta", {})
        if meta.get("err") is not None:
            return None

        pre_balances = meta.get("preTokenBalances", [])
        post_balances = meta.get("postTokenBalances", [])

        account_keys = []
        message = tx.get("transaction", {}).get("message", {})
        for ak in message.get("accountKeys", []):
            if isinstance(ak, dict):
                account_keys.append(ak.get("pubkey", ""))
            else:
                account_keys.append(str(ak))

        pre_sol = meta.get("preBalances", [])
        post_sol = meta.get("postBalances", [])

        wallet_address = None
        sol_spent = 0.0

        for i, key in enumerate(account_keys):
            if key in self.tracked_wallets:
                wallet_address = key
                if i < len(pre_sol) and i < len(post_sol):
                    sol_spent = (pre_sol[i] - post_sol[i]) / 1e9
                break

        if not wallet_address or sol_spent <= 0:
            return None

        post_token_map: dict[str, dict] = {}
        for bal in post_balances:
            mint = bal.get("mint", "")
            if mint and mint not in IGNORED_MINTS:
                owner = bal.get("owner", "")
                if owner == wallet_address:
                    post_token_map[mint] = bal

        pre_token_map: dict[str, dict] = {}
        for bal in pre_balances:
            mint = bal.get("mint", "")
            if mint and mint not in IGNORED_MINTS:
                owner = bal.get("owner", "")
                if owner == wallet_address:
                    pre_token_map[mint] = bal

        token_address = None
        for mint, post_bal in post_token_map.items():
            post_amount = float(post_bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
            pre_bal = pre_token_map.get(mint, {})
            pre_amount = float(pre_bal.get("uiTokenAmount", {}).get("uiAmount", 0) or 0)
            if post_amount > pre_amount:
                token_address = mint
                break

        if not token_address:
            return None

        return SwapEvent(
            wallet_address=wallet_address,
            token_address=token_address,
            amount_sol=sol_spent,
            tx_signature=signature,
            timestamp=int(time.time()),
        )

    # ── REST polling fallback ───────────────────────────────────────────

    async def _rest_poll_loop(self):
        while self._running:
            for addr in list(self.tracked_wallets.keys()):
                if not self._running:
                    break
                try:
                    await self._poll_wallet_rest(addr)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning("rest poll failed wallet=%s error=%s", shorten_address(addr), exc)
                except Exception:
                    logger.exception("unexpected rest poll error wallet=%s", shorten_address(addr))
            await asyncio.sleep(settings.WALLET_POLL_INTERVAL)

    @retry_with_backoff(max_retries=2, base_delay=2.0)
    async def _poll_wallet_rest(self, address: str):
        await self._rate_limiter.acquire()

        url = (
            f"{settings.HELIUS_REST_URL}/v0/addresses/{address}/transactions"
            f"?api-key={settings.HELIUS_API_KEY}&type=SWAP"
        )

        last_sig = self._last_rest_signature.get(address)
        if last_sig:
            url += f"&before={last_sig}"

        async with self._session.get(url) as resp:
            if resp.status != 200:
                logger.warning("rest poll status=%d wallet=%s", resp.status, shorten_address(address))
                return
            txns = await resp.json()

        if not txns:
            return

        self._last_rest_signature[address] = txns[0].get("signature", "")

        for txn in txns:
            sig = txn.get("signature", "")
            if not sig or sig in self._seen_signatures:
                continue

            swap = self._parse_helius_enhanced_tx(txn, address)
            if swap:
                self._seen_signatures.add(sig)
                await self._process_swap(swap)

    def _parse_helius_enhanced_tx(self, txn: dict, wallet_address: str) -> Optional[SwapEvent]:
        tx_type = txn.get("type", "")
        if tx_type != "SWAP":
            return None

        token_transfers = txn.get("tokenTransfers", [])
        native_transfers = txn.get("nativeTransfers", [])

        sol_spent = 0.0
        for nt in native_transfers:
            if nt.get("fromUserAccount") == wallet_address:
                sol_spent += nt.get("amount", 0) / 1e9

        if sol_spent <= 0:
            return None

        token_address = None
        for tt in token_transfers:
            mint = tt.get("mint", "")
            if mint and mint not in IGNORED_MINTS and tt.get("toUserAccount") == wallet_address:
                token_address = mint
                break

        if not token_address:
            return None

        timestamp = txn.get("timestamp", int(time.time()))

        return SwapEvent(
            wallet_address=wallet_address,
            token_address=token_address,
            amount_sol=sol_spent,
            tx_signature=txn.get("signature", ""),
            timestamp=timestamp,
        )

    # ── Shared processing ───────────────────────────────────────────────

    async def _process_swap(self, swap: SwapEvent):
        logger.info(
            "swap detected wallet=%s token=%s sol=%.4f sig=%s",
            shorten_address(swap.wallet_address),
            shorten_address(swap.token_address),
            swap.amount_sol,
            swap.tx_signature[:12],
        )

        self.recent_swaps[swap.token_address].append(swap)

        try:
            db = await get_db()
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO wallet_swaps
                       (wallet_address, token_address, tx_signature, amount_sol, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                    (swap.wallet_address, swap.token_address, swap.tx_signature,
                     swap.amount_sol, swap.timestamp),
                )
                await db.commit()
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.error("db insert failed: %s", exc)

    # ── Convergence detection ───────────────────────────────────────────

    async def _convergence_checker(self):
        while self._running:
            try:
                now = int(time.time())
                for token_address, swaps in list(self.recent_swaps.items()):
                    if not swaps:
                        continue

                    recent = [s for s in swaps if now - s.timestamp <= settings.CONVERGENCE_WINDOW]
                    if not recent:
                        continue

                    unique_wallets = list({s.wallet_address for s in recent})

                    if len(unique_wallets) >= settings.MIN_APES:
                        last_emit = self._emitted_plays.get(token_address, 0)
                        if now - last_emit > settings.CONVERGENCE_WINDOW:
                            timestamps = [s.timestamp for s in recent]
                            signal = PlaySignal(
                                token_address=token_address,
                                wallets=unique_wallets,
                                ape_count=len(unique_wallets),
                                first_swap_ts=min(timestamps),
                                last_swap_ts=max(timestamps),
                                window_seconds=max(timestamps) - min(timestamps),
                            )
                            await self.signal_queue.put(signal)
                            self._emitted_plays[token_address] = now
                            logger.info(
                                "CONVERGENCE token=%s apes=%d window=%ds wallets=[%s]",
                                shorten_address(token_address),
                                signal.ape_count,
                                signal.window_seconds,
                                ", ".join(shorten_address(w) for w in unique_wallets),
                            )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("convergence checker error")

            await asyncio.sleep(2)

    # ── Cleanup loop ────────────────────────────────────────────────────

    async def _cleanup_loop(self):
        max_swap_age = settings.CONVERGENCE_WINDOW * 2
        sig_max_age = 600
        emit_max_age = settings.CONVERGENCE_WINDOW

        while self._running:
            try:
                now = int(time.time())
                now_mono = time.monotonic()

                for token_address in list(self.recent_swaps.keys()):
                    self.recent_swaps[token_address] = [
                        s for s in self.recent_swaps[token_address]
                        if now - s.timestamp <= max_swap_age
                    ]
                    if not self.recent_swaps[token_address]:
                        del self.recent_swaps[token_address]

                cutoff_sigs = now - sig_max_age
                if len(self._seen_signatures) > 10000:
                    self._seen_signatures.clear()
                    logger.info("cleared seen signatures (overflow)")

                expired_plays = [
                    t for t, ts in self._emitted_plays.items()
                    if now - ts > emit_max_age
                ]
                for t in expired_plays:
                    del self._emitted_plays[t]

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("cleanup error")

            await asyncio.sleep(60)
