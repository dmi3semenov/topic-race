from __future__ import annotations

from pathlib import Path

import bar_chart_race as bcr
import pandas as pd

from .config import OUT_DIR


def render_race(
    df: pd.DataFrame,
    filename: str = "topic_race.mp4",
    n_bars: int = 10,
    steps_per_period: int = 10,
    period_length_ms: int = 500,
    title: str = "Топики — гонка популярности",
) -> Path:
    if df.empty:
        raise ValueError("Empty dataframe — nothing to render")

    out_path = OUT_DIR / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bcr.bar_chart_race(
        df=df,
        filename=str(out_path),
        orientation="h",
        sort="desc",
        n_bars=n_bars,
        fixed_order=False,
        fixed_max=False,
        steps_per_period=steps_per_period,
        period_length=period_length_ms,
        interpolate_period=True,
        label_bars=True,
        bar_size=0.85,
        period_label={"x": 0.99, "y": 0.25, "ha": "right", "va": "center"},
        period_fmt="%Y-%m-%d",
        title=title,
        title_size=16,
        bar_label_size=10,
        tick_label_size=10,
        shared_fontdict={"family": "DejaVu Sans"},
        scale="linear",
        fig=None,
        writer="ffmpeg",
        dpi=144,
        cmap="tab20",
        filter_column_colors=True,
    )
    return out_path
