#!/usr/bin/env python3
"""boss-kit core: where code and data live, which project and boss this is, the boss registry,
lessons, and the instruction loader. Every bin/ script imports it.

Code is the kit ($BOSS_KIT_HOME, else the folder above bin/). Data is $BOSS_HOME (default
~/.claude/boss):

  bosses.json                     registry: boss id -> project, workspace, worktree, host, heartbeat
  lessons.md                      shared lessons, for every boss
  org.md org.json                 optional org layer: instructions and config for every project on this machine
  <project>/BOSS.md config.json ledger.md lessons.md prompts/      shared by the project's bosses
  <project>/bosses/<boss-id>/     next.txt review.txt notes.md pages.jsonl events.jsonl cache/ inbox/ inbox/done/

Config is layered, later wins (dicts deep-merged, lists replaced): the kit's DEFAULTS, $BOSS_HOME/org.json (org, only when
present), $BOSS_HOME/config.json (user), <project>/config.json (project), <project>/bosses/<boss-id>/config.json (one boss).

usage: bosskit.py show            the resolved paths, as JSON
       bosskit.py instructions    template + host commands + org.md + project BOSS.md + project and shared lessons (the /boss loader);
                                  a domain boss also gets playbooks/domain-boss.md. --full: every playbook inlined in the template
       bosskit.py config show [--json]                                 every config key, its value and the layer it came from
       bosskit.py config set --level user|project|boss KEY=VALUE... [--apply]
                                  shows the resolved config after the change; writes only with --apply
       bosskit.py detect          the environment, as JSON: host CLIs, gh, git, $BOSS_HOME (for onboarding)
       bosskit.py onboard questions [--text]   the onboarding form (skills/boss/questions.json) with current values, packed
                                  into AskUserQuestion calls; --text for people (bin/boss-init --questions)
       bosskit.py onboard apply FILE [--project NAME] [--level user|project|boss] [--apply]
                                  the form's answers as config, BOSS.md ## Expectations and Domain lines; writes only with --apply
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
LEVELS = ("user", "project", "boss")
# The kit's config layer: every key a boss reads, with its default.
DEFAULTS = {
    "host": "",                 # the host plugin's name (bosshost.py); "" detects it from the session
    "hosts": {},                # each host plugin's own settings, under its name
    "base_branch": "main",
    "ledger": "ledger.md",
    "wake": False,              # mail to this boss also messages its session
    "extra_prs": [],
    "tracker": {"type": "none"},
    "models": {"strong": "opus", "mid": "sonnet", "cheap": "haiku"},
    "effort": "",
    # where proof and review pages go: auto (the host's pages, else a claude.ai artifact) | host | artifact,
    # or {"provider": "<name>", "publish": "<command with <dir>>"}: every page goes there instead
    "pages": "auto",
    "boss_name": "BOSS",        # what the boss names its own workspace or session at session start; "" leaves it
    # The boss pane's buttons: a click submits the prompt to the boss's own session, as if typed. A prompt only asks;
    # section 3's gates still hold. Worker prompts fill {name}, {id}, {pr} and {branch} per worker.
    "deck_buttons": [
        {"label": "Status", "prompt": "Status: what needs me, the stack and the workers, in plain words."},
        {"label": "Sweep PRs", "prompt": "Run the gh PR sweep, then verify any DONE or ready PR (section 7). Ask before merging."},
        {"label": "Check workers", "prompt": "Read every worker's screen and re-arm any dead watcher."},
        {"label": "Review page", "prompt": "Publish the review page now (section 12)."},
        {"label": "Cleanup", "prompt": "Retire merged workspaces after the leftover check, and tidy junk. "
                                       "Ask before merging, and before anything outward."},
        {"label": "Mail", "prompt": "Read the boss-mail inbox and handle each message (section 13)."},
        {"label": "Lessons", "prompt": "Record today's incidents as lessons (section 14)."},
    ],
    "deck_worker_buttons": [
        {"label": "Status", "prompt": "Worker {name} ({id}): read its screen and its notes, then give me its state in one line."},
        {"label": "Verify", "prompt": "Verify worker {name}'s PR {pr} on {branch} with the section 7 checks. Ask before merging."},
        {"label": "Nudge", "prompt": "Nudge worker {name} ({id}): ask it for its completion envelope, or a one-line pending status."},
        {"label": "Cleanup", "prompt": "Cleanup worker {name} ({id}): run the leftover check on its worktree; if its PRs are merged "
                                       "and nothing is left over or queued, ask me to archive it (archive at once only under a "
                                       "standing cleanup OK); close its dead panes."},
    ],
    # What goes on GitHub; `instructions` states it in plain words (github_text). comments: the PR comments the boss and
    # its workers may post, any of COMMENT_KINDS ([] posts none); draft: workers open draft PRs; body: what the PR body
    # carries (tracker, proof); ready: who marks a verified PR ready (boss | never); merge: boss-merge's method
    # (squash | merge | rebase); style: the status comment (short | detailed).
    "github": {"comments": ["status", "proof", "demo", "review_replies"], "draft": True, "body": ["tracker", "proof"],
               "ready": "boss", "merge": "squash", "style": "short"},
    "proof": "demo",            # UI proof: demo (a recorded demo, mandatory when UI-heavy) | screenshots (screenshots on a page do)
    "cleanup": "ask",           # finished workspaces: ask before archiving each | auto (a standing OK, section 8)
    "report": {"style": "action-first", "verbosity": "short"},  # section 9: action-first | voice; short | normal | detailed
}
# The PR comments config's github.comments may allow: kind -> (who posts it, what it is).
COMMENT_KINDS = {
    "status": ("worker", "one short plain-English done or blocked note: what changed and the checks run, its last line the "
                         "hidden marker `<!-- BOSS_WORKER_DONE task: <id> -->`"),
    "proof": ("worker", "the proof links (pages, demo) in that note"),
    "demo": ("worker", "the demo video, attached to the PR"),
    "marker": ("worker", "only the hidden marker line, as an otherwise empty comment: GitHub shows nothing, the watcher "
                         "and the PR sweep read it"),
    "review_replies": ("worker", "replies on the PR's review threads"),
    "verify": ("boss", "a short note of what you verified, when you mark the PR ready (or, with ready never, once verified)"),
    "merged": ("boss", "a short note after you merge: the merge sha and any follow-up"),
}
QUESTIONS = os.path.join(KIT, "skills", "boss", "questions.json")  # the onboarding form: the skill and boss-init read it


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
    """This session's id on its host (bosshost.self_id); '' outside any host session."""
    import bosshost
    return bosshost.self_id()


