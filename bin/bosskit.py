#!/usr/bin/env python3
"""boss-kit core: where code and data live, which project and boss this is, the boss registry,
lessons, and the instruction loader. Every bin/ script imports it.

Code is the kit ($BOSS_KIT_HOME, else the folder above bin/). Data is $BOSS_HOME (default
~/.claude/boss):

  bosses.json                     registry: boss id -> project, workspace, worktree, host, heartbeat
  lessons.md                      shared lessons, for every boss
  <project>/BOSS.md config.json ledger.md lessons.md prompts/      shared by the project's bosses
  <project>/bosses/<boss-id>/     next.txt review.txt notes.md events.jsonl cache/ inbox/ inbox/done/

usage: bosskit.py show            the resolved paths, as JSON
       bosskit.py instructions    template + project BOSS.md + project and shared lessons (the /boss loader)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from types import SimpleNamespace

KIT = os.environ.get("BOSS_KIT_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STALE_S = 1800                      # a boss with no heartbeat for 30 min is not live
PRUNE_S = 7 * 86400                 # a registry entry silent for a week is dropped on the next write
SHARED_BUDGET_LINES, SHARED_RECENT = 150, 20
# The CLAUDE.local.md heading that makes a worktree a boss, optionally naming the one workspace that is.
MARKER = re.compile(r"^# Boss workspace(?:[ \t]+(\S+))?[ \t]*$", re.M)
DOMAIN = re.compile(r"^Domain:[ \t]*([A-Za-z0-9._-]+)[ \t]*$", re.M)
FOLDER = re.compile(r"^Folder:[ \t]*(\S(?:.*\S)?)[ \t]*$", re.M)
HEADING = re.compile(r"^## (\d+)\. (.*)$", re.M)


def home():
    return os.environ.get("BOSS_HOME") or os.path.expanduser("~/.claude/boss")


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def worktree(cwd=None):
    cwd = os.path.abspath(cwd or os.getcwd())
    return _git(cwd, "rev-parse", "--show-toplevel") or cwd


def projects(h=None):
    h = h or home()
    return [d for d in sorted(os.listdir(h)) if os.path.isfile(os.path.join(h, d, "config.json"))] if os.path.isdir(h) else []


def remote_repo(wt):
    """owner/repo of the worktree's origin, from an ssh or https remote."""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", _git(wt, "remote", "get-url", "origin"))
    return m.group(1).lower() if m else ""


