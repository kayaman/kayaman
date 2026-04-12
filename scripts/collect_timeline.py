#!/usr/bin/env python3
"""
collect_timeline.py

Clones all non-forked, non-archived repos for a github.com user,
walks git history for commits authored by them, and builds a
week-by-week LOC-added breakdown per language.

Output → /tmp/timeline.json
"""

import json
import os
import subprocess
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

GH_TOKEN    = os.environ["GH_TOKEN"]
GH_USERNAME = os.environ["GH_USERNAME"]
GH_EMAIL    = os.environ.get("GH_EMAIL", "")
WEEKS_BACK  = int(os.environ.get("WEEKS_BACK", "26"))

REPOS_DIR   = Path("/tmp/repos")
OUTPUT_FILE = Path("/tmp/timeline.json")
TOP_N       = 6

EXT_MAP: dict[str, str | None] = {
    ".py":    "Python",
    ".ts":    "TypeScript",  ".tsx": "TypeScript",
    ".js":    "JavaScript",  ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".tf":    "HCL",         ".hcl": "HCL",
    ".rs":    "Rust",
    ".go":    "Go",
    ".sh":    "Shell",       ".bash": "Shell",
    ".sql":   "SQL",
    ".rb":    "Ruby",
    ".java":  "Java",
    ".kt":    "Kotlin",
    ".scala": "Scala",
    ".c":     "C",           ".h":   "C",
    ".cpp":   "C++",         ".hpp": "C++",
    ".ipynb": "Jupyter",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".css": "CSS",
    ".html": "HTML",
    ".txt": "Text",
    ".svg": "SVG",
    # Noise — exclude
    ".xml": None,
    ".lock": None,
    ".sum":  None,
}


def api(path: str) -> list | dict:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def get_email() -> str:
    if GH_EMAIL:
        return GH_EMAIL
    user = api(f"/users/{GH_USERNAME}")
    email = user.get("email") or f"{GH_USERNAME}@users.noreply.github.com"
    print(f"[collect] Author email: {email}")
    return email


def list_repos() -> list[dict]:
    repos, page = [], 1
    while True:
        batch = api(f"/user/repos?type=owner&per_page=100&page={page}")
        if not batch:
            break
        repos.extend(r for r in batch if not r["fork"] and not r["archived"])
        if len(batch) < 100:
            break
        page += 1
    print(f"[collect] {len(repos)} repos")
    return repos


def clone(repo: dict) -> Path | None:
    dest = REPOS_DIR / repo["name"]
    url  = repo["clone_url"].replace("https://", f"https://oauth2:{GH_TOKEN}@")
    if dest.exists():
        subprocess.run(["git", "-C", str(dest), "fetch", "--quiet", "--all"],
                       capture_output=True)
        return dest
    r = subprocess.run(["git", "clone", "--quiet", url, str(dest)],
                       capture_output=True)
    return dest if r.returncode == 0 else None


def isoweek(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def ext_lang(filename: str) -> str | None:
    return EXT_MAP.get(Path(filename).suffix.lower(), "Other")


def scan_repo(path: Path, email: str, since: datetime) -> dict:
    """Returns {isoweek: {lang: lines_added}}"""
    log = subprocess.run([
        "git", "-C", str(path), "log",
        f"--author={email}",
        f"--since={since.strftime('%Y-%m-%d')}",
        "--format=%H %aI",
        "--no-merges",
    ], capture_output=True, text=True)

    if not log.stdout.strip():
        return {}

    weekly: dict = defaultdict(lambda: defaultdict(int))

    for line in log.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        commit_hash, date_str = parts
        try:
            dt   = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            week = isoweek(dt)
        except ValueError:
            continue

        numstat = subprocess.run([
            "git", "-C", str(path),
            "diff-tree", "--no-commit-id", "-r", "--numstat", commit_hash,
        ], capture_output=True, text=True)

        for stat in numstat.stdout.strip().splitlines():
            cols = stat.split("\t")
            if len(cols) != 3 or cols[0] == "-":
                continue
            try:
                added = int(cols[0])
            except ValueError:
                continue
            lang = ext_lang(cols[2])
            if lang is None:
                continue
            weekly[week][lang] += added

    return {w: dict(l) for w, l in weekly.items()}


def week_range(n: int) -> list[str]:
    now, seen, out = datetime.now(timezone.utc), set(), []
    for i in range(n - 1, -1, -1):
        w = isoweek(now - timedelta(weeks=i))
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def main():
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    email  = get_email()
    since  = datetime.now(timezone.utc) - timedelta(weeks=WEEKS_BACK)
    weeks  = week_range(WEEKS_BACK)
    repos  = list_repos()

    global_weekly: dict = defaultdict(lambda: defaultdict(int))

    for i, repo in enumerate(repos, 1):
        print(f"[collect] {i}/{len(repos)} {repo['name']}", flush=True)
        path = clone(repo)
        if not path:
            continue
        for w, langs in scan_repo(path, email, since).items():
            for lang, n in langs.items():
                global_weekly[w][lang] += n

    totals: dict = defaultdict(int)
    for langs in global_weekly.values():
        for lang, n in langs.items():
            totals[lang] += n

    top_langs = [l for l, _ in sorted(totals.items(), key=lambda x: -x[1])
                 if l != "Other"][:TOP_N]

    series = {
        lang: [global_weekly.get(w, {}).get(lang, 0) for w in weeks]
        for lang in top_langs
    }

    OUTPUT_FILE.write_text(json.dumps({
        "weeks":        weeks,
        "languages":    top_langs,
        "series":       series,
        "totals":       {l: totals[l] for l in top_langs},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    print(f"\n[collect] Top languages (last {WEEKS_BACK} weeks):")
    for lang in top_langs:
        print(f"  {lang:<20} +{totals[lang]:>8,} lines")


if __name__ == "__main__":
    main()
