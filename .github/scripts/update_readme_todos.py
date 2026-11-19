#!/usr/bin/env python3
from __future__ import annotations
import difflib, os, re, subprocess, sys
from collections import OrderedDict
from pathlib import Path

R = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
BASE = os.environ.get("BASE_REF", "origin/main")
APPLY = os.environ.get("APPLY", "false").lower() == "true"
H = "### 📝 Complete TODO List"
ROW = re.compile(r"^- \[ \] \*\*(?P<p>.+?):(?P<n>\d+)\*\* - (?P<m>.*)$")
TODO = re.compile(r"#\s*TODO:?[ \t]*(?P<m>.*?)[ \t]*$")

def git(*args, check=True):
    p = subprocess.run(["git", *args], cwd=R, text=True, capture_output=True)
    if check and p.returncode:
        raise SystemExit(f"git {' '.join(args)} failed\n{p.stdout}\n{p.stderr}")
    return p.stdout

def scan_text(text):
    out=[]
    for n,line in enumerate(text.splitlines(),1):
        m=TODO.search(line)
        if m and m.group("m").strip():
            out.append((n,m.group("m").strip()))
    return out

def show_main(path):
    p=subprocess.run(["git","show",f"{BASE}:{path}"],cwd=R,text=True,capture_output=True)
    return p.stdout if p.returncode==0 else None

readme=R/"README.md"
old=readme.read_text()
lines=old.splitlines()
hs=[i for i,x in enumerate(lines) if x==H]
assert len(hs)==1, f"title count {len(hs)}"
h=hs[0]
e=next(i for i in range(h+1,len(lines)) if lines[i].startswith("## "))
entries=[]
for i in range(h+1,e):
    if not lines[i].strip(): continue
    m=ROW.match(lines[i]); assert m, f"bad README line {i+1}: {lines[i]}"
    entries.append((m["p"],int(m["n"]),m["m"]))
assert entries == sorted(entries,key=lambda x:(x[0],x[1])), "baseline not sorted"
groups=OrderedDict()
for p,n,msg in entries: groups.setdefault(p,[]).append((n,msg))
print(f"Baseline TODO rows: {len(entries)} in {len(groups)} files")

statuses=[x.split("\t") for x in git("diff","--name-status","-M",BASE).splitlines() if x]
changed=set()
print("Changed files main -> current tree:")
for parts in statuses:
    print("  "+" | ".join(parts))
    ps=parts[1:]
    if any(p.endswith(".py") and not p.startswith(".github/") for p in ps):
        changed.update(p for p in ps if not p.startswith(".github/"))
assert changed, "no changed Python files found"
print("Selected Python groups:", ", ".join(sorted(changed)))

replacements={}
for p in sorted(changed):
    old_text=show_main(p)
    old_scan=scan_text(old_text) if old_text is not None else []
    baseline=groups.get(p,[])
    # A changed existing group must be parsed exactly before replacement.
    if p in groups:
        assert old_scan == baseline, (
            f"parser/baseline mismatch for {p}\nscan={old_scan!r}\nreadme={baseline!r}"
        )
    cur_path=R/p
    new_scan=scan_text(cur_path.read_text()) if cur_path.exists() else []
    assert new_scan == sorted(new_scan), f"unsorted scan for {p}"
    replacements[p]=new_scan
    print(f"{p}: {len(baseline)} README old rows / {len(old_scan)} main markers -> {len(new_scan)} dev markers")
    for n,msg in new_scan: print(f"  {n}: {msg}")

final=OrderedDict((p,list(v)) for p,v in groups.items())
for p,items in replacements.items():
    if items: final[p]=items
    else: final.pop(p,None)
final_entries=[(p,n,m) for p in sorted(final) for n,m in sorted(final[p])]
render=[f"- [ ] **{p}:{n}** - {m}" for p,n,m in final_entries]
new_text="\n".join(lines[:h+1]+[""]+render+[""]+lines[e:])+"\n"
# Round-trip and invariant checks.
new_lines=new_text.splitlines()
nh=new_lines.index(H); ne=next(i for i in range(nh+1,len(new_lines)) if new_lines[i].startswith("## "))
parsed=[]
for line in new_lines[nh+1:ne]:
    if line.strip():
        m=ROW.match(line); assert m, line
        parsed.append((m["p"],int(m["n"]),m["m"]))
assert parsed==final_entries
assert new_text.count(H)==1
print(f"Final rows: {len(final_entries)} (delta {len(final_entries)-len(entries):+d})")
diff=list(difflib.unified_diff(old.splitlines(),new_text.splitlines(),fromfile="README old",tofile="README new",lineterm="",n=1))
print("README DIFF BEGIN")
print("\n".join(diff))
print("README DIFF END")
if APPLY:
    readme.write_text(new_text,encoding="utf-8",newline="\n")
    print("README updated")
else:
    print("DRY RUN; set APPLY=true to write")
