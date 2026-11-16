#!/usr/bin/env python3
"""boss-kit core: where code and data live, which project and boss this is, the boss registry,
lessons, and the instruction loader. Every bin/ script imports it.

Code is the kit ($BOSS_KIT_HOME, else the folder above bin/). Data is $BOSS_HOME (default
~/.claude/boss):

  bosses.json                     registry: boss id -> project, workspace, worktree, host, heartbeat
  lessons.md                      shared lessons, for every boss
  <project>/BOSS.md config.json ledger.md lessons.md prompts/      shared by the project's bosses
  <project>/bosses/<boss-id>/     next.txt review.txt notes.md events.jsonl cache/ inbox/ inbox/done/

Config is layered, later wins (dicts deep-merged, lists replaced): the kit's DEFAULTS, $BOSS_HOME/config.json (user),
<project>/config.json (project), <project>/bosses/<boss-id>/config.json (one boss).

usage: bosskit.py show            the resolved paths, as JSON
       bosskit.py instructions    template + host commands + project BOSS.md + project and shared lessons (the /boss loader)
       bosskit.py config show [--json]                                 every config key, its value and the layer it came from
       bosskit.py config set --level user|project|boss KEY=VALUE... [--apply]
                                  shows the resolved config after the change; writes only with --apply
       bosskit.py detect          the environment, as JSON: host CLIs, gh, git, $BOSS_HOME (for onboarding)
"""
import hashlib
import json
import os
import re
import shutil
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
# The first line of a worker's completion envelope. BOSS_ is what dispatches ask for; SUPERSET_ is the older token.
ENVELOPE = r"(?:BOSS|SUPERSET)_WORKER_(DONE|BLOCKED)"
HOSTS = ("superset", "coderplex")
LEVELS = ("user", "project", "boss")
# The kit's config layer: every key a boss reads, with its default.
DEFAULTS = {
    "host": "",                 # superset | coderplex; "" detects it from the session (see host_kind)
    "superset_host": "",        # superset only: the host id; "" = the first host
    "base_branch": "main",
    "ledger": "ledger.md",
    "wake": False,              # mail to this boss also messages its session
    "extra_prs": [],
    "tracker": {"type": "none"},
    "models": {"strong": "opus", "mid": "sonnet", "cheap": "haiku"},
    "effort": "",
    "pages": "auto",            # where proof and review pages go: auto (the host's pages, else a claude.ai artifact) | host | artifact
    "boss_name": "BOSS",        # what the boss names its own workspace or session at session start; "" leaves it
}


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


def self_id():
    """This session's id on its host: the Paradev workspace, else the coderplex session; '' outside both."""
    return os.environ.get("SUPERSET_WORKSPACE_ID") or os.environ.get("CODERPLEX_SESSION_ID") or ""


def host_kind(cfg=None):
    """Which host runs the workers: config's host, else the session's own (the pane passes it as $BOSS_HOST_KIND),
    else whichever CLI is installed, else superset. No host set inside a Paradev workspace is superset, as before."""
    for kind in ((cfg or {}).get("host"), os.environ.get("BOSS_HOST_KIND")):
        if kind in HOSTS:
            return kind
    if os.environ.get("SUPERSET_WORKSPACE_ID"):
        return "superset"
    if os.environ.get("CODERPLEX_SESSION_ID"):
        return "coderplex"
    has_superset = shutil.which("superset") or os.path.exists(os.path.expanduser("~/.superset/bin/superset"))
    return "coderplex" if not has_superset and shutil.which("coderplex-ctl") else "superset"


def boss_id(cwd=None, h=None):
    """This session's host id (a Paradev workspace or coderplex session) when running inside one, else the workspace
    this worktree registered under (a process started without the session's env, like a mod's), else a short hash of the path."""
    if self_id():
        return self_id()
    wt = worktree(cwd)
    known = [(b.get("heartbeat", 0), i) for i, b in registry(h).items() if b.get("worktree") == wt and b.get("workspace") == i]
    return max(known)[1] if known else "wt-" + hashlib.sha1(wt.encode()).hexdigest()[:8]


def load(cwd=None, name=None):
    h = home()
    name = name or project_name(cwd, h)
    pdir = os.path.join(h, name)
    json.load(open(os.path.join(pdir, "config.json")))  # the project's own layer must parse
    bid = boss_id(cwd, h)
    bdir = os.path.join(pdir, "bosses", bid)
    for d in ("cache", "inbox/done"):
        os.makedirs(os.path.join(bdir, d), exist_ok=True)
    layers = config_layers(h, name, bid)
    cfg = merged(layers)
    return SimpleNamespace(home=h, name=name, cfg=cfg, layers=layers, host=host_kind(cfg), pdir=pdir, bid=bid, bdir=bdir,
                           worktree=worktree(cwd), workspace="" if bid.startswith("wt-") else bid,
                           cache=os.path.join(bdir, "cache"), inbox=os.path.join(bdir, "inbox"))


