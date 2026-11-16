"""A host plugin for the kit's tests: workers come from fixture files, actions are logged, nothing runs."""
import json
import os

import bosskit
import bosshost


def fix(name):
    return os.path.join(os.environ.get("FIX", ""), name)


def read(name, default):
    try:
        return json.load(open(fix(name)))
    except (OSError, ValueError):
        return default


class Host(bosshost.Host):

    def log(self, *args):
        with open(fix("calls"), "a") as f:
            f.write(json.dumps([self.name, *args]) + "\n")

    def host_id(self):
        return "fake-host"

    def workers(self, ids=None):
        listed = {w["id"]: w for w in read("list.json", [])}
        out = []
        for w in read("snapshot.json", {}).get("workspaces", []):
            info = listed.get(w["id"], {})
            out.append({**w, "tags": [t.strip() for t in (info.get("tags") or "").split(",") if t.strip()],
                        "worktree": info.get("worktreePath") or "", "terminals": w.get("terminals") or []})
        return out

    def by_branch(self, branch):
        w = next((w for w in read("list.json", []) if w.get("branch") == branch), None)
        return {"id": w["id"], "worktree": w.get("worktreePath") or ""} if w else None

    def create(self, repo, branch, prompt, model="", effort="", name="", folder=""):
        self.log("create", repo, branch, prompt, model, effort, name, folder)
        return "new00001"

    def send(self, wid, text, terminal=None):
        self.log("send", wid, text, terminal)

    def rename(self, wid, name):
        self.log("rename", wid, name)

    def archive(self, wid):
        self.log("archive", wid)

    def screen(self, wid, terminal):
        return bosskit._read(fix("screen.txt"))

    def close(self, wid, terminals, dry=False):
        self.log("close", wid, terminals, dry)
        return [f"closed {t}" for t in terminals]