def host_kind(cfg=None):
    """The host plugin this boss uses (bosshost.kind)."""
    import bosshost
    return bosshost.kind(cfg)


def boss_id(cwd=None, h=None):
    """This session's id on its host when running inside one, else the workspace
    this worktree registered under (a process started without the session's env, like a mod's), else a short hash of the path."""
    if self_id():
        return self_id()
    wt = worktree(cwd)
    known = [(b.get("heartbeat", 0), i) for i, b in registry(h).items() if b.get("worktree") == wt and b.get("workspace") == i]
    return max(known)[1] if known else "wt-" + hashlib.sha1(wt.encode()).hexdigest()[:8]


def load(cwd=None, name=None, make=True, resolve_host=True):
    """The resolved project and boss; make=False creates no folders (config show and set's dry run), resolve_host=False
    leaves host '' (config set, which must repair a config naming a removed plugin)."""
    h = home()
    name = name or project_name(cwd, h)
    pdir = os.path.join(h, name)
    json.load(open(os.path.join(pdir, "config.json")))  # the project's own layer must parse
    bid = boss_id(cwd, h)
    bdir = os.path.join(pdir, "bosses", bid)
    for d in ("cache", "inbox/done") if make else ():
        os.makedirs(os.path.join(bdir, d), exist_ok=True)
    layers = config_layers(h, name, bid)
    cfg = merged(layers)
    return SimpleNamespace(home=h, name=name, cfg=cfg, layers=layers, host=host_kind(cfg) if resolve_host else "", pdir=pdir, bid=bid, bdir=bdir,
                           worktree=worktree(cwd), workspace="" if bid.startswith("wt-") else bid,
                           cache=os.path.join(bdir, "cache"), inbox=os.path.join(bdir, "inbox"))


# ---- config: kit defaults < org < user < project < boss --------------------------------------

def layer_path(h, level, project=None, bid=None):
    return {"org": os.path.join(h, "org.json"), "user": os.path.join(h, "config.json"), "project": os.path.join(h, project or "", "config.json"),
            "boss": os.path.join(h, project or "", "bosses", bid or "", "config.json")}[level]


def _json_file(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except OSError:
        return {}
    except ValueError as e:
        sys.exit(f"bosskit: {path} is not valid JSON: {e}")


def base_layers(h):
    """The layers every project shares: kit, org (only when $BOSS_HOME/org.json exists), user."""
    org = layer_path(h, "org")
    return [("kit", "", DEFAULTS)] + ([("org", org, _json_file(org))] if os.path.exists(org) else []) + \
           [("user", layer_path(h, "user"), _json_file(layer_path(h, "user")))]


def config_layers(h, project, bid=None):
    """[(layer, path, dict)], lowest first: kit, org, user, project, and the boss's own when bid is given."""
    out = base_layers(h) + [("project", layer_path(h, "project", project), _json_file(layer_path(h, "project", project)))]
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
            if v == {} and (any(o.startswith(key + ".") for o in out) or isinstance(out.get(key, (None,))[0], dict)):
                continue  # {} over a dict: deep_merge changes nothing, so the lower values keep their layers
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


def write_layers(layers, changes, apply=False, now=None):
    """The resolved config with each {level: change} merged into that level's file, as text; with apply, writes each
    changed file (merged into what is there, an existing file copied to <file>.bak-<time> first)."""
    for level in changes:
        if not next((p for l, p, _ in layers if l == level), None):
            sys.exit(f"bosskit: no {level} layer here (boss needs a resolved boss, project a resolved project)")
    new = [(l, p, deep_merge(d, changes[l]) if l in changes else d) for l, p, d in layers]
    if merged(new).get("host"):
        host_kind(merged(new))  # the proposed host must be installed: exits naming the installed ones
    text = show_config(new)
    for level, path, body in new:
        if level not in changes:
            continue
        text += f"\n\n{'wrote' if apply else 'would write'} {path}:\n" + json.dumps(body, indent=1)
        if apply:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path):
                shutil.copy2(path, f"{path}.bak-{int(now or time.time())}")
            save_json(path, body)
    return text


