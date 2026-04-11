from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import pandas as pd
import plotly.graph_objects as go


@dataclass
class EventFrame:
    timestamp: datetime
    counts: dict[str, int]


def build_event_frames(
    df: pd.DataFrame,
    since: datetime | None = None,
    until: datetime | None = None,
    max_frames: int | None = None,
) -> list[EventFrame]:
    """One frame per message event — cumulative counts as of that message's timestamp.

    If max_frames is set and we have more events, we downsample (keeping the last event
    so the final state is exact).
    """
    if df.empty:
        return []

    work = df.sort_values("date").reset_index(drop=True)
    if since is not None:
        work = work[work["date"] >= since]
    if until is not None:
        work = work[work["date"] <= until]
    if work.empty:
        return []

    counts: dict[str, int] = {}
    frames: list[EventFrame] = []
    name_col = "display_name" if "display_name" in work.columns else "topic_title"
    for _, row in work.iterrows():
        topic = row[name_col]
        counts[topic] = counts.get(topic, 0) + 1
        frames.append(EventFrame(timestamp=row["date"].to_pydatetime(), counts=dict(counts)))

    if max_frames and len(frames) > max_frames:
        step = max(1, len(frames) // max_frames)
        downsampled = frames[::step]
        if downsampled[-1] is not frames[-1]:
            downsampled.append(frames[-1])
        frames = downsampled

    return frames


_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
    "#5254a3", "#8ca252", "#bd9e39", "#ad494a", "#a55194",
]


def _topic_colors(topics: Sequence[str]) -> dict[str, str]:
    return {t: _PALETTE[i % len(_PALETTE)] for i, t in enumerate(topics)}


def _subsample(items: list, max_n: int):
    if len(items) <= max_n:
        return items
    step = max(1, len(items) // max_n)
    return items[::step]


def make_plotly_race(
    frames: list[EventFrame],
    top_n: int = 15,
    frame_ms: int = 120,
    transition_ms: int = 100,
    title: str = "Топики — гонка популярности",
) -> go.Figure:
    if not frames:
        return go.Figure()

    # Cumulative counts → final counts == peak counts. Pick the top-N topics to track
    # across the whole animation; these form a fixed y-axis category set.
    final_counts = frames[-1].counts
    tracked: list[str] = [
        t for t, _ in sorted(final_counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    ]
    if not tracked:
        return go.Figure()

    colors = _topic_colors(tracked)
    bar_colors = [colors[t] for t in tracked]

    max_x = max(final_counts[t] for t in tracked)
    x_range = [0, max(1, max_x) * 1.15]

    def values_for(f: EventFrame) -> list[int]:
        return [int(f.counts.get(t, 0)) for t in tracked]

    init_values = values_for(frames[0])

    bar_trace = go.Bar(
        x=init_values,
        y=tracked,
        orientation="h",
        marker=dict(color=bar_colors),
        text=[str(v) if v > 0 else "" for v in init_values],
        textposition="outside",
        texttemplate="%{text}",
        cliponaxis=False,
        hovertemplate="%{y}: %{x}<extra></extra>",
    )

    plotly_frames: list[go.Frame] = []
    for f in frames:
        values = values_for(f)
        plotly_frames.append(
            go.Frame(
                data=[
                    go.Bar(
                        x=values,
                        y=tracked,
                        orientation="h",
                        marker=dict(color=bar_colors),
                        text=[str(v) if v > 0 else "" for v in values],
                        textposition="outside",
                    )
                ],
                layout=go.Layout(
                    title=dict(
                        text=f"{title}  •  {f.timestamp.strftime('%Y-%m-%d %H:%M')}"
                    )
                ),
                name=f.timestamp.isoformat(),
            )
        )

    slider_steps = [
        dict(
            method="animate",
            label=f.timestamp.strftime("%y-%m-%d"),
            args=[
                [f.timestamp.isoformat()],
                dict(
                    frame=dict(duration=0, redraw=True),
                    transition=dict(duration=0),
                    mode="immediate",
                ),
            ],
        )
        for f in _subsample(frames, 40)
    ]

    fig = go.Figure(
        data=[bar_trace],
        layout=go.Layout(
            title=dict(
                text=f"{title}  •  {frames[0].timestamp.strftime('%Y-%m-%d %H:%M')}"
            ),
            xaxis=dict(range=x_range, title="Сообщений"),
            yaxis=dict(
                categoryorder="total ascending",
                automargin=True,
            ),
            height=max(520, 36 * top_n + 160),
            margin=dict(l=10, r=140, t=100, b=60),
            showlegend=False,
            updatemenus=[
                dict(
                    type="buttons",
                    direction="left",
                    x=0,
                    y=1.08,
                    xanchor="left",
                    yanchor="bottom",
                    pad=dict(t=0, r=10),
                    showactive=False,
                    buttons=[
                        dict(
                            label="▶ Play",
                            method="animate",
                            args=[
                                None,
                                dict(
                                    frame=dict(duration=frame_ms, redraw=True),
                                    transition=dict(duration=transition_ms, easing="linear"),
                                    fromcurrent=True,
                                    mode="immediate",
                                ),
                            ],
                        ),
                        dict(
                            label="⏸ Pause",
                            method="animate",
                            args=[
                                [None],
                                dict(
                                    frame=dict(duration=0, redraw=False),
                                    transition=dict(duration=0),
                                    mode="immediate",
                                ),
                            ],
                        ),
                    ],
                )
            ],
            sliders=[
                dict(
                    active=0,
                    x=0.15,
                    y=1.08,
                    xanchor="left",
                    yanchor="bottom",
                    len=0.85,
                    pad=dict(t=0, b=0),
                    currentvalue=dict(visible=False),
                    steps=slider_steps,
                )
            ],
        ),
        frames=plotly_frames,
    )
    return fig
