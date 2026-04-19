#!/usr/bin/env python3
"""
render_svg.py

Reads /tmp/timeline.json and produces assets/loc_chart.svg —
a premium, modern GitHub profile activity visualization.

Layout:
  ┌─ Header ──────────────────────────────────────────┐
  │  ● DEVELOPER ACTIVITY           Period right-aligned
  ├─ KPI strip (4 metrics) ───────────────────────────┤
  ├─ Weekly activity chart (stacked, gradient bars) ──┤
  ├─ Language breakdown (ranked bars) ────────────────┤
  └─ Footer (source, timestamp) ──────────────────────┘

The SVG is self-contained: CSS custom properties + prefers-color-scheme
adapt it to GitHub light/dark themes without any JavaScript.
"""

import json
import math
from datetime import datetime
from pathlib import Path

INPUT_FILE  = Path("/tmp/timeline.json")
OUTPUT_FILE = Path("assets/loc_chart.svg")

# ── Palette ───────────────────────────────────────────────────────────────────
# Each entry is (base_color, gradient_top_color) — gradient_top is rendered at
# the top of each stacked bar so bars look lit from above.
LANG_COLORS: dict[str, tuple[str, str]] = {
    "Python":     ("#3776AB", "#5497D4"),
    "TypeScript": ("#3178C6", "#5198E8"),
    "JavaScript": ("#E9B824", "#F7DF1E"),
    "HCL":        ("#6366F1", "#8B8EF7"),
    "Shell":      ("#22C55E", "#4ADE80"),
    "SQL":        ("#F59E0B", "#FBBF24"),
    "Rust":       ("#F97316", "#FB9A4A"),
    "Go":         ("#06B6D4", "#38D3E8"),
    "Java":       ("#B07219", "#D4A05F"),
    "Kotlin":     ("#A855F7", "#C084FC"),
    "Jupyter":    ("#DA5B0B", "#FF7F3F"),
    "C":          ("#64748B", "#94A3B8"),
    "C++":        ("#F34B7D", "#FF75A1"),
    "Ruby":       ("#EF4444", "#F87171"),
    "Scala":      ("#DC322F", "#F14C4A"),
    "JSON":       ("#14B8A6", "#2DD4BF"),
    "Markdown":   ("#8B5CF6", "#A78BFA"),
    "YAML":       ("#EC4899", "#F472B6"),
    "TOML":       ("#9C4221", "#BE5D3A"),
    "CSS":        ("#563D7C", "#7A58A8"),
    "HTML":       ("#E34C26", "#F76E4A"),
    "Text":       ("#94A3B8", "#CBD5E1"),
    "Other":      ("#6B7280", "#9CA3AF"),
}
DEFAULT_COLOR = ("#6B7280", "#9CA3AF")


def color_for(lang: str) -> tuple[str, str]:
    return LANG_COLORS.get(lang, DEFAULT_COLOR)


# ── Helpers ───────────────────────────────────────────────────────────────────
def iso_to_date(iso_week: str):
    try:
        year, week = iso_week.split("-W")
        return datetime.strptime(f"{year}-W{int(week):02d}-1", "%G-W%V-%u")
    except Exception:
        return None


