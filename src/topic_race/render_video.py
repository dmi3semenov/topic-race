"""Record the D3 bar chart race to an MP4 using a headless browser.

Pipeline:
1. Build the event frames from the SQLite cache.
2. Compute frame_ms so the total animation length matches (audio_duration - start).
3. Render the D3 HTML in vertical mode (9:16) with autoplay + no controls.
4. Launch Chromium via Playwright at 1080×1920, record the viewport to webm.
5. Wait for the animation to finish (`window.__animationDone`), then close context.
6. Convert webm → mp4 with ffmpeg, mux the audio starting at `audio_start_sec`.
7. Final file goes to `out/<name>.mp4`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from .aggregate import load_messages_df
from .animate import EventFrame, build_event_frames
from .config import DATA_DIR, OUT_DIR
from .d3_race import make_d3_race_html
from .storage import connect

log = logging.getLogger(__name__)

REELS_WIDTH = 1080
REELS_HEIGHT = 1920
DEFAULT_AUDIO = DATA_DIR / "audio" / "universe_size.m4a"


@dataclass
class RenderResult:
    mp4_path: Path
    n_frames: int
    frame_ms: int
    duration_sec: float
    audio_used: Path | None
    audio_start_sec: float


def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds."""
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


def _compute_frame_ms(
    n_frames: int,
    target_duration_sec: float,
) -> int:
    if n_frames <= 1:
        return 500
    return max(20, int(round(target_duration_sec * 1000 / n_frames)))


def build_schedule(
    n_frames: int,
    total_ms: float,
    pacing: str = "ease-in-out",
    start_mult: float = 1.6,
    end_mult: float = 2.6,
    intro_frac: float = 0.15,
    outro_frac: float = 0.15,
    min_ms: int = 40,
) -> list[int]:
    """Return per-frame durations (ms) summing to approximately total_ms.

    pacing:
      - "linear"      — constant time per frame
      - "ease-out"    — slow start, fast end (legacy)
      - "ease-in"     — fast start, slow end
      - "ease-in-out" — asymmetric: intro slow, main fast, outro very slow.
                        Controlled by start_mult / end_mult / intro_frac / outro_frac.
    """
    if n_frames <= 0:
        return []
    if n_frames == 1:
        return [max(min_ms, int(total_ms))]

    if pacing == "linear":
        weights = [1.0] * n_frames
    elif pacing == "ease-out":
        weights = [((n_frames - i) / n_frames) ** 1.6 for i in range(n_frames)]
    elif pacing == "ease-in":
        weights = [((i + 1) / n_frames) ** 1.6 for i in range(n_frames)]
    elif pacing == "ease-in-out":
        weights = []
        for i in range(n_frames):
            p = i / (n_frames - 1)
            if p < intro_frac:
                # intro: linearly ease from start_mult → 1.0
                t = p / intro_frac
                w = start_mult * (1 - t) + 1.0 * t
            elif p < 1.0 - outro_frac:
                # main: fast, weight = 1.0
                w = 1.0
            else:
                # outro: ease from 1.0 → end_mult
                t = (p - (1.0 - outro_frac)) / outro_frac
                w = 1.0 * (1 - t) + end_mult * t
            weights.append(w)
    else:
        raise ValueError(f"Unknown pacing: {pacing!r}")

    s = sum(weights)
    raw = [total_ms * w / s for w in weights]
    return [max(min_ms, int(round(x))) for x in raw]


async def _record_webm(
    html_path: Path,
    out_dir: Path,
    width: int,
    height: int,
    max_duration_sec: float,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            record_video_dir=str(out_dir),
            record_video_size={"width": width, "height": height},
        )
        page = await context.new_page()
        await page.goto(f"file://{html_path}", wait_until="networkidle")
        # Small pad for fonts / initial paint — autoplay has a 500ms built-in delay.
        await asyncio.sleep(1.0)
        # Wait until the animation flags itself done, or hit the hard cap.
        deadline = asyncio.get_event_loop().time() + max_duration_sec + 3
        while asyncio.get_event_loop().time() < deadline:
            done = await page.evaluate("() => window.__animationDone === true")
            if done:
                break
            await asyncio.sleep(0.5)
        # Let the final frame breathe for 300ms.
        await asyncio.sleep(0.3)
        await context.close()
        await browser.close()

    # Playwright saves the video when context closes. Find the newest webm.
    webms = sorted(out_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime)
    if not webms:
        raise RuntimeError(f"No webm produced in {out_dir}")
    return webms[-1]


