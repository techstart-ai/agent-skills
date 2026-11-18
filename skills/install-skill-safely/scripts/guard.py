#!/usr/bin/env python3
"""Inspect a skill in quarantine with SkillSpector, then install the inspected copy.

  guard.py inspect <git-url | local-dir> [--subdir PATH]
  guard.py install <quarantine-dir> <skill-subdir> <dest-skills-dir> [--user-approved]

inspect exit codes: 0 SAFE, 10 CAUTION, 20 DO_NOT_INSTALL or incomplete scan, 2 error.
The source is never executed: it is cloned with git hooks off, or copied.
Stdlib only.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
QUARANTINE = os.path.join(HOME, ".claude", "skill-quarantine")
LOG = os.path.join(HOME, ".claude", "skill-install-log.md")
VERDICT_FILE = "guard-verdict.json"
# Files that run code on install or on every session, so a human must read them.
AUTORUN = ("hooks.json", ".mcp.json", "package.json", "install.sh", "setup.py", "Makefile")


def die(msg):
    print("ERROR: " + msg)
    sys.exit(2)


def skillspector():
    exe = shutil.which("skillspector") or os.path.join(HOME, ".local", "bin", "skillspector")
    if not os.path.exists(exe):
        die("skillspector not found. Install: uv tool install --python 3.13 "
            "git+https://github.com/NVIDIA/skillspector.git")
    return exe


def fetch(source, qdir):
    """Put the source in qdir/src without running anything from it. Returns the commit or 'local'."""
    src = os.path.join(qdir, "src")
    if os.path.isdir(source):
        shutil.copytree(source, src, symlinks=True)
        return "local"
    if not source.startswith(("https://", "git@")):
        die("source must be an https/git URL or an existing directory: " + source)
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--depth", "1",
                        "--no-recurse-submodules", source, src], capture_output=True, text=True)
    if r.returncode:
        die("git clone failed: " + r.stderr.strip()[-300:])
    return subprocess.run(["git", "-C", src, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def inspect(source, subdir):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = os.path.basename(source.rstrip("/")).replace(".git", "") or "skill"
    qdir = os.path.join(QUARANTINE, "%s-%s" % (name, stamp))
    os.makedirs(qdir)
    commit = fetch(source, qdir)
    target = os.path.normpath(os.path.join(qdir, "src", subdir or ""))
    if not target.startswith(qdir) or not os.path.isdir(target):
        die("subdir not found inside the source: %s" % subdir)

    # Scan exactly what would be installed: each skill folder, grouped by its parent folder.
    if os.path.exists(os.path.join(target, "SKILL.md")):
        groups = {target: False}
    else:
        groups = {}
        for root, dirs, files in os.walk(target):
            dirs[:] = [x for x in dirs if x not in (".git", "node_modules")]
            if "SKILL.md" in files:
                groups[os.path.dirname(root)] = True
                dirs[:] = []
        if not groups:
            die("no SKILL.md found under %s" % target)
    skills, omitted, report = [], 0, os.path.join(qdir, "skillspector-*.json")
    for n, (gdir, recursive) in enumerate(sorted(groups.items())):
        rep = os.path.join(qdir, "skillspector-%d.json" % n)
        cmd = [skillspector(), "scan", gdir, "--no-llm", "--format", "json", "--output", rep]
        if recursive:
            cmd += ["--recursive", "--max-skills", "500"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 2 or not os.path.exists(rep):
            die("skillspector failed on %s: %s" % (gdir, (r.stderr or r.stdout).strip()[-400:]))
        d = json.load(open(rep))
        omitted += d.get("skills_omitted") or 0
        for s_ in (d["skills"] if d.get("multi_skill") else [d]):
            s_["_dir"] = os.path.relpath(os.path.join(gdir, s_.get("path") or "") if recursive else gdir, target)
            skills.append(s_)

    order = {"SAFE": 0, "CAUTION": 1, "DO_NOT_INSTALL": 2}
    worst, complete, rows = "SAFE", True, []
    for s in skills:
        ra = s.get("risk_assessment", {})
        rec = ra.get("recommendation", "DO_NOT_INSTALL")
        if order.get(rec, 2) > order[worst]:
            worst = rec
        if not (s.get("analysis_completeness") or {}).get("is_complete", False):
            complete = False
        rows.append((s["_dir"] if s["_dir"] != "." else name, rec,
                     ra.get("score"), s.get("issues", [])))
    if omitted:
        complete = False

    autorun = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules")]
        autorun += [os.path.relpath(os.path.join(root, f), target) for f in files if f in AUTORUN]
    licence = [f for f in os.listdir(os.path.join(qdir, "src")) if f.upper().startswith(("LICENSE", "LICENCE"))]

    verdict = worst if complete else "DO_NOT_INSTALL"
    json.dump({"verdict": verdict, "source": source, "commit": commit, "subdir": subdir or "",
               "complete": complete, "name": name, "skills": [r[0] for r in rows]},
              open(os.path.join(qdir, VERDICT_FILE), "w"))

    print("VERDICT: %s%s" % (verdict, "" if complete else " (scan incomplete)"))
    print("source: %s @ %s" % (source, commit))
    print("quarantine: %s" % qdir)
    print("skills: %d (only skill folders are scanned and installed) | licence file: %s"
          % (len(rows), ", ".join(licence) or "NONE"))
    print("auto-run files to read by hand: %s" % (", ".join(sorted(autorun)[:15]) or "none"))
    for name_, rec, score, issues in rows:
        if not issues and rec == "SAFE":
            continue
        print("- %s: %s score %s, %d finding(s)" % (name_, rec, score, len(issues)))
        seen = set()
        for i in sorted(issues, key=lambda x: ["CRITICAL", "HIGH", "MEDIUM", "LOW"].index(x.get("severity", "LOW"))
                        if x.get("severity") in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else 9):
            loc = i.get("location") or {}
            key = (i.get("id"), loc.get("file"), loc.get("start_line"))
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > 8:
                print("    ... more in %s" % report)
                break
            print("    %s %s %s:%s %s" % (i.get("severity"), i.get("id"), loc.get("file"),
                                           loc.get("start_line"), (i.get("pattern") or "")[:110]))
    sys.exit({"SAFE": 0, "CAUTION": 10}.get(verdict, 20))


def install(qdir, subdir, dest_root, approved):
    qdir = os.path.realpath(qdir)
    if not qdir.startswith(os.path.realpath(QUARANTINE) + os.sep):
        die("not a quarantine folder: " + qdir)
    try:
        v = json.load(open(os.path.join(qdir, VERDICT_FILE)))
    except (OSError, ValueError):
        die("no inspection verdict in %s; run inspect first" % qdir)
    # The user decides, not the scanner: anything short of SAFE needs their explicit yes.
    if v["verdict"] != "SAFE" and not approved:
        die("verdict is %s; show the user every risk and pass --user-approved only after they "
            "choose to proceed" % v["verdict"])
    src = os.path.normpath(os.path.join(qdir, "src", v["subdir"], subdir))
    if not src.startswith(qdir) or not os.path.exists(os.path.join(src, "SKILL.md")):
        die("no SKILL.md in %s" % src)
    root = os.path.normpath(os.path.join(qdir, "src"))
    dest = os.path.join(os.path.expanduser(dest_root), v["name"] if src == root else os.path.basename(src))
    if os.path.exists(dest):
        die("already exists, not overwriting: " + dest)
    shutil.copytree(src, dest, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    with open(LOG, "a") as f:
        f.write("- %s | %s | %s @ %s | verdict %s%s\n" % (
            datetime.date.today().isoformat(), dest, v["source"], v["commit"], v["verdict"],
            " (user approved)" if approved else ""))
    print("installed: %s (logged in %s)" % (dest, LOG))


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "inspect":
        sub = a[a.index("--subdir") + 1] if "--subdir" in a and len(a) > a.index("--subdir") + 1 else ""
        inspect(a[1], sub)
    elif len(a) >= 4 and a[0] == "install":
        install(a[1], a[2], a[3], "--user-approved" in a)
    else:
        die(__doc__)


if __name__ == "__main__":
    main()
