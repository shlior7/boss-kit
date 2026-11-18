"""Codex CLI host.  Workers are isolated local worktrees, never existing interactive sessions."""
import json
import os
import subprocess

import bossnative
import bosshost


class Host(bosshost.Host):
    def __init__(self, cfg, manifest):
        super().__init__(cfg, manifest)
        self.cli = bosshost.installed(manifest) or "codex"

    def workers(self, ids=None):
        return bossnative.list_workers("codex", self.cfg, ids)

    def create(self, repo, branch, prompt, model="", effort="", name="", folder=""):
        def command(worktree, text, model, effort, log):
            argv = [self.cli, "exec", "--json", "-C", worktree, "--sandbox", "workspace-write",
                    "--output-last-message", log + ".final"]
            if model:
                argv += ["--model", model]
            # Codex exposes reasoning effort through config; keep an empty setting out of the invocation.
            if effort:
                argv += ["-c", f'model_reasoning_effort="{effort}"']
            return argv + [text]
        return bossnative.create("codex", self.cfg, command, branch, prompt, model, effort, name, folder)

    def send(self, wid, text, terminal=None):
        record = bossnative.get("codex", self.cfg, wid)
        # The exec JSON event stream records thread.started; use it only once it exists, rather than guessing an id.
        try:
            raw = open(record["log"]).read()
            events = []
            for line in raw.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            thread = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), "")
        except (OSError, ValueError, AttributeError):
            thread = ""
        if not thread:
            raise bosshost.Unsupported(f"sending to {wid}: Codex has not published its thread id yet; wait and retry")
        r = subprocess.run([self.cli, "queue", "--thread", thread, "--message", text, "--resume"], capture_output=True, text=True)
        if r.returncode:
            raise bosshost.Unsupported("sending to Codex worker failed: " + (r.stderr or r.stdout).strip()[:200])

    def archive(self, wid):
        bossnative.archive("codex", self.cfg, wid)

    def rename(self, wid, name):
        bossnative.rename("codex", self.cfg, wid, name)

    def move(self, wid, folder):
        bossnative.move("codex", self.cfg, wid, folder)

    def screen(self, wid, terminal):
        return bossnative.screen("codex", self.cfg, wid)

    def archive_cmd(self, wid):
        return f"boss-host archive {wid}  # only after the Codex process exits; worktree is retained"
