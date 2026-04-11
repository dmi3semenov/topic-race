from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from topic_race.aggregate import load_messages_df
from topic_race.animate import build_event_frames
from topic_race.config import load_settings
from topic_race.d3_race import make_d3_race_html
from topic_race.pipeline import run_sync
from topic_race.render_video import DEFAULT_AUDIO, render_reel
from topic_race.storage import connect


st.set_page_config(page_title="Topic Race", layout="wide")
st.title("Topic Race — гонка топиков Telegram-группы")

settings = load_settings()
st.caption(f"Группа: **{settings.group_name}**")

with st.sidebar:
    st.header("Сбор данных")
    sync_mode = st.radio("Режим", ["Окно (дней)", "Вся история"], horizontal=True)
    since_days = st.number_input("Дней назад", 1, 3650, 14, disabled=sync_mode != "Окно (дней)")

    if st.button("Обновить из Telegram", type="primary"):
        log_area = st.empty()
        log_lines: list[str] = []

        def progress(msg: str) -> None:
            log_lines.append(msg)
            log_area.code("\n".join(log_lines))

        with st.spinner("Подключаюсь к Telegram…"):
            try:
                days_arg = None if sync_mode == "Вся история" else int(since_days)
                group, n_topics, n_new = run_sync(days_arg, progress=progress)
                st.success(f"{group.title}: топиков {n_topics}, новых сообщений {n_new}")
            except Exception as e:
                st.error(f"Ошибка: {e}")
                st.exception(e)

    st.divider()
    st.header("Параметры анимации")
    top_n = st.slider("Сколько топиков показывать", 3, 25, 15)
    frame_ms = st.slider("Длина кадра, мс", 40, 500, 120, step=10)
    transition_ms = st.slider("Длина перехода, мс", 20, 400, 100, step=10)
    max_frames = st.number_input("Макс. кадров (0 = без лимита)", 0, 10000, 800)

    st.divider()
    st.header("Окно данных")
    window_mode = st.radio("", ["Все данные", "Дней"], horizontal=True, label_visibility="collapsed")
    history_days = st.number_input("Последние N дней", 1, 3650, 30, disabled=window_mode != "Дней")


def _latest_group_id() -> int | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT chat_id FROM groups ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None


chat_id = _latest_group_id()
if chat_id is None:
    st.info("Сначала обнови данные из Telegram кнопкой слева.")
    st.stop()

with connect() as conn:
    messages_df = load_messages_df(conn, chat_id)

if messages_df.empty:
    st.warning("В кеше нет сообщений. Нажми «Обновить из Telegram».")
    st.stop()

since = (
    datetime.now(timezone.utc) - timedelta(days=int(history_days))
    if window_mode == "Дней"
    else None
)

frames = build_event_frames(
    messages_df,
    since=since,
    max_frames=None if max_frames == 0 else int(max_frames),
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Сообщений в кеше", f"{len(messages_df):,}")
col2.metric("Топиков с активностью", messages_df["topic_title"].nunique())
col3.metric("Событий в окне", len(frames))
if frames:
    span = frames[-1].timestamp - frames[0].timestamp
    col4.metric("Период", f"{span.days} дн.")

if not frames:
    st.warning("Нет сообщений в выбранном окне.")
    st.stop()

st.subheader("Bar chart race")
st.caption("Нажми ▶ Play над графиком. Каждый кадр — одно новое сообщение.")

html, component_height = make_d3_race_html(
    frames,
    top_n=int(top_n),
    frame_ms=int(frame_ms),
    transition_ms=int(transition_ms),
    title=f"{settings.group_name} — гонка топиков",
)
components.html(html, height=component_height, scrolling=False)

st.divider()
st.subheader("📱 Reels (9:16) — одним кликом")
st.caption(
    "Рендерит вертикальное 1080×1920 MP4 с треком Universe Size (начало с 40 сек). "
    "Ease-out темп: медленно в начале (читаются новые топики), быстро ближе к концу."
)

col_r1, col_r2, col_r3, col_r4 = st.columns(4)
with col_r1:
    reel_duration = st.slider("Длина, сек", 60, 370, 120, step=10, key="reel_dur")
with col_r2:
    reel_intro = st.slider("Intro, сек", 0, 10, 4, step=1, key="reel_intro")
with col_r3:
    reel_audio_start = st.slider("Старт аудио, сек", 0, 120, 40, step=5, key="reel_audio_start")
with col_r4:
    reel_pacing = st.selectbox(
        "Темп",
        ["ease-in-out", "ease-out", "linear", "ease-in"],
        index=0,
        key="reel_pacing",
    )

has_audio = DEFAULT_AUDIO.exists()
if not has_audio:
    st.warning(f"Трек не найден: {DEFAULT_AUDIO}. Видео запишется без звука.")

if st.button("🎬 Записать Reels", type="primary"):
    with st.spinner("Рендерю headless Chromium + ffmpeg…"):
        try:
            result = render_reel(
                top_n=int(top_n),
                audio_path=DEFAULT_AUDIO if has_audio else None,
                audio_start_sec=float(reel_audio_start),
                target_duration_sec=float(reel_duration),
                intro_duration_sec=float(reel_intro),
                pacing=reel_pacing,
                group_name=settings.group_name,
            )
            st.success(
                f"Готово! {result.mp4_path.name} — "
                f"{result.n_frames} кадров, средн. {result.frame_ms}мс/кадр, "
                f"{result.duration_sec:.0f} сек"
            )
            st.session_state["last_reel"] = str(result.mp4_path)
        except Exception as e:
            st.error(f"Ошибка: {e}")
            st.exception(e)

last_reel = st.session_state.get("last_reel")
if last_reel and Path(last_reel).exists():
    st.video(last_reel)
    with open(last_reel, "rb") as f:
        st.download_button(
            "⬇ Скачать Reels MP4",
            f,
            file_name=Path(last_reel).name,
            mime="video/mp4",
        )

with st.expander("Все топики по количеству (отладка)"):
    st.caption(
        "Здесь видно количество сообщений на каждый **отдельный** topic_id. "
        "Если у тебя два топика с одним названием — они идут отдельными строками."
    )
    per_topic = (
        messages_df.groupby(["topic_id", "topic_title", "display_name"])
        .size()
        .reset_index(name="сообщений")
        .sort_values("сообщений", ascending=False)
    )
    st.dataframe(per_topic, use_container_width=True, height=400)

with st.expander("Последние сообщения (отладка)"):
    recent = messages_df.sort_values("date", ascending=False).head(30)[
        ["date", "topic_id", "display_name"]
    ]
    st.dataframe(recent, use_container_width=True)
