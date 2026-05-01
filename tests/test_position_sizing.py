"""Validate position sizing tiers in ExecutionEngine.compute_position_size().

Uses a lightweight fake TokenScore to avoid pulling in network-dependent code.
"""

from dataclasses import dataclass

import pytest

from agent.execution import ExecutionEngine
from config import settings


@dataclass
class FakeTokenScore:
    total_score: int = 0
    volume_1h: float = 0.0


@pytest.fixture
def engine():
    return ExecutionEngine()


@pytest.fixture
def max_cap():
    return settings.MAX_POSITION_SOL


def test_tier1_score60_apes2(engine, max_cap):
    size = engine.compute_position_size(FakeTokenScore(total_score=60), ape_count=2)
    assert size > 0
    assert size <= max_cap


def test_tier2_score70_apes3(engine, max_cap):
    size = engine.compute_position_size(FakeTokenScore(total_score=70), ape_count=3)
    assert size >= 2.0
    assert size <= max_cap


def test_tier3_score80_apes4(engine, max_cap):
    size = engine.compute_position_size(FakeTokenScore(total_score=80), ape_count=4)
    assert size >= 4.0
    assert size <= max_cap


def test_tier4_score90_apes5(engine, max_cap):
    size = engine.compute_position_size(FakeTokenScore(total_score=90), ape_count=5)
    assert size >= 7.0
    assert size <= max_cap


def test_insufficient_apes_returns_zero(engine):
    assert engine.compute_position_size(FakeTokenScore(total_score=90), ape_count=1) == 0
    assert engine.compute_position_size(FakeTokenScore(total_score=60), ape_count=1) == 0
    assert engine.compute_position_size(FakeTokenScore(total_score=65), ape_count=1) == 0


def test_below_threshold_returns_zero(engine):
    assert engine.compute_position_size(FakeTokenScore(total_score=59), ape_count=5) == 0


def test_max_cap_respected(engine, max_cap):
    score = FakeTokenScore(total_score=90, volume_1h=1_000_000)
    size = engine.compute_position_size(score, ape_count=5)
    assert size <= max_cap


def test_volume_multiplier_applied(engine):
    low_vol = FakeTokenScore(total_score=90, volume_1h=100)
    high_vol = FakeTokenScore(total_score=90, volume_1h=1_000_000)
    size_low = engine.compute_position_size(low_vol, ape_count=5)
    size_high = engine.compute_position_size(high_vol, ape_count=5)
    assert size_high >= size_low
