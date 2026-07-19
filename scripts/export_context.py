"""Export the project's source code into a single snapshot file.

Concatenates every relevant source file into one .txt, so the exact code
can be handed to an assistant/reviewer as context instead of maintaining
hand-written mirrors that drift from reality. Regenerate at the end of a
session; the output is disposable (gitignored).

Usage (from repo root):
    python scripts/export_context.py
"""
from __future__ import annotations
from pathlib import Path

# Repo root = parent of scripts/ (this file lives in scripts/).
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "project_snapshot.txt"

# Allowlist: what counts as source worth snapshotting. Anything not listed
# here (e.g. *.db, images) is excluded by default — safer than a denylist.
INCLUDE_SUFFIXES = {".py", ".sql", ".toml"}
INCLUDE_NAMES = {"requirements.txt", ".gitignore", "README.md"}

# Directory names we never descend into (generated / env / VCS internals).
EXCLUDE_DIRS = {".venv", "__pycache__", ".git", ".vscode"}


def is_excluded(path: Path) -> bool:
    """True if any path segment is an excluded dir or an egg-info folder."""
    return any(
        part in EXCLUDE_DIRS or part.endswith(".egg-info")
        for part in path.parts
    )


def collect_files() -> list[Path]:
    """Every included source file under ROOT, sorted for stable output."""
    files = [
        p for p in ROOT.rglob("*")
        if p.is_file()
        and not is_excluded(p)
        and (p.suffix in INCLUDE_SUFFIXES or p.name in INCLUDE_NAMES)
    ]
    return sorted(files)


def main() -> None:
    files = collect_files()
    with OUTPUT.open("w", encoding="utf-8") as out:
        # Manifest first: the reader sees the project's shape at a glance.
        out.write("# PROJECT SNAPSHOT\n\n## Files included:\n")
        for f in files:
            out.write(f"- {f.relative_to(ROOT)}\n")
        # Then each file, fenced by an unmistakable header.
        for f in files:
            rel = f.relative_to(ROOT)
            out.write(f"\n{'=' * 80}\n# FILE: {rel}\n{'=' * 80}\n\n")
            out.write(f.read_text(encoding="utf-8"))
            out.write("\n")
    print(f"Wrote {len(files)} files to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()