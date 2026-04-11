#!/usr/bin/env python3
"""
render_svg.py

Reads /tmp/timeline.json and produces /tmp/loc_chart.svg —
a stacked bar chart of lines added per week, coloured by language.

The SVG uses CSS custom properties so it renders correctly on both
GitHub's light and dark themes without JavaScript.
"""

import json
import math
from pathlib import Path
from datetime import datetime

INPUT_FILE  = Path("/tmp/timeline.json")
OUTPUT_FILE = Path("/tmp/loc_chart.svg")

# ── Palette (works on both light/dark backgrounds) ───────────────────────────
LANG_COLORS: dict[str, str] = {
    "Python":     "#3572A5",
    "TypeScript": "#3178C6",
    "JavaScript": "#F7DF1E",
    "HCL":        "#844FBA",
    "Shell":      "#89E051",
    "SQL":        "#E38C00",
    "Rust":       "#DEA584",
    "Go":         "#00ADD8",
    "Java":       "#B07219",
    "Kotlin":     "#A97BFF",
    "Jupyter":    "#DA5B0B",
    "C":          "#555555",
    "C++":        "#F34B7D",
    "Ruby":       "#CC342D",
    "Scala":      "#DC322F",
    "Other":      "#8B8B8B",
}
DEFAULT_COLOR = "#8B8B8B"


def fmt_week(iso_week: str) -> str:
    """'2024-W40' → 'W40' or 'Oct' at month boundaries."""
    try:
        year, week = iso_week.split("-W")
        # Find the Monday of this ISO week
        dt = datetime.strptime(f"{year}-W{int(week):02d}-1", "%G-W%V-%u")
        # Show month name on first week of month
        if dt.day <= 7:
            return dt.strftime("%b")
        return f"W{week}"
    except Exception:
        return iso_week


