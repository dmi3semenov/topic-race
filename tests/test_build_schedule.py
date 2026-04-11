"""Tests for the frame-pacing schedule generator."""
from __future__ import annotations

import pytest

from topic_race.render_video import build_schedule


def test_empty_and_single() -> None:
    assert build_schedule(0, 5000) == []
    out = build_schedule(1, 5000)
    assert len(out) == 1
    assert out[0] == pytest.approx(5000, abs=1)


def test_linear_is_uniform() -> None:
    out = build_schedule(10, 1000, pacing="linear")
    assert len(out) == 10
    assert min(out) == max(out)  # all equal


def test_sum_matches_total_ms() -> None:
    """The schedule should approximately sum to the requested total.

    ease-in / ease-out can drift up to ~10% because of the min_ms floor
    (early frames in ease-in have tiny raw weights and get floored to min_ms,
    inflating the sum). That's an acceptable tradeoff for keeping early
    frames legible rather than flashing by in 1ms.
    """
    for pacing in ("linear", "ease-in-out"):
        out = build_schedule(100, 10_000, pacing=pacing)
        total = sum(out)
        assert abs(total - 10_000) < 500, f"{pacing}: {total=}"

    for pacing in ("ease-in", "ease-out"):
        out = build_schedule(100, 10_000, pacing=pacing)
        total = sum(out)
        # Up to 15% overshoot tolerated due to min_ms floor
        assert 9500 <= total <= 11500, f"{pacing}: {total=}"


def test_ease_out_slows_start_speeds_end() -> None:
    out = build_schedule(200, 20_000, pacing="ease-out")
    first = sum(out[:10]) / 10
    last = sum(out[-10:]) / 10
    assert first > last, "ease-out should start slow and speed up"


def test_ease_in_speeds_start_slows_end() -> None:
    out = build_schedule(200, 20_000, pacing="ease-in")
    first = sum(out[:10]) / 10
    last = sum(out[-10:]) / 10
    assert first < last


def test_ease_in_out_is_fastest_in_middle() -> None:
    """Asymmetric bell: edges slow, middle fast. Outro is slower than intro."""
    out = build_schedule(200, 20_000, pacing="ease-in-out")
    first = sum(out[:20]) / 20
    middle = sum(out[90:110]) / 20
    last = sum(out[-20:]) / 20

    # Middle must be faster than both edges
    assert middle < first
    assert middle < last
    # Default end_mult > start_mult → outro slower than intro
    assert last > first


def test_ease_in_out_respects_multipliers() -> None:
    """With larger end_mult, the outro frames should be longer than intro frames."""
    out = build_schedule(
        200, 20_000, pacing="ease-in-out",
        start_mult=1.2, end_mult=3.0,
    )
    first = out[0]
    last = out[-1]
    # Last frame should be ~2.5x the first
    ratio = last / first
    assert 2.0 < ratio < 3.2, f"ratio={ratio}"


def test_min_ms_floor() -> None:
    out = build_schedule(100, 50, pacing="linear", min_ms=40)
    # Every frame at least min_ms
    assert all(ms >= 40 for ms in out)


def test_invalid_pacing_raises() -> None:
    with pytest.raises(ValueError):
        build_schedule(10, 1000, pacing="warp-speed")
