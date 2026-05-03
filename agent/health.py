import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import settings
from agent.utils import RateLimiter, create_aiohttp_session

logger = logging.getLogger("savage.health")

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclass
class HealthCheckResult:
    name: str
    ok: bool
    latency_ms: float
    details: str = ""
    required: bool = True


@dataclass
class HealthReport:
    ok: bool
    results: list[HealthCheckResult] = field(default_factory=list)


class HealthChecker:
    def __init__(self):
        self._timeout = settings.HEALTH_CHECK_TIMEOUT
        self._helius_limiter = RateLimiter(settings.HELIUS_RATE_LIMIT)
        self._dex_limiter = RateLimiter(settings.DEXSCREENER_RATE_LIMIT)
        self._jupiter_limiter = RateLimiter(settings.JUPITER_RATE_LIMIT)

    async def check_helius_rpc(self) -> HealthCheckResult:
        session = create_aiohttp_session(timeout_total=int(self._timeout))
        try:
            await self._helius_limiter.acquire()
            t0 = time.monotonic()
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
            async with session.post(settings.HELIUS_RPC_URL, json=payload) as resp:
                body = await resp.json()
            latency = (time.monotonic() - t0) * 1000
            result_val = body.get("result", "")
            ok = resp.status == 200 and result_val == "ok"
            return HealthCheckResult(
                name="helius_rpc", ok=ok, latency_ms=latency,
                details=result_val if ok else f"status={resp.status} result={result_val}",
            )
        except Exception as exc:
            return HealthCheckResult(name="helius_rpc", ok=False, latency_ms=0, details=str(exc))
        finally:
            await session.close()

    async def check_helius_rest(self) -> HealthCheckResult:
        session = create_aiohttp_session(timeout_total=int(self._timeout))
        try:
            await self._helius_limiter.acquire()
            t0 = time.monotonic()
            url = f"{settings.HELIUS_REST_URL}/v0/addresses/{settings.WSOL_MINT}/balances?api-key={settings.HELIUS_API_KEY}"
            async with session.get(url) as resp:
                await resp.read()
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status in (200, 404)
            return HealthCheckResult(
                name="helius_rest", ok=ok, latency_ms=latency,
                details=f"status={resp.status}",
            )
        except Exception as exc:
            return HealthCheckResult(name="helius_rest", ok=False, latency_ms=0, details=str(exc))
        finally:
            await session.close()

    async def check_dexscreener(self) -> HealthCheckResult:
        session = create_aiohttp_session(timeout_total=int(self._timeout))
        try:
            await self._dex_limiter.acquire()
            t0 = time.monotonic()
            url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{settings.WSOL_MINT}"
            async with session.get(url) as resp:
                body = await resp.json()
            latency = (time.monotonic() - t0) * 1000
            pairs = body.get("pairs") or []
            ok = resp.status == 200 and len(pairs) > 0
            return HealthCheckResult(
                name="dexscreener", ok=ok, latency_ms=latency,
                details=f"pairs={len(pairs)}",
            )
        except Exception as exc:
            return HealthCheckResult(name="dexscreener", ok=False, latency_ms=0, details=str(exc))
        finally:
            await session.close()

    async def check_jupiter(self) -> HealthCheckResult:
        session = create_aiohttp_session(timeout_total=int(self._timeout))
        try:
            await self._jupiter_limiter.acquire()
            t0 = time.monotonic()
            url = (
                f"{settings.JUPITER_API_URL}/quote"
                f"?inputMint={settings.WSOL_MINT}"
                f"&outputMint={USDC_MINT}"
                f"&amount=100000000"
                f"&slippageBps=50"
            )
            async with session.get(url) as resp:
                body = await resp.json()
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status == 200 and int(body.get("outAmount", 0)) > 0
            return HealthCheckResult(
                name="jupiter", ok=ok, latency_ms=latency,
                details=f"outAmount={body.get('outAmount', 0)}" if ok else f"status={resp.status}",
            )
        except Exception as exc:
            return HealthCheckResult(name="jupiter", ok=False, latency_ms=0, details=str(exc))
        finally:
            await session.close()

    async def check_telegram(self) -> HealthCheckResult:
        if not settings.TELEGRAM_BOT_TOKEN:
            return HealthCheckResult(
                name="telegram", ok=False, latency_ms=0,
                details="TELEGRAM_BOT_TOKEN not set", required=True,
            )
        session = create_aiohttp_session(timeout_total=int(self._timeout))
        try:
            t0 = time.monotonic()
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe"
            async with session.get(url) as resp:
                body = await resp.json()
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status == 200 and body.get("ok", False)
            username = body.get("result", {}).get("username", "")
            return HealthCheckResult(
                name="telegram", ok=ok, latency_ms=latency,
                details=f"bot=@{username}" if ok else f"status={resp.status}",
            )
        except Exception as exc:
            return HealthCheckResult(name="telegram", ok=False, latency_ms=0, details=str(exc))
        finally:
            await session.close()

    async def check_grok(self) -> HealthCheckResult:
        required = settings.REQUIRE_GROK
        if not settings.GROK_API_KEY:
            return HealthCheckResult(
                name="grok", ok=not required, latency_ms=0,
                details="not configured", required=required,
            )
        session = create_aiohttp_session(timeout_total=int(self._timeout))
        try:
            t0 = time.monotonic()
            headers = {"Authorization": f"Bearer {settings.GROK_API_KEY}"}
            url = f"{settings.GROK_API_URL}/models"
            async with session.get(url, headers=headers) as resp:
                await resp.read()
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status == 200
            return HealthCheckResult(
                name="grok", ok=ok, latency_ms=latency,
                details=f"status={resp.status}", required=required,
            )
        except Exception as exc:
            return HealthCheckResult(
                name="grok", ok=False, latency_ms=0,
                details=str(exc), required=required,
            )
        finally:
            await session.close()

    async def check_wallet(self) -> HealthCheckResult:
        import os
        required = not settings.DRY_RUN or settings.REQUIRE_TRADING_WALLET
        has_encrypted = bool(settings.ENCRYPTION_KEY and settings.TRADER_WALLET_KEY)
        has_raw = bool(os.getenv("TRADER_WALLET_PRIVATE_KEY", ""))
        ok = has_encrypted or has_raw
        details = "encrypted" if has_encrypted else ("raw_key" if has_raw else "not configured")
        return HealthCheckResult(
            name="wallet", ok=ok if required else True, latency_ms=0,
            details=details if ok else ("not configured (ok in dry-run)" if not required else "not configured"),
            required=required,
        )

    async def run_all(self) -> HealthReport:
        checks = [
            self.check_helius_rpc(),
            self.check_helius_rest(),
            self.check_dexscreener(),
            self.check_jupiter(),
            self.check_telegram(),
            self.check_grok(),
            self.check_wallet(),
        ]
        results: list[HealthCheckResult] = []
        done, pending = await asyncio.wait(
            [asyncio.create_task(c) for c in checks],
            timeout=self._timeout + 2,
        )
        for task in done:
            try:
                results.append(task.result())
            except Exception as exc:
                results.append(HealthCheckResult(name="unknown", ok=False, latency_ms=0, details=str(exc)))
        for task in pending:
            task.cancel()
            results.append(HealthCheckResult(name="timeout", ok=False, latency_ms=0, details="timed out"))

        all_ok = all(r.ok for r in results if r.required)
        return HealthReport(ok=all_ok, results=results)
