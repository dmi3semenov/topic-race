"""Tests for ffmpeg atempo chain construction.

ffmpeg's atempo filter only accepts 0.5..2.0 per call, so >2x or <0.5x must
be expressed as a chain. We also drop no-op filters at tempo==1.0."""
from __future__ import annotations

import pytest

from topic_race.render_video import _atempo_chain


def test_tempo_1_is_noop() -> None:
    assert _atempo_chain(1.0) == ""


def test_tempo_1p5() -> None:
    assert _atempo_chain(1.5) == "atempo=1.5"


def test_tempo_2_exact() -> None:
    # 2.0 is within a single atempo call — the loop should NOT split,
    # and the residual-1.0 shouldn't append a redundant segment.
    result = _atempo_chain(2.0)
    assert result == "atempo=2.0"


def test_tempo_3_chains() -> None:
    """3x needs two atempo calls: 2.0 * 1.5."""
    result = _atempo_chain(3.0)
    parts = result.split(",")
    assert parts[0] == "atempo=2.0"
    assert parts[1].startswith("atempo=1.5")


def test_tempo_4_chains() -> None:
    """4x → 2.0 * 2.0."""
    result = _atempo_chain(4.0)
    assert result == "atempo=2.0,atempo=2.0"


def test_tempo_0p5_exact() -> None:
    assert _atempo_chain(0.5) == "atempo=0.5"


def test_tempo_0p25_chains() -> None:
    """0.25x → 0.5 * 0.5."""
    result = _atempo_chain(0.25)
    assert result == "atempo=0.5,atempo=0.5"


def test_tempo_zero_or_negative() -> None:
    assert _atempo_chain(0) == ""
    assert _atempo_chain(-1) == ""