def _fmt_tempo(v: float) -> str:
    """Format a tempo value for ffmpeg: '2.0', '1.5', '1.3333' — no trailing zeros."""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if "." not in s:
        s += ".0"
    return s


def _atempo_chain(tempo: float) -> str:
    """Return an ffmpeg filter string for atempo. ffmpeg atempo only accepts
    0.5..2.0 per instance, so for >2x we chain multiple atempo calls."""
    if tempo <= 0:
        return ""
    filters: list[str] = []
    remaining = tempo
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-3:
        filters.append(f"atempo={_fmt_tempo(remaining)}")
    return ",".join(filters)


def _mux(
    webm_path: Path,
    audio_path: Path | None,
    audio_start_sec: float,
    audio_tempo: float,
    output_mp4: Path,
    target_duration_sec: float,
) -> None:
    """Convert webm to mp4 (h264) and optionally overlay an audio track.

    If audio_path is None, just transcode video. If audio_path is given, trim
    audio to start at audio_start_sec, speed up by audio_tempo, and cut at
    target_duration_sec. Audio is volume-reduced with fade in/out.
    """
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if output_mp4.exists():
        output_mp4.unlink()

    if audio_path and audio_path.exists():
        # Audio filter chain: tempo first (changes timing), then volume + fades.
        fade_out_dur = 2.0
        fade_out_start = max(0.0, target_duration_sec - fade_out_dur)
        filters = []
        atempo = _atempo_chain(audio_tempo)
        if atempo:
            filters.append(atempo)
        filters.extend([
            "volume=0.55",
            "afade=t=in:st=0:d=0.8",
            f"afade=t=out:st={fade_out_start}:d={fade_out_dur}",
        ])
        audio_filter = ",".join(filters)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(webm_path),
            "-ss", f"{audio_start_sec}",
            "-i", str(audio_path),
            "-t", f"{target_duration_sec}",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-af", audio_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_mp4),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(webm_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "20",
            "-movflags", "+faststart",
            str(output_mp4),
        ]

    log.info("Running ffmpeg: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)


async def _render_reel_async(
    frames: list[EventFrame],
    audio_path: Path | None,
    audio_start_sec: float,
    audio_tempo: float,
    top_n: int,
    title: str,
    subtitle: list[str] | str,
    intro_lines: list[str] | None,
    intro_duration_sec: float,
    output_name: str,
    target_duration_sec: float,
    pacing: str,
) -> RenderResult:
    n = len(frames)
    if n == 0:
        raise ValueError("No event frames to render")

    # target_duration_sec is the whole video (intro + race). Race gets the rest.
    race_duration_sec = max(5.0, target_duration_sec - intro_duration_sec)
    race_total_ms = race_duration_sec * 1000

    schedule = build_schedule(n, race_total_ms, pacing=pacing)
    mean_frame_ms = max(20, int(round(race_total_ms / n)))

    html, _ = make_d3_race_html(
        frames,
        top_n=top_n,
        frame_ms=mean_frame_ms,
        transition_ms=mean_frame_ms,
        title=title,
        subtitle=subtitle,
        layout="vertical",
        hide_controls=True,
        autoplay=True,
        frame_durations=schedule,
        intro_lines=intro_lines,
        intro_duration_ms=int(intro_duration_sec * 1000),
    )

    with tempfile.TemporaryDirectory(prefix="topic_race_") as td:
        td_path = Path(td)
        html_path = td_path / "reel.html"
        html_path.write_text(html, encoding="utf-8")

        webm_dir = td_path / "video"
        webm_path = await _record_webm(
            html_path,
            webm_dir,
            REELS_WIDTH,
            REELS_HEIGHT,
            # Intro plays first, then race — Playwright has to keep recording
            # through both phases.
            max_duration_sec=target_duration_sec,
        )

        output_mp4 = OUT_DIR / output_name
        _mux(
            webm_path,
            audio_path,
            audio_start_sec,
            audio_tempo,
            output_mp4,
            target_duration_sec,
        )

    return RenderResult(
        mp4_path=output_mp4,
        n_frames=n,
        frame_ms=mean_frame_ms,
        duration_sec=target_duration_sec,
        audio_used=audio_path if (audio_path and audio_path.exists()) else None,
        audio_start_sec=audio_start_sec,
    )


_RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def ru_date(dt: datetime) -> str:
    """Format a date in Russian: '7 июня 2025'."""
    return f"{dt.day} {_RU_MONTHS[dt.month - 1]} {dt.year}"


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    """Russian plural agreement: returns the correct form for n.

    Examples:
        ru_plural(1, "пост", "поста", "постов") == "пост"
        ru_plural(2, "пост", "поста", "постов") == "поста"
        ru_plural(5, "пост", "поста", "постов") == "постов"
        ru_plural(11, "пост", "поста", "постов") == "постов"  # special case
        ru_plural(21, "пост", "поста", "постов") == "пост"
        ru_plural(761, "пост", "поста", "постов") == "пост"   # ends in 1
    """
    n = abs(int(n))
    mod100 = n % 100
    if 11 <= mod100 <= 14:
        return many
    mod10 = n % 10
    if mod10 == 1:
        return one
    if 2 <= mod10 <= 4:
        return few
    return many


def render_reel(
    top_n: int = 15,
    audio_path: Path | None = DEFAULT_AUDIO,
    audio_start_sec: float = 40.0,
    audio_tempo: float = 1.5,
    target_duration_sec: float = 120.0,
    intro_duration_sec: float = 4.5,
    pacing: str = "ease-in-out",
    group_name: str = "Материалы",
    title: str | None = None,
    subtitle: list[str] | None = None,
    intro_lines: list[str] | None = None,
    output_name: str | None = None,
) -> RenderResult:
    """Synchronous wrapper. Reads messages from SQLite, renders the reel.

    Defaults to a 120-second clip with intro card + ease-in-out pacing
    (slow intro → fast middle → slow finale). Audio volume is lowered
    and faded out in the last two seconds.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT chat_id FROM groups ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("No group cached — run `main.py --all` first.")
        chat_id = row[0]
        df = load_messages_df(conn, chat_id)

    frames = build_event_frames(df)
    if not frames:
        raise RuntimeError("No event frames — is the cache empty?")

    start_dt = frames[0].timestamp
    end_dt = frames[-1].timestamp
    n_posts = len(frames)
    n_topics = len({t for f in frames for t in f.counts})

    topic_word = ru_plural(n_topics, "топик", "топика", "топиков")
    post_word = ru_plural(n_posts, "пост", "поста", "постов")

    if title is None:
        title = f"Популярные топики в группе «{group_name}»"
    if subtitle is None:
        subtitle = [
            f"{ru_date(start_dt)} — {ru_date(end_dt)}",
            f"{n_topics} {topic_word} • {n_posts} {post_word}",
        ]
    if intro_lines is None:
        intro_lines = [
            "Topic Race",
            "Топ-15 топиков по числу добавленных постов",
            f"Группа «{group_name}»",
            f"{ru_date(start_dt)} — {ru_date(end_dt)}",
        ]

    if output_name is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_name = f"reel_{stamp}.mp4"

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} not found on PATH")

    return asyncio.run(
        _render_reel_async(
            frames=frames,
            audio_path=audio_path,
            audio_start_sec=audio_start_sec,
            audio_tempo=audio_tempo,
            top_n=top_n,
            title=title,
            subtitle=subtitle,
            intro_lines=intro_lines,
            intro_duration_sec=intro_duration_sec,
            output_name=output_name,
            target_duration_sec=target_duration_sec,
            pacing=pacing,
        )
    )
