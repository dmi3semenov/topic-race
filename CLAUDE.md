# Topic Race — контекст для Claude Code

## О чём проект

Bar chart race (анимированные столбики-рейтинг) для топиков приватной
Telegram-группы. Первый полноценный pet-project пользователя с оригинальной
идеей. Конечный продукт — вертикальное Reels-видео (1080×1920) под музыку
«Universe Size» (сравнение планет Солнечной системы).

## Текущее состояние

MVP готов и работает. Можно:
- загрузить данные из Telegram (`main.py --all`)
- смотреть интерактивный D3 bar chart race в Streamlit (`app.py`)
- генерировать Reels MP4 одним кликом из UI или через `render_reel()`
- крутить параметры (темп, длительность, intro/outro, аудио)

Данные — приватная группа «Материалы» (83 топика, 761 пост, 10 месяцев).
Треки и кеш лежат в `data/` (gitignored).

### Открытый PR

На момент завершения прошлой сессии:
- PR #1 (`feature/reels-polish`) — все правки после первого коммита.
  Нужно проверить видео `out/reel_20260411_215056.mp4` и замерджить.

## Как запускать

```bash
uv sync                                          # установка зависимостей
uv run python main.py --all                      # загрузка данных из Telegram
uv run streamlit run src/topic_race/app.py       # дашборд
uv run pytest                                    # тесты (73 шт.)
uv run python -c "from topic_race.render_video import render_reel; render_reel()"  # рендер Reels
```

Первая авторизация Telegram: см. `auth.py` (двухшаговая, без TTY).
Креды лежат в глобальном `~/.claude/secrets/telegram.env`.

## Архитектура данных

```
Telegram API (Telethon user-client)
    ↓ iter_messages(reply_to=topic_id) по каждому топику
SQLite cache (data/cache.db)
    ↓ load_messages_df → collapse albums → disambiguate titles
pandas DataFrame (date, topic_id, display_name)
    ↓ build_event_frames → 1 кадр на сообщение
EventFrame[] (timestamp + cumulative counts dict)
    ↓ make_d3_race_html → D3 SVG в HTML
    ↓ или render_reel → Playwright headless → webm → ffmpeg mp4 + audio
```

## Важные решения и грабли

### Telethon API
- `GetForumTopicsRequest` — в `telethon.tl.functions.messages` (не `.channels`),
  параметр `peer=` (не `channel=`). Ломалось при миграции.
- `iter_messages(reply_to=topic_id)` — корректный способ получить сообщения
  топика. НЕ использовать `min_id` для инкрементальной догрузки — если
  предыдущий sync был с `--days 14`, `min_id` установится на последнее
  сообщение, и при `--all` старые сообщения не дозагрузятся. Поэтому
  всегда fetch с `min_id=0`, дедуп через `INSERT OR IGNORE`.
- Flood waits (12-18 сек) на `GetRepliesRequest` — Telethon обрабатывает
  автоматически, просто sync занимает ~3-5 минут на 83 топика.

### Media-альбомы
- Telegram возвращает каждое фото альбома как отдельный `Message` (с общим
  `grouped_id`). Пользователь считает альбом одним постом. Мы коллапсируем
  в `load_messages_df` по `(topic_id, grouped_id)`, оставляя один ряд
  per album. Без этого Openclaw показывал 21 вместо 19.

### Дубли названий топиков
- В группе два топика «Изучить» (id=425 и 859). Если агрегировать по
  `topic_title`, счётчики сливаются (12 вместо 7+5). Решение: колонка
  `display_name` с суффиксом `#<topic_id>` для дубликатов.

### Headless Chromium + visibility
- Попытка скрыть чарт через `visibility: hidden` во время intro ломала
  рендеринг в headless — SVG не перерисовывался при flip обратно на
  `visible`. Решение: убрали visibility, используем только физическое
  перекрытие intro-overlay (position: fixed, z-index, opaque background).

### ffmpeg filter_complex
- В `_mux`, видео — input #0, аудио — input #1. Фильтр должен ссылаться
  на `[1:a]`, не `[0:a]`.
- `atempo` принимает только 0.5–2.0; для >2x нужна цепочка (`_atempo_chain`).

## Что пользователь хочет дальше (см. TODO.md)

1. **Финализировать Reels** — мелкие правки по фидбеку (текст intro, пауза,
   финал). Может потребовать ещё 1-2 итерации.
2. **Сервис для чужих групп** — обобщить, чтобы другие могли указать свою
   группу и получить такое же видео.
3. **Другие viral-генераторы из Telegram-данных** — Wrapped, heatmap, граф
   общения, эволюция стикеров. Идеи в TODO.md.

## Стиль работы пользователя

- Итерационный: показывает видео → даёт фидбек → правим → новый рендер.
  Рендер занимает ~2 мин, экстракция кадров через ffmpeg для отладки.
- Предпочитает русские описания тестов с контекстом бага.
- Хочет культуру тестирования — добавлять тесты на каждый фикс.
- Все коммиты — по-русски, conventional commits, ветки + PR.
- Не мерджит PR сам — только через GitHub UI после ревью.
