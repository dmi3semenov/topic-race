"""Smoke tests for make_d3_race_html — the HTML template builder.

We don't try to render the D3 animation here (that needs a browser). Instead
we verify the template produces valid-looking HTML with the right knobs wired
through the payload."""
from __future__ import annotations

from datetime import datetime, timezone

from topic_race.animate import EventFrame
from topic_race.d3_race import make_d3_race_html


def _frame(sec: int, **counts: int) -> EventFrame:
    return EventFrame(
        timestamp=datetime(2025, 6, 7, 12, 0, sec, tzinfo=timezone.utc),
        counts=dict(counts),
    )


def test_basic_html_structure() -> None:
    frames = [_frame(0, LLM=1), _frame(1, LLM=1, ML=1), _frame(2, LLM=2, ML=1)]
    html, height = make_d3_race_html(frames, title="Тест", subtitle="подзаголовок")
    assert "<svg" in html
    assert "d3.v7" in html
    assert "__DATA_JSON__" not in html, "placeholder should be substituted"
    assert height > 0


def test_vertical_layout_flag_reaches_payload() -> None:
    frames = [_frame(0, LLM=1)]
    html, height = make_d3_race_html(frames, layout="vertical")
    assert "vertical" in html  # body class or data flag
    assert height == 1920


def test_intro_lines_rendered_into_html_and_body_has_intro_class() -> None:
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        intro_lines=["Topic Race", "Группа «Материалы»"],
        autoplay=True,
        hide_controls=True,
    )
    # Body class drives CSS for first-paint intro visibility
    assert "has-intro" in html
    assert "hide-controls" in html
    # Intro content is server-rendered so there's no flash before JS runs
    assert "Topic Race" in html
    assert "Группа «Материалы»" in html


def test_html_escapes_intro_dangerous_characters() -> None:
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        intro_lines=["<script>alert('xss')</script>"],
    )
    # In the visible <div id="intro">, angle brackets are HTML-escaped.
    assert "&lt;script&gt;" in html
    # The raw text also appears inside the embedded JSON payload, which sits
    # inside a <script> block. The critical escape is the closing tag —
    # `</script` inside the JSON would prematurely close the outer <script>.
    # We verify the only </script in the document is the one that legitimately
    # closes our own block.
    count_close = html.count("</script>")
    # Our template has exactly one <script src=d3> and one inline <script>
    # block, so exactly two closing tags total.
    assert count_close == 2, f"unexpected </script> count: {count_close}"


def test_subtitle_can_be_a_list_of_lines() -> None:
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        subtitle=["строка 1", "строка 2"],
    )
    # Both lines should survive into the payload JSON
    assert "строка 1" in html
    assert "строка 2" in html


def test_empty_frames_does_not_crash() -> None:
    html, height = make_d3_race_html([])
    assert "<svg" in html
    assert height > 0
