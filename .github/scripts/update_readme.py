import json, re, pathlib

data = json.loads(pathlib.Path("/tmp/tokei.json").read_text())

rows = []
for lang, stats in sorted(data.items(), key=lambda x: -x[1]["code"]):
    if lang == "Total":
        continue
    rows.append(f"| {lang} | {stats['code']:,} | {stats['comments']:,} | {stats['blanks']:,} |")

table = "\n".join([
    "| Language | Code | Comments | Blanks |",
    "|----------|-----:|--------:|-------:|",
    *rows[:10]
])

total = data.get("Total", {})
summary = f"**Total: {total.get('code', 0):,} lines of code** across {total.get('files', 0):,} files\n\n"

block = f"\n{summary}{table}\n"

readme = pathlib.Path("README.md").read_text()
readme = re.sub(
    r"<!--START_SECTION:loc-->.*?<!--END_SECTION:loc-->",
    f"<!--START_SECTION:loc-->{block}<!--END_SECTION:loc-->",
    readme, flags=re.DOTALL
)
pathlib.Path("README.md").write_text(readme)
