import asyncio
import functools
import json
import logging
import logging.handlers
import os
import random
import time
from typing import Optional

import aiohttp

from config import settings


logger = logging.getLogger("savage.utils")


class RateLimiter:
    """Token-bucket rate limiter for async API calls."""

    def __init__(self, rate: int, per: float = 1.0):
        self.rate = rate
        self.per = per
        self.tokens = float(rate)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
            self.last_refill = now
            if self.tokens < 1:
                wait_time = (1 - self.tokens) * (self.per / self.rate)
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


def create_aiohttp_session(
    timeout_total: int = 30,
    timeout_connect: int = 10,
) -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=timeout_total, connect=timeout_connect)
    return aiohttp.ClientSession(timeout=timeout)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (aiohttp.ClientError, asyncio.TimeoutError),
):
    """Decorator: retries an async function with exponential backoff + jitter."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        break
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = random.uniform(0, delay * 0.5)
                    logger.warning(
                        "retry attempt=%d/%d func=%s error=%s delay=%.2fs",
                        attempt + 1,
                        max_retries,
                        func.__name__,
                        str(exc),
                        delay + jitter,
                    )
                    await asyncio.sleep(delay + jitter)
            raise last_exc
        return wrapper
    return decorator


def shorten_address(addr: str) -> str:
    if len(addr) <= 8:
        return addr
    return f"{addr[:4]}...{addr[-4:]}"


def setup_logging(level: Optional[str] = None, json_format: Optional[bool] = None):
    """Configure structured JSON logging with stdout + rotating file handler."""
    level = level or settings.LOG_LEVEL
    use_json = json_format if json_format is not None else settings.LOG_FORMAT_JSON

    root = logging.getLogger("savage")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return

    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_obj = {
                "ts": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0] is not None:
                log_obj["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_obj)

    text_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    json_formatter = JsonFormatter()

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(json_formatter if use_json else text_formatter)
    root.addHandler(stdout_handler)

    os.makedirs(settings.LOG_DIR, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        settings.LOG_DIR / "savage.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(json_formatter)
    root.addHandler(file_handler)
