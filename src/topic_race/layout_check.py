"""Approximate SVG text width checker for Reels layout sanity tests.

We don't have a real font renderer in tests (that needs a browser). Instead
we approximate text width by multiplying character count by a per-weight
factor proportional to font size. The numbers are conservative (err on the
side of «assumes text is wider») so tests catch overflow before it reaches
the screen.

Typical workflow:
    warnings = check_title_fits([...], ...)
    assert not warnings, warnings
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# Calibrated against DejaVu Sans at common weights. Cyrillic characters are
# mostly wider than Latin, so we bias slightly up.
_WIDTH_FACTOR = {
    "regular": 0.58,
    "medium": 0.60,
    "bold": 0.64,
    "extrabold": 0.66,
}


@dataclass(frozen=True)
class TextSpec:
    text: str
    font_size: int
    weight: str = "regular"   # 'regular' | 'medium' | 'bold' | 'extrabold'


def estimate_text_width(spec: TextSpec) -> float:
    """Rough pixel width of the text at its font size. Cyrillic-friendly."""
    factor = _WIDTH_FACTOR.get(spec.weight, _WIDTH_FACTOR["regular"])
    return len(spec.text) * spec.font_size * factor


def check_lines_fit(
    lines: Sequence[TextSpec],
    viewport_width: int,
    margin_left: int,
    margin_right: int,
    min_right_padding: int = 20,
) -> list[str]:
    """Return human-readable warnings for any line that doesn't fit.

    Empty list means everything fits. Each warning points at the specific
    line and tells by how much it overflows.
    """
    available = viewport_width - margin_left - margin_right - min_right_padding
    warnings: list[str] = []
    for i, spec in enumerate(lines):
        w = estimate_text_width(spec)
        if w > available:
            overflow = w - available
            warnings.append(
                f"line {i} '{spec.text}' "
                f"~{w:.0f}px wide > available {available}px (overflow {overflow:.0f}px)"
            )
    return warnings