def abbreviate(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def render(data: dict) -> str:
    weeks     = data["weeks"]
    languages = data["languages"]
    series    = data["series"]
    totals    = data["totals"]
    generated = data.get("generated_at", "")[:10]

    n_weeks = len(weeks)
    if n_weeks == 0:
        return "<svg xmlns='http://www.w3.org/2000/svg'><text>No data</text></svg>"

    # ── Layout constants ──────────────────────────────────────────────────────
    WIDTH        = 860
    PAD_LEFT     = 52     # y-axis labels
    PAD_RIGHT    = 180    # legend
    PAD_TOP      = 44
    PAD_BOTTOM   = 36     # x-axis labels
    CHART_W      = WIDTH - PAD_LEFT - PAD_RIGHT
    CHART_H      = 200
    HEIGHT       = PAD_TOP + CHART_H + PAD_BOTTOM + 20  # +20 for subtitle

    BAR_GAP      = 2
    bar_w        = max(4, (CHART_W - BAR_GAP * n_weeks) / n_weeks)
    bar_step     = bar_w + BAR_GAP

    # ── Compute stacked max ───────────────────────────────────────────────────
    week_totals = [
        sum(series.get(lang, [0] * n_weeks)[i] for lang in languages)
        for i in range(n_weeks)
    ]
    max_val = max(week_totals) if week_totals else 1

    # Round max up to a nice number for y-axis
    magnitude = 10 ** math.floor(math.log10(max_val)) if max_val > 0 else 1
    nice_max  = math.ceil(max_val / magnitude) * magnitude

    def scale_y(v: int) -> float:
        return CHART_H - (v / nice_max) * CHART_H

    # ── SVG pieces ────────────────────────────────────────────────────────────
    bars_svg   = []
    xlabels    = []
    gridlines  = []

    # Grid lines (3 horizontal)
    for fraction in [0.25, 0.5, 0.75, 1.0]:
        val = int(nice_max * fraction)
        y   = PAD_TOP + scale_y(val)
        gridlines.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" '
            f'x2="{PAD_LEFT + CHART_W}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="1" stroke-dasharray="3,3"/>'
        )
        gridlines.append(
            f'<text x="{PAD_LEFT - 6}" y="{y + 4:.1f}" '
            f'text-anchor="end" font-size="10" fill="var(--muted)">'
            f'{abbreviate(val)}</text>'
        )

    # Bars
    prev_label = ""
    for i, week in enumerate(weeks):
        x        = PAD_LEFT + i * bar_step
        baseline = PAD_TOP + CHART_H
        stack    = 0

        for lang in reversed(languages):  # bottom-up stack
            val = series.get(lang, [0] * n_weeks)[i]
            if val == 0:
                continue
            bar_h = max(1, (val / nice_max) * CHART_H)
            y     = baseline - stack - bar_h
            color = LANG_COLORS.get(lang, DEFAULT_COLOR)
            bars_svg.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
                f'fill="{color}" opacity="0.9">'
                f'<title>{week}: {lang} +{val:,} lines</title>'
                f'</rect>'
            )
            stack += bar_h

        # X-axis labels — show month transitions + every 4th week label
        label = fmt_week(week)
        if label != prev_label and (label.isalpha() or i % 4 == 0):
            xval = x + bar_w / 2
            xlabels.append(
                f'<text x="{xval:.1f}" y="{PAD_TOP + CHART_H + 16}" '
                f'text-anchor="middle" font-size="10" fill="var(--muted)">'
                f'{label}</text>'
            )
            prev_label = label

    # Legend
    legend_items = []
    lx = PAD_LEFT + CHART_W + 16
    ly = PAD_TOP + 8
    for lang in languages:
        color = LANG_COLORS.get(lang, DEFAULT_COLOR)
        total = totals.get(lang, 0)
        legend_items.append(
            f'<rect x="{lx}" y="{ly}" width="10" height="10" fill="{color}" rx="2"/>'
            f'<text x="{lx + 14}" y="{ly + 9}" font-size="11" fill="var(--fg)">'
            f'{lang}</text>'
            f'<text x="{lx + 140}" y="{ly + 9}" font-size="10" '
            f'fill="var(--muted)" text-anchor="end">+{abbreviate(total)}</text>'
        )
        ly += 18

    total_all = sum(totals.values())
    legend_items.append(
        f'<text x="{lx}" y="{ly + 12}" font-size="10" fill="var(--muted)">'
        f'Total: +{total_all:,} lines</text>'
    )

    # Axis frame
    axis = (
        f'<line x1="{PAD_LEFT}" y1="{PAD_TOP}" '
        f'x2="{PAD_LEFT}" y2="{PAD_TOP + CHART_H}" '
        f'stroke="var(--border)" stroke-width="1"/>'
        f'<line x1="{PAD_LEFT}" y1="{PAD_TOP + CHART_H}" '
        f'x2="{PAD_LEFT + CHART_W}" y2="{PAD_TOP + CHART_H}" '
        f'stroke="var(--border)" stroke-width="1"/>'
    )

    # Title + subtitle
    title_y    = PAD_TOP - 18
    subtitle_y = HEIGHT - 6
    period     = f"{weeks[0]} → {weeks[-1]}"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {WIDTH} {HEIGHT}"
     width="{WIDTH}" height="{HEIGHT}"
     role="img" aria-label="Lines of code written per week by language">

  <defs>
    <style>
      :root {{
        --bg:     #ffffff;
        --fg:     #24292f;
        --muted:  #8b949e;
        --border: #d0d7de;
        --grid:   #eaeef2;
      }}
      @media (prefers-color-scheme: dark) {{
        :root {{
          --bg:     #0d1117;
          --fg:     #e6edf3;
          --muted:  #7d8590;
          --border: #30363d;
          --grid:   #21262d;
        }}
      }}
      text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                           "Noto Sans", Helvetica, Arial, sans-serif; }}
    </style>
  </defs>

  <rect width="{WIDTH}" height="{HEIGHT}" fill="var(--bg)" rx="6"/>

  <!-- Title -->
  <text x="{PAD_LEFT}" y="{title_y}"
        font-size="13" font-weight="600" fill="var(--fg)">
    Lines written — last 26 weeks
  </text>
  <text x="{PAD_LEFT}" y="{title_y + 14}"
        font-size="10" fill="var(--muted)">{period}</text>

  <!-- Grid -->
  {"".join(gridlines)}

  <!-- Bars -->
  {"".join(bars_svg)}

  <!-- Axes -->
  {axis}

  <!-- X labels -->
  {"".join(xlabels)}

  <!-- Legend -->
  {"".join(legend_items)}

  <!-- Footer -->
  <text x="{PAD_LEFT}" y="{subtitle_y}"
        font-size="9" fill="var(--muted)">
    Generated {generated} · git diff-tree --numstat · GHE private repos
  </text>
</svg>"""

    return svg


def main():
    if not INPUT_FILE.exists():
        raise SystemExit(f"[render_svg] {INPUT_FILE} not found")

    data = json.loads(INPUT_FILE.read_text())
    svg  = render(data)
    OUTPUT_FILE.write_text(svg)
    print(f"[render_svg] SVG written → {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
