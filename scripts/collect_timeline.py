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
MAX_REPOS  = int(os.environ.get("MAX_REPOS", "25"))

REPOS_DIR = Path("/tmp/repos")
OUTPUT_FILE = Path(os.environ.get("OUTPUT_FILE", "/tmp/timeline.json"))
TOP_N = 10

EXT_MAP: dict[str, str | None] = {
    ".py":    "Python",
    ".ts":    "TypeScript",  ".tsx": "TypeScript",
    ".js":    None,          ".jsx": None,         ".mjs": None,
    ".tf":    "Terraform",   ".hcl": "Terraform",
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
    ".json":  "JSON",
    ".yaml":  "YAML",        ".yml": "YAML",
    ".toml":  "TOML",
    ".md":    "Markdown",    ".mdx": "Markdown",
    ".css":   "CSS",         ".scss": "CSS",       ".sass": "CSS",   ".less": "CSS",
    ".html":  "HTML",
    ".txt":   "Text",
    ".svg":   "SVG",
    # Modern web / app frameworks
    ".astro":  "Astro",
    ".svelte": "Svelte",
    ".vue":    "Vue",
    # Schema / IDLs
    ".graphql": "GraphQL",   ".gql":  "GraphQL",
    ".proto":   "Protobuf",
    # Other widely-used languages
    ".swift": "Swift",
    ".dart":  "Dart",
    ".lua":   "Lua",
    ".cs":    "C#",
    ".php":   "PHP",
    ".r":     "R",
    ".tex":   "LaTeX",
    ".mk":    "Make",
    # Noise — exclude
    ".xml":  None,
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
    # Pull top-N by most-recent push. GitHub serves at most 100/page; for
    # MAX_REPOS up to 100 a single page is enough.
    #
    # Coverage tradeoff: a repo active inside the WEEKS_BACK window but
    # pushed past by MAX_REPOS+ other repos will silently drop from the
    # chart. For workflow ergonomics this is fine — bump MAX_REPOS env var
    # to widen the net. Persisting per-repo contributions across runs would
    # be the more durable fix but is intentionally out of scope here.
    per_page = min(100, max(MAX_REPOS, 1))
    batch = api(
        source,
        f"/user/repos?type=owner&sort=pushed&direction=desc&per_page={per_page}",
    )
    repos = [r for r in batch if not r["fork"] and not r["archived"]][:MAX_REPOS]
    print(
        f"[collect] {source.label}: {len(repos)} repos "
        f"(top {MAX_REPOS} by pushed_at, filtered from page of {len(batch)})",
        flush=True,
    )
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


SPECIAL_FILENAMES: dict[str, str] = {
    # Bash / shell rc files
    ".bashrc": "Bash", ".bash_profile": "Bash", ".bash_logout": "Bash",
    ".bash_aliases": "Bash",
    ".zshrc": "Bash", ".zshenv": "Bash", ".zprofile": "Bash",
    ".zlogin": "Bash", ".zlogout": "Bash",
    ".profile": "Bash", ".inputrc": "Bash",
    # Containers
    "Dockerfile": "Dockerfile", "dockerfile": "Dockerfile",
    "Containerfile": "Dockerfile",
    # Build
    "Makefile": "Make", "makefile": "Make", "GNUmakefile": "Make",
    "Justfile": "Make", "justfile": "Make",
}


def ext_lang(filename: str) -> str | None:
    name = Path(filename).name
    if name in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[name]
    return EXT_MAP.get(Path(filename).suffix.lower(), "Other")


def _empty_week() -> dict:
    return {
        "added":   defaultdict(int),
        "deleted": defaultdict(int),
        "commits": 0,
    }


def scan_repo(path: Path, email: str, since: datetime) -> dict:
    """
    Returns {isoweek: {"added": {lang: int}, "deleted": {lang: int}, "commits": int}}.

    Commits are counted per ISO week regardless of whether numstat produced
    any countable rows (binary-only or empty commits still indicate activity).
    """
    log = subprocess.run([
        "git", "-C", str(path), "log",
        f"--author={email}",
        f"--since={since.strftime('%Y-%m-%d')}",
        "--format=%H %aI",
        "--no-merges",
    ], capture_output=True, text=True)

    if not log.stdout.strip():
        return {}

    weekly: dict = defaultdict(_empty_week)

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

        weekly[week]["commits"] += 1

        numstat = subprocess.run([
            "git", "-C", str(path),
            "diff-tree", "--no-commit-id", "-r", "--numstat", commit_hash,
        ], capture_output=True, text=True)

        for stat in numstat.stdout.strip().splitlines():
            cols = stat.split("\t")
            if len(cols) != 3:
                continue
            # Binary files report '-' for both added and deleted
            if cols[0] == "-" or cols[1] == "-":
                continue
            try:
                added   = int(cols[0])
                deleted = int(cols[1])
            except ValueError:
                continue
            lang = ext_lang(cols[2])
            if lang is None:
                continue
            weekly[week]["added"][lang]   += added
            weekly[week]["deleted"][lang] += deleted

    return {
        w: {
            "added":   dict(s["added"]),
            "deleted": dict(s["deleted"]),
            "commits": s["commits"],
        }
        for w, s in weekly.items()
    }


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

    global_added:   dict = defaultdict(lambda: defaultdict(int))   # week -> {lang: int}
    global_deleted: dict = defaultdict(lambda: defaultdict(int))   # week -> {lang: int}
    global_commits: dict = defaultdict(int)                        # week -> int
    repos_per_week: dict = defaultdict(set)                        # week -> {repo_name}
    repos_touched_total: set[str] = set()
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
            scan = scan_repo(path, email, since)
            for w, stats in scan.items():
                for lang, n in stats["added"].items():
                    global_added[w][lang] += n
                for lang, n in stats["deleted"].items():
                    global_deleted[w][lang] += n
                global_commits[w] += stats["commits"]
                if stats["commits"] > 0:
                    repos_per_week[w].add(repo["name"])
                    repos_touched_total.add(repo["name"])

    # Top languages ranked by GROSS ADDED (not net) — net would re-rank
    # whenever you delete code, hiding real activity in a language.
    totals_added: dict = defaultdict(int)
    totals_deleted: dict = defaultdict(int)
    for w_langs in global_added.values():
        for lang, n in w_langs.items():
            totals_added[lang] += n
    for w_langs in global_deleted.values():
        for lang, n in w_langs.items():
            totals_deleted[lang] += n

    top_langs = [l for l, _ in sorted(totals_added.items(), key=lambda x: -x[1])
                 if l != "Other"][:TOP_N]

    series = {
        lang: [global_added.get(w, {}).get(lang, 0) for w in weeks]
        for lang in top_langs
    }
    series_deleted = {
        lang: [global_deleted.get(w, {}).get(lang, 0) for w in weeks]
        for lang in top_langs
    }
    commits_per_week = [global_commits.get(w, 0) for w in weeks]
    repos_per_week_counts = [len(repos_per_week.get(w, ())) for w in weeks]

    gross_added   = sum(totals_added[l] for l in top_langs)
    gross_deleted = sum(totals_deleted[l] for l in top_langs)

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
        "totals": {l: totals_added[l] for l in top_langs},
        "series_deleted": series_deleted,
        "totals_deleted": {l: totals_deleted[l] for l in top_langs},
        "commits_per_week": commits_per_week,
        "repos_per_week":   repos_per_week_counts,
        "totals_meta": {
            "gross_added":   gross_added,
            "gross_deleted": gross_deleted,
            "net":           gross_added - gross_deleted,
            "commits":       sum(commits_per_week),
            "repos":         len(repos_touched_total),
        },
        "source_label": source_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    print(f"\n[collect] Top languages (last {WEEKS_BACK} weeks):")
    for lang in top_langs:
        print(
            f"  {lang:<20} +{totals_added[lang]:>8,} / "
            f"-{totals_deleted[lang]:>8,} lines"
        )
    print(
        f"\n[collect] Net: +{gross_added - gross_deleted:,} · "
        f"commits: {sum(commits_per_week):,} · "
        f"repos touched: {len(repos_touched_total)}"
    )


if __name__ == "__main__":
    main()