def set_config(layers, level, change, apply=False, now=None):
    """write_layers for one level."""
    return write_layers(layers, {level: change}, apply, now) + ("" if apply else "\n\n(dry run: nothing written; add --apply to write)")


# ---- onboarding: the form in skills/boss/questions.json, its answers as config and BOSS.md changes --------------------

def _dig(d, key):
    for k in key.split("."):
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _nest(key, value):
    for k in reversed(key.split(".")):
        value = {k: value}
    return value


def form():
    return json.load(open(QUESTIONS))


def _keys(q):
    return q["key"] if isinstance(q.get("key"), list) else [q["key"]] if q.get("key") else []


def _current(q, cfg, wt):
    """A question's value now: its config key's (a multiSelect only the part its options cover), or the worktree's domain."""
    if q["id"] == "domain":
        return boss_domain(wt)
    if q["id"] == "folder":
        return boss_folder(wt)
    keys = _keys(q)
    if not keys:
        return None
    cur = _dig(cfg, keys[0])
    if q.get("multiSelect"):
        vals = [o["value"] for o in q["options"]]
        return [v for v in cur or [] if v in vals]
    return cur


def _derived(q, det, cfg):
    """What the environment answers for a question with derive: an existing project's own value, else detect's."""
    if det.get("project"):
        return det["project"] if q["id"] == "name" else (_dig(cfg, q["key"]) if q.get("key") else None) or _dig(det, q["derive"])
    if q["id"] == "name":
        name = (_dig(det, "git.repo") or "").split("/")[-1]
        return "" if any(p["name"] == name for p in det["boss_home"]["projects"]) else name  # a clash is asked
    return _dig(det, q["derive"])


def _label(o, cur):
    return o["label"] + (" (current)" if cur else "")


CURRENT = re.compile(r"\s*\(current\)\s*$")


def _short(v):
    """A current value that is no option, as a short readable label: a pages provider's name, else the value."""
    t = v["provider"] if isinstance(v, dict) and v.get("provider") else v if isinstance(v, str) else json.dumps(v)
    return t if len(t) <= 30 else t[:29] + "…"


def _host_options(det, cfg):
    """The host question's options: the installed plugins (all of them when none answers), the current one first, at most 4."""
    hosts = {n: h for n, h in det["hosts"].items() if h.get("ok")} or det["hosts"]
    names = sorted(hosts, key=lambda n: n != (cfg.get("host") or det.get("detected_host")))
    return [{"label": n, "value": n, "description": hosts[n].get("description", "")} for n in names], len(names) > 4


def onboard_questions(cfg, det, wt):
    """The form as the skill asks it: AskUserQuestion calls of at most 4 questions (each current value first and marked),
    the free-text questions, and what detect answered."""
    f = form()
    ask, plain, derived = [], [], {}
    for q in f["questions"]:
        if q.get("derive"):
            v = _derived(q, det, cfg)
            if q.get("options_from") == "hosts" and v in (None, ""):
                only = _host_options(det, cfg)[0]
                v = only[0]["value"] if len(only) == 1 else v  # one plugin: nothing to ask
            if v not in (None, ""):
                derived[q["id"]] = v
                continue
        cur = _current(q, cfg, wt)
        if q.get("free"):
            plain.append({"id": q["id"], "question": q["question"], "current": cur})
            continue
        text, opts = q["question"], q.get("options")
        if q.get("options_from") == "hosts":
            opts, many = _host_options(det, cfg)
            if len(opts) < 2:  # no plugin to pick from: typed in chat
                plain.append({"id": q["id"], "question": text, "current": cur})
                continue
            text += " (Other: type a plugin name.)" if many else ""
        if q.get("multiSelect"):
            out = [{"label": _label(o, o["value"] in cur), "description": o["description"]} for o in opts]
        else:
            match = [o for o in opts if o["value"] == cur or (o["value"] == "$default" and cur == _dig(DEFAULTS, _keys(q)[0]))]
            rest = [o for o in opts if o not in match]
            first = [{**match[0], "label": _label(match[0], True)}] if match else \
                [] if cur in (None, "") else [{"label": f"{_short(cur)} (current)", "description": "keep the value set now"}]
            out = [{"label": o["label"], "description": o["description"]} for o in first + rest]
            if len(out) > 4:  # the last options make room for the current one; Other still takes them
                text += " (Other takes any value: " + ", ".join(o["label"] for o in out[4:]) + ", or your own.)"
                out = out[:4]
        ask.append({"id": q["id"], "question": text, "header": q["header"], "multiSelect": bool(q.get("multiSelect")), "options": out})
    return {"calls": [ask[i:i + 4] for i in range(0, len(ask), 4)], "plain": plain, "derived": derived, "followups": f["followups"],
            "expectations": f["expectations"], "fixed": f["fixed"], "closing": f["closing"]}


