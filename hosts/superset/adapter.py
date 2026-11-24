"""The superset host plugin: Paradev (formerly Superset) CLI 2.x. A worker is a workspace: a git worktree with terminals,
its agent in one of them. These are the commands boss-kit has always run.

Config (hosts.superset): host_id (the host's machine id; "" = $BOSS_HOST, else the first host), project (the Paradev
project id new workspaces are created in; "" = the project whose repo matches). The older top-level superset_host
still counts as host_id.
"""
import json
import os
import re
import subprocess

import bosshost
from bosshost import _json, run


class Host(bosshost.Host):

    def __init__(self, cfg, manifest):
        super().__init__(cfg, manifest)
        self.cli = bosshost.installed(manifest) or "superset"
        self._host = None

    def sh(self, *args, timeout=40):
        return run([self.cli, *args], timeout=timeout)

    def host_id(self):
        if self._host is None:
            self._host = self.cfg.get("host_id") or os.environ.get("BOSS_HOST") or self.root.get("superset_host") or ""
            if not self._host:
                d = _json(self.sh("hosts", "list", "--json"), [])
                d = d if isinstance(d, list) else d.get("hosts", [])
                self._host = d[0].get("id", "") if d and isinstance(d[0], dict) else ""
        return self._host

    def workers(self, ids=None):
        """Every workspace on the host (the snapshot), with its tags and worktree from `workspaces list`."""
        spaces = _json(self.sh("snapshot", "--host", self.host_id(), "--json"), {})
        spaces = spaces.get("workspaces", []) if isinstance(spaces, dict) else []
        rows = _json(self.sh("workspaces", "list", "--host", self.host_id(), "--json"), [])
        listed = {w["id"]: w for w in rows if isinstance(w, dict) and w.get("id")} if isinstance(rows, list) else {}
        out = []
        for w in spaces:
            info = listed.get(w.get("id"), {})
            out.append({**w, "tags": [t.strip() for t in (info.get("tags") or "").split(",") if t.strip()],
                        "worktree": info.get("worktreePath") or "", "terminals": w.get("terminals") or []})
        return out

    def worker(self, ws):
        """One workspace from its own snapshot (cheaper than the host's), or {}."""
        spaces = _json(self.sh("snapshot", "--workspace", ws, "--json", timeout=20), {})
        spaces = spaces.get("workspaces", []) if isinstance(spaces, dict) else []
        return next((w for w in spaces if w.get("id") == ws), {})

    def _local(self):
        rows = _json(self.sh("workspaces", "list", "--local", "--json"), [])
        return rows if isinstance(rows, list) else rows.get("workspaces", [])

    def worktree(self, ws):
        """From `workspaces list` (the snapshot has no worktree path): one quick local call; '' when archived."""
        w = next((w for w in self._local() if (w.get("id", "").startswith(ws[:8]) or ws.startswith(w.get("id") or "\0"))
                  and not w.get("archivedAt")), None)
        return (w or {}).get("worktreePath") or ""

    def by_branch(self, branch):
        w = next((w for w in self._local() if w.get("branch") == branch and not w.get("archivedAt")), None)
        return {"id": w["id"], "worktree": w.get("worktreePath") or ""} if w else None

    def _project(self, repo):
        if self.cfg.get("project"):
            return self.cfg["project"]
        want = self.slug(repo) or repo.lower()
        ps = [p for p in _json(self.sh("projects", "list", "--json"), []) if isinstance(p, dict) and p.get("id")]
        # its repo first; a name match only for a project that has no repository at all
        hit = next((p for p in ps if p.get("repo") and self.slug(p["repo"]) == want), None) or \
            next((p for p in ps if not p.get("repo") and p.get("name", "").lower() == want.rsplit("/", 1)[-1]), None)
        if hit:
            return hit["id"]
        self._no(f"creating a workspace for {repo!r}", "no Paradev project has that repo: set hosts.superset.project")

    @staticmethod
    def slug(remote):
        """owner/repo of an https, ssh or scp-style remote, or of owner/repo itself; '' when it names none."""
        m = re.search(r"([^/:@\s]+)/([^/:\s]+?)(?:\.git)?/?$", (remote or "").strip().lower())
        return f"{m.group(1)}/{m.group(2)}" if m else ""

    def create(self, repo, branch, prompt, model="", effort="", name="", folder=""):
        argv = [self.cli, "workspaces", "create", "--local", "--project", self._project(repo), "--branch", branch,
                "--name", name or branch, "--agent", "claude", "--prompt", prompt, "--json"]
        argv += ["--model", model] if model else []
        argv += ["--effort", effort] if effort else []
        argv += ["--tag", folder] if folder else []
        r = subprocess.run(argv, capture_output=True, text=True, check=True)
        d = _json(r.stdout, {})
        wid = d.get("id") or (d.get("workspace") or {}).get("id") if isinstance(d, dict) else ""
        if not wid:
            raise bosshost.Unsupported(f"superset: workspaces create printed no id: {r.stdout[:200]}")
        return wid

    def send(self, ws, text, terminal=None):
        """Clear the input line (an idle session often shows an auto-suggestion), then submit *text*."""
        if not terminal:
            terminal = next((t["id"] for t in self.worker(ws).get("terminals", []) if t.get("agent")), "")
        base = [self.cli, "terminals", "send", "--workspace", ws, "--terminal", terminal or "", "--local"]
        subprocess.run(base + ["--keys", "ctrl+u"], check=True, capture_output=True)
        subprocess.run(base + ["--text", text], check=True, capture_output=True)

    def rename(self, ws, name):
        self.sh("workspaces", "update", ws, "--host", self.host_id(), "--name", name, timeout=20)

    def move(self, ws, folder):
        self.sh("workspaces", "update", ws, "--local", "--tag", folder, timeout=20)

    def open(self, ws):
        self.sh("workspaces", "open", ws, "--local", timeout=20)

    def archive(self, ws):
        subprocess.run([self.cli, "workspaces", "archive", ws, "--local"], check=True, capture_output=True)

    def watch_env(self):
        """The watcher's machine and CLI: the ones this adapter resolved."""
        return {"BOSS_HOST": self.host_id(), "BOSS_HOST_CLI": self.cli}

    def archive_cmd(self, ws):
        return f"superset workspaces archive {ws} --local"

    def screen(self, ws, terminal):
        out = _json(self.sh("terminals", "read", "--workspace", ws, "--terminal", terminal, "--max-lines", "400", "--json", timeout=20), {})
        return out.get("text", "") if isinstance(out, dict) else ""

    # ---- closing: the pane, not just the terminal, so no "Session ended" tab stays behind -------------
    def _sh_ok(self, *args):
        r = subprocess.run([self.cli, *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"superset {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:200]}")
        return r.stdout

    def _live(self, ws):
        out = json.loads(self._sh_ok("terminals", "list", "--local", "--workspace", ws, "--json"))
        return {s["terminalId"] for s in out.get("sessions", []) if not s.get("exited")}, out.get("sessions", [])

    def _panes(self, ws):
        """[(paneId, terminalId)] across the main area and the right sidebar."""
        d = json.loads(self._sh_ok("panes", "list", "--workspace", ws, "--json"))
        tabs = list(d.get("tabs", [])) + list((d.get("sidebar") or {}).get("tabs", []))
        return [(p["id"], p.get("terminalId")) for t in tabs for p in t.get("panes", []) if p.get("kind") == "terminal"]

    @staticmethod
    def dead_panes(pane_list, live):
        """Terminal panes whose terminal is no longer a live session."""
        return [pid for pid, tid in pane_list if tid and tid not in live]

    @staticmethod
    def resolve(prefix, ids):
        hits = sorted({i for i in ids if i.startswith(prefix)})
        if len(hits) != 1:
            raise SystemExit(f"boss-close: terminal {prefix!r} matches {len(hits)} sessions")
        return hits[0]

    def _close_pane(self, ws, pid, dry):
        if not dry:
            self._sh_ok("panes", "close", "--workspace", ws, "--pane", pid, "--json")
        return ("would close " if dry else "closed ") + pid

    def close(self, ws, terminals, dry=False):
        _, listed = self._live(ws)
        by_terminal = {tid: pid for pid, tid in self._panes(ws) if tid}
        out = []
        for prefix in terminals:
            tid = self.resolve(prefix, [s["terminalId"] for s in listed] + list(by_terminal))
            if tid in by_terminal:
                out.append(self._close_pane(ws, by_terminal[tid], dry))
            else:
                if not dry:
                    self._sh_ok("terminals", "close", "--local", "--workspace", ws, "--terminal", tid)
                out.append(("would close terminal " if dry else "closed terminal ") + tid)
        return out

    def close_dead(self, wss, dry=False):
        if wss is None:
            d = json.loads(self._sh_ok("workspaces", "list", "--local", "--json"))
            wss = [w["id"] for w in (d if isinstance(d, list) else d.get("workspaces", []))]
        out, n = [], 0
        for ws in wss:
            try:
                for pid in self.dead_panes(self._panes(ws), self._live(ws)[0]):
                    out.append(self._close_pane(ws, pid, dry))
                    n += 1
            except RuntimeError as e:  # a workspace without a desktop pane layout: skip it, say so
                out.append(f"skip {ws[:8]}: {e}")
        return out + [f"{'would close' if dry else 'closed'} {n} dead pane(s)"]