# ---- config: kit defaults < user < project < boss --------------------------------------------

def layer_path(h, level, project=None, bid=None):
    return {"user": os.path.join(h, "config.json"), "project": os.path.join(h, project or "", "config.json"),
            "boss": os.path.join(h, project or "", "bosses", bid or "", "config.json")}[level]


def _json_file(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except OSError:
        return {}
    except ValueError as e:
        sys.exit(f"bosskit: {path} is not valid JSON: {e}")


def config_layers(h, project, bid=None):
    """[(layer, path, dict)], lowest first: kit, user, project, and the boss's own when bid is given."""
    out = [("kit", "", DEFAULTS), ("user", layer_path(h, "user"), _json_file(layer_path(h, "user"))),
           ("project", layer_path(h, "project", project), _json_file(layer_path(h, "project", project)))]
    if bid:
        out.append(("boss", layer_path(h, "boss", project, bid), _json_file(layer_path(h, "boss", project, bid))))
    return out


def deep_merge(a, b):
    """b over a: dicts merge key by key, anything else (lists too) is replaced."""
    out = dict(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def merged(layers):
    cfg = {}
    for _, _, d in layers:
        cfg = deep_merge(cfg, d)
    return cfg


def config_for(h, project, bid=None):
    """A project's resolved config without loading a boss (worker mode, mail)."""
    return merged(config_layers(h, project, bid))


def sources(layers):
    """{dotted leaf key: (value, layer)} of the merged config: the layer each value comes from."""
    out = {}

    def walk(d, layer, prefix=""):
        for k, v in d.items():
            key = prefix + k
            if isinstance(v, dict) and v:
                for old in [o for o in out if o == key]:  # a dict replaces a scalar set lower down
                    del out[old]
                walk(v, layer, key + ".")
            else:
                for old in [o for o in out if o.startswith(key + ".")]:  # a scalar replaces a whole dict
                    del out[old]
                out[key] = (v, layer)
    for layer, _, d in layers:
        walk(d, layer)
    return dict(sorted(out.items()))


def show_config(layers, as_json=False):
    src = sources(layers)
    if as_json:
        return json.dumps({k: {"value": v, "from": l} for k, (v, l) in src.items()}, indent=1)
    width = max(map(len, src), default=0)
    files = "\n".join(f"  {l:<8} {p}{'' if os.path.exists(p) else '  (none)'}" for l, p, _ in layers if p)
    return "\n".join(f"{k:<{width}}  {json.dumps(v)}  ({l})" for k, (v, l) in src.items()) + "\n\nlayers, later wins:\n  kit      DEFAULTS in bin/bosskit.py\n" + files


def parse_sets(pairs):
    """KEY=VALUE pairs (dotted keys nest) as one dict; a value is JSON when it parses, else a string."""
    out = {}
    for pair in pairs:
        key, eq, raw = pair.partition("=")
        if not eq or not key:
            sys.exit(f"bosskit: expected KEY=VALUE, got {pair!r}")
        try:
            val = json.loads(raw)
        except ValueError:
            val = raw
        d = out
        *parents, leaf = key.split(".")
        for p in parents:
            d = d.setdefault(p, {})
        d[leaf] = val
    return out


def set_config(layers, level, change, apply=False, now=None):
    """The resolved config with *change* merged into *level*'s file, as text; with apply, writes that file
    (merged into what is there, an existing file copied to <file>.bak-<time> first)."""
    path = next((p for l, p, _ in layers if l == level), None)
    if not path:
        sys.exit(f"bosskit: no {level} layer here (boss needs a resolved boss, project a resolved project)")
    new = [(l, p, deep_merge(d, change) if l == level else d) for l, p, d in layers]
    body = next(d for l, _, d in new if l == level)
    text = show_config(new) + f"\n\n{'wrote' if apply else 'would write'} {path}:\n" + json.dumps(body, indent=1)
    if apply:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            shutil.copy2(path, f"{path}.bak-{int(now or time.time())}")
        save_json(path, body)
    else:
        text += "\n\n(dry run: nothing written; add --apply to write)"
    return text


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
    return bound is not None and bound in ("", self_id())


def not_boss_note(ctx):
    bound = boss_marker(ctx.worktree)
    if bound is None:
        return f"Not a boss: {ctx.worktree}/CLAUDE.local.md has no '# Boss workspace' heading."
    return (f"Not the boss: CLAUDE.local.md binds the boss to workspace {bound}, and this session is "
            f"{self_id() or 'outside a host session'}. Ignore the boss instructions and work as a normal session.")


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


# ---- leftovers: what archiving a worktree would lose (BOSS-template.md section 8) ------------

# Ignored output a fresh checkout rebuilds: dependency and build folders, caches, the boss's worker notes.
REBUILDABLE = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
               "out", ".next", ".turbo", ".cache", ".parcel-cache", "coverage", "target", ".gradle", ".boss-worker"}


def leftovers(wt, branch):
    """Uncommitted files, commits not on origin/<branch>, and ignored files beyond rebuildable output, one line each.
    [] means the worktree can be archived."""
    if not os.path.isdir(wt):
        return [f"worktree {wt} is missing"]
    out = []
    for line in subprocess.run(["git", "-C", wt, "status", "--porcelain", "--ignored"], capture_output=True, text=True).stdout.splitlines():
        path = line[3:].rstrip("/")
        if not line.startswith("!! "):
            out.append(f"uncommitted: {line}")
        elif not REBUILDABLE.intersection(path.split("/")) and not path.endswith(".pyc"):
            out.append(f"ignored: {path}")
    if not _git(wt, "rev-parse", "--verify", "-q", f"origin/{branch}"):
        return out + [f"unpushed: origin/{branch} not found, cannot tell"]
    return out + [f"unpushed: {c}" for c in _git(wt, "log", "--oneline", f"origin/{branch}..HEAD").splitlines()]


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
             (f"hosts/{ctx.host}.md (host commands)", _read(os.path.join(KIT, "hosts", f"{ctx.host}.md"))),
             (f"{ctx.name}/BOSS.md", _read(os.path.join(ctx.pdir, "BOSS.md"))),
             (f"{ctx.name}/lessons.md (project lessons)", _read(os.path.join(ctx.pdir, "lessons.md"))),
             ("lessons.md (shared lessons)", shared_view(_read(os.path.join(ctx.home, "lessons.md"))))]
    domain = boss_domain(ctx.worktree)
    if domain:
        ddir = os.path.join(ctx.pdir, "domains")
        parts.insert(3, (f"{ctx.name}/domains/{domain}.md (domain charter)", _read(os.path.join(ddir, f"{domain}.md"))))
        parts.insert(4, (f"{ctx.name}/domains/{domain}-state.md (domain state, you keep it current)", _read(os.path.join(ddir, f"{domain}-state.md"))))
    head = f"# Boss session: project {ctx.name}, boss {ctx.bid}, host {ctx.host}" + (f", domain {domain}" if domain else "") + "\n"
    if domain:
        head += (f"\nYour folder: workspaces tagged '{boss_folder(ctx.worktree)}' (a Paradev tag or a coderplex section). Tag every workspace you create with it, and read, "
                 "message, verify and archive only workspaces in it; anything else goes to the main boss by boss-mail.\n")
    return head + "".join(f"\n\n<!-- {name} -->\n\n{body.strip()}\n" for name, body in parts if body.strip())


