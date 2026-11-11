#!/usr/bin/env python3
"""Boss deck data: one JSON snapshot of what the boss manages, for the boss-deck mod.

Read-only. Sources: the project ledger's dispatch rows (task per workspace), `superset snapshot`
(each worker's agent state), running `boss-watch-done*` processes (armed watchers), `gh` for my
open PRs (cached 5 min so a 60 s refresh stays cheap), and the tracker snapshot that
boss-tasks.py writes. Configuration: projects/<name>/config.json (see bin/bosskit.py).

usage: boss-deck-data.py [--selftest]
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosskit  # noqa: E402

PR_TTL_S = 300
MAX_WORKERS = 8
# ponytail: a watcher is "stale" by age or an idle worker; a real liveness probe would read the terminal
STALE_AGE_S = 7200
IDLE_STALE_S = 1800
PR_FIELDS = ("number,title,isDraft,reviewDecision,mergeable,statusCheckRollup,reviewRequests,"
             "url,baseRefName,headRefName,updatedAt,body,comments")
# Proof links a PR or a ledger row can carry: a published page, an artifact, a demo video.
URL_RE = re.compile(r"https?://[^\s)<>\]\"']+")
PROOF_KINDS = (
    ("page", re.compile(r"^https://app\.superset\.sh/page/")),
    ("artifact", re.compile(r"^https://claude\.ai/(?:code/)?artifact/")),
    ("demo", re.compile(r"(?:\.(?:mp4|webm|mov|gif)(?:\?|$))|^https://github\.com/user-attachments/assets/|^https://(?:www\.)?loom\.com/share/")),
)


def proof_links(text):
    """[{label, url}] for every proof link in *text*, deduplicated, in order of appearance."""
    out, seen = [], set()
    for url in URL_RE.findall(text or ""):
        url = url.rstrip(".,;:")
        kind = next((k for k, rx in PROOF_KINDS if rx.search(url)), None)
        if kind and url not in seen:
            seen.add(url)
            out.append({"label": kind, "url": url})
    return out


def run(argv, timeout=40):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ledger_tasks(path):
    """Workspace-id prefix -> (task, status word, date), newest row per workspace.

    The first dispatch table appends (newest last); each "## Dispatches <date>" section
    prepends (newest first). Rank by date, then by that order.
    """
    rows = []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return {}
    prepends = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            prepends = line.startswith("## Dispatches")
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 7 or not re.match(r"\d{4}-\d{2}-\d{2}", cols[1]):
            continue
        ws = re.match(r"(?:NEW )?([0-9a-f]{8})", cols[3])
        if not ws:
            continue
        task = cols[2].split(":", 1)[0].strip()
        status = (cols[5].split()[0] if cols[5] else "?").rstrip(",:")
        # A Proof column (6th), or "proof: <url>" anywhere in the row.
        proof = proof_links(" ".join(cols[6:-1]) + " " + " ".join(re.findall(r"proof:\s*(\S+)", line)))
        rows.append(((cols[1], prepends, -i if prepends else i), ws.group(1), task, status, cols[1], proof))
    tasks = {}
    for _, prefix, task, status, date, proof in sorted(rows, reverse=True, key=lambda r: r[0]):
        tasks.setdefault(prefix, (task, status, date, proof))
    return dict(sorted(tasks.items(), key=lambda kv: kv[1][2], reverse=True))


def watchers():
    out = run(["ps", "-axo", "pid=,etime=,command="])
    found = []
    for line in out.splitlines():
        m = re.search(r"^\s*\d+\s+(\S+)\s+\S*bash\s+\S*boss-watch-done\S*\s+([0-9a-f-]{36})\s+([0-9a-f-]{36})", line)
        if m:
            found.append({"ws": m.group(2), "term": m.group(3), "ageS": etime_s(m.group(1))})
    return found


def etime_s(etime):
    days, _, rest = etime.rpartition("-")
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + s


def host(cfg):
    h = os.environ.get("BOSS_HOST") or cfg.get("superset_host")
    if h:
        return h
    try:
        d = json.loads(run(["superset", "hosts", "list", "--json"]) or "[]")
        d = d if isinstance(d, list) else d.get("hosts", [])
        return d[0]["id"] if d else ""
    except (ValueError, KeyError, IndexError):
        return ""


def snapshot(cfg):
    raw = run(["superset", "snapshot", "--host", host(cfg), "--json"])
    try:
        return json.loads(raw).get("workspaces", [])
    except ValueError:
        return []


def ci_summary(rollup):
    fail = pend = ok = 0
    for c in rollup or []:
        name = (c.get("name") or c.get("context") or "").lower()
        if "approval" in name:  # a missing review, not CI
            continue
        state = (c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
        if state in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"):
            fail += 1
        elif state in ("SUCCESS", "SKIPPED", "NEUTRAL"):
            ok += 1
        else:
            pend += 1
    return "red" if fail else "pending" if pend else "green"


def pr_row(repo, p, primary):
    text = " ".join([p.get("body") or ""] + [c.get("body") or "" for c in p.get("comments") or []])
    return {
        "proof": proof_links(text),
        "repo": repo, "primary": primary, "num": p["number"], "title": p["title"][:60],
        "draft": p.get("isDraft", False), "review": p.get("reviewDecision") or "",
        "merge": p.get("mergeable") or "", "ci": ci_summary(p.get("statusCheckRollup")),
        "reviewers": [r.get("login") or r.get("name") or "" for r in p.get("reviewRequests") or []],
        "url": p.get("url", ""), "base": p.get("baseRefName", ""), "head": p.get("headRefName", ""),
        "updated": p.get("updatedAt", ""),
    }


def prs(cfg, sdir):
    cache = os.path.join(sdir, "deck-prs.json")
    try:
        cached = json.load(open(cache))
        if time.time() - cached["at"] < PR_TTL_S:
            return cached["prs"]
    except (OSError, ValueError, KeyError):
        pass
    rows = []
    raw = run(["gh", "pr", "list", "--repo", cfg["repo"], "--author", cfg["me"],
               "--state", "open", "--json", PR_FIELDS, "--limit", "30"], timeout=60)
    for p in json.loads(raw or "[]"):
        rows.append(pr_row(cfg["repo"], p, True))
    for ref in cfg.get("extra_prs", []):  # "owner/repo#123"
        repo, _, num = ref.partition("#")
        raw = run(["gh", "pr", "view", num, "--repo", repo, "--json", PR_FIELDS + ",state"], timeout=60)
        if raw and json.loads(raw).get("state") == "OPEN":
            rows.append(pr_row(repo, json.loads(raw), repo == cfg["repo"]))
    json.dump({"at": time.time(), "prs": rows}, open(cache, "w"))
    return rows


def board(cfg, sdir):
    try:
        tasks = json.load(open(os.path.join(sdir, "tracker.json"))).values()
    except (OSError, ValueError):
        return {}
    me = (cfg.get("tracker") or {}).get("assignee")
    mine = [t for t in tasks if t.get("assignee") == me and t.get("status") not in ("Done", "Cancelled")]
    return {
        "mine": len(mine),
        "p1": sum(t.get("priority") in ("P0", "P1") for t in mine),
        "inProgress": sum(t.get("status") == "In Progress" for t in mine),
    }


def attention(workers, armed, prs):
    """What needs the user or the boss, most urgent first."""
    items = []
    for w in workers:
        if w["state"] == "blocked":
            items.append({"level": "act", "text": f"{w['name']}: blocked on {w['task']}"})
        elif w["state"] != "working" and w["ledger"] == "DISPATCHED" and not w["watched"]:
            items.append({"level": "check", "text": f"{w['name']}: idle, {w['task']} has no watcher"})
    for w in armed:
        if w["stale"]:
            items.append({"level": "check", "text": f"watcher {w['ws'][:8]} stale ({w['ageS'] // 60}m)"})
    for p in prs:
        tag = f"#{p['num']}" if p.get("primary") else f"{p['repo']}#{p['num']}"
        if p["ci"] == "red" and not p["draft"]:
            items.append({"level": "act", "text": f"{tag} CI red"})
        elif p["review"] == "APPROVED" and p["ci"] == "green" and not p["draft"]:
            items.append({"level": "act", "text": f"{tag} approved + green: ready to merge"
                          + ("" if p.get("proof") else " (no proof)")})
    order = {"act": 0, "check": 1}
    return sorted(items, key=lambda i: order[i["level"]])


def main():
    _, cfg, pdir, sdir = bosskit.load()
    tasks = ledger_tasks(os.path.join(pdir, cfg.get("ledger", "ledger.md")))
    armed = watchers()
    spaces = snapshot(cfg)
    by_prefix = {w["id"][:8]: w for w in spaces}
    watched = {w["ws"][:8] for w in armed}
    workers = []
    for prefix, (task, status, date, proof) in list(tasks.items()):
        if len(workers) >= MAX_WORKERS and prefix not in watched:
            continue
        w = by_prefix.get(prefix)
        if w is None and prefix not in watched:
            continue  # archived workspace
        agents = [t for t in (w or {}).get("terminals", []) if t.get("agent")]
        agent_states = [t["agent"].get("state") for t in agents]
        state = "working" if "working" in agent_states else (agent_states[0] if agent_states else "gone")
        workers.append({
            "ws": prefix, "id": (w or {}).get("id", ""), "term": agents[0]["id"] if agents else "",
            "name": (w or {}).get("name", "?")[:28], "branch": (w or {}).get("branch", ""),
            "task": task, "ledger": status, "date": date, "state": state, "watched": prefix in watched,
            "proof": proof,
        })
    states = {w["ws"]: w["state"] for w in workers}
    for w in armed:
        idle = states.get(w["ws"][:8]) not in ("working", None)
        w["stale"] = w["ageS"] > STALE_AGE_S or (idle and w["ageS"] > IDLE_STALE_S)
    pr_rows = prs(cfg, sdir)
    try:
        now_line = open(os.path.join(sdir, "next.txt")).read().strip().splitlines()[0][:120]
    except (OSError, IndexError):
        now_line = ""
    review = None
    rpath = os.path.join(sdir, "review.txt")
    try:
        url = open(rpath).read().split()[0]
        review = {"url": url, "date": time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(rpath)))}
    except (OSError, IndexError):
        pass
    print(json.dumps({
        "at": int(time.time()), "next": now_line, "review": review, "attention": attention(workers, armed, pr_rows),
        "workers": workers, "watchers": armed, "prs": pr_rows, "board": board(cfg, sdir),
    }))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        assert etime_s("01:19") == 79 and etime_s("1:02:03") == 3723 and etime_s("2-00:00:01") == 172801
        assert ci_summary([{"name": "Ownership approval", "conclusion": "FAILURE"}, {"name": "x", "conclusion": "SUCCESS"}]) == "green"
        assert ci_summary([{"name": "x", "status": "IN_PROGRESS"}]) == "pending"
        assert ci_summary([{"name": "x", "conclusion": "FAILURE"}]) == "red"
        w = {"name": "pr-1", "task": "t", "state": "idle", "ledger": "DISPATCHED", "watched": False}
        p = {"num": 9, "repo": "acme/widgets", "primary": True, "ci": "green", "review": "APPROVED", "draft": False}
        got = [i["text"] for i in attention([w], [], [p])]
        assert got == ["#9 approved + green: ready to merge (no proof)", "pr-1: idle, t has no watcher"], got
        p["proof"] = [{"label": "page", "url": "https://app.superset.sh/page/x"}]
        assert attention([], [], [p])[0]["text"] == "#9 approved + green: ready to merge"
        text = ("Demo: https://github.com/user-attachments/assets/ab12 and page https://app.superset.sh/page/fix-42-ab3d. "
                "Also (https://claude.ai/code/artifact/9f2e), a clip https://cdn.example.com/run.mp4?x=1, "
                "plus junk: https://github.com/acme/widgets/pull/42 https://example.com/img.png and again "
                "https://app.superset.sh/page/fix-42-ab3d.")
        assert [(x["label"], x["url"]) for x in proof_links(text)] == [
            ("demo", "https://github.com/user-attachments/assets/ab12"),
            ("page", "https://app.superset.sh/page/fix-42-ab3d"),
            ("artifact", "https://claude.ai/code/artifact/9f2e"),
            ("demo", "https://cdn.example.com/run.mp4?x=1"),
        ], proof_links(text)
        assert proof_links("") == [] and proof_links(None) == []
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("## Dispatches 2026-01-02\n\n| Date | Task | WS | Model | Status |\n|---|---|---|---|---|\n"
                    "| 2026-01-02 | fix-42: do it | 1a2b3c4d / 5e6f | mid | DISPATCHED, watcher armed | https://app.superset.sh/page/p42 |\n"
                    "| 2026-01-01 | old-41: older | 1a2b3c4d / 5e6f | mid | DONE |\n")
        assert ledger_tasks(f.name) == {"1a2b3c4d": ("fix-42", "DISPATCHED", "2026-01-02",
                                                     [{"label": "page", "url": "https://app.superset.sh/page/p42"}])}, ledger_tasks(f.name)
        print("ok")
    else:
        main()
