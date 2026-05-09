#!/usr/bin/env python3
"""
collect_timeline.py

Clones all non-forked, non-archived repos for the configured account sources,
walks git history for commits authored by them, and builds a week-by-week
LOC-added breakdown per language.

Output → /tmp/timeline.json
"""

import json
import os
import subprocess
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

WEEKS_BACK = int(os.environ.get("WEEKS_BACK", "26"))

REPOS_DIR = Path("/tmp/repos")
OUTPUT_FILE = Path(os.environ.get("OUTPUT_FILE", "/tmp/timeline.json"))
TOP_N = 10

EXT_MAP: dict[str, str | None] = {
    ".py":    "Python",
    ".ts":    "TypeScript",  ".tsx": "TypeScript",
    ".js":    None,          ".jsx": None,         ".mjs": None,
    ".tf":    "HCL",         ".hcl": "HCL",
    ".rs":    "Rust",
    ".go":    "Go",
    ".sh":    "Bash",        ".bash": "Bash",        ".zsh": "Bash",
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


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    username: str
    token: str
    email: str
    api_base: str
    server_url: str
    noreply_domain: str

    @property
    def repo_dir(self) -> Path:
        return REPOS_DIR / self.key


def build_source() -> Source:
    username = os.environ.get("GH_USERNAME", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    email = os.environ.get("GH_EMAIL", "").strip()

    missing = [name for name, value in (("GH_USERNAME", username), ("GH_TOKEN", token)) if not value]
    if missing:
        raise SystemExit(f"[collect] Missing required environment values: {', '.join(missing)}")

    return Source(
        key="gh",
        label="github.com",
        username=username,
        token=token,
        email=email,
        api_base="https://api.github.com",
        server_url="https://github.com",
        noreply_domain="users.noreply.github.com",
    )


def configured_sources() -> list[Source]:
    return [build_source()]


def api(source: Source, path: str) -> list | dict:
    url = f"{source.api_base}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {source.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "loc-timeline-bot",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def get_email(source: Source) -> str:
    if source.email:
        return source.email
    user = api(source, f"/users/{source.username}")
    email = user.get("email") or f"{source.username}@{source.noreply_domain}"
    return email


def list_repos(source: Source) -> list[dict]:
    repos, page = [], 1
    while True:
        batch = api(source, f"/user/repos?type=owner&per_page=100&page={page}")
        if not batch:
            break
        repos.extend(r for r in batch if not r["fork"] and not r["archived"])
        if len(batch) < 100:
            break
        page += 1
    print(f"[collect] {source.label}: {len(repos)} repos", flush=True)
    return repos


def authenticated_clone_url(source: Source, clone_url: str) -> str:
    parts = urlsplit(clone_url)
    username = quote(source.username, safe="")
    token = quote(source.token, safe="")
    return urlunsplit(
        (
            parts.scheme or "https",
            f"{username}:{token}@{parts.netloc}",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


def clone(source: Source, repo: dict) -> Path | None:
    dest = source.repo_dir / repo["name"]
    url = authenticated_clone_url(source, repo["clone_url"])
    if dest.exists():
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--quiet", "--all"],
            capture_output=True,
            text=True,
        )
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)],
        capture_output=True,
        text=True,
    )
    return dest if r.returncode == 0 else None


def isoweek(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


BASH_FILENAMES = {
    ".bashrc", ".bash_profile", ".bash_logout", ".bash_aliases",
    ".zshrc", ".zshenv", ".zprofile", ".zlogin", ".zlogout",
    ".profile", ".inputrc",
}


def ext_lang(filename: str) -> str | None:
    name = Path(filename).name
    if name in BASH_FILENAMES:
        return "Bash"
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
    since = datetime.now(timezone.utc) - timedelta(weeks=WEEKS_BACK)
    weeks = week_range(WEEKS_BACK)
    sources = configured_sources()

    global_weekly: dict = defaultdict(lambda: defaultdict(int))
    active_labels: list[str] = []

    for source in sources:
        email = get_email(source)
        repos = list_repos(source)
        active_labels.append(source.label)
        for i, repo in enumerate(repos, 1):
            print(
                f"[collect] {source.label}: processing repo {i} of {len(repos)}",
                flush=True,
            )
            path = clone(source, repo)
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

    if not active_labels:
        source_label = "configured sources"
    elif len(active_labels) == 1:
        source_label = active_labels[0]
    else:
        source_label = " + ".join(active_labels)

    OUTPUT_FILE.write_text(json.dumps({
        "weeks": weeks,
        "languages": top_langs,
        "series": series,
        "totals": {l: totals[l] for l in top_langs},
        "source_label": source_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    print(f"\n[collect] Top languages (last {WEEKS_BACK} weeks):")
    for lang in top_langs:
        print(f"  {lang:<20} +{totals[lang]:>8,} lines")


if __name__ == "__main__":
    main()