def abbrev(n: int, precision: int = 1) -> str:
    """Compact number: 1,234 → '1.2k', 1_234_567 → '1.2M'."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.{precision}f}M".replace(".0M", "M")
    if n >= 10_000:
        return f"{n/1_000:.0f}k"
    if n >= 1_000:
        return f"{n/1_000:.{precision}f}k".replace(".0k", "k")
    return str(n)


def rounded_top_rect(x: float, y: float, w: float, h: float, r: float) -> str:
    """Path for a rect with only the top two corners rounded."""
    r = min(r, w / 2, h)
    if r <= 0 or h <= 0:
        return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"/>'
    return (
        f'<path d="M {x:.2f},{y+h:.2f} '
        f'V {y+r:.2f} '
        f'Q {x:.2f},{y:.2f} {x+r:.2f},{y:.2f} '
        f'H {x+w-r:.2f} '
        f'Q {x+w:.2f},{y:.2f} {x+w:.2f},{y+r:.2f} '
        f'V {y+h:.2f} Z"/>'
    )


# ── Stats computation ─────────────────────────────────────────────────────────
def compute_stats(data: dict) -> dict:
    weeks     = data["weeks"]
    languages = data["languages"]
    series    = data["series"]
    totals    = data["totals"]

    n_weeks = len(weeks)
    week_totals = [
        sum(series.get(lang, [0] * n_weeks)[i] for lang in languages)
        for i in range(n_weeks)
    ]
    total_all = sum(totals.values())
    active = sum(1 for t in week_totals if t > 0)

    peak_idx = max(range(n_weeks), key=lambda i: week_totals[i]) if week_totals else 0
    peak_week = weeks[peak_idx] if weeks else ""
    peak_dt = iso_to_date(peak_week)
    peak_label = f"{peak_dt.strftime('%b')} {peak_dt.day}" if peak_dt else peak_week
    peak_val = week_totals[peak_idx] if week_totals else 0

    top_lang = languages[0] if languages else "—"
    top_lang_pct = (totals.get(top_lang, 0) / total_all * 100) if total_all else 0

    avg = total_all // max(1, n_weeks)

    return {
        "total": total_all,
        "top_lang": top_lang,
        "top_lang_pct": top_lang_pct,
        "peak_val": peak_val,
        "peak_label": peak_label,
        "avg": avg,
        "active": active,
        "n_weeks": n_weeks,
        "n_langs": len(languages),
        "week_totals": week_totals,
    }


# ── Renderer ──────────────────────────────────────────────────────────────────
def render(data: dict) -> str:
    weeks     = data["weeks"]
    languages = data["languages"]
    series    = data["series"]
    totals    = data["totals"]
    generated = data.get("generated_at", "")[:10]
    stats     = compute_stats(data)

    n_weeks = len(weeks)
    if n_weeks == 0:
        return "<svg xmlns='http://www.w3.org/2000/svg'><text>No data</text></svg>"

    # ── Canvas ────────────────────────────────────────────────────────────────
    W           = 960
    H           = 580
    PAD         = 28

    # ── Header ────────────────────────────────────────────────────────────────
    HEADER_Y    = 40

    # ── KPI strip (4 cards) ───────────────────────────────────────────────────
    KPI_Y       = 72
    KPI_H       = 96
    KPI_N       = 4
    KPI_GAP     = 14
    KPI_W       = (W - 2 * PAD - (KPI_N - 1) * KPI_GAP) / KPI_N

    # ── Chart ─────────────────────────────────────────────────────────────────
    CHART_TOP      = 208  # section title sits at CHART_TOP - 12
    CHART_AXIS_W   = 40
    CHART_LEFT     = PAD + CHART_AXIS_W
    CHART_RIGHT    = W - PAD
    CHART_W        = CHART_RIGHT - CHART_LEFT
    CHART_H        = 176
    CHART_BOTTOM   = CHART_TOP + CHART_H

    BAR_GAP  = 3
    bar_w    = max(4, (CHART_W - BAR_GAP * n_weeks) / n_weeks)
    bar_step = bar_w + BAR_GAP

    # Stacked maximum + nice rounded y-axis.
    # If one week is a huge outlier (e.g. initial bulk import), cap the axis
    # at a readable scale and mark the clipped bar with a ↑ indicator so the
    # rest of the history stays legible.
    week_totals = stats["week_totals"]
    sorted_totals = sorted(week_totals, reverse=True)
    max_val = sorted_totals[0] if sorted_totals else 1
    second  = sorted_totals[1] if len(sorted_totals) > 1 else max_val
    # Outlier rule: max is > 2.5× second → cap at ~1.15× second
    clipped_week_idx: int | None = None
    clipped_week_val: int | None = None
    if max_val > 2.5 * max(second, 1):
        cap_raw = int(second * 1.15)
        clipped_week_idx = week_totals.index(max_val)
        clipped_week_val = max_val
    else:
        cap_raw = max_val

    magnitude = 10 ** math.floor(math.log10(cap_raw)) if cap_raw > 0 else 1
    nice_max = math.ceil(cap_raw / magnitude) * magnitude

    def y_of(v: float) -> float:
        return CHART_BOTTOM - (v / nice_max) * CHART_H

    # ── Language breakdown ────────────────────────────────────────────────────
    LB_TOP   = CHART_BOTTOM + 48           # section title at LB_TOP - 12
    LB_ROW_H = 20
    LB_COL_GAP = 40
    LB_COLS  = 2
    LB_COL_W = (W - 2 * PAD - (LB_COLS - 1) * LB_COL_GAP) / LB_COLS

    n_langs = len(languages)
    LB_ROWS_PER_COL = math.ceil(n_langs / LB_COLS)

    # ── Build SVG pieces ──────────────────────────────────────────────────────
    total_all = stats["total"]

    # Gradients — one per language
    gradient_defs = []
    for lang in languages:
        base, top = color_for(lang)
        gid = f"g-{lang.lower().replace('+','p').replace('#','s')}"
        gradient_defs.append(
            f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{top}" stop-opacity="1"/>'
            f'<stop offset="100%" stop-color="{base}" stop-opacity="1"/>'
            f'</linearGradient>'
        )
    # Soft card background gradient (also used for chart frame)
    gradient_defs.append(
        '<linearGradient id="card-bg" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="var(--card-top)"/>'
        '<stop offset="100%" stop-color="var(--card-bot)"/>'
        '</linearGradient>'
    )

    def grad_id(lang: str) -> str:
        return f"g-{lang.lower().replace('+','p').replace('#','s')}"

    # ─── Grid lines + y-axis labels ───────────────────────────────────────────
    grid = []
    for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
        val = int(nice_max * frac)
        y = y_of(val)
        dash = "" if frac == 0 else ' stroke-dasharray="2,4"'
        grid.append(
            f'<line x1="{CHART_LEFT}" y1="{y:.1f}" '
            f'x2="{CHART_RIGHT}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="1"{dash}/>'
        )
        if frac > 0:
            grid.append(
                f'<text x="{CHART_LEFT - 8}" y="{y + 3.5:.1f}" '
                f'text-anchor="end" class="axis">{abbrev(val)}</text>'
            )

    # ─── Bars (stacked, with rounded tops on topmost segment) ────────────────
    bars = []
    clip_overlay = []
    for i, week in enumerate(weeks):
        x = CHART_LEFT + i * bar_step
        base_y = CHART_BOTTOM
        is_clipped = (i == clipped_week_idx)
        week_total = week_totals[i]

        # For clipped weeks we scale segments down proportionally so the whole
        # stack exactly fills the chart height, then draw a chevron + label above.
        if is_clipped and week_total > 0:
            scale = (CHART_H * 0.94) / week_total   # leave a tiny headroom
        else:
            scale = CHART_H / nice_max if nice_max > 0 else 1

        segments = []
        for lang in reversed(languages):
            v = series.get(lang, [0] * n_weeks)[i]
            if v <= 0:
                continue
            h = max(1.2, v * scale)
            segments.append((lang, v, h))
        if not segments:
            continue

        stack = 0
        for idx, (lang, v, h) in enumerate(segments):
            y = base_y - stack - h
            is_top = (idx == len(segments) - 1)
            gid = grad_id(lang)
            title = f"<title>{week} · {lang}: +{v:,}</title>"
            if is_top:
                path = rounded_top_rect(x, y, bar_w, h, r=min(2.5, bar_w / 3))
                # inject fill + title
                if path.startswith("<rect"):
                    piece = path.replace(
                        "/>", f' fill="url(#{gid})">{title}</rect>', 1)
                else:
                    piece = path.replace(
                        'Z"/>', f'Z" fill="url(#{gid})">{title}</path>', 1)
                bars.append(piece)
            else:
                bars.append(
                    f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" '
                    f'height="{h:.2f}" fill="url(#{gid})">{title}</rect>'
                )
            stack += h

        # Chevron + label on the clipped bar
        if is_clipped:
            cx = x + bar_w / 2
            top_y = CHART_TOP
            # Upward chevron (two small lines forming ‹
            chev = (
                f'<path d="M {cx-5:.1f} {top_y+6} L {cx:.1f} {top_y+1} '
                f'L {cx+5:.1f} {top_y+6}" stroke="var(--fg)" '
                f'stroke-width="1.6" stroke-linecap="round" '
                f'stroke-linejoin="round" fill="none" opacity="0.85"/>'
            )
            clip_overlay.append(chev)
            clip_overlay.append(
                f'<text x="{cx:.1f}" y="{top_y - 4}" text-anchor="middle" '
                f'class="clip-label">+{abbrev(week_total)}</text>'
            )

    # ─── X-axis month labels ──────────────────────────────────────────────────
    xlabels = []
    last_month = ""
    for i, week in enumerate(weeks):
        dt = iso_to_date(week)
        if not dt:
            continue
        label = dt.strftime("%b").upper()
        if label != last_month and dt.day <= 7:
            cx = CHART_LEFT + i * bar_step + bar_w / 2
            xlabels.append(
                f'<text x="{cx:.1f}" y="{CHART_BOTTOM + 18:.1f}" '
                f'text-anchor="middle" class="axis">{label}</text>'
            )
            last_month = label

    # ─── KPI cards ────────────────────────────────────────────────────────────
    def kpi_card(idx: int, label: str, value: str, sub: str,
                 accent: str) -> list[str]:
        x = PAD + idx * (KPI_W + KPI_GAP)
        y = KPI_Y
        pieces = []
        # Card bg
        pieces.append(
            f'<rect x="{x:.1f}" y="{y}" width="{KPI_W:.1f}" height="{KPI_H}" '
            f'rx="10" fill="url(#card-bg)" stroke="var(--border)"/>'
        )
        # Accent stripe on the left
        pieces.append(
            f'<rect x="{x:.1f}" y="{y + 12}" width="3" height="{KPI_H - 24}" '
            f'rx="1.5" fill="{accent}"/>'
        )
        # Label (uppercase, tracked)
        pieces.append(
            f'<text x="{x + 16:.1f}" y="{y + 24}" class="kpi-label">{label}</text>'
        )
        # Big value
        pieces.append(
            f'<text x="{x + 16:.1f}" y="{y + 60}" class="kpi-value">{value}</text>'
        )
        # Subtext
        pieces.append(
            f'<text x="{x + 16:.1f}" y="{y + 82}" class="kpi-sub">{sub}</text>'
        )
        return pieces

    top_lang_color = color_for(stats["top_lang"])[0]
    kpis = []
    kpis += kpi_card(
        0, "TOTAL LINES",
        abbrev(stats["total"]),
        f"across {stats['n_langs']} languages",
        "#22C55E",
    )
    kpis += kpi_card(
        1, "TOP LANGUAGE",
        stats["top_lang"],
        f"{stats['top_lang_pct']:.1f}% of activity",
        top_lang_color,
    )
    kpis += kpi_card(
        2, "PEAK WEEK",
        abbrev(stats["peak_val"]),
        f"week of {stats['peak_label']}",
        "#F97316",
    )
    kpis += kpi_card(
        3, "WEEKLY AVG",
        abbrev(stats["avg"]),
        f"over {stats['n_weeks']} weeks",
        "#3178C6",
    )

    # ─── Language breakdown rows ──────────────────────────────────────────────
    lb_rows = []
    max_total = max(totals.values()) if totals else 1
    for i, lang in enumerate(languages):
        col = i // LB_ROWS_PER_COL
        row = i % LB_ROWS_PER_COL
        cx = PAD + col * (LB_COL_W + LB_COL_GAP)
        cy = LB_TOP + row * LB_ROW_H

        base, top = color_for(lang)
        gid = grad_id(lang)
        total = totals.get(lang, 0)
        pct = total / total_all * 100 if total_all else 0
        bar_full = LB_COL_W - 180     # reserve right for value + %
        bar_len = bar_full * (total / max_total) if max_total else 0

        # Color dot
        lb_rows.append(
            f'<circle cx="{cx + 5:.1f}" cy="{cy + 6}" r="4" fill="{base}"/>'
        )
        # Language name
        lb_rows.append(
            f'<text x="{cx + 16:.1f}" y="{cy + 10}" class="lb-name">{lang}</text>'
        )
        # Track (background bar)
        lb_rows.append(
            f'<rect x="{cx + 92:.1f}" y="{cy + 3}" width="{bar_full:.1f}" '
            f'height="6" rx="3" fill="var(--track)"/>'
        )
        # Filled bar (gradient)
        if bar_len > 0:
            lb_rows.append(
                f'<rect x="{cx + 92:.1f}" y="{cy + 3}" width="{bar_len:.1f}" '
                f'height="6" rx="3" fill="url(#{gid})"/>'
            )
        # Value (abbreviated)
        lb_rows.append(
            f'<text x="{cx + LB_COL_W - 52:.1f}" y="{cy + 10}" '
            f'class="lb-val" text-anchor="end">+{abbrev(total)}</text>'
        )
        # Percentage
        lb_rows.append(
            f'<text x="{cx + LB_COL_W:.1f}" y="{cy + 10}" '
            f'class="lb-pct" text-anchor="end">{pct:.1f}%</text>'
        )

    # ─── Period string ────────────────────────────────────────────────────────
    period = f"Last {n_weeks} weeks · {weeks[0]} → {weeks[-1]}"

    # ─── Assemble ─────────────────────────────────────────────────────────────
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {W} {H}"
     width="{W}" height="{H}"
     role="img" aria-label="Developer activity — weekly lines of code by language">

  <defs>
    <style>
      svg {{
        --bg:        #FFFFFF;
        --fg:        #0F172A;
        --muted:     #64748B;
        --subtle:    #94A3B8;
        --border:    #E2E8F0;
        --grid:      #EEF2F6;
        --track:     #EEF2F6;
        --card-top:  #FFFFFF;
        --card-bot:  #F8FAFC;
        --accent:    #3178C6;
      }}
      @media (prefers-color-scheme: dark) {{
        svg {{
          --bg:        #0D1117;
          --fg:        #E6EDF3;
          --muted:     #8B949E;
          --subtle:    #6E7681;
          --border:    #21262D;
          --grid:      #161B22;
          --track:     #1C2128;
          --card-top:  #161B22;
          --card-bot:  #0D1117;
          --accent:    #58A6FF;
        }}
      }}
      text {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                     "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
        fill: var(--fg);
      }}
      .mono {{
        font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo,
                     Consolas, "Liberation Mono", monospace;
        font-variant-numeric: tabular-nums;
      }}
      .eyebrow {{
        font-size: 11px; font-weight: 600; letter-spacing: 2px;
        fill: var(--muted);
      }}
      .period {{
        font-size: 11px; fill: var(--muted);
        font-variant-numeric: tabular-nums;
      }}
      .section {{
        font-size: 10.5px; font-weight: 600; letter-spacing: 1.8px;
        fill: var(--muted);
      }}
      .kpi-label {{
        font-size: 9.5px; font-weight: 600; letter-spacing: 1.5px;
        fill: var(--muted);
      }}
      .kpi-value {{
        font-size: 26px; font-weight: 700; fill: var(--fg);
        font-variant-numeric: tabular-nums;
      }}
      .kpi-sub {{
        font-size: 10.5px; fill: var(--muted);
      }}
      .axis {{
        font-size: 9.5px; fill: var(--subtle);
        font-variant-numeric: tabular-nums;
      }}
      .lb-name {{ font-size: 11px; font-weight: 500; fill: var(--fg); }}
      .lb-val  {{ font-size: 10.5px; fill: var(--muted);
                  font-variant-numeric: tabular-nums; }}
      .lb-pct  {{ font-size: 10.5px; font-weight: 600; fill: var(--fg);
                  font-variant-numeric: tabular-nums; }}
      .clip-label {{ font-size: 9.5px; font-weight: 600; fill: var(--fg);
                     font-variant-numeric: tabular-nums; }}
      .footer {{ font-size: 9.5px; fill: var(--subtle); }}
    </style>
    {"".join(gradient_defs)}
  </defs>

  <!-- Canvas -->
  <rect width="{W}" height="{H}" fill="var(--bg)" rx="12"/>

  <!-- Header: eyebrow with accent dot (left) + period (right) -->
  <circle cx="{PAD + 4}" cy="{HEADER_Y - 4}" r="4" fill="var(--accent)"/>
  <text x="{PAD + 16}" y="{HEADER_Y}" class="eyebrow">DEVELOPER ACTIVITY</text>
  <text x="{W - PAD}" y="{HEADER_Y}" class="period" text-anchor="end">{period}</text>

  <!-- Divider under header -->
  <line x1="{PAD}" y1="{HEADER_Y + 14}" x2="{W - PAD}" y2="{HEADER_Y + 14}"
        stroke="var(--border)" stroke-width="1"/>

  <!-- KPI cards -->
  {"".join(kpis)}

  <!-- Chart section title -->
  <text x="{PAD}" y="{CHART_TOP - 12}" class="section">WEEKLY ACTIVITY</text>
  <text x="{W - PAD}" y="{CHART_TOP - 12}" class="period" text-anchor="end">
    lines added per ISO week
  </text>

  <!-- Grid -->
  {"".join(grid)}

  <!-- Bars -->
  {"".join(bars)}

  <!-- Clipped-outlier indicators -->
  {"".join(clip_overlay)}

  <!-- X-axis labels -->
  {"".join(xlabels)}

  <!-- Language breakdown section title -->
  <text x="{PAD}" y="{LB_TOP - 12}" class="section">LANGUAGE BREAKDOWN</text>
  <text x="{W - PAD}" y="{LB_TOP - 12}" class="period" text-anchor="end">
    ranked by lines added
  </text>

  {"".join(lb_rows)}

  <!-- Footer -->
  <line x1="{PAD}" y1="{H - 30}" x2="{W - PAD}" y2="{H - 30}"
        stroke="var(--border)" stroke-width="1"/>
  <text x="{PAD}" y="{H - 14}" class="footer">
    Generated {generated} · git diff-tree --numstat · non-forked, non-archived repos
  </text>
  <text x="{W - PAD}" y="{H - 14}" class="footer" text-anchor="end">
    github.com · auto-updated
  </text>
</svg>"""
    return svg


def main():
    if not INPUT_FILE.exists():
        raise SystemExit(f"[render_svg] {INPUT_FILE} not found")

    data = json.loads(INPUT_FILE.read_text())
    svg  = render(data)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(svg)
    print(f"[render_svg] SVG written → {OUTPUT_FILE} ({len(svg):,} bytes)")


if __name__ == "__main__":
    main()
