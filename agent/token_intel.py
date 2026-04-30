import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import aiosqlite

from config import settings
from db import get_db
from agent.utils import RateLimiter, create_aiohttp_session, retry_with_backoff, shorten_address

logger = logging.getLogger("savage.token_intel")


@dataclass
class TokenScore:
    token_address: str
    total_score: int
    volume_score: int
    holder_score: int
    distribution_score: int
    dev_safety_score: int
    passed: bool
    abort_reason: Optional[str] = None
    volume_1h: float = 0
    volume_24h: float = 0
    liquidity_usd: float = 0
    holder_count: int = 0
    top10_concentration: float = 0
    top3_concentration: float = 0
    mint_authority_enabled: bool = False
    has_social_links: bool = False
    symbol: str = ""
    name: str = ""


class TokenIntel:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._helius_limiter = RateLimiter(settings.HELIUS_RATE_LIMIT)
        self._dexscreener_limiter = RateLimiter(settings.DEXSCREENER_RATE_LIMIT)
        self._rug_db: dict = {}

    async def initialize(self):
        self._session = create_aiohttp_session(timeout_total=settings.RPC_TIMEOUT)
        rug_path = settings.DATA_DIR / "rug_db.json"
        try:
            with open(rug_path) as f:
                self._rug_db = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._rug_db = {"known_ruggers": [], "flagged_patterns": []}
        logger.info("token intel initialized, rug_db has %d known ruggers", len(self._rug_db.get("known_ruggers", [])))

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def score_token(self, token_address: str) -> TokenScore:
        cached = await self._get_cached_score(token_address)
        if cached:
            return cached

        try:
            helius_data, dex_data = await asyncio.wait_for(
                asyncio.gather(
                    self._fetch_helius_data(token_address),
                    self._fetch_dexscreener_data(token_address),
                    return_exceptions=True,
                ),
                timeout=settings.SCORING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("scoring timeout token=%s", shorten_address(token_address))
            return TokenScore(
                token_address=token_address,
                total_score=0, volume_score=0, holder_score=0,
                distribution_score=0, dev_safety_score=0,
                passed=False, abort_reason="scoring_timeout",
            )

        if isinstance(helius_data, Exception):
            logger.warning("helius fetch failed token=%s: %s", shorten_address(token_address), helius_data)
            helius_data = {}
        if isinstance(dex_data, Exception):
            logger.warning("dexscreener fetch failed token=%s: %s", shorten_address(token_address), dex_data)
            dex_data = {}

        score = self._compute_score(token_address, helius_data, dex_data)
        await self._cache_score(score)
        return score

    # ── Helius data fetching ────────────────────────────────────────────

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    async def _fetch_helius_data(self, token_address: str) -> dict:
        data: dict = {}

        await self._helius_limiter.acquire()
        account_resp = await self._rpc_call("getAccountInfo", [
            token_address, {"encoding": "jsonParsed"}
        ])
        account_info = account_resp.get("result", {}).get("value", {})
        parsed = account_info.get("data", {}).get("parsed", {}).get("info", {})
        data["decimals"] = parsed.get("decimals", 0)
        data["supply"] = int(parsed.get("supply", "0"))
        data["mint_authority"] = parsed.get("mintAuthority")
        data["freeze_authority"] = parsed.get("freezeAuthority")

        await self._helius_limiter.acquire()
        holders_resp = await self._rpc_call("getTokenLargestAccounts", [token_address])
        holders = holders_resp.get("result", {}).get("value", [])
        data["top_holders"] = holders[:20]

        total_supply = data["supply"]
        if total_supply > 0:
            top3_sum = sum(
                float(h.get("uiAmount", 0) or 0) for h in holders[:3]
            )
            top10_sum = sum(
                float(h.get("uiAmount", 0) or 0) for h in holders[:10]
            )
            decimals = data["decimals"]
            ui_supply = total_supply / (10 ** decimals) if decimals > 0 else total_supply
            data["top3_concentration"] = top3_sum / ui_supply if ui_supply > 0 else 0
            data["top10_concentration"] = top10_sum / ui_supply if ui_supply > 0 else 0
        else:
            data["top3_concentration"] = 0
            data["top10_concentration"] = 0

        return data

    async def _rpc_call(self, method: str, params: list) -> dict:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with self._session.post(settings.HELIUS_RPC_URL, json=payload) as resp:
            if resp.status != 200:
                raise aiohttp.ClientError(f"RPC {method} returned {resp.status}")
            return await resp.json()

    # ── DexScreener data fetching ───────────────────────────────────────

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    async def _fetch_dexscreener_data(self, token_address: str) -> dict:
        await self._dexscreener_limiter.acquire()
        url = f"{settings.DEXSCREENER_API_URL}/dex/tokens/{token_address}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                raise aiohttp.ClientError(f"dexscreener returned {resp.status}")
            raw = await resp.json()

        pairs = raw.get("pairs") or []
        if not pairs:
            return {}

        pair = pairs[0]
        return {
            "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
            "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
            "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
            "price_change_5m": float(pair.get("priceChange", {}).get("m5", 0) or 0),
            "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
            "socials": pair.get("info", {}).get("socials", []) if pair.get("info") else [],
            "symbol": pair.get("baseToken", {}).get("symbol", ""),
            "name": pair.get("baseToken", {}).get("name", ""),
            "holder_count": int(pair.get("holders", 0) or 0),
        }

    # ── Score computation ───────────────────────────────────────────────

    def _compute_score(self, token_address: str, helius: dict, dex: dict) -> TokenScore:
        volume_1h = dex.get("volume_1h", 0)
        volume_24h = dex.get("volume_24h", 0)
        liquidity_usd = dex.get("liquidity_usd", 0)
        holder_count = dex.get("holder_count", 0)
        top10 = helius.get("top10_concentration", 0)
        top3 = helius.get("top3_concentration", 0)
        mint_auth = helius.get("mint_authority") is not None
        has_socials = bool(dex.get("socials"))
        symbol = dex.get("symbol", "")
        name = dex.get("name", "")

        abort_reason = None

        if top3 > settings.MAX_TOP3_CONCENTRATION:
            abort_reason = f"top3 concentration {top3:.1%} > {settings.MAX_TOP3_CONCENTRATION:.0%}"

        if mint_auth and liquidity_usd < 10000:
            abort_reason = abort_reason or "mint authority enabled, no LP lock evidence"

        known_ruggers = {r.get("address", "").lower() for r in self._rug_db.get("known_ruggers", [])}
        dev_addr = (helius.get("mint_authority") or "").lower()
        top_holder_addrs = [
            (h.get("address", "") or "").lower() for h in helius.get("top_holders", [])
        ]
        dev_is_rugger = dev_addr in known_ruggers
        for tha in top_holder_addrs[:3]:
            if tha in known_ruggers:
                dev_is_rugger = True
                break

        critical_rugger = False
        for r in self._rug_db.get("known_ruggers", []):
            if r.get("address", "").lower() in (dev_addr, *top_holder_addrs[:3]):
                if r.get("severity") == "critical":
                    critical_rugger = True
                    break

        if critical_rugger:
            abort_reason = abort_reason or "dev/holder in rug_db with critical severity"

        if abort_reason:
            return TokenScore(
                token_address=token_address,
                total_score=0, volume_score=0, holder_score=0,
                distribution_score=0, dev_safety_score=0,
                passed=False, abort_reason=abort_reason,
                volume_1h=volume_1h, volume_24h=volume_24h,
                liquidity_usd=liquidity_usd, holder_count=holder_count,
                top10_concentration=top10, top3_concentration=top3,
                mint_authority_enabled=mint_auth, has_social_links=has_socials,
                symbol=symbol, name=name,
            )

        # Volume velocity score (0-25)
        hourly_avg = volume_24h / 24 if volume_24h > 0 else 1
        ratio = volume_1h / max(hourly_avg, 1)
        if ratio > 5:
            v_score = 25
        elif ratio > 3:
            v_score = 20
        elif ratio > 2:
            v_score = 15
        elif ratio > 1:
            v_score = 10
        else:
            v_score = 5

        # Holder health score (0-25)
        if holder_count > 5000:
            h_score = 25
        elif holder_count > 1000:
            h_score = 20
        elif holder_count > 500:
            h_score = 15
        elif holder_count > 100:
            h_score = 10
        else:
            h_score = 5

        if top10 > settings.MAX_HOLDER_CONCENTRATION:
            h_score = max(0, h_score - 10)
        elif top10 > 0.40:
            h_score = max(0, h_score - 5)

        # Distribution score (0-25)
        if top3 > 0.40:
            d_score = 5
        elif top3 > 0.30:
            d_score = 10
        elif top3 > 0.20:
            d_score = 15
        elif top3 > 0.10:
            d_score = 20
        else:
            d_score = 25

        # Dev safety score (0-25)
        ds_score = 25
        if mint_auth and liquidity_usd < 50000:
            ds_score -= 15
        if dev_is_rugger:
            ds_score = 0

        total = v_score + h_score + d_score + ds_score
        passed = total >= settings.BUY_SCORE_THRESHOLD

        score = TokenScore(
            token_address=token_address,
            total_score=total,
            volume_score=v_score,
            holder_score=h_score,
            distribution_score=d_score,
            dev_safety_score=ds_score,
            passed=passed,
            volume_1h=volume_1h,
            volume_24h=volume_24h,
            liquidity_usd=liquidity_usd,
            holder_count=holder_count,
            top10_concentration=top10,
            top3_concentration=top3,
            mint_authority_enabled=mint_auth,
            has_social_links=has_socials,
            symbol=symbol,
            name=name,
        )

        logger.info(
            "scored token=%s symbol=%s total=%d (v=%d h=%d d=%d ds=%d) passed=%s",
            shorten_address(token_address), symbol, total,
            v_score, h_score, d_score, ds_score, passed,
        )
        return score

    # ── Cache ───────────────────────────────────────────────────────────

    async def _get_cached_score(self, token_address: str) -> Optional[TokenScore]:
        try:
            db = await get_db()
            try:
                cursor = await db.execute(
                    """SELECT * FROM token_scores
                       WHERE token_address = ?
                       AND scored_at > datetime('now', '-5 minutes')""",
                    (token_address,),
                )
                row = await cursor.fetchone()
                if row:
                    raw = json.loads(row["raw_data"]) if row["raw_data"] else {}
                    return TokenScore(
                        token_address=token_address,
                        total_score=int(row["buy_score"]),
                        volume_score=int(row["volume_score"] or 0),
                        holder_score=int(row["holder_score"] or 0),
                        distribution_score=int(row["distribution_score"] or 0),
                        dev_safety_score=int(row["dev_safety_score"] or 0),
                        passed=int(row["buy_score"]) >= settings.BUY_SCORE_THRESHOLD,
                        volume_1h=raw.get("volume_1h", 0),
                        volume_24h=raw.get("volume_24h", 0),
                        liquidity_usd=raw.get("liquidity_usd", 0),
                        holder_count=raw.get("holder_count", 0),
                        top10_concentration=raw.get("top10_concentration", 0),
                        top3_concentration=raw.get("top3_concentration", 0),
                        mint_authority_enabled=raw.get("mint_authority_enabled", False),
                        has_social_links=raw.get("has_social_links", False),
                        symbol=raw.get("symbol", ""),
                        name=raw.get("name", ""),
                    )
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.warning("cache lookup failed: %s", exc)
        return None

    async def _cache_score(self, score: TokenScore):
        raw_data = json.dumps({
            "volume_1h": score.volume_1h,
            "volume_24h": score.volume_24h,
            "liquidity_usd": score.liquidity_usd,
            "holder_count": score.holder_count,
            "top10_concentration": score.top10_concentration,
            "top3_concentration": score.top3_concentration,
            "mint_authority_enabled": score.mint_authority_enabled,
            "has_social_links": score.has_social_links,
            "symbol": score.symbol,
            "name": score.name,
        })
        try:
            db = await get_db()
            try:
                await db.execute(
                    """INSERT OR REPLACE INTO token_scores
                       (token_address, buy_score, volume_score, holder_score,
                        distribution_score, dev_safety_score, raw_data, scored_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (score.token_address, score.total_score, score.volume_score,
                     score.holder_score, score.distribution_score, score.dev_safety_score,
                     raw_data),
                )
                await db.commit()
            finally:
                await db.close()
        except aiosqlite.Error as exc:
            logger.warning("cache write failed: %s", exc)
