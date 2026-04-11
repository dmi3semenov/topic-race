"""D3.js-based bar chart race renderer. Returns an HTML string embeddable in Streamlit."""
from __future__ import annotations

import json
from typing import Sequence

from .animate import EventFrame


_PALETTE = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac",
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173",
]


def _frames_to_payload(frames: Sequence[EventFrame]) -> list[dict]:
    return [
        {"t": f.timestamp.isoformat(), "counts": {k: int(v) for k, v in f.counts.items()}}
        for f in frames
    ]


def _build_color_map(frames: Sequence[EventFrame]) -> dict[str, str]:
    """Assign stable colors to topics, ordered by final count (leaders get palette top)."""
    if not frames:
        return {}
    final = frames[-1].counts
    ordered = sorted(final.keys(), key=lambda t: final[t], reverse=True)
    return {t: _PALETTE[i % len(_PALETTE)] for i, t in enumerate(ordered)}


def make_d3_race_html(
    frames: Sequence[EventFrame],
    top_n: int = 15,
    frame_ms: int = 120,
    transition_ms: int = 120,
    bar_height: int = 36,
    title: str = "Топики — гонка популярности",
    subtitle: str | Sequence[str] = "",
    layout: str = "landscape",
    hide_controls: bool = False,
    autoplay: bool = False,
    frame_durations: Sequence[int] | None = None,
    intro_lines: Sequence[str] | None = None,
    intro_duration_ms: int = 4000,
) -> tuple[str, int]:
    """Return (html, height_px). height_px is what to pass to st.components.v1.html.

    layout: "landscape" (default, for the Streamlit dashboard) or "vertical"
            (9:16, for Reels/Shorts rendering).
    hide_controls: hide the Play/Pause toolbar — useful for recording.
    autoplay: start animation automatically on load — for recording.
    """
    payload = {
        "frames": _frames_to_payload(frames),
        "colors": _build_color_map(frames),
        "top_n": top_n,
        "frame_ms": frame_ms,
        "transition_ms": transition_ms,
        "bar_height": bar_height,
        "title": title,
        "subtitle": list(subtitle) if isinstance(subtitle, (list, tuple)) else subtitle,
        "layout": layout,
        "hide_controls": hide_controls,
        "autoplay": autoplay,
        "frame_durations": list(frame_durations) if frame_durations else None,
        "intro_lines": list(intro_lines) if intro_lines else None,
        "intro_duration_ms": intro_duration_ms,
    }
    # Escape `</script` and `</style` so user-provided text inside JSON can't
    # break out of the embedding <script> block.
    data_json = (
        json.dumps(payload, ensure_ascii=False)
        .replace("</script", "<\\/script")
        .replace("</style", "<\\/style")
    )

    if layout == "vertical":
        height_px = 1920
    else:
        height_px = 80 + 50 + bar_height * top_n + 80

    # Body classes affect initial paint (intro visible from first frame, race hidden).
    body_classes: list[str] = []
    if layout == "vertical":
        body_classes.append("vertical")
    if hide_controls:
        body_classes.append("hide-controls")
    if intro_lines:
        body_classes.append("has-intro")

    intro_html = ""
    if intro_lines:
        parts = []
        for i, line in enumerate(intro_lines):
            safe = (
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            parts.append(f'<div class="line l{i}">{safe}</div>')
        intro_html = "\n".join(parts)

    html = (
        _TEMPLATE
        .replace("__DATA_JSON__", data_json)
        .replace("__HEIGHT__", str(height_px))
        .replace("__BODY_CLASS__", " ".join(body_classes))
        .replace("__INTRO_CONTENT__", intro_html)
    )
    return html, height_px


_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html, body {
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #ffffff;
    color: #222;
  }
  .controls {
    padding: 10px 12px;
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid #eee;
  }
  .controls button {
    padding: 6px 14px;
    font-size: 14px;
    border: 1px solid #d0d0d0;
    background: #f7f7f7;
    border-radius: 6px;
    cursor: pointer;
  }
  .controls button:hover { background: #ececec; }
  .controls input[type=range] { flex: 1; }
  .controls .progress { font-size: 13px; color: #666; min-width: 120px; text-align: right; font-variant-numeric: tabular-nums; }
  .chart-wrap { padding: 10px 12px 4px 12px; }
  svg { display: block; }
  .bar-label { font-size: 14px; fill: #222; font-weight: 600; }
  .bar-value { font-size: 14px; fill: #222; font-variant-numeric: tabular-nums; font-weight: 700; }
  .date-big { font-size: 48px; font-weight: 800; fill: #d4d4d4; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
  .axis text { font-size: 11px; fill: #888; }
  .axis path, .axis line { stroke: #e5e5e5; }
  .title { font-size: 16px; fill: #333; font-weight: 700; }
  /* Vertical mode (9:16) — bigger fonts, no padding, bars fill the viewport */
  body.vertical .chart-wrap { padding: 0; }
  body.vertical .bar-label { font-size: 26px; }
  body.vertical .bar-value { font-size: 26px; }
  body.vertical .date-big { font-size: 120px; }
  body.vertical .axis text { font-size: 22px; }
  body.vertical .title { font-size: 36px; }
  body.hide-controls .controls { display: none; }

  /* Intro overlay */
  #intro {
    position: fixed;
    inset: 0;
    display: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #ffffff;
    z-index: 10;
    padding: 60px 40px;
    text-align: center;
    transition: opacity 0.7s ease-out;
  }
  /* If the page is configured with intro, show it immediately (no flash of
     the race before the intro kicks in). Also hide the race until done. */
  body.has-intro #intro { display: flex; }
  body.has-intro .chart-wrap { visibility: hidden; }
  body.has-intro.intro-done .chart-wrap { visibility: visible; }
  body.has-intro.intro-done #intro { display: none; }
  #intro.fade-out { opacity: 0; }
  #intro .line {
    opacity: 0;
    transform: translateY(16px);
    transition: opacity 0.6s ease-out, transform 0.6s ease-out;
    color: #1a1a1a;
    line-height: 1.2;
  }
  #intro .line.show { opacity: 1; transform: translateY(0); }
  #intro .line.l0 { font-size: 110px; font-weight: 800; letter-spacing: -0.03em; margin-bottom: 18px; }
  #intro .line.l1 { font-size: 38px; font-weight: 500; color: #777; margin-bottom: 64px; }
  #intro .line.l2 { font-size: 56px; font-weight: 700; color: #1a1a1a; margin-bottom: 56px; }
  #intro .line.l3 { font-size: 34px; font-weight: 500; color: #999; }
  /* Landscape intro is smaller */
  body:not(.vertical) #intro { padding: 20px; }
  body:not(.vertical) #intro .line.l0 { font-size: 42px; margin-bottom: 8px; }
  body:not(.vertical) #intro .line.l1 { font-size: 16px; margin-bottom: 24px; }
  body:not(.vertical) #intro .line.l2 { font-size: 24px; margin-bottom: 20px; }
  body:not(.vertical) #intro .line.l3 { font-size: 14px; }

  /* Subtitle under the main title */
  .subtitle { font-size: 13px; fill: #888; font-weight: 500; }
  body.vertical .subtitle { font-size: 30px; font-weight: 500; }
</style>
</head>
<body class="__BODY_CLASS__">
<div class="controls">
  <button id="play">▶ Play</button>
  <button id="pause">⏸ Pause</button>
  <button id="reset">⏮ Reset</button>
  <input type="range" id="slider" min="0" max="0" value="0" />
  <span class="progress" id="progress">0 / 0</span>
  <label style="font-size:12px;color:#666;">скорость
    <select id="speed" style="margin-left:4px;">
      <option value="0.5">0.5x</option>
      <option value="1" selected>1x</option>
      <option value="2">2x</option>
      <option value="4">4x</option>
      <option value="8">8x</option>
    </select>
  </label>
</div>
<div id="intro">__INTRO_CONTENT__</div>
<div class="chart-wrap"><svg id="chart"></svg></div>

<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const DATA = __DATA_JSON__;
const TOP_N = DATA.top_n;
const BASE_FRAME_MS = DATA.frame_ms;
const BASE_TRANSITION_MS = DATA.transition_ms;
const IS_VERTICAL = DATA.layout === "vertical";

// Body classes are already set from Python so first paint is correct;
// keep the JS add() as a fallback.
if (IS_VERTICAL && !document.body.classList.contains("vertical")) {
  document.body.classList.add("vertical");
}
if (DATA.hide_controls && !document.body.classList.contains("hide-controls")) {
  document.body.classList.add("hide-controls");
}

const margin = IS_VERTICAL
  ? {top: 240, right: 140, bottom: 80, left: 320}
  : {top: 44, right: 140, bottom: 24, left: 220};
const barPadding = IS_VERTICAL ? 14 : 6;

function getWidth() {
  if (IS_VERTICAL) return window.innerWidth;
  return Math.max(600, document.documentElement.clientWidth - 24);
}
function getHeight() {
  if (IS_VERTICAL) return window.innerHeight;
  return margin.top + (DATA.bar_height + barPadding) * TOP_N + margin.bottom;
}

let width = getWidth();
let height = getHeight();
// Compute bar height so all TOP_N bars fill the available area (vertical mode),
// or honor the configured bar_height (landscape mode).
let BAR_H = IS_VERTICAL
  ? Math.max(20, Math.floor((height - margin.top - margin.bottom) / TOP_N) - barPadding)
  : DATA.bar_height;
let totalBarH = BAR_H + barPadding;
let innerHeight = totalBarH * TOP_N;

const svg = d3.select("#chart")
  .attr("width", width)
  .attr("height", height);

const xScale = d3.scaleLinear().range([margin.left, width - margin.right]);
// Start with a small domain; we expand it per-frame to the current leader * 1.1
xScale.domain([0, 1]);

// Title
svg.append("text")
  .attr("class", "title")
  .attr("x", margin.left)
  .attr("y", IS_VERTICAL ? 80 : 20)
  .text(DATA.title);

// Subtitle under title — accepts either a string or an array of lines.
if (DATA.subtitle) {
  const subtitleLines = Array.isArray(DATA.subtitle) ? DATA.subtitle : [DATA.subtitle];
  const lineH = IS_VERTICAL ? 44 : 16;
  const startY = IS_VERTICAL ? 140 : 38;
  subtitleLines.forEach((line, i) => {
    svg.append("text")
      .attr("class", "subtitle")
      .attr("x", margin.left)
      .attr("y", startY + i * lineH)
      .text(line);
  });
}

// Big date label, bottom-right
const dateLabel = svg.append("text")
  .attr("class", "date-big")
  .attr("x", width - margin.right - 8)
  .attr("y", IS_VERTICAL ? (height - 30) : (margin.top + innerHeight - 10))
  .attr("text-anchor", "end")
  .text("");

// Grid layer (under bars)
const gridG = svg.append("g").attr("class", "grid");

// Top axis
const xAxisG = svg.append("g")
  .attr("class", "axis")
  .attr("transform", `translate(0, ${margin.top - 4})`);

// Bar groups container (above grid)
const barsG = svg.append("g").attr("class", "bars");

// Keyed data join: each bar-group is keyed by topic name
function topicsForFrame(idx) {
  const frame = DATA.frames[idx];
  const entries = Object.entries(frame.counts)
    .map(([name, value]) => ({name, value}))
    .sort((a, b) => b.value - a.value || a.name.localeCompare(b.name))
    .slice(0, TOP_N);
  return entries.map((d, i) => ({...d, rank: i}));
}

function yForRank(rank) {
  return margin.top + rank * totalBarH;
}

let currentIdx = 0;

function renderFrame(idx, dur) {
  const topics = topicsForFrame(idx);
  const frame = DATA.frames[idx];

  // Dynamic x-domain: leader's value (with headroom)
  const leader = topics.length > 0 ? topics[0].value : 1;
  xScale.domain([0, Math.max(1, leader) * 1.12]);

  const t = d3.transition().duration(dur).ease(d3.easeLinear);

  // Axis + grid transition
  xAxisG.transition(t).call(
    d3.axisTop(xScale)
      .ticks(Math.max(3, Math.floor((width - margin.left - margin.right) / 90)))
      .tickSizeOuter(0)
  );

  gridG.selectAll("line")
    .data(xScale.ticks(6))
    .join(
      enter => enter.append("line")
        .attr("stroke", "#eee")
        .attr("y1", margin.top - 4)
        .attr("y2", margin.top + innerHeight)
        .attr("x1", d => xScale(d))
        .attr("x2", d => xScale(d)),
      update => update.call(u => u.transition(t)
        .attr("x1", d => xScale(d))
        .attr("x2", d => xScale(d))),
      exit => exit.remove()
    );

  // Bars
  barsG.selectAll("g.bar-group")
    .data(topics, d => d.name)
    .join(
      enter => {
        const g = enter.append("g")
          .attr("class", "bar-group")
          // Enter from below the visible rank area — classic Bostock slide-in
          .attr("transform", `translate(0, ${yForRank(TOP_N)})`)
          .attr("opacity", 0);
        g.append("rect")
          .attr("class", "bar")
          .attr("x", margin.left)
          .attr("y", 0)
          .attr("height", BAR_H)
          .attr("width", d => Math.max(0, xScale(d.value) - margin.left))
          .attr("rx", 4)
          .attr("fill", d => DATA.colors[d.name] || "#999");
        g.append("text")
          .attr("class", "bar-label")
          .attr("x", margin.left - 8)
          .attr("y", BAR_H / 2)
          .attr("dy", "0.35em")
          .attr("text-anchor", "end")
          .text(d => d.name);
        g.append("text")
          .attr("class", "bar-value")
          .attr("x", d => xScale(d.value) + 6)
          .attr("y", BAR_H / 2)
          .attr("dy", "0.35em")
          .text(d => d.value);
        return g;
      },
      update => update,
      exit => exit.call(ex => ex.transition(t)
        .attr("opacity", 0)
        .attr("transform", `translate(0, ${yForRank(TOP_N)})`)
        .remove())
    )
    .call(merged => {
      merged.transition(t)
        .attr("transform", d => `translate(0, ${yForRank(d.rank)})`)
        .attr("opacity", 1);

      merged.select("rect.bar").transition(t)
        .attr("width", d => Math.max(0, xScale(d.value) - margin.left));

      merged.select("text.bar-value").transition(t)
        .attrTween("x", function(d) {
          const prevX = +this.getAttribute("x") || margin.left + 6;
          const nextX = xScale(d.value) + 6;
          return d3.interpolateNumber(prevX, nextX);
        })
        .tween("text", function(d) {
          const self = this;
          const start = parseInt(self.textContent) || 0;
          const end = d.value;
          const interp = d3.interpolateRound(start, end);
          return tt => { self.textContent = interp(tt); };
        });
    });

  // Date label
  const dObj = new Date(frame.t);
  const dateStr = dObj.getFullYear() + "-" +
    String(dObj.getMonth() + 1).padStart(2, "0") + "-" +
    String(dObj.getDate()).padStart(2, "0");
  dateLabel.text(dateStr);

  // Progress
  document.getElementById("slider").value = idx;
  document.getElementById("progress").textContent = (idx + 1) + " / " + DATA.frames.length;
  currentIdx = idx;
}

// Controls
let playing = false;
let playTimer = null;
let speed = 1;

function baseFrameMsAt(idx) {
  if (DATA.frame_durations && DATA.frame_durations.length > idx) {
    return DATA.frame_durations[idx];
  }
  return BASE_FRAME_MS;
}
function effectiveFrameMs() { return Math.max(20, baseFrameMsAt(currentIdx) / speed); }
function effectiveTransitionMs() { return Math.max(20, baseFrameMsAt(currentIdx) / speed); }

function playLoop() {
  if (!playing) return;
  if (currentIdx >= DATA.frames.length - 1) { playing = false; return; }
  renderFrame(currentIdx + 1, effectiveTransitionMs());
  playTimer = setTimeout(playLoop, effectiveFrameMs());
}

document.getElementById("play").onclick = () => {
  if (playing) return;
  if (currentIdx >= DATA.frames.length - 1) {
    renderFrame(0, 0);
  }
  playing = true;
  playLoop();
};

document.getElementById("pause").onclick = () => {
  playing = false;
  clearTimeout(playTimer);
};

document.getElementById("reset").onclick = () => {
  playing = false;
  clearTimeout(playTimer);
  renderFrame(0, 0);
};

document.getElementById("slider").max = DATA.frames.length - 1;
document.getElementById("slider").oninput = (e) => {
  playing = false;
  clearTimeout(playTimer);
  renderFrame(+e.target.value, 0);
};

document.getElementById("speed").onchange = (e) => {
  speed = parseFloat(e.target.value);
};

// Resize handling
window.addEventListener("resize", () => {
  width = getWidth();
  height = getHeight();
  BAR_H = IS_VERTICAL
    ? Math.max(20, Math.floor((height - margin.top - margin.bottom) / TOP_N) - barPadding)
    : DATA.bar_height;
  totalBarH = BAR_H + barPadding;
  innerHeight = totalBarH * TOP_N;
  svg.attr("width", width).attr("height", height);
  xScale.range([margin.left, width - margin.right]);
  dateLabel.attr("x", width - margin.right - 8)
    .attr("y", IS_VERTICAL ? (height - 30) : (margin.top + innerHeight - 10));
  renderFrame(currentIdx, 0);
});

// Initial
renderFrame(0, 0);

// ----- Intro overlay animation -----
// Intro HTML is already rendered server-side and visible from first paint
// (body.has-intro CSS). We animate lines in, wait, then fade out and reveal
// the race. Chart stays `visibility: hidden` via CSS until we flip the flag.
function playIntro() {
  const root = document.getElementById("intro");
  if (!root || !DATA.intro_lines || DATA.intro_lines.length === 0) {
    return Promise.resolve();
  }
  const lines = root.querySelectorAll(".line");
  const dur = DATA.intro_duration_ms || 4000;
  const perLine = Math.min(600, Math.floor(dur / (lines.length + 1)));
  return new Promise(resolve => {
    lines.forEach((el, i) => {
      setTimeout(() => el.classList.add("show"), perLine * (i + 0.2));
    });
    setTimeout(() => {
      root.classList.add("fade-out");
      setTimeout(() => {
        document.body.classList.add("intro-done");
        resolve();
      }, 700);
    }, dur);
  });
}

function startAutoPlay() {
  window.__animationDone = false;
  playing = true;
  (function loopAuto() {
    if (!playing) return;
    if (currentIdx >= DATA.frames.length - 1) {
      window.__animationDone = true;
      playing = false;
      return;
    }
    renderFrame(currentIdx + 1, effectiveTransitionMs());
    playTimer = setTimeout(loopAuto, effectiveFrameMs());
  })();
}

if (DATA.autoplay) {
  // No artificial delay — intro is already on screen from first paint.
  (async () => {
    await playIntro();
    startAutoPlay();
  })();
}
</script>
</body>
</html>
"""