def _value(q, a, parse=True):
    """One answer as its config value: an option's label or value, else Other text (JSON when it parses and *parse*)."""
    if isinstance(a, str):
        a = re.sub(r"\s*\((current|Recommended)\)$", "", a).strip()
        o = next((o for o in q.get("options") or [] if o["label"].lower() == a.lower()), None)
        if o or not parse:
            return o["value"] if o else a
        try:
            return json.loads(a)
        except ValueError:
            return a
    return a


def _values(q, a):
    """A multiSelect answer as a list: [] for none ('none', '', [])."""
    if isinstance(a, str):
        a = [] if a.strip().lower() in ("", "none") else [s for s in re.split(r"\s*,\s*", a.strip())]
    return [_value(q, x) for x in a or [] if not (isinstance(x, str) and x.strip().lower() == "none")]


def onboard_changes(answers, layers, level=None, wt=None):
    """The answers file as ({level: config change}, extras): extras holds name, domain, folder and expectations.
    A question left out, or answered with its "(current)" choice, keeps its value: nothing is written for it, whatever
    the label says. Only values that differ from the resolved config are written."""
    f, cfg = form(), merged(layers)
    qs = f["questions"] + f["followups"]
    extras, want = {}, {}
    for q in qs:
        if q["id"] not in answers:
            continue
        a = answers[q["id"]]
        if not q.get("multiSelect") and isinstance(a, str) and CURRENT.search(a):
            continue  # keep: a "(current)" label is a display, never a value
        if q["id"] in ("name", "domain", "folder"):
            extras.setdefault(q["id"], _value(q, a, parse=False))  # the question with options first: "Main boss" is ""
            continue
        for key in _keys(q):
            if q.get("multiSelect"):
                want.setdefault(key, {})[q["id"]] = _values(q, a)
            else:
                v = _value(q, a)
                want[key] = (q, _dig(DEFAULTS, key) if v == "$default" else v)
    if "expectations" in answers:
        e = answers["expectations"]
        x = f["expectations"]
        extras["expectations"] = "\n".join(f"- {_value(x, a, False)}" for a in e) if isinstance(e, list) else _value(x, e, False)
    if extras.get("domain") == "$ask":
        sys.exit("bosskit: answer domain with the domain boss's name")
    changes = {}
    for key, v in want.items():
        if isinstance(v, dict):  # multiSelect questions sharing a key: answered parts, plus the current part of the rest
            parts = [q for q in qs if q.get("multiSelect") and key in _keys(q)]
            v = (parts[0], [x for q in parts for x in (v[q["id"]] if q["id"] in v else _current(q, cfg, wt))])
            v = (v[0], list(dict.fromkeys(v[1])))
        q, val = v
        if val is None or val == _dig(cfg, key):
            continue
        lvl = level or q["level"]
        src = [LEVELS.index(l) for k, (_, l) in sources(layers).items() if (k == key or k.startswith(key + ".")) and l in LEVELS]
        if not level and src and max(src) > LEVELS.index(lvl):
            lvl = LEVELS[max(src)]  # set higher up: written lower, it would stay hidden
        if key == "host" and not level and _dig(next((d for l, _, d in layers if l == "project"), {}), "host") not in (None, "", val):
            lvl = "boss"  # the project's other bosses keep theirs
        changes[lvl] = deep_merge(changes.get(lvl, {}), _nest(key, val))
    return changes, extras


def set_section(text, heading, body):
    """*text* with the markdown section *heading* holding *body*: replaced when there, else appended."""
    block = f"{heading}\n\n{body.strip()}\n"
    m = re.search(rf"^{re.escape(heading)}[ \t]*\n.*?(?=^## |\Z)", text, re.M | re.S)
    if m:
        return text[:m.start()] + block + ("\n" if text[m.end():] else "") + text[m.end():]
    return text.rstrip("\n") + "\n\n" + block


def onboard_apply(answers, name=None, level=None, apply=False, cwd=None, now=None):
    """The resolved config, BOSS.md and CLAUDE.local.md after the answers, as text; with apply, writes them."""
    h, wt = home(), worktree(cwd)
    name = name or answers.get("name") or project_name(cwd, h)
    if os.path.isfile(layer_path(h, "project", name)):
        layers = load(cwd, name, make=apply, resolve_host=False).layers
    else:  # a new project: boss-init writes its folder first
        layers = config_layers(h, name, boss_id(cwd, h))
    changes, extras = onboard_changes(answers, layers, level, wt)
    text = write_layers(layers, changes, apply, now)
    if "expectations" in extras:
        path = os.path.join(h, name, "BOSS.md")
        text += f"\n\n{'wrote' if apply else 'would write'} {path}, ## Expectations:\n{extras['expectations']}"
        if apply:
            old = _read(path)
            if old:
                shutil.copy2(path, f"{path}.bak-{int(now or time.time())}")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(set_section(old, form()["expectations"]["heading"], extras["expectations"]))
    if extras.get("domain"):
        local, have = os.path.join(wt, "CLAUDE.local.md"), boss_domain(wt)
        lines = f"Domain: {extras['domain']}\n" + (f"Folder: {extras['folder']}\n" if extras.get("folder") not in (None, "", extras["domain"]) else "")
        if have and have != extras["domain"]:
            text += f"\n\n{local} already says Domain: {have}; not changed (edit it yourself to make this boss {extras['domain']})"
        elif not have:
            text += f"\n\n{'added to' if apply else 'would add to'} {local}:\n{lines}"
            if apply:
                old = _read(local)
                open(local, "w").write(old + ("\n" if old and not old.endswith("\n") else "") + lines)
    return text + ("" if apply else "\n\n(dry run: nothing written; add --apply to write)")


