#!/usr/bin/env python3
import json, os, re, subprocess, sys, tokenize
from pathlib import Path

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
README = ROOT / "README.md"
HEADING = "### 📝 Complete TODO List"
ENTRY_RE = re.compile(r"^- \[ \] \*\*(?P<path>.+?):(?P<line>\d+)\*\* - (?P<message>.*)$")
EXPECTED = {
    "luffy/deepscaler/utils.py": [
        (45, "Add logging for API calls and errors"),
        (46, "Support batch processing for multiple prompts"),
        (47, "Add timeout configuration for API calls"),
        (107, "Implement Vertex AI initialization and authentication"),
        (108, "Configure safety settings for content generation"),
        (109, "Set up GenerativeModel with proper system instructions"),
        (110, "Implement retry logic with exponential backoff"),
        (111, "Add comprehensive error handling for API access issues"),
        (112, "Handle rate limiting and quota management"),
        (113, "Implement response validation and text extraction"),
        (114, "Add support for different generation configurations"),
    ],
    "luffy/verl/verl/protocol.py": [
        (114, "Optimize memory usage during tensor reshaping"),
        (115, "Add support for different tensor types and shapes"),
        (136, "Optimize tensor view operations for performance"),
        (137, "Add error handling for invalid batch dimensions"),
        (169, "(zhangchi.usc1992) add consistency check"),
        (265, "we can actually lift this restriction if needed"),
        (351, "(zhangchi.usc1992) whether to copy"),
    ],
}

def git_lines(args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).splitlines()

def message_from_comment(comment):
    idx = comment.find("TODO")
    if idx < 0:
        return None
    msg = comment[idx + 4:].strip()
    # Ordinary TODOs use a colon immediately after TODO. Tagged TODOs begin
    # with "(author)" and retain their original separator/text.
    if msg.startswith(":"):
        msg = msg[1:].strip()
    return msg

def extract_todos(relpath):
    path = ROOT / relpath
    if not path.exists():
        return []
    rows = []
    try:
        with tokenize.open(path) as fh:
            for tok in tokenize.generate_tokens(fh.readline):
                if tok.type == tokenize.COMMENT and "TODO" in tok.string:
                    msg = message_from_comment(tok.string)
                    if msg is not None:
                        rows.append({"path": relpath, "line": tok.start[0], "message": msg})
    except (tokenize.TokenError, SyntaxError, UnicodeError):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "#" in line and "TODO" in line[line.find("#"):]:
                msg = message_from_comment(line[line.find("#"):])
                if msg is not None:
                    rows.append({"path": relpath, "line": lineno, "message": msg})
    return rows

def render(entry):
    return f"- [ ] **{entry['path']}:{entry['line']}** - {entry['message']}"

def main():
    changed = sorted(x for x in git_lines(["diff", "--name-only", "origin/main...HEAD", "--"]) if x.endswith(".py"))
    print("Changed Python files:", json.dumps(changed, indent=2))
    if set(changed) != set(EXPECTED):
        raise SystemExit(f"Unexpected changed Python files: {changed!r}")

    all_rows = []
    for path in sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.py") if ".git" not in p.relative_to(ROOT).parts):
        rows = extract_todos(path)
        if rows:
            all_rows.extend(rows)
    all_rows.sort(key=lambda e: (e["path"], e["line"]))
    Path("/tmp/all_todos_extracted.json").write_text(json.dumps(all_rows, indent=2, ensure_ascii=False) + "\n")
    print(f"Extracted {len(all_rows)} TODO comments from all Python files")

    new_by_path = {}
    for path in changed:
        rows = extract_todos(path)
        actual = [(e["line"], e["message"]) for e in rows]
        print(f"\n{path}: {len(rows)} TODOs")
        for line, msg in actual:
            print(f"  {line}: {msg}")
        if actual != EXPECTED[path]:
            raise SystemExit(f"Parsed TODOs do not match verified expectation for {path}: {actual!r}")
        new_by_path[path] = rows

    text = README.read_text(encoding="utf-8")
    trailing_newline = text.endswith("\n")
    lines = text.splitlines()
    if lines.count(HEADING) != 1:
        raise SystemExit("Expected exactly one Complete TODO List heading")
    h = lines.index(HEADING)
    next_h2 = next(i for i in range(h + 1, len(lines)) if lines[i].startswith("## "))
    matches = []
    for i in range(h + 1, next_h2):
        m = ENTRY_RE.match(lines[i])
        if m:
            matches.append((i, {"path": m.group("path"), "line": int(m.group("line")), "message": m.group("message"), "raw": lines[i]}))
    if not matches:
        raise SystemExit("No README TODO entries found")
    first, last = matches[0][0], matches[-1][0]
    for i in range(first, last + 1):
        if not ENTRY_RE.match(lines[i]):
            raise SystemExit(f"Non-entry line among TODO entries at line {i+1}: {lines[i]!r}")

    old_entries = [e for _, e in matches]
    changed_set = set(changed)
    combined = [e for e in old_entries if e["path"] not in changed_set]
    for rows in new_by_path.values():
        combined.extend(rows)
    combined.sort(key=lambda e: (e["path"], e["line"]))
    rendered = [render(e) for e in combined]
    unchanged_before = [e["raw"] for e in old_entries if e["path"] not in changed_set]
    unchanged_after = [render(e) for e in combined if e["path"] not in changed_set]
    if unchanged_before != unchanged_after:
        raise SystemExit("Unchanged README entries were reordered or rewritten")

    updated = lines[:h+1] + lines[h+1:first] + rendered + lines[last+1:next_h2] + lines[next_h2:]
    new_text = "\n".join(updated)
    if trailing_newline:
        new_text += "\n"
    if new_text == text:
        raise SystemExit("README would not change")
    if HEADING not in new_text:
        raise SystemExit("Heading missing after update")
    README.write_text(new_text, encoding="utf-8")
    print(f"\nREADME entries: old={len(old_entries)}, new={len(combined)}")
    print("README updated successfully")

if __name__ == "__main__":
    main()
