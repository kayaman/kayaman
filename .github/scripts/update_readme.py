#!/usr/bin/env python3
"""
update_readme.py

Reads /tmp/timeline.json, builds a README section pointing at
assets/loc_chart.svg (already committed by the workflow), and
pushes the updated README to the profile repo via the Contents API.

Markers in README.md:
  <!--START_SECTION:loc-->
  <!--END_SECTION:loc-->
"""

import base64
import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

GH_TOKEN    = os.environ["GH_TOKEN"]
GH_USERNAME = os.environ["GH_USERNAME"]
REPO        = f"{GH_USERNAME}/{GH_USERNAME}"
API_BASE    = "https://api.github.com"
README_PATH = "README.md"
SVG_PATH    = "assets/loc_chart.svg"
START       = "<!--START_SECTION:loc-->"
END         = "<!--END_SECTION:loc-->"
DATA_FILE   = Path("/tmp/timeline.json")


def gh(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "loc-timeline-bot",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} → {e.code}: {e.read().decode()}") from e


def get_readme() -> tuple[str, str]:
    data = gh("GET", f"/repos/{REPO}/contents/{README_PATH}")
    return base64.b64decode(data["content"]).decode(), data["sha"]


def section(data: dict) -> str:
    totals    = data["totals"]
    languages = data["languages"]
    weeks     = data["weeks"]
    generated = data.get("generated_at", "")[:10]
    period    = f"{weeks[0]} → {weeks[-1]}" if weeks else ""
    total_all = sum(totals.values())

    # Cache-bust the SVG URL so GitHub doesn't serve a stale version
    date_str  = datetime.now(timezone.utc).strftime("%Y%m%d")
    svg_url   = (
        f"https://raw.githubusercontent.com/{REPO}/main/"
        f"{SVG_PATH}?v={date_str}"
    )

    rows = "\n".join(
        f"| {lang} | +{totals[lang]:,} | {totals[lang]/total_all*100:.1f}% |"
        for lang in languages
    )

    return f"""
![Lines of code written per week]({svg_url})

<details>
<summary>Breakdown · {period}</summary>

| Language | Lines added | Share |
|----------|------------:|------:|
{rows}

<sub>Source: git history · `diff-tree --numstat` · updated {generated}</sub>
</details>
"""


def main():
    if not DATA_FILE.exists():
        raise SystemExit(f"[readme] {DATA_FILE} not found")

    data = json.loads(DATA_FILE.read_text())

    readme, sha = get_readme()

    pattern = re.compile(
        rf"{re.escape(START)}.*?{re.escape(END)}", re.DOTALL
    )
    if not pattern.search(readme):
        raise SystemExit(
            f"[readme] Markers not found. Add to your README:\n  {START}\n  {END}"
        )

    new_readme = pattern.sub(f"{START}{section(data)}{END}", readme)

    if new_readme == readme:
        print("[readme] No changes.")
        return

    total = sum(data["totals"].values())
    gh("PUT", f"/repos/{REPO}/contents/{README_PATH}", body={
        "message": f"chore: update LOC timeline (+{total:,} lines)",
        "content": base64.b64encode(new_readme.encode()).decode(),
        "sha": sha,
    })
    print("[readme] ✓ README updated")


if __name__ == "__main__":
    main()