def config_cmd(args):
    """bosskit.py config show [--json] | set --level L KEY=VALUE... [--apply]"""
    sub = args[0] if args else "show"
    if sub == "show":
        ctx = load()
        return show_config(ctx.layers, "--json" in args) + ("" if "--json" in args else f"\n\nhost: {ctx.host}")
    if sub == "set":
        level = args[args.index("--level") + 1] if "--level" in args[:-1] else ""
        if level not in LEVELS:
            sys.exit(f"bosskit: config set needs --level {'|'.join(LEVELS)}")
        pairs = [a for i, a in enumerate(args[1:], 1) if "=" in a and args[i - 1] != "--level"]
        if level == "user":  # needs no project: the user layer is shared by all of them
            layers = [("kit", "", DEFAULTS), ("user", layer_path(home(), "user"), _json_file(layer_path(home(), "user")))]
        else:
            layers = load().layers
        return set_config(layers, level, parse_sets(pairs), "--apply" in args)
    sys.exit(config_cmd.__doc__)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "config":
        print(config_cmd(sys.argv[2:]))
        return
    ctx = load()
    if cmd == "show":
        print(json.dumps({"kit": KIT, "home": ctx.home, "project": ctx.name, "boss": ctx.bid, "worktree": ctx.worktree,
                          "boss_md": os.path.join(ctx.pdir, "BOSS.md"), "ledger": os.path.join(ctx.pdir, ctx.cfg.get("ledger", "ledger.md")),
                          "lessons": os.path.join(ctx.pdir, "lessons.md"), "shared_lessons": os.path.join(ctx.home, "lessons.md"),
                          "boss_dir": ctx.bdir, "next": os.path.join(ctx.bdir, "next.txt"),
                          "review": os.path.join(ctx.bdir, "review.txt"), "inbox": ctx.inbox, "is_boss": is_boss(ctx),
                          "host": ctx.host}, indent=1))
    elif cmd == "instructions":
        print(instructions(ctx) if is_boss(ctx) else not_boss_note(ctx))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
