# Topic Race

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/dmi3semenov/topic-race/blob/main/topic_race_colab.ipynb)

Bar chart race для топиков Telegram-группы — анимированный рейтинг топиков
по числу добавленных постов за всю историю. На выходе — вертикальное Reels-видео
(1080×1920) с музыкой, intro-слайдом и плавным outro.

## Что это

В Telegram есть форумные группы с топиками (темами). Каждый топик наполняется
сообщениями — репостами, заметками, ссылками. Topic Race парсит историю группы,
считает накопительную статистику по каждому топику и визуализирует её в виде
анимированного bar chart race — кто в лидерах, кто кого обгоняет, как менялась
картина со временем.

### Пример

Группа **«Материалы»** — приватная группа с 83 топиками (LLM, Claude code,
Промптинг, Vibe, RAG и т.д.), 761 пост за 10 месяцев.

Результат: 2-минутное вертикальное видео с треком «Universe Size»:
- Intro-слайд: «Topic Race • Топ-15 топиков • Группа «Материалы» • период»
- 3-секундная пауза на первом кадре (LLM = 1)
- Гонка с ease-in-out темпом: медленно в начале, быстро в середине, медленно в конце
- 11-секундное удержание финала с золотистой рамкой

## Быстрый старт

### 1. Установка

```bash
git clone https://github.com/dmi3semenov/topic-race.git
cd topic-race
uv sync
```

Системные зависимости: **ffmpeg** (для рендера видео) и **Chromium** (для Playwright):

```bash
brew install ffmpeg          # macOS
uv run playwright install chromium
```

### 2. Настройка Telegram

Credentials (`TG_API_ID`, `TG_API_HASH`, `TG_PHONE`) читаются из shell
env — обычно их уже выставил `~/.zshrc` через auto-source из
`~/.claude/secrets/telegram.env`. Ничего копировать не нужно.

Project-specific переменные (`TG_GROUP_NAME` — название форумной
группы, `TG_SESSION_NAME` — имя сессионного файла Telethon) лежат
прямо в `.env` в корне проекта. Можешь отредактировать под свою
группу.

Для запуска без shell (CI / Docker / launchd) — скопируй
`.env.example` в `.env`, раскомментируй credentials и заполни из
`~/.claude/secrets/telegram.env`.

Первая авторизация — интерактивная (нужен код из Telegram):

```bash
# Шаг 1: запросить код
uv run python -m topic_race.auth request

# Шаг 2: ввести код (и 2FA-пароль, если включён)
uv run python -m topic_race.auth submit 12345
# или с 2FA:
uv run python -m topic_race.auth submit 12345 --password mypass
```

### 3. Загрузка данных

```bash
# Последние 14 дней:
uv run python main.py --days 14

# Вся история:
uv run python main.py --all
```

Данные кешируются в `data/cache.db` (SQLite). Повторные запуски дополняют кеш.

### 4. Streamlit-дашборд

```bash
uv run streamlit run src/topic_race/app.py
```

Интерактивный D3 bar chart race прямо в браузере: Play / Pause / Reset / слайдер /
выбор скорости. Плюс кнопка **«Записать Reels»** для генерации вертикального MP4.

### 5. Рендер Reels из CLI

```bash
uv run python -c "from topic_race.render_video import render_reel; r = render_reel(); print(r.mp4_path)"
```

Готовый MP4 попадает в `out/`. Параметры (длительность, темп, intro, outro, аудио)
настраиваются через аргументы `render_reel(...)` или через слайдеры в Streamlit UI.

## Аудио

По умолчанию ожидается трек в `data/audio/universe_size.m4a`. Скачать можно через
yt-dlp:

```bash
uv run yt-dlp -x --audio-format m4a -o "data/audio/universe_size.%(ext)s" "https://vkvideo.ru/video-147438031_456239017"
```

## Тесты

```bash
uv run pytest
```

73 unit-теста, описания на русском. Покрывают: плюрализацию, расписание темпа,
ffmpeg-фильтры, агрегацию с альбомами и дубль-названиями, HTML-генератор,
layout-overflow.

## Структура проекта

```
src/topic_race/
├── config.py           — загрузка .env, пути
├── auth.py             — двухшаговая авторизация Telegram (без TTY)
├── telegram_client.py  — Telethon: поиск группы, fetch топиков и сообщений
├── storage.py          — SQLite: схема + CRUD (groups, topics, messages)
├── aggregate.py        — messages → DataFrame (свёртка альбомов, disambiguation)
├── animate.py          — DataFrame → EventFrame[] (по одному кадру на сообщение)
├── d3_race.py          — EventFrame[] → HTML с D3 bar chart race
├── render_video.py     — HTML → webm (Playwright) → mp4 + аудио (ffmpeg)
├── layout_check.py     — приближённая оценка ширины SVG-текста
├── render.py           — legacy: bar_chart_race (matplotlib) → mp4
└── app.py              — Streamlit UI
```

## Лицензия

MIT
