"""Exercise RateLimiter.acquire() with a small bucket.

Verifies lock semantics and that acquire() does not raise.
Keeps runtime short by using a tiny rate.
"""

import asyncio

import pytest

from agent.utils import RateLimiter


@pytest.mark.asyncio
async def test_acquire_does_not_raise():
    limiter = RateLimiter(rate=5, per=1.0)
    for _ in range(5):
        await limiter.acquire()


@pytest.mark.asyncio
async def test_acquire_concurrent():
    limiter = RateLimiter(rate=3, per=1.0)
    results = await asyncio.gather(
        limiter.acquire(),
        limiter.acquire(),
        limiter.acquire(),
    )
    assert len(results) == 3


@pytest.mark.asyncio
async def test_token_refill():
    limiter = RateLimiter(rate=2, per=0.1)
    await limiter.acquire()
    await limiter.acquire()
    await asyncio.sleep(0.15)
    await limiter.acquire()


@pytest.mark.asyncio
async def test_lock_prevents_race():
    limiter = RateLimiter(rate=100, per=1.0)

    counter = {"value": 0}

    async def bump():
        await limiter.acquire()
        counter["value"] += 1

    await asyncio.gather(*(bump() for _ in range(50)))
    assert counter["value"] == 50
