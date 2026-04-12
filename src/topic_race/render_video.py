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
    start_mult: float = 4.0,
    end_mult: float = 2.6,
    intro_frac: float = 0.04,
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


def build_variable_tempo_filter(
    audio_start_sec: float,
    target_duration_sec: float,
    intro_sec: float = 10.0,
    intro_tempo: float = 1.0,
    main_tempo: float = 2.0,
    outro_sec: float = 8.0,
    outro_tempo: float = 1.0,
    volume: float = 0.55,
    fade_out_sec: float = 6.0,
    audio_input_label: str = "0:a",
) -> tuple[str, list[str]]:
    """Build an ffmpeg filter_complex string for variable-tempo audio.

    The output has three segments in *output time*:
      1) intro_sec at intro_tempo (usually 1.0x — normal speed)
      2) main_duration at main_tempo (usually 2.0x — fast, the race burns through)
      3) outro_sec at outro_tempo (usually 0.6x — slow dramatic finale)

    Segments are cut from the source audio starting at audio_start_sec.
    Each segment consumes `seg_out * seg_tempo` seconds of source time.

    Returns (filter_complex_string, output_label_list). The label to map as the
    audio output is the last element of output_label_list.
    """
    if main_tempo <= 0 or intro_tempo <= 0 or outro_tempo <= 0:
        raise ValueError("Tempos must be positive")
    if intro_sec + outro_sec >= target_duration_sec:
        raise ValueError(
            f"intro+outro ({intro_sec + outro_sec}s) must be < target "
            f"({target_duration_sec}s)"
        )

    main_out_sec = target_duration_sec - intro_sec - outro_sec

    # Source offsets: how much source time each output segment consumes.
    src_intro_start = audio_start_sec
    src_intro_end = src_intro_start + intro_sec * intro_tempo
    src_main_end = src_intro_end + main_out_sec * main_tempo
    src_outro_end = src_main_end + outro_sec * outro_tempo

    fade_out_start = max(0.0, target_duration_sec - fade_out_sec)

    a = f"[{audio_input_label}]"
    parts = [
        f"{a}atrim={_fmt_tempo(src_intro_start)}:{_fmt_tempo(src_intro_end)},"
        f"asetpts=PTS-STARTPTS,{_atempo_chain(intro_tempo) or 'anull'}[s1]",
        f"{a}atrim={_fmt_tempo(src_intro_end)}:{_fmt_tempo(src_main_end)},"
        f"asetpts=PTS-STARTPTS,{_atempo_chain(main_tempo) or 'anull'}[s2]",
        f"{a}atrim={_fmt_tempo(src_main_end)}:{_fmt_tempo(src_outro_end)},"
        f"asetpts=PTS-STARTPTS,{_atempo_chain(outro_tempo) or 'anull'}[s3]",
        f"[s1][s2][s3]concat=n=3:v=0:a=1[cat]",
        f"[cat]volume={volume},"
        f"afade=t=in:st=0:d=0.8,"
        f"afade=t=out:st={_fmt_tempo(fade_out_start)}:d={_fmt_tempo(fade_out_sec)}"
        f"[aout]",
    ]
    return ";".join(parts), ["aout"]


def _mux(
    webm_path: Path,
    audio_path: Path | None,
    audio_start_sec: float,
    audio_tempo: float,
    output_mp4: Path,
    target_duration_sec: float,
    intro_normal_sec: float = 10.0,
    outro_slow_sec: float = 8.0,
    outro_tempo: float = 1.0,
    fade_out_sec: float = 6.0,
) -> None:
    """Convert webm to mp4 (h264) and optionally overlay an audio track.

    Audio has 3 segments in output time:
      - first `intro_normal_sec` at 1.0x (normal speed — the intro card)
      - middle at `audio_tempo` (fast main section)
      - last `outro_slow_sec` at `outro_tempo` (slow finale, natural tail)
    """
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if output_mp4.exists():
        output_mp4.unlink()

    if audio_path and audio_path.exists():
        # Input #0 is webm video (no audio), input #1 is the audio file.
        filter_complex, labels = build_variable_tempo_filter(
            audio_start_sec=audio_start_sec,
            target_duration_sec=target_duration_sec,
            intro_sec=intro_normal_sec,
            intro_tempo=1.0,
            main_tempo=audio_tempo,
            outro_sec=outro_slow_sec,
            outro_tempo=outro_tempo,
            fade_out_sec=fade_out_sec,
            audio_input_label="1:a",
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(webm_path),
            "-i", str(audio_path),
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", f"[{labels[-1]}]",
            "-t", f"{target_duration_sec}",
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
    audio_intro_sec: float,
    audio_outro_sec: float,
    audio_outro_tempo: float,
    audio_fade_out_sec: float,
    top_n: int,
    title: str | list[str],
    subtitle: list[str] | str,
    intro_lines: list[str] | None,
    intro_duration_sec: float,
    pre_race_pause_sec: float,
    outro_hold_sec: float,
    output_name: str,
    target_duration_sec: float,
    pacing: str,
) -> RenderResult:
    n = len(frames)
    if n == 0:
        raise ValueError("No event frames to render")

    # Total video timeline:
    #   intro_card → pre_race_pause (LLM=1 visible) → scheduled race → outro_hold
    race_total_sec = max(5.0, target_duration_sec - intro_duration_sec)
    scheduled_race_sec = max(5.0, race_total_sec - pre_race_pause_sec - outro_hold_sec)
    scheduled_ms = scheduled_race_sec * 1000

    schedule = build_schedule(n, scheduled_ms, pacing=pacing)
    mean_frame_ms = max(20, int(round(scheduled_ms / n)))

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
        pre_race_pause_ms=int(pre_race_pause_sec * 1000),
        outro_hold_ms=int(outro_hold_sec * 1000),
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
            intro_normal_sec=audio_intro_sec,
            outro_slow_sec=audio_outro_sec,
            outro_tempo=audio_outro_tempo,
            fade_out_sec=audio_fade_out_sec,
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
    audio_tempo: float = 1.3,
    audio_intro_sec: float = 25.0,
    audio_outro_sec: float = 8.0,
    audio_outro_tempo: float = 1.0,
    audio_fade_out_sec: float = 6.0,
    target_duration_sec: float = 131.0,
    intro_duration_sec: float = 4.5,
    pre_race_pause_sec: float = 3.0,
    outro_hold_sec: float = 11.0,
    pacing: str = "ease-in-out",
    group_name: str = "Материалы",
    title: str | list[str] | None = None,
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
        title = f"Топ-15 топиков в группе «{group_name}»"
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
            audio_intro_sec=audio_intro_sec,
            audio_outro_sec=audio_outro_sec,
            audio_outro_tempo=audio_outro_tempo,
            audio_fade_out_sec=audio_fade_out_sec,
            top_n=top_n,
            title=title,
            subtitle=subtitle,
            intro_lines=intro_lines,
            intro_duration_sec=intro_duration_sec,
            pre_race_pause_sec=pre_race_pause_sec,
            outro_hold_sec=outro_hold_sec,
            output_name=output_name,
            target_duration_sec=target_duration_sec,
            pacing=pacing,
        )
    )
