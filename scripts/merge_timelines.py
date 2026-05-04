#!/usr/bin/env python3
"""merge_timelines.py — merge github.com and GHE timeline JSONs."""
import json
from collections import defaultdict
from pathlib import Path

GH_FILE  = Path("/tmp/timeline.json")
GHE_FILE = Path("/tmp/timeline_ghe.json")
TOP_N    = 10

def load(p):
    return json.loads(p.read_text()) if p.exists() else None

gh  = load(GH_FILE)
ghe = load(GHE_FILE)

if gh is None:
    raise SystemExit("No github.com timeline found")

if ghe is None:
    print("[merge] No GHE timeline found, skipping merge")
else:
    all_weeks = sorted(set(gh["weeks"]) | set(ghe["weeks"]))
    merged_weekly = defaultdict(lambda: defaultdict(int))
    for src in (gh, ghe):
        for lang, counts in src["series"].items():
            for week, n in zip(src["weeks"], counts):
                merged_weekly[week][lang] += n
    totals = defaultdict(int)
    for langs in merged_weekly.values():
        for lang, n in langs.items():
            totals[lang] += n
    top_langs = [l for l, _ in sorted(totals.items(), key=lambda x: -x[1])
                 if l.lower() != "other"][:TOP_N]
    series = {
        lang: [merged_weekly.get(w, {}).get(lang, 0) for w in all_weeks]
        for lang in top_langs
    }
    GH_FILE.write_text(json.dumps({
        "weeks": all_weeks,
        "languages": top_langs,
        "series": series,
        "totals": {l: totals[l] for l in top_langs},
        "generated_at": gh["generated_at"],
    }, indent=2))
    print(f"[merge] Merged {len(gh['weeks'])} gh.com + {len(ghe['weeks'])} GHE weeks -> {len(all_weeks)} total weeks")