def questions_text(q_out):
    """The form as plain text, for bin/boss-init --questions: each question's id, options and current value."""
    f = form()
    out = ["The /boss onboarding form. Answer in a JSON file, {\"<id>\": <answer>, ...}: an option's label or value, a list for a",
           "check-any question ([] or \"none\" for none), or your own text. Leave an id out to keep its current value. Then:",
           "  boss-init <name> --answers FILE    (a new project)",
           "  bosskit.py onboard apply FILE [--level user|project|boss] [--apply]    (an existing one)", ""]
    for line in f["fixed"]:
        out.append(f"Fixed: {line}")
    for k, v in q_out["derived"].items():
        out.append(f"Derived: {k} = {json.dumps(v)}")
    for q in f["questions"] + f["followups"] + [f["expectations"]]:
        where = ", ".join(_keys(q) + [q["level"]] if _keys(q) else []) or ("BOSS.md " + q["heading"] if q.get("heading") else q["id"])
        out.append(f"\n{q['id']}  [{where}{', any of' if q.get('multiSelect') else ''}]  {q['question']}")
        out += [f"    {json.dumps(o['value']):<16} {o['label']}: {o['description']}".rstrip(": ") for o in q.get("options") or []]
    return "\n".join(out + ["", f["closing"]]) + "\n"


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
    """The sidebar folder (a worker tag) a domain boss owns: a 'Folder: <tag>' line in CLAUDE.local.md (spaces
    allowed), else its domain name. '' for the project's main boss, which covers every folder."""
    domain = boss_domain(wt)
    m = FOLDER.search(_read(os.path.join(wt, "CLAUDE.local.md"))) if domain else None
    return m.group(1) if m else domain


def with_host_import(text, host):
    """CLAUDE.local.md *text* with host plugin *host*'s prompt imported on the line after the template's (same kit path):
    a boss that imports the template directly needs its host commands too. Unchanged without a template line, or with a
    host prompt already imported."""
    if re.search(r"^@\S*/hosts/[^/\s]+/prompt\.md[ \t]*$", text, re.M):
        return text
    m = re.search(r"^(@\S*/)BOSS-template\.md[ \t]*$", text, re.M)
    return text[:m.end()] + f"\n{m.group(1)}hosts/{host}/prompt.md" + text[m.end():] if m else text


