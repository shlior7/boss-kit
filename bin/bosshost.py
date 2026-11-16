#!/usr/bin/env python3
"""boss-kit host adapters: the one place scripts and the boss-deck mod talk to the host that runs the workers.

Two hosts, same methods; get(cfg) picks one by bosskit.host_kind(cfg):
  superset   Paradev (formerly Superset) CLI 2.x: workspaces with terminals; the commands are the ones the kit always ran
  coderplex  coderplex-ctl: one session per worker (worktree + agent); messages queue until the agent is idle and wake it

A worker is {id, name, branch, worktree, tags, terminals: [{id, title, agent: {state}}]}, agent state working | idle |
blocked. A coderplex session has one agent, shown as one terminal, so every reader treats both hosts alike.

usage: bosshost.py kind | self | host-id | workers [ID...] | send ID TEXT [TERMINAL] | rename ID NAME | open ID
       bosshost.py screen ID TERMINAL     the terminal's screen text (superset); nothing on coderplex
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosskit  # noqa: E402


def run(argv, timeout=40):
    """stdout of a host command, '' when it fails or the CLI is missing."""
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


class Superset:
    kind = "superset"
    queues = False  # text sent mid-turn can be dropped: wake only an idle terminal

    def __init__(self, cfg=None):
        self.cfg = cfg or {}
        self._host = None

    def self_id(self):
        return os.environ.get("SUPERSET_WORKSPACE_ID", "")

    def host_id(self):
        if self._host is None:
            self._host = os.environ.get("BOSS_HOST") or self.cfg.get("superset_host") or ""
            if not self._host:
                d = _json(run(["superset", "hosts", "list", "--json"]), [])
                d = d if isinstance(d, list) else d.get("hosts", [])
                self._host = d[0].get("id", "") if d and isinstance(d[0], dict) else ""
        return self._host

    def workers(self, ids=None):
        """Every workspace on the host (the snapshot), with its tags and worktree from `workspaces list`."""
        spaces = _json(run(["superset", "snapshot", "--host", self.host_id(), "--json"]), {})
        spaces = spaces.get("workspaces", []) if isinstance(spaces, dict) else []
        rows = _json(run(["superset", "workspaces", "list", "--host", self.host_id(), "--json"]), [])
        listed = {w["id"]: w for w in rows if isinstance(w, dict) and w.get("id")} if isinstance(rows, list) else {}
        out = []
        for w in spaces:
            info = listed.get(w.get("id"), {})
            out.append({**w, "tags": [t.strip() for t in (info.get("tags") or "").split(",") if t.strip()],
                        "worktree": info.get("worktreePath") or "", "terminals": w.get("terminals") or []})
        return out

    def worker(self, ws):
        """One workspace from its own snapshot (cheaper than the host's), or {}."""
        spaces = _json(run(["superset", "snapshot", "--workspace", ws, "--json"], timeout=20), {})
        spaces = spaces.get("workspaces", []) if isinstance(spaces, dict) else []
        return next((w for w in spaces if w.get("id") == ws), {})

    def by_branch(self, branch):
        """The local workspace on *branch*, {id, worktree}, or None."""
        rows = _json(run(["superset", "workspaces", "list", "--local", "--json"]), [])
        rows = rows if isinstance(rows, list) else rows.get("workspaces", [])
        w = next((w for w in rows if w.get("branch") == branch and not w.get("archivedAt")), None)
        return {"id": w["id"], "worktree": w.get("worktreePath") or ""} if w else None

    def send(self, ws, text, terminal=None):
        """Clear the input line (an idle session often shows an auto-suggestion), then submit *text*."""
        base = ["superset", "terminals", "send", "--workspace", ws, "--terminal", terminal or "", "--local"]
        subprocess.run(base + ["--keys", "ctrl+u"], check=True, capture_output=True)
        subprocess.run(base + ["--text", text], check=True, capture_output=True)

    def rename(self, ws, name):
        run(["superset", "workspaces", "update", ws, "--host", self.host_id(), "--name", name], timeout=20)

    def open(self, ws):
        run(["superset", "workspaces", "open", ws, "--local"], timeout=20)

    def screen(self, ws, terminal):
        out = _json(run(["superset", "terminals", "read", "--workspace", ws, "--terminal", terminal, "--max-lines", "400", "--json"], timeout=20), {})
        return out.get("text", "") if isinstance(out, dict) else ""

    def archive_cmd(self, ws):
        return f"superset workspaces archive {ws} --local"


class Coderplex:
    kind = "coderplex"
    queues = True  # `sessions send` waits for the agent to go idle and wakes a stopped one

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def self_id(self):
        return os.environ.get("CODERPLEX_SESSION_ID", "")

    def host_id(self):
        return "local"

    def _ls(self):
        d = _json(run(["coderplex-ctl", "sessions", "ls", "--json"]), {})
        return d.get("sessions", []) if isinstance(d, dict) else []

    def _show(self, sid):
        d = _json(run(["coderplex-ctl", "sessions", "show", sid, "--json"], timeout=20), {})
        s = (d.get("sessions") or [{}])[0] if isinstance(d, dict) else {}
        return s if isinstance(s, dict) else {}

    @staticmethod
    def state(phase):
        """agentPhase as an agent state: working, idle (no phase), anything else is waiting on someone: blocked."""
        # ponytail: only "working" and null were seen; a permission prompt's phase is assumed to be neither
        return "working" if phase == "working" else "idle" if phase in (None, "", "idle", "ready", "done") else "blocked"

    def _worker(self, s):
        """A session as a worker: its one agent is its one terminal (none for a shell session)."""
        mode = s.get("agentMode") or s.get("agent") or ""
        agent = mode and mode != "shell"
        return {"id": s.get("id", ""), "name": s.get("title") or s.get("customName") or "", "branch": s.get("branch") or "",
                "worktree": s.get("worktree") or "", "tags": [s["section"]] if s.get("section") else [],
                "link": s.get("link") or "",
                "terminals": [{"id": f"agent-1:{mode}", "title": s.get("title") or "", "agent": {"state": self.state(s.get("agentPhase"))}}] if agent else []}

    def workers(self, ids=None):
        """The sessions whose id starts with one of *ids* (all when None), each read in full for its agent phase."""
        keep = [s["id"] for s in self._ls() if s.get("id") and (ids is None or any(s["id"].startswith(i[:8]) or i.startswith(s["id"]) for i in ids))]
        return [self._worker(s) for s in map(self._show, keep) if s.get("id")]

    def worker(self, sid):
        s = self._show(sid)
        return self._worker(s) if s.get("id") else {}

    def by_branch(self, branch):
        s = next((s for s in self._ls() if s.get("branch") == branch), None)
        return {"id": s["id"], "worktree": self._show(s["id"]).get("worktree") or ""} if s else None

    def send(self, sid, text, terminal=None):
        """Queue *text* for the session's agent; it arrives as a prompt once the agent is idle. *terminal* is a tab id."""
        subprocess.run(["coderplex-ctl", "sessions", "send", sid, "--text", text] + (["--tab", terminal.split(":")[0]] if terminal else []),
                       check=True, capture_output=True)

    def rename(self, sid, name):
        run(["coderplex-ctl", "sessions", "rename", sid, "--name", name], timeout=20)

    def open(self, sid):
        run(["open", f"coderplex://session/local/{sid}"], timeout=10)

    def screen(self, sid, terminal):
        return None  # no screen read on coderplex: the worker's own .boss-worker/status.json says what it is doing

    def archive_cmd(self, sid):
        return f"coderplex-ctl sessions archive {sid}"  # never --ttl without the user's OK: it deletes the session


def get(cfg=None, kind=None):
    return {"superset": Superset, "coderplex": Coderplex}[kind or bosskit.host_kind(cfg)](cfg)


def _cfg():
    try:
        return bosskit.load().cfg
    except SystemExit:  # no project here: the host still resolves from the session
        return {}


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("kind", [])
    host = get(_cfg())
    if cmd == "kind":
        print(host.kind)
    elif cmd == "self":
        print(host.self_id())
    elif cmd == "host-id":
        print(host.host_id())
    elif cmd == "workers":
        print(json.dumps(host.workers(args or None), indent=1))
    elif cmd == "send" and len(args) in (2, 3):
        host.send(*args)
    elif cmd == "rename" and len(args) == 2:
        host.rename(*args)
    elif cmd == "open" and len(args) == 1:
        host.open(args[0])
    elif cmd == "screen" and len(args) == 2:
        print(host.screen(*args) or "")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
