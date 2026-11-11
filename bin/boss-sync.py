#!/usr/bin/env python3
"""boss-sync: keep open PR branches conflict-free against their base. Zero LLM, token-frugal.

For each selected open PR (stacked ones after their base): merge origin/<base> into the branch in a
throwaway worktree (no node_modules needed), resolve conflicts that are ONLY in generated files by taking
the base's copy and re-running a regen command, abort and report anything else. Never force-pushes.

usage (run inside the project's git checkout or one of its worktrees):
  boss-sync.py --all|--only=N,N [--skip=N,N] [--push] [--if-moved]
               [--gen=README.md,docs/README.md --regen="node scripts/make-index.mjs"]
  no --push = dry run.  --if-moved = exit after one `git ls-remote` when the default branch has not moved
  since the last --push run.  Output is quiet: changed branches and NEW real conflicts only.
"""
import json, os, shutil, subprocess, sys, tempfile

args = sys.argv[1:]
def opt(name, default=""):
    return next((a.split("=", 1)[1] for a in args if a.startswith(name + "=")), default)
def nums(name):
    return {int(x) for x in opt(name).split(",") if x}

PUSH, ALL, IFMOVED = "--push" in args, "--all" in args, "--if-moved" in args
ONLY, SKIP = nums("--only"), nums("--skip")
GEN = {f for f in opt("--gen").split(",") if f}
REGEN = opt("--regen")
if not (ALL or ONLY):
    sys.exit("pass --all or --only=N,N (explicit scope keeps worktree work bounded)")

def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd or REPO, capture_output=True, text=True)

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
if not REPO:
    sys.exit("run inside the git repo")
DEFAULT = json.loads(sh("gh", "repo", "view", "--json", "defaultBranchRef").stdout)["defaultBranchRef"]["name"]
STATE_DIR = os.path.join(os.environ.get("BOSS_HOME") or os.path.expanduser("~/.claude/boss"), "sync")
os.makedirs(STATE_DIR, exist_ok=True)
STATE = os.path.join(STATE_DIR, REPO.strip("/").replace("/", "_") + ".json")
try:
    st = json.load(open(STATE))
except Exception:
    st = {}
head_sha = sh("git", "ls-remote", "origin", f"refs/heads/{DEFAULT}").stdout.split()[0]
if IFMOVED and st.get("base") == head_sha and not ONLY:
    print(f"{DEFAULT} unchanged ({head_sha[:9]}), nothing to do"); sys.exit(0)

sh("git", "fetch", "origin", "--prune", "-q")
prs = json.loads(sh("gh", "pr", "list", "--state", "open", "--limit", "200",
                    "--json", "number,headRefName,baseRefName,isDraft").stdout)
prs = [p for p in prs if p["number"] not in SKIP and (not ONLY or p["number"] in ONLY)]
by_head = {p["headRefName"]: p for p in prs}

def depth(p):
    d = 0
    while p["baseRefName"] in by_head:
        p = by_head[p["baseRefName"]]; d += 1
        if d > 50: break
    return d

prs.sort(key=depth)
tmp = tempfile.mkdtemp(prefix="boss-sync-")
report = []
for p in prs:
    n, head, base = p["number"], p["headRefName"], p["baseRefName"]
    if sh("git", "merge-base", "--is-ancestor", f"origin/{base}", f"origin/{head}").returncode == 0:
        report.append((n, "up to date")); continue
    wt = os.path.join(tmp, f"pr{n}")
    try:
        r = sh("git", "worktree", "add", "--detach", wt, f"origin/{head}")
        if r.returncode:
            report.append((n, "ERROR worktree: " + r.stderr.strip()[:150])); continue
        git = lambda *a: sh("git", "-c", "core.hooksPath=/dev/null", *a, cwd=wt)
        if git("merge", "--no-edit", f"origin/{base}").returncode == 0:
            status = "merged clean"
        else:
            un = [f for f in git("diff", "--name-only", "--diff-filter=U").stdout.split() if f]
            if not un or not GEN or any(f not in GEN for f in un) or not REGEN:
                git("merge", "--abort")
                report.append((n, "REAL CONFLICT: " + ", ".join(un[:5]))); continue
            for f in un:
                git("checkout", f"origin/{base}", "--", f)
            g = subprocess.run(REGEN, shell=True, cwd=wt, capture_output=True, text=True)
            if g.returncode:
                git("merge", "--abort"); report.append((n, "regen failed: " + g.stderr.strip()[:150])); continue
            git("add", "-A", "--", *sorted(GEN))
            if git("commit", "--no-edit").returncode:
                git("merge", "--abort"); report.append((n, "commit failed")); continue
            status = "merged, generated files regenerated"
        if sh("git", "merge-tree", "--write-tree", "--name-only", "--no-messages", f"origin/{base}", "HEAD", cwd=wt).returncode:
            report.append((n, "STILL CONFLICTS after sync (not pushed)")); continue
        if PUSH:
            pu = sh("git", "push", "origin", f"HEAD:{head}", cwd=wt)  # plain push, never --force
            status += " + pushed" if pu.returncode == 0 else " (PUSH FAILED: " + pu.stderr.strip()[:120] + ")"
            sh("git", "fetch", "origin", head, "-q")
        else:
            status += " (dry run, not pushed)"
        report.append((n, status))
    finally:
        sh("git", "worktree", "remove", "--force", wt)
shutil.rmtree(tmp, ignore_errors=True)

known = st.get("conflicts", {})
quiet = [n for n, x in report if x == "up to date"]
again = [n for n, x in report if x.startswith("REAL CONFLICT") and known.get(str(n)) == head_sha]
for n, x in report:
    if n not in quiet and n not in again:
        print(n, x)
if again:
    print("still conflicting, already reported at this base:", ", ".join(map(str, again)))
print(f"{len(quiet)} up to date at {head_sha[:9]}")
if PUSH:
    json.dump({"base": head_sha, "conflicts": {str(n): head_sha for n, x in report if x.startswith("REAL CONFLICT")}}, open(STATE, "w"))