def boss_local_md(h, kit, project, host, sid=""):
    """A boss worktree's CLAUDE.local.md, imports form: the marker, the template, the host's prompt, the project's files."""
    home_dir = os.path.expanduser("~")
    t = lambda p: "~" + p[len(home_dir):] if p.startswith(home_dir + os.sep) else p
    return with_host_import(f"# Boss workspace {sid}".rstrip() + f"\n\n@{t(kit)}/BOSS-template.md\n@{t(h)}/{project}/BOSS.md\n"
                            f"@{t(h)}/{project}/lessons.md\n@{t(h)}/lessons.md\n", host)


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
    reg[ctx.bid] = {"project": ctx.name, "workspace": ctx.workspace, "worktree": ctx.worktree, "host": host, "hostKind": ctx.host,
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


def host_prompt(ctx):
    """The resolved host plugin's commands: the only host text a boss ever loads. When config's `pages` names a provider,
    its Pages line says where pages go instead."""
    import bosshost
    text = HOST_PR_LINE.sub(lambda _: "GitHub: " + worker_github_line(ctx.cfg), bosshost.get(ctx.cfg, ctx.host).prompt())
    p = ctx.cfg.get("pages")
    if not isinstance(p, dict) or not p.get("provider"):
        return text
    line = (f"- Pages: pages go to {p['provider']}: publish with `{p.get('publish') or '?'}`; "
            "never the host's pages or a claude.ai artifact.")
    out, n = re.subn(r"^- Pages:.*$", lambda _: line, text, flags=re.M)
    return out if n else text.rstrip("\n") + "\n" + line + "\n"


# A host prompt's own PR-comment sentence for the dispatch text; the GitHub block's worker line replaces it.
HOST_PR_LINE = re.compile(r"On the PR, post one short plain-English status comment.*?never the envelope\.")


def comment_kinds(cfg):
    g = cfg.get("github") or {}
    return [k for k in COMMENT_KINDS if k in (g.get("comments") or [])]


def worker_github_line(cfg):
    """The GitHub sentence every dispatched prompt carries: exactly the posts config's github allows a worker."""
    g, on = cfg.get("github") or {}, comment_kinds(cfg)
    body = [w for w in ("tracker", "proof") if w in (g.get("body") or [])]
    out = ["Push and open a draft PR as soon as your first commit exists." if g.get("draft", True) else
           "Push and open a PR (not a draft) as soon as your first commit exists.", "Never mark it ready yourself."]
    out.append("Fill in the PR body in plain English: what changed and why" +
               "".join(f", the {'tracker link' if w == 'tracker' else 'proof links'}" for w in body) + ".")
    marker = "`<!-- BOSS_WORKER_DONE task: <id> -->` (`<!-- BOSS_WORKER_BLOCKED task: <id> -->` when blocked)"
    if "status" in on:
        what = "what changed, the checks you ran" + (", the proof links" if "proof" in on else "") + \
               (", a short table of checks and the files changed" if g.get("style") == "detailed" else "")
        out.append(f"When done or blocked, post ONE short plain-English status comment on the PR ({what}) ending with the line {marker}; never the envelope.")
    elif "marker" in on:
        out.append(f"When done or blocked, post one PR comment holding only the line {marker} and no other text; never the envelope.")
    else:
        out.append("Post no status comment on the PR.")
    out.append("Attach the demo video to the PR." if "demo" in on else "Never post the demo on the PR: its path or URL goes in the envelope.")
    out.append("You may reply on the PR's review threads." if "review_replies" in on else
               "Never reply on review threads: fix the code and tell the boss which threads need an answer.")
    return " ".join(out + ["Post nothing else on GitHub."])


def done_paths(host):
    """How this host tells the boss a worker is done without GitHub: its own watcher, the worker's message."""
    import bosshost
    return (["the host's own watcher (the host commands say how it reads the envelope)"] if host.watch_script() else []) + \
           (["the envelope message the worker sends you"] if type(host).messages is not bosshost.Host.messages else [])


def github_text(cfg, host):
    """The boss's GitHub and settings block, in plain words: what the boss and its workers may post, who marks ready, how
    it merges, and what done detection is left when no marker goes on the PR."""
    g, on = cfg.get("github") or {}, comment_kinds(cfg)
    junk = sorted(set(g.get("comments") or []) - set(COMMENT_KINDS))
    out = ["## Settings in effect (from config: `bosskit.py config show`)",
           "These override every other line about the same thing in these instructions and the host commands.",
           "### GitHub (`github`)",
           "Post exactly what is allowed here, you and your workers alike, and nothing else on GitHub."]
    if on:
        out.append("- PR comments allowed: " + ", ".join(on) + ".")
        out += [f"  - `{k}` ({COMMENT_KINDS[k][0]}): {COMMENT_KINDS[k][1]}" for k in on]
        off = [k for k in COMMENT_KINDS if k not in on]
        out += ["- Not allowed: " + ", ".join(off) + "."] if off else []
    else:
        out.append("- PR comments allowed: none. Neither you nor any worker posts a PR comment, a review reply or a demo on GitHub.")
    if junk:
        out.append(f"- Ignored, not a comment kind: {', '.join(junk)} (the kinds: {', '.join(COMMENT_KINDS)}).")
    if "proof" in on and "status" not in on:
        out.append("- `proof` needs `status`: with no status comment, proof links go in the envelope and the PR body only.")
    paths = done_paths(host)
    if "status" in on or "marker" in on:
        out.append(f"- Done detection: the envelope ({' or '.join(paths) or 'the host commands say how'}), and on GitHub the hidden "
                   f"marker in the {'status comment' if 'status' in on else 'marker-only comment'}, which the watcher and the PR sweep read.")
    elif paths:
        out.append(f"- Done detection: no marker goes on GitHub, so the watcher and the PR sweep see a PR only when it leaves draft or "
                   f"merges. Done comes from {' and '.join(paths)}. The envelope stays mandatory on every dispatch.")
    else:
        out.append("- Done detection, warning: this host gives the watcher no screen or message path, so a PR marker is its only done "
                   "signal, and none is allowed. A finished worker shows only as the idle fire: on each one, read the worker and its PR "
                   "before re-arming. To get the signal back without a visible note, ask the user to allow `marker` (an otherwise empty "
                   "comment holding only the hidden line).")
    body = [w for w in ("tracker", "proof") if w in (g.get("body") or [])]
    out.append("- PR body: " + (" and ".join(f"the {'tracker link' if w == 'tracker' else 'proof links'}" for w in body) + ", besides what changed."
                                if body else "what changed only: no tracker link, no proof links."))
    out.append("- Draft PRs: workers open a draft PR as soon as the first commit exists." if g.get("draft", True) else
               "- Draft PRs: off. Workers open a ready PR, so leaving draft is no done signal (the watcher ignores it).")
    out.append("- Ready: you mark a verified PR ready (`gh pr ready N`, section 7)." if g.get("ready", "boss") == "boss" else
               "- Ready: never. Nobody marks a PR ready: once verified, tell the user it is ready for review and leave it draft.")
    out.append(f"- Merge: `bin/boss-merge` merges with --{g.get('merge') or 'squash'}. Never without the user's OK in this "
               "conversation (section 3); no setting changes that.")
    out.append(f'- Every dispatched prompt carries this line, in place of any PR-comment line in the host commands: "GitHub: {worker_github_line(cfg)}"')
    out.append("### Other settings")
    out.append("- UI proof (`proof`): " + ("screenshots of each step on a page are enough, even for UI-heavy work; a demo is optional."
                                         if cfg.get("proof") == "screenshots" else "a recorded demo, mandatory for UI-heavy work (section 5, rule 6)."))
    out.append("- Cleanup (`cleanup`): " + ("a standing OK: archive a finished workspace once its leftover check is clean, and report it. "
                                           "Still ask for research workspaces, ones the user typed into, or ones with leftovers."
                                           if cfg.get("cleanup") == "auto" else "ask before archiving each finished workspace (section 8)."))
    r = cfg.get("report") or {}
    out.append(f"- Reports (`report`): {'voice: plain sentences, no tables or symbols' if r.get('style') == 'voice' else 'action-first (section 9)'}, "
               f"{r.get('verbosity') or 'short'}" + {"normal": ": a few lines per item where it helps.",
                                                     "detailed": ": reasons and evidence for each item, still action-first."}.get(r.get("verbosity"), ": the fewest lines that work."))
    return "\n".join(out) + "\n"


def org_files(h):
    """The org layer's files that exist: $BOSS_HOME/org.md (instructions) and org.json (config)."""
    return [p for p in (os.path.join(h, "org.md"), os.path.join(h, "org.json")) if os.path.exists(p)]


def for_host(host, text, what):
    """*text* without what names another installed host, and a note saying how much was left out: a boss sees only its own
    host. A lessons file loses whole entries; other text (project facts) loses the lines."""
    import bosshost
    if not text.strip() or not bosshost.foreign(host, text):
        return text
    entries = lesson_entries(text)
    if not entries:
        lines = text.splitlines()
        keep = [l for l in lines if not bosshost.foreign(host, l)]
        return (f"(Your host is {host}: {len(lines) - len(keep)} line(s) of {what} are about another host and are left out.)\n\n"
                + "\n".join(keep) + "\n")
    keep = [e for _, _, e in entries if not bosshost.foreign(host, e)]
    lines = text[:text.index(entries[0][1])].splitlines()  # the preamble before the first entry loses its lines
    head = [l for l in lines if not bosshost.foreign(host, l)]
    gone = f", and {len(lines) - len(head)} line(s) before them" if len(head) < len(lines) else ""
    return (f"(Your host is {host}: {len(entries) - len(keep)} of {len(entries)} {what} are about another host and are left out{gone}.)\n\n"
            + "".join(l + "\n" for l in head) + "\n\n".join(keep) + "\n")


PLAYBOOK = re.compile(r"`playbooks/([\w-]+\.md)`")


def playbook(name):
    return _read(os.path.join(KIT, "playbooks", name))


def inline_playbooks(text):
    """The template with each playbook it names inlined after the first section that names it (instructions --full)."""
    seen, out = set(), []
    for chunk in re.split(r"(?=^## )", text, flags=re.M):
        out.append(chunk)
        for name in PLAYBOOK.findall(chunk):
            if name not in seen:
                seen.add(name)
                out.append(f"\n<!-- playbooks/{name} -->\n\n{playbook(name).strip()}\n\n")
    return "".join(out)


def instructions(ctx, full=False):
    import bosshost
    lessons = lambda path, what: for_host(ctx.host, _read(path), what)
    template = _read(os.path.join(KIT, "BOSS-template.md"))
    parts = [("BOSS-template.md" + (" (playbooks inlined)" if full else ""), inline_playbooks(template) if full else template),
             (f"host plugin {ctx.host} (host commands)", host_prompt(ctx)),
             ("settings in effect (config)", github_text(ctx.cfg, bosshost.get(ctx.cfg, ctx.host))),
             ("org.md (org layer)", for_host(ctx.host, _read(os.path.join(ctx.home, "org.md")), "the org facts")),
             (f"{ctx.name}/BOSS.md", for_host(ctx.host, _read(os.path.join(ctx.pdir, "BOSS.md")), "the project facts")),
             (f"{ctx.name}/lessons.md (project lessons)", lessons(os.path.join(ctx.pdir, "lessons.md"), "project lessons")),
             ("lessons.md (shared lessons)", shared_view(lessons(os.path.join(ctx.home, "lessons.md"), "shared lessons")))]
    domain = boss_domain(ctx.worktree)
    if domain:
        ddir = os.path.join(ctx.pdir, "domains")
        parts.insert(5, (f"{ctx.name}/domains/{domain}.md (domain charter)", _read(os.path.join(ddir, f"{domain}.md"))))
        parts.insert(6, (f"{ctx.name}/domains/{domain}-state.md (domain state, you keep it current)", _read(os.path.join(ddir, f"{domain}-state.md"))))
        if not full:  # --full has it inlined in the template already
            parts.insert(5, ("playbooks/domain-boss.md (domain boss playbook)", playbook("domain-boss.md")))
    org = org_files(ctx.home)
    head = (f"# Boss session: project {ctx.name}, boss {ctx.bid}, host {ctx.host}" + (f", domain {domain}" if domain else "")
            + (f", org layer: {' + '.join(map(os.path.basename, org))}" if org else "") + "\n")
    if domain:
        head += (f"\nYour folder: workspaces tagged '{boss_folder(ctx.worktree)}' (the host's folders). Tag every workspace you create with it, and read, "
                 "message, verify and archive only workspaces in it; anything else goes to the main boss by boss-mail.\n")
    return head + "".join(f"\n\n<!-- {name} -->\n\n{body.strip()}\n" for name, body in parts if body.strip())


def _out(argv, timeout=15):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def detect(cwd=None):
    """What onboarding needs to propose a config: each host plugin (installed, answering, this session's id on it), the
    host this session would resolve to, gh, git, and $BOSS_HOME's projects and layers. Read-only: it writes nothing."""
    import bosshost
    h, wt = home(), worktree(cwd)
    try:
        project = project_name(cwd, h)
    except SystemExit:
        project = None
    head = _git(wt, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if not head:  # worktrees often lack origin/HEAD: ask the remote
        m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD", _out(["git", "-C", wt, "ls-remote", "--symref", "origin", "HEAD"]) or "", re.M)
        head = f"origin/{m.group(1)}" if m else ""
    projs = [{"name": n, "repo": c.get("repo", ""), "host": c.get("host", "")}
             for n, c in ((n, _json_file(layer_path(h, "project", n))) for n in projects(h))]
    bid = boss_id(cwd, h)
    layers = {lvl: layer_path(h, lvl, project, bid) for lvl in LEVELS if lvl == "user" or project}
    hosts = {}
    for name, m in bosshost.plugins().items():
        try:
            hosts[name] = {"description": m.get("description", ""), **bosshost.get({}, name).detect()}
        except Exception as e:  # a broken plugin is reported, never fatal
            hosts[name] = {"description": m.get("description", ""), "error": str(e)[:200]}
    try:
        detected = bosshost.kind({})
    except SystemExit:
        detected = ""
    return {
        "session": {"id": bosshost.self_id(), "boss_id": bid},
        "hosts": hosts,
        "detected_host": detected,
        "gh": {"login": _out(["gh", "api", "user", "--jq", ".login"]) or ""},
        "git": {"worktree": wt, "repo": remote_repo(wt), "branch": _git(wt, "rev-parse", "--abbrev-ref", "HEAD"),
                "default_branch": head.split("/", 1)[1] if "/" in head else ""},
        "boss_home": {"path": h, "exists": os.path.isdir(h), "projects": projs},
        "project": project,
        "layers": {lvl: {"path": p, "exists": os.path.exists(p)} for lvl, p in layers.items()},
        "marker": boss_marker(wt),
    }


def onboard_cmd(args):
    """bosskit.py onboard questions [--text] | apply FILE [--project NAME] [--level L] [--apply]"""
    sub = args[0] if args else ""
    if sub == "questions":
        try:
            cfg = load(make=False, resolve_host=False).cfg
        except SystemExit:  # no project yet: the shared layers
            cfg = merged(base_layers(home()))
        q = onboard_questions(cfg, detect(), worktree())
        return questions_text(q) if "--text" in args else json.dumps(q, indent=1)
    if sub == "apply" and len(args) > 1:
        level = args[args.index("--level") + 1] if "--level" in args[:-1] else None
        if level not in (None, *LEVELS):
            sys.exit(f"bosskit: onboard apply --level {'|'.join(LEVELS)}")
        name = args[args.index("--project") + 1] if "--project" in args[:-1] else None
        return onboard_apply(_json_file(args[1]), name, level, "--apply" in args)
    sys.exit(onboard_cmd.__doc__)


def config_cmd(args):
    """bosskit.py config show [--json] | set --level L KEY=VALUE... [--apply]"""
    sub = args[0] if args else "show"
    if sub == "show":
        ctx = load(make=False)
        return show_config(ctx.layers, "--json" in args) + ("" if "--json" in args else f"\n\nhost: {ctx.host}")
    if sub == "set":
        level = args[args.index("--level") + 1] if "--level" in args[:-1] else ""
        if level not in LEVELS:
            sys.exit(f"bosskit: config set needs --level {'|'.join(LEVELS)}")
        pairs = [a for i, a in enumerate(args[1:], 1) if "=" in a and args[i - 1] != "--level"]
        if level == "user":  # needs no project: the user layer is shared by all of them
            layers = base_layers(home())
        else:
            layers = load(make="--apply" in args, resolve_host=False).layers
        return set_config(layers, level, parse_sets(pairs), "--apply" in args)
    sys.exit(config_cmd.__doc__)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "config":
        print(config_cmd(sys.argv[2:]))
        return
    if cmd == "detect":
        print(json.dumps(detect(), indent=1))
        return
    if cmd == "onboard":
        print(onboard_cmd(sys.argv[2:]))
        return
    ctx = load()
    if cmd == "show":
        print(json.dumps({"kit": KIT, "home": ctx.home, "project": ctx.name, "boss": ctx.bid, "worktree": ctx.worktree,
                          "boss_md": os.path.join(ctx.pdir, "BOSS.md"), "ledger": os.path.join(ctx.pdir, ctx.cfg.get("ledger", "ledger.md")),
                          "lessons": os.path.join(ctx.pdir, "lessons.md"), "shared_lessons": os.path.join(ctx.home, "lessons.md"),
                          "boss_dir": ctx.bdir, "next": os.path.join(ctx.bdir, "next.txt"),
                          "review": os.path.join(ctx.bdir, "review.txt"), "inbox": ctx.inbox, "is_boss": is_boss(ctx),
                          "host": ctx.host, **({"org": org_files(ctx.home)} if org_files(ctx.home) else {})}, indent=1))
    elif cmd == "instructions":
        print(instructions(ctx, "--full" in sys.argv[2:]) if is_boss(ctx) else not_boss_note(ctx))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
