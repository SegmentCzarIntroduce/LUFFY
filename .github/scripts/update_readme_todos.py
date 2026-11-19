#!/usr/bin/env python3
"""Update README's Complete TODO List from Python TODO markers on dev-only changes.

This helper runs in CI. It first proves its parser reproduces the committed
main/README baseline exactly, then replaces only TODO groups for .py files
changed from origin/main to the current dev tree.
"""
from __future__ import annotations

import difflib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
BASE_REF = os.environ.get("BASE_REF", "origin/main")
APPLY = os.environ.get("APPLY", "false").strip().lower() == "true"
HEADING = "### 📝 Complete TODO List"
ENTRY_RE = re.compile(
    r"^- \[ \] \*\*(?P<path>.+?):(?P<line>[0-9]+)\*\* - (?P<message>.*)$"
)
# The baseline was produced from source comments of the form:
#   # TODO: message
#   # TODO(message-owner): message
# The optional colon is consumed only immediately after the literal TODO.
TODO_RE = re.compile(r"#\s*TODO:?[ \t]*(?P<message>.*?)[ \t]*$")


def run_git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO, text=True, capture_output=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode})\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def scan_python_tree(root: Path):
    """Return ordered {posix_path: [(line_number, message), ...]} for .py files."""
    scanned: "OrderedDict[str, list[tuple[int, str]]]" = OrderedDict()
    for dirpath, dirnames, filenames in os.walk(root):
        # Never inspect VCS metadata or this temporary CI helper's own directory.
        dirnames[:] = sorted(
            d for d in dirnames if d not in {".git", ".github"}
        )
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel_path = path.relative_to(root).as_posix()
            items: list[tuple[int, str]] = []
            text = path.read_text(encoding="utf-8")
            for line_no, source_line in enumerate(text.splitlines(), start=1):
                match = TODO_RE.search(source_line)
                if match:
                    message = match.group("message").strip()
                    items.append((line_no, message))
            if items:
                scanned[rel_path] = items
    return OrderedDict((p, scanned[p]) for p in sorted(scanned))


def flatten_scan(scan) -> list[tuple[str, int, str]]:
    return [
        (path, line_no, message)
        for path, items in scan.items()
        for line_no, message in items
    ]


def render_entry(path: str, line_no: int, message: str) -> str:
    return f"- [ ] **{path}:{line_no}** - {message}"


def parse_readme(readme_text: str):
    lines = readme_text.splitlines()
    heading_indexes = [i for i, line in enumerate(lines) if line == HEADING]
    if len(heading_indexes) != 1:
        raise RuntimeError(
            f"Expected exactly one unchanged title {HEADING!r}, found {len(heading_indexes)}"
        )
    heading_index = heading_indexes[0]
    section_end = None
    for i in range(heading_index + 1, len(lines)):
        if lines[i].startswith("## "):
            section_end = i
            break
    if section_end is None:
        raise RuntimeError("Could not find the end of Complete TODO List section")

    entries: list[tuple[str, int, str]] = []
    rendered_entries: list[str] = []
    for i in range(heading_index + 1, section_end):
        line = lines[i]
        if not line.strip():
            continue
        match = ENTRY_RE.match(line)
        if not match:
            raise RuntimeError(f"Malformed README TODO line {i + 1}: {line!r}")
        entry = (
            match.group("path"),
            int(match.group("line")),
            match.group("message"),
        )
        entries.append(entry)
        rendered_entries.append(render_entry(*entry))
        if line != rendered_entries[-1]:
            raise RuntimeError(
                f"Baseline line {i + 1} does not match canonical format:\n"
                f"old: {line!r}\nnew: {rendered_entries[-1]!r}"
            )

    return lines, heading_index, section_end, entries


def group_entries(entries: list[tuple[str, int, str]]):
    groups: "OrderedDict[str, list[tuple[int, str]]]" = OrderedDict()
    for path, line_no, message in entries:
        groups.setdefault(path, []).append((line_no, message))
    for path, items in groups.items():
        if items != sorted(items, key=lambda x: x[0]):
            raise RuntimeError(f"Baseline entries for {path} are not line-sorted")
    paths = [p for p, _, _ in entries]
    if paths != sorted(paths):
        raise RuntimeError("Baseline entries are not path-lexicographically sorted")
    all_entries = [(p, ln, msg) for p, its in groups.items() for ln, msg in its]
    if all_entries != entries:
        raise RuntimeError("Baseline entries are not globally sorted by path,line")
    return groups


