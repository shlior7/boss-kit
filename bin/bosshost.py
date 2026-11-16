#!/usr/bin/env python3
"""boss-kit host plugins: what runs the workers is a plugin; the kit itself names none.

A host plugin is a folder with a host.json manifest, found in (first wins on a name clash):
  $BOSS_HOST_PATH (os.pathsep-separated folders of plugins), $BOSS_HOME/hosts/, the kit's hosts/

  host.json    {"name", "description", "priority" (lower is tried first when detecting),
                "session_env": [vars that hold this session's id on the host], "terminal_env": [the session's own terminal],
                "cli": [commands or paths that show the host is installed, ~ expanded],
                "queues": does a message wait for the agent to go idle (true) or can text sent mid-turn be dropped (false),
                "prompt": the boss's host commands (default prompt.md), "watch": an own watcher script (optional),
                "envelope_aliases": older envelope token prefixes this host's workers may still write (BOSS_ always counts),
                "proof_links": [{"label", "pattern"}] proof URLs this host publishes, "defaults": the plugin's config,
                "keywords": [words that name this host in text]; with its name, CLIs and env vars they keep it out of other hosts' bosses}
  adapter.py   class Host(bosshost.Host), overriding what the host can do; the rest raises Unsupported
  prompt.md    the commands the boss uses on this host, loaded after the boss prompt
A boss uses exactly one host: config's "host" (the plugin name), else the session's (the pane passes $BOSS_HOST_KIND),
else the first plugin, by priority, whose session_env is set, then whose cli is installed. Only that plugin's prompt,
adapter, envelope aliases and proof links are used. A plugin's own settings live in config under hosts.<name>.

A worker is {id, name, branch, worktree, tags, terminals: [{id, title, agent: {state}}]}, agent state working | idle | blocked.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosskit  # noqa: E402

MANIFEST = "host.json"


class Unsupported(Exception):
    """The host cannot do this; the message says what to do instead."""


def run(argv, timeout=40):
    """stdout of a command, '' when it fails or is missing."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def _list(v):
    return [v] if isinstance(v, str) else list(v or [])


def plugin_dirs():
    return [p for p in os.environ.get("BOSS_HOST_PATH", "").split(os.pathsep) if p] + \
           [os.path.join(bosskit.home(), "hosts"), os.path.join(bosskit.KIT, "hosts")]


def plugins():
    """{name: manifest} of every installed host plugin, by priority; each manifest carries its folder as "dir"."""
    found = {}
    for root in plugin_dirs():
        for d in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            path = os.path.join(root, d, MANIFEST)
            m = _json(bosskit._read(path), None)
            if isinstance(m, dict) and m.get("name") and m["name"] not in found:
                found[m["name"]] = {**m, "dir": os.path.join(root, d), "session_env": _list(m.get("session_env")),
                                    "terminal_env": _list(m.get("terminal_env")), "cli": _list(m.get("cli"))}
    return dict(sorted(found.items(), key=lambda kv: (kv[1].get("priority", 100), kv[0])))


def keywords(manifest):
    """Lower-case words that identify a host in text: its name, keywords, CLI names, env vars and envelope aliases."""
    words = [manifest["name"], *_list(manifest.get("keywords")), *(os.path.basename(c) for c in manifest["cli"]),
             *manifest["session_env"], *manifest["terminal_env"], *(f"{a}_WORKER_" for a in _list(manifest.get("envelope_aliases")))]
    return {w.lower() for w in words if w}


def foreign(name, text):
    """The other installed hosts' keywords that *text* mentions (none of host *name*'s own): what would leak into its boss."""
    ps = plugins()
    own = keywords(ps[name]) if name in ps else set()
    low = (text or "").lower()
    return sorted({w for n, m in ps.items() if n != name for w in keywords(m) - own if w in low})


def installed(manifest):
    """The first of the plugin's CLIs found on PATH or on disk, else ''."""
    for c in manifest["cli"]:
        hit = shutil.which(c) or (os.path.expanduser(c) if os.path.sep in c and os.path.exists(os.path.expanduser(c)) else "")
        if hit:
            return hit
    return ""


def session_ids():
    """[(plugin name, session id, terminal id)] of every plugin whose session_env is set, by priority."""
    out = []
    for name, m in plugins().items():
        sid = next((os.environ[v] for v in m["session_env"] if os.environ.get(v)), "")
        if sid:
            out.append((name, sid, next((os.environ[v] for v in m["terminal_env"] if os.environ.get(v)), "")))
    return out


def self_id():
    """This session's id on its host: $BOSS_SESSION_ID (the pane sets it), else the session_env of the plugin $BOSS_HOST_KIND
    names, else of the first plugin; '' outside any."""
    if os.environ.get("BOSS_SESSION_ID"):
        return os.environ["BOSS_SESSION_ID"]
    ids, k = session_ids(), os.environ.get("BOSS_HOST_KIND")
    return next((sid for n, sid, _ in ids if n == k or not k), "")


