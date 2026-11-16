"""The coderplex host plugin: coderplex-ctl. A worker is a session: its own git worktree, terminal and agent on one daemon.
A message to a session queues until its agent is idle and wakes a stopped one; a worker's envelope comes back to the
boss as a message, which arrives as a new prompt in the boss's pane. No screen read.

Config (hosts.coderplex): target (local | remote, where new sessions go; messages reach the same daemon only), agent.
"""
import subprocess
from datetime import datetime

import bosskit
import bosshost
from bosshost import _json, run


class Host(bosshost.Host):

    def ctl(self, *args, timeout=40):
        return run(["coderplex-ctl", *args], timeout=timeout)

    def host_id(self):
        return self.cfg.get("target") or "local"

    def _ls(self):
        d = _json(self.ctl("sessions", "ls", "--json"), {})
        return d.get("sessions", []) if isinstance(d, dict) else []

    def _show(self, sid):
        d = _json(self.ctl("sessions", "show", sid, "--json", timeout=20), {})
        s = (d.get("sessions") or [{}])[0] if isinstance(d, dict) else {}
        return s if isinstance(s, dict) else {}

    @staticmethod
    def state(phase):
        """agentPhase as an agent state: working; idle (no phase, or "review": its turn ended and it waits for a reader);
        anything else is waiting on someone: blocked."""
        # ponytail: seen working, review and null (daemon 0.522.0); a permission prompt's phase is assumed to be none of them
        return "working" if phase == "working" else "idle" if phase in (None, "", "idle", "review", "ready", "done") else "blocked"

    def _worker(self, s):
        """A session as a worker: its one agent is its one terminal (none for a shell session)."""
        mode = s.get("agentMode") or s.get("agent") or ""
        agent = mode and mode != "shell"
        return {"id": s.get("id", ""), "name": s.get("title") or s.get("customName") or "", "branch": s.get("branch") or "",
                "worktree": s.get("worktree") or "", "tags": [s["section"]] if s.get("section") else [], "link": s.get("link") or "",
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

    def create(self, repo, branch, prompt, model="", effort="", name="", folder=""):
        argv = ["coderplex-ctl", "sessions", "create", "--target", self.host_id(), "--repo", repo.rsplit("/", 1)[-1],
                "--branch", branch, "--agent", self.cfg.get("agent") or "claude", "--prompt", prompt, "--json"]
        argv += ["--model", model] if model else []
        argv += ["--effort", effort] if effort else []
        argv += ["--name", name[:40]] if name else []
        r = subprocess.run(argv, capture_output=True, text=True)
        d = _json(r.stdout, {})
        sid = ((d.get("created") or {}).get("id") or "") if isinstance(d, dict) else ""
        if not sid:
            raise bosshost.Unsupported(f"coderplex: sessions create failed: {((d.get('error') or {}).get('message') if isinstance(d, dict) else '') or r.stderr[:200]}")
        if folder:
            self.move(sid, folder)
        return sid

    def send(self, sid, text, terminal=None):
        """Queue *text* for the session's agent; it arrives as a prompt once the agent is idle. *terminal* is a tab id."""
        subprocess.run(["coderplex-ctl", "sessions", "send", sid, "--text", text] + (["--tab", terminal.split(":")[0]] if terminal else []),
                       check=True, capture_output=True)

    def rename(self, sid, name):
        self.ctl("sessions", "rename", sid, "--name", name, timeout=20)

    def move(self, sid, folder):
        self.ctl("sessions", "move", sid, "--section", folder, timeout=20)

    def open(self, sid):
        run(["open", f"coderplex://session/local/{sid}"], timeout=10)

    def archive(self, sid):
        subprocess.run(["coderplex-ctl", "sessions", "archive", sid], check=True, capture_output=True)  # never --ttl: it deletes

    def archive_cmd(self, sid):
        return f"coderplex-ctl sessions archive {sid}"

    def detect(self):
        d = super().detect()
        st = _json(self.ctl("status", "--json"), {}) if d["cli"] else {}
        d["ok"] = any(t.get("ok") for t in (st.get("targets") or [])) if isinstance(st, dict) else False
        return d

    # ---- messages: how a worker's envelope reaches the boss -----------------------------------
    def _messages(self, boss):
        d = _json(self.ctl("sessions", "messages", boss, "--json"), {})
        return d.get("messages", []) if isinstance(d, dict) else []

    @staticmethod
    def _between(m, a, b):
        return (m.get("from") or {}).get("session", "").startswith(a[:8]) and (m.get("to") or {}).get("session", "").startswith(b[:8])

    @staticmethod
    def _body(m):
        b = m.get("body") or {}
        return b if isinstance(b, str) else b.get("text") or bosskit._read(b.get("file") or "")

    def messages(self, boss, sid):
        return [(m.get("messageId"), self._body(m), (m.get("createdAt") or 0) / 1000) for m in self._messages(boss) if self._between(m, sid, boss)]

    def dispatched_at(self, boss, sid):
        """The boss's last message to the session, else the session's creation."""
        sent = [(m.get("createdAt") or 0) / 1000 for m in self._messages(boss) if self._between(m, boss, sid)]
        try:
            created = datetime.fromisoformat(self._show(sid).get("createdAt", "").replace("Z", "+00:00")).timestamp()
        except ValueError:
            created = 0
        return max(sent + [created])