def main() -> int:
    print(f"Repository: {REPO}")
    print(f"APPLY={APPLY}; BASE_REF={BASE_REF}")

    readme_path = REPO / "README.md"
    old_readme = readme_path.read_text(encoding="utf-8")
    old_lines, heading_idx, section_end_idx, baseline_entries = parse_readme(old_readme)
    baseline_groups = group_entries(baseline_entries)
    print(f"Parsed README baseline TODO entries: {len(baseline_entries)}")
    print(f"Baseline files with TODOs: {len(baseline_groups)}")

    # Check out main's tree into a temporary directory via git archive and prove
    # that this parser exactly reproduces the existing README baseline.
    archive = subprocess.run(
        ["git", "archive", BASE_REF], cwd=REPO, capture_output=True, check=True
    ).stdout
    with tempfile.TemporaryDirectory(prefix="luffy-main-") as tmp_name:
        tmp_path = Path(tmp_name)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
            try:
                tf.extractall(tmp_path, filter="data")
            except TypeError:  # pragma: no cover - older Python fallback
                tf.extractall(tmp_path)
        main_scan = scan_python_tree(tmp_path)
    main_entries = flatten_scan(main_scan)
    if main_entries != baseline_entries:
        old_rendered = [render_entry(*e) for e in baseline_entries]
        new_rendered = [render_entry(*e) for e in main_entries]
        diff = list(
            difflib.unified_diff(
                old_rendered,
                new_rendered,
                fromfile="README baseline",
                tofile=f"Python scan of {BASE_REF}",
                lineterm="",
                n=2,
            )
        )
        print("\n".join(diff[:240]))
        print(
            f"Parser self-test failed: README={len(baseline_entries)} "
            f"main_scan={len(main_entries)}"
        )
        return 2
    print("Parser self-test passed: Python scan of main exactly matches README baseline.")

    # Main-to-current-dev endpoint differences. Filter in Python so old git
    # pathspec/glob behavior differences cannot hide a changed Python file.
    diff_output = run_git("diff", "--name-status", "-M", BASE_REF)
    changed_paths: set[str] = set()
    status_rows = [row for row in diff_output.splitlines() if row.strip()]
    print("All changed files from main to current tree:")
    for row in status_rows:
        parts = row.split("\t")
        status, paths = parts[0], parts[1:]
        print("  " + " | ".join(parts))

        def is_project_python(path: str) -> bool:
            return path.endswith(".py") and not path.startswith(".github/")

        if any(is_project_python(path) for path in paths):
            # For a rename, retain both old and new path fields; current tree
            # scan decides whether a group is replaced, removed, or added.
            changed_paths.update(path for path in paths if not path.startswith(".github/"))
    print("Changed project Python paths selected for TODO-group update:")
    for path in sorted(changed_paths):
        print(f"  {path}")
    if not changed_paths:
        print("ERROR: expected main-to-dev Python changes but git diff found none", file=sys.stderr)
        return 3

    current_scan = scan_python_tree(REPO)
    current_groups = OrderedDict(
        (path, [(line_no, message) for line_no, message in items])
        for path, items in current_scan.items()
    )

    final_groups: "OrderedDict[str, list[tuple[int, str]]]" = OrderedDict()
    for path, items in baseline_groups.items():
        final_groups[path] = list(items)

    for path in sorted(changed_paths):
        old_count = len(final_groups.get(path, []))
        new_items = current_groups.get(path, [])
        if new_items:
            final_groups[path] = list(new_items)
        else:
            final_groups.pop(path, None)
        print(f"\nUpdated group {path}: {old_count} baseline entries -> {len(new_items)} current entries")
        for line_no, message in new_items:
            print(f"  {line_no:5d}: {message}")

    # Add newly-created Python files containing TODOs (also covered by changed set).
    for path in sorted(changed_paths):
        if path in current_groups and path not in final_groups:
            final_groups[path] = list(current_groups[path])

    final_entries: list[tuple[str, int, str]] = []
    for path in sorted(final_groups):
        items = sorted(final_groups[path], key=lambda x: x[0])
        final_groups[path] = items
        final_entries.extend((path, line_no, message) for line_no, message in items)

    # Verify global ordering and section parsing of generated text.
    rendered_final = [render_entry(*entry) for entry in final_entries]
    reparsed = [
        (m.group("path"), int(m.group("line")), m.group("message"))
        for line in rendered_final
        if (m := ENTRY_RE.match(line))
    ]
    assert reparsed == final_entries

    new_lines = (
        old_lines[: heading_idx + 1]
        + [""]
        + rendered_final
        + [""]
        + old_lines[section_end_idx:]
    )
    new_readme = "\n".join(new_lines) + "\n"
    _, _, _, parsed_new = parse_readme(new_readme)
    if parsed_new != final_entries:
        raise RuntimeError("Generated README failed round-trip parsing")
    if HEADING not in new_readme or new_readme.count(HEADING) != 1:
        raise RuntimeError("Section title was changed or duplicated!")

    print(f"\nFinal TODO entry count: {len(final_entries)} (baseline {len(baseline_entries)})")
    readme_diff = list(
        difflib.unified_diff(
            old_readme.splitlines(),
            new_readme.splitlines(),
            fromfile="README.md(old)",
            tofile="README.md(new)",
            lineterm="",
            n=1,
        )
    )
    # CI log should be enough to audit all changed location/message lines.
    print("\nREADME diff:")
    print("\n".join(readme_diff))

    if APPLY:
        readme_path.write_text(new_readme, encoding="utf-8", newline="\n")
        print(f"Wrote updated {readme_path}")
    else:
        print("DRY RUN (APPLY=false): README.md was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
