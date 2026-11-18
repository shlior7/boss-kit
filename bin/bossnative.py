"""Safe local-process workers for host plugins that run each worker as a detached CLI process.

Each worker owns a normal git worktree and one detached CLI process.  The record is local
to $BOSS_HOME, so discovering or archiving a worker never requires interrogating another
provider's private session store.  Archiving deliberately refuses a live process and never
removes a worktree: a boss must make that cleanup decision explicitly.
"""
import json
import os
import re
import subprocess
import time
import uuid

import bosskit
import bosshost


def _project(cfg):
    raw = os.environ.get("BOSS_PROJECT") or cfg.get("repo") or "default"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-") or "default"


def root(kind, cfg):
    return os.path.join(bosskit.home(), _project(cfg), "native-workers", kind)


def record_path(kind, cfg, wid):
    return os.path.join(root(kind, cfg), wid + ".json")


def records(kind, cfg):
    directory = root(kind, cfg)
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(directory, name)))
            if isinstance(data, dict) and data.get("id"):
                out.append(data)
        except (OSError, ValueError):
            continue
    return out


def get(kind, cfg, wid):
    hits = [d for d in records(kind, cfg) if d["id"].startswith(wid) or wid.startswith(d["id"])]
    if len(hits) != 1:
        raise bosshost.Unsupported(f"native worker {wid!r} matches {len(hits)} records")
    return hits[0]


def save(kind, cfg, data):
    os.makedirs(root(kind, cfg), exist_ok=True)
    bosskit.save_json(record_path(kind, cfg, data["id"]), data)


def running(pid):
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def worker(data):
    active = running(data.get("pid")) and not data.get("archived")
    return {"id": data["id"], "name": data.get("name") or data.get("branch") or data["id"][:8],
            "branch": data.get("branch", ""), "worktree": data.get("worktree", ""),
            "tags": [data["folder"]] if data.get("folder") else [],
            "terminals": [{"id": "agent", "title": data.get("name") or "", "agent": {"state": "working" if active else "idle"}}]}


def list_workers(kind, cfg, ids=None):
    rows = [worker(d) for d in records(kind, cfg)]
    if ids is None:
        return rows
    return [w for w in rows if any(w["id"].startswith(i) or i.startswith(w["id"]) for i in ids)]


def git_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise bosshost.Unsupported("creating a native worker: run boss-host from a git worktree")
    return r.stdout.strip()


def new_worktree(kind, cfg, branch, wid):
    base = cfg.get("worktrees_dir") or os.path.join(bosskit.home(), _project(cfg), "worktrees", kind)
    base = os.path.abspath(os.path.expanduser(base))
    os.makedirs(base, exist_ok=True)
    leaf = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip(".-")[:48] or "worker"
    path = os.path.join(base, leaf + "-" + wid[:8])
    root = git_root()
    r = subprocess.run(["git", "-C", root, "worktree", "add", "-b", branch, path], capture_output=True, text=True)
    if r.returncode:
        raise bosshost.Unsupported("creating a native worktree failed: " + (r.stderr or r.stdout).strip()[:240])
    return path


def create(kind, cfg, command, branch, prompt, model="", effort="", name="", folder=""):
    wid = uuid.uuid4().hex
    worktree = new_worktree(kind, cfg, branch, wid)
    log = os.path.join(root(kind, cfg), wid + ".log")
    argv = command(worktree, prompt, model, effort, log)
    os.makedirs(root(kind, cfg), exist_ok=True)
    try:
        with open(log, "w") as output:
            proc = subprocess.Popen(argv, cwd=worktree, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                    start_new_session=True, text=True)
    except OSError as e:
        # The branch/worktree is intentionally retained for recovery; removing it here could erase agent output.
        raise bosshost.Unsupported(f"starting {kind} worker failed; retained {worktree}: {e}")
    data = {"id": wid, "pid": proc.pid, "branch": branch, "worktree": worktree, "log": log,
            "name": name, "folder": folder, "created_at": time.time(), "command": argv}
    save(kind, cfg, data)
    return wid


def archive(kind, cfg, wid):
    data = get(kind, cfg, wid)
    if running(data.get("pid")):
        raise bosshost.Unsupported(f"archiving {wid}: worker process is still running; wait for it to finish (boss-kit never kills a worker)")
    data["archived"] = True
    data["archived_at"] = time.time()
    save(kind, cfg, data)


def rename(kind, cfg, wid, name):
    data = get(kind, cfg, wid)
    data["name"] = name
    save(kind, cfg, data)


def move(kind, cfg, wid, folder):
    data = get(kind, cfg, wid)
    data["folder"] = folder
    save(kind, cfg, data)


def screen(kind, cfg, wid, limit=16000):
    data = get(kind, cfg, wid)
    try:
        with open(data.get("log", ""), errors="replace") as f:
            return f.read()[-limit:]
    except OSError:
        return ""