def project_name(cwd=None, h=None):
    """$BOSS_PROJECT, then the worktree's .boss file, then its git remote, then the only project."""
    h = h or home()
    if os.environ.get("BOSS_PROJECT"):
        return os.environ["BOSS_PROJECT"]
    wt = worktree(cwd)
    try:
        m = re.search(r"^\s*project:\s*(\S+)", open(os.path.join(wt, ".boss")).read(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    names = projects(h)
    repo = remote_repo(wt)
    for name in names if repo else ():
        if json.load(open(os.path.join(h, name, "config.json"))).get("repo", "").lower() == repo:
            return name
    if len(names) == 1:
        return names[0]
    sys.exit("bosskit: no project for %s (set BOSS_PROJECT, add a .boss file, or run bin/boss-init; found: %s)"
             % (wt, ", ".join(names) or "none"))


def boss_id(cwd=None, h=None):
    """The Paradev workspace id when running inside one, else the workspace this worktree registered
    under (a process started without the workspace's env, like a mod's), else a short hash of the path."""
    if os.environ.get("SUPERSET_WORKSPACE_ID"):
        return os.environ["SUPERSET_WORKSPACE_ID"]
    wt = worktree(cwd)
    known = [(b.get("heartbeat", 0), i) for i, b in registry(h).items() if b.get("worktree") == wt and b.get("workspace") == i]
    return max(known)[1] if known else "wt-" + hashlib.sha1(wt.encode()).hexdigest()[:8]


def load(cwd=None, name=None):
    h = home()
    name = name or project_name(cwd, h)
    pdir = os.path.join(h, name)
    with open(os.path.join(pdir, "config.json")) as f:
        cfg = json.load(f)
    bid = boss_id(cwd, h)
    bdir = os.path.join(pdir, "bosses", bid)
    for d in ("cache", "inbox/done"):
        os.makedirs(os.path.join(bdir, d), exist_ok=True)
    return SimpleNamespace(home=h, name=name, cfg=cfg, pdir=pdir, bid=bid, bdir=bdir, worktree=worktree(cwd),
                           workspace="" if bid.startswith("wt-") else bid,
                           cache=os.path.join(bdir, "cache"), inbox=os.path.join(bdir, "inbox"))


def boss_marker(wt):
    """The worktree's boss marker: None when absent, else the workspace id it binds ('' for a bare marker)."""
    m = MARKER.search(_read(os.path.join(wt, "CLAUDE.local.md")))
    return None if m is None else (m.group(1) or "")


def boss_domain(wt):
    """The domain this boss owns inside its project ('' for the project's main boss): a 'Domain: <name>' line in
    CLAUDE.local.md. A domain boss also loads <project>/domains/<name>.md (its charter) and <name>-state.md (its notes)."""
    m = DOMAIN.search(_read(os.path.join(wt, "CLAUDE.local.md")))
    return m.group(1) if m else ""


def boss_folder(wt):
    """The Paradev sidebar folder (workspace tag) a domain boss owns: a 'Folder: <tag>' line in CLAUDE.local.md (spaces
    allowed), else its domain name. '' for the project's main boss, which covers every folder."""
    domain = boss_domain(wt)
    m = FOLDER.search(_read(os.path.join(wt, "CLAUDE.local.md"))) if domain else None
    return m.group(1) if m else domain


def is_boss(ctx):
    """The marker is there and, when it names a workspace, this session is that workspace. A copy of the
    boss's CLAUDE.local.md in another worktree, or another workspace on the same checkout, is then no boss."""
    bound = boss_marker(ctx.worktree)
    return bound is not None and bound in ("", os.environ.get("SUPERSET_WORKSPACE_ID", ""))


def not_boss_note(ctx):
    bound = boss_marker(ctx.worktree)
    if bound is None:
        return f"Not a boss: {ctx.worktree}/CLAUDE.local.md has no '# Boss workspace' heading."
    return (f"Not the boss: CLAUDE.local.md binds the boss to workspace {bound}, and this session is "
            f"{os.environ.get('SUPERSET_WORKSPACE_ID') or 'outside Paradev'}. Ignore the boss instructions and work as a normal session.")


# ---- registry -------------------------------------------------------------------------------

def registry(h=None):
    try:
        return json.load(open(os.path.join(h or home(), "bosses.json")))
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    """Write atomically, so two bosses refreshing at once never leave half a file."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def heartbeat(ctx, host="", summary=None, now=None):
    """Write this boss's entry, dropping entries silent past PRUNE_S and any other entry for this
    boss's workspace or worktree (an id it was once known by)."""
    # ponytail: read-modify-write without a lock; a lost heartbeat is rewritten on the next refresh
    os.makedirs(ctx.home, exist_ok=True)
    now = int(now or time.time())
    reg = {i: b for i, b in registry(ctx.home).items()
           if i != ctx.bid and now - b.get("heartbeat", 0) < PRUNE_S and not same_boss(b, ctx.workspace, ctx.worktree)}
    reg[ctx.bid] = {"project": ctx.name, "workspace": ctx.workspace, "worktree": ctx.worktree, "host": host,
                    "heartbeat": now, **(summary or {})}
    save_json(os.path.join(ctx.home, "bosses.json"), reg)


def same_boss(entry, workspace, wt):
    """Whether a registry entry names the boss of this workspace or worktree."""
    return bool((workspace and entry.get("workspace") == workspace) or (wt and entry.get("worktree") == wt))


def live(reg, now=None, project=None):
    now = now or time.time()
    return {i: b for i, b in reg.items()
            if now - b.get("heartbeat", 0) < STALE_S and (project is None or b.get("project") == project)}


def tracker_snapshot(ctx):
    """The tracker snapshot boss-tasks.py last wrote: cache/tracker.json, else the pre-0.5 one a
    migration left in the boss dir. None when there is neither."""
    for path in (os.path.join(ctx.cache, "tracker.json"), os.path.join(ctx.bdir, "tracker.json")):
        try:
            return json.load(open(path))
        except (OSError, ValueError):
            continue
    return None


# ---- events: each workspace's stage log, one JSON line {at, ws, stage, note} ------------------

def add_event(ctx, ws, stage, note="", now=None):
    """Append one stage event to this boss's events.jsonl and return it."""
    e = {"at": int(now or time.time()), "ws": ws, "stage": stage, "note": note}
    with open(os.path.join(ctx.bdir, "events.jsonl"), "a") as f:
        f.write(json.dumps(e) + "\n")
    return e


def events(bdir):
    """This boss's stage events, oldest first; unreadable lines are skipped."""
    # ponytail: reads the whole log each refresh; trim old lines if it ever grows past a few thousand
    out = []
    for line in _read(os.path.join(bdir, "events.jsonl")).splitlines():
        try:
            e = json.loads(line)
            out.append({"at": int(e["at"]), "ws": str(e["ws"]), "stage": str(e["stage"]), "note": str(e.get("note") or "")})
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(out, key=lambda e: e["at"])


# ---- lessons --------------------------------------------------------------------------------

def lesson_entries(text):
    """[(number, heading line, full entry text)] of a lessons file."""
    marks = list(HEADING.finditer(text or ""))
    return [(int(m.group(1)), m.group(0), text[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(text))].rstrip())
            for i, m in enumerate(marks)]


def shared_view(text, budget=SHARED_BUDGET_LINES, recent=SHARED_RECENT):
    """The shared lessons as loaded: whole when short, else every title plus the newest entries in full."""
    if len(text.splitlines()) <= budget:
        return text
    entries = lesson_entries(text)
    titles = "\n".join(f"- {h[3:]}" for _, h, _ in entries)
    full = "\n\n".join(e for _, _, e in entries[-recent:])
    return (f"(Shared lessons are {len(text.splitlines())} lines, over the {budget}-line budget: every title, then the "
            f"{recent} most recent in full. Read {os.path.join(home(), 'lessons.md')} for the rest.)\n\n"
            f"### All titles\n{titles}\n\n### Most recent\n{full}\n")


def _read(path):
    try:
        return open(path).read()
    except OSError:
        return ""


def instructions(ctx):
    parts = [("BOSS-template.md", _read(os.path.join(KIT, "BOSS-template.md"))),
             (f"{ctx.name}/BOSS.md", _read(os.path.join(ctx.pdir, "BOSS.md"))),
             (f"{ctx.name}/lessons.md (project lessons)", _read(os.path.join(ctx.pdir, "lessons.md"))),
             ("lessons.md (shared lessons)", shared_view(_read(os.path.join(ctx.home, "lessons.md"))))]
    domain = boss_domain(ctx.worktree)
    if domain:
        ddir = os.path.join(ctx.pdir, "domains")
        parts.insert(2, (f"{ctx.name}/domains/{domain}.md (domain charter)", _read(os.path.join(ddir, f"{domain}.md"))))
        parts.insert(3, (f"{ctx.name}/domains/{domain}-state.md (domain state, you keep it current)", _read(os.path.join(ddir, f"{domain}-state.md"))))
    head = f"# Boss session: project {ctx.name}, boss {ctx.bid}" + (f", domain {domain}" if domain else "") + "\n"
    if domain:
        head += (f"\nYour folder: Paradev workspaces tagged '{boss_folder(ctx.worktree)}'. Tag every workspace you create with it, and read, "
                 "message, verify and archive only workspaces in it; anything else goes to the main boss by boss-mail.\n")
    return head + "".join(f"\n\n<!-- {name} -->\n\n{body.strip()}\n" for name, body in parts if body.strip())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    ctx = load()
    if cmd == "show":
        print(json.dumps({"kit": KIT, "home": ctx.home, "project": ctx.name, "boss": ctx.bid, "worktree": ctx.worktree,
                          "boss_md": os.path.join(ctx.pdir, "BOSS.md"), "ledger": os.path.join(ctx.pdir, ctx.cfg.get("ledger", "ledger.md")),
                          "lessons": os.path.join(ctx.pdir, "lessons.md"), "shared_lessons": os.path.join(ctx.home, "lessons.md"),
                          "boss_dir": ctx.bdir, "next": os.path.join(ctx.bdir, "next.txt"),
                          "review": os.path.join(ctx.bdir, "review.txt"), "inbox": ctx.inbox, "is_boss": is_boss(ctx)}, indent=1))
    elif cmd == "instructions":
        print(instructions(ctx) if is_boss(ctx) else not_boss_note(ctx))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