def kind(cfg=None):
    """The one host this boss uses. A host named in config or by the pane must be installed: no silent fallback."""
    ps = plugins()
    for source, k in (("config's host", (cfg or {}).get("host")), ("$BOSS_HOST_KIND", os.environ.get("BOSS_HOST_KIND"))):
        if k:
            if k not in ps:
                sys.exit(f"bosshost: {source} is {k!r}, but no host plugin has that name (installed: {', '.join(ps) or 'none'})")
            return k
    ids = session_ids()
    if ids:
        return ids[0][0]
    hit = next((n for n, m in ps.items() if installed(m)), None)
    if hit or ps:
        return hit or next(iter(ps))
    sys.exit(f"bosshost: no host plugin installed (looked in {', '.join(plugin_dirs())})")


def load(manifest):
    """The plugin's Host class."""
    path = os.path.join(manifest["dir"], "adapter.py")
    loader = importlib.machinery.SourceFileLoader(f"bosshost_{manifest['name']}", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod.Host


def get(cfg=None, name=None):
    """The resolved host, ready to use."""
    m = plugins()[name or kind(cfg)]
    return load(m)(cfg or {}, m)


class Host:
    """What a host can do. Override what yours supports; the rest raises Unsupported with a hint."""

    def __init__(self, cfg, manifest):
        self.manifest = manifest
        self.name = manifest["name"]
        self.queues = bool(manifest.get("queues"))
        self.root = cfg or {}
        self.cfg = bosskit.deep_merge(manifest.get("defaults") or {}, (self.root.get("hosts") or {}).get(self.name) or {})

    def _no(self, what, hint=""):
        raise Unsupported(f"{self.name}: {what} is not supported" + (f"; {hint}" if hint else ""))

    def self_id(self):
        return next((os.environ[v] for v in self.manifest["session_env"] if os.environ.get(v)), "") or os.environ.get("BOSS_SESSION_ID", "")

    def terminal_id(self):
        return next((os.environ[v] for v in self.manifest["terminal_env"] if os.environ.get(v)), "")

    def host_id(self):
        return ""

    def prompt(self):
        return bosskit._read(os.path.join(self.manifest["dir"], self.manifest.get("prompt") or "prompt.md"))

    def watch_script(self):
        w = self.manifest.get("watch")
        return os.path.join(self.manifest["dir"], w) if w else ""

    def watch_env(self):
        """Env for the plugin's own watcher (its resolved instance, CLI path)."""
        return {}

    def envelope_prefixes(self):
        return ["BOSS"] + [p for p in _list(self.manifest.get("envelope_aliases")) if p.isidentifier()]

    def proof_links(self):
        return [(p["label"], p["pattern"]) for p in self.manifest.get("proof_links") or [] if p.get("label") and p.get("pattern")]

    def detect(self):
        """What onboarding shows for this host: installed CLI, whether it answers, this session's id on it."""
        return {"cli": installed(self.manifest), "ok": bool(installed(self.manifest)), "session": self.self_id() if self.manifest["session_env"] and any(os.environ.get(v) for v in self.manifest["session_env"]) else ""}

    # ---- workers -------------------------------------------------------------------------
    def workers(self, ids=None):
        self._no("listing workers")

    def worker(self, wid):
        """One worker; {} when it is gone, None when the host could not be read."""
        return next((w for w in self.workers([wid]) if w.get("id", "").startswith(wid[:8]) or wid.startswith(w.get("id", "\0"))), {})

    def by_branch(self, branch):
        w = next((w for w in self.workers() if w.get("branch") == branch), None)
        return {"id": w["id"], "worktree": w.get("worktree") or ""} if w else None

    def create(self, repo, branch, prompt, model="", effort="", name="", folder=""):
        """Start a worker on a new branch with *prompt*; returns its id."""
        self._no("creating a worker")

    def send(self, wid, text, terminal=None):
        self._no("sending a message")

    def rename(self, wid, name):
        self._no("renaming")

    def move(self, wid, folder):
        self._no("folders")

    def open(self, wid):
        self._no("opening a worker")

    def archive(self, wid):
        self._no("archiving")

    def archive_cmd(self, wid):
        return f"boss-host archive {wid}"

    def screen(self, wid, terminal):
        """The worker's screen text, or None when the host cannot read it."""
        return None

    def messages(self, boss, wid):
        """[(message id, text, sent at in seconds)] from the worker to the boss, or None when the host has no messages."""
        return None

    def dispatched_at(self, boss, wid):
        """When the latest dispatch to the worker went out, in seconds (0 = unknown): messages before it are old."""
        return 0

    def close(self, wid, terminals, dry=False):
        """Close these terminals of the worker; returns what it did, one line each."""
        self._no("closing terminals", "archive the worker instead")

    def close_dead(self, wids, dry=False):
        """Close the leftovers of ended sessions in these workers (all when None); returns lines."""
        self._no("closing ended sessions")
