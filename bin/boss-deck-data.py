#!/usr/bin/env python3
"""Boss deck data: one JSON snapshot of what the boss manages, for the boss-deck mod.

Read-only. Sources: the project ledger's dispatch rows (task per workspace), `superset snapshot`
(each worker's agent state), running `boss-watch-done*` processes (armed watchers), `gh` for my
open PRs (cached 5 min so a 60 s refresh stays cheap), this boss's events.jsonl (each workspace's
stage log, from bin/boss-event and the watcher), the tracker snapshot boss-tasks.py writes,
this boss's inbox, and the registry of bosses (this project's: the main boss and its domain
bosses). Each run is also this boss's heartbeat, carrying its domain and next line.
Each workspace joins its PR by branch and gets a stage: move, checking, working, review or done
(merged or retired today, archived workspaces included).
Paths and project resolution: bin/bosskit.py.

usage: boss-deck-data.py [--session-start] [--fresh] [--workspace ID] [--cwd DIR] [--selftest]
  --fresh: skip the PR cache (the pane passes it right after the boss merges, comments or dispatches)
  --session-start: also mark this boss's new session (the base for "N new shared lessons"), and
                   rename this boss's own Paradev workspace to BOSS
  --workspace, --cwd: the session's workspace id and directory, which the mod passes so its process
                      resolves the same boss as the session's shell
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosskit  # noqa: E402

PR_TTL_S = 300
MAX_WORKERS = 8
DONE_TODAY_ROWS = 5
EVENT_ROWS = 8  # a workspace's newest events, for its timeline
# Event stages, lower-cased. DONE_EVENTS: the worker finished; END_EVENTS: the work is over; CHECKED_EVENTS: the boss verified it.
DONE_EVENTS = {"done", "pr ready"}
END_EVENTS = {"merged", "retired"}
CHECKED_EVENTS = {"checked", "ready"}
# Ledger status words that mean the boss verified the row's work.
VERIFIED_LEDGER = {"VERIFIED", "CHECKED", "READY", "MERGED", "ARCHIVED"}
# A PR comment that starts a DONE envelope (bin/boss-watch-done.sh's pick() uses the same test).
DONE_COMMENT = re.compile(r"(^|\n)[ \t>`]*SUPERSET_WORKER_DONE[ \t]+task:[ \t]*[A-Za-z0-9._-]")
# What a boss names its own Paradev workspace at session start.
BOSS_NAME = "BOSS"
# A boss refreshes every minute; past this its heartbeat age shows (bosskit.live drops it after STALE_S).
BOSS_STALE_S = 300
STATE_LINES = 3  # a domain boss's state file, in its details
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
        text = cols[2].strip()
        status = (cols[5].split()[0] if cols[5] else "?").rstrip(",:")
        # A Proof column (6th), or "proof: <url>" anywhere in the row.
        # Optional columns: Proof (6th), Boss (7th). Old rows have neither and still parse.
        proof = proof_links(" ".join(cols[6:7]) + " " + " ".join(re.findall(r"proof:\s*(\S+)", line)))
        boss = cols[7] if len(cols) >= 9 else ""
        rows.append(((cols[1], prepends, -i if prepends else i), ws.group(1), text, status, cols[1], proof, boss))
    tasks = {}
    for _, prefix, text, status, date, proof, boss in sorted(rows, reverse=True, key=lambda r: r[0]):
        tasks.setdefault(prefix, (task_id(text), status, date, proof, boss, text))
    return dict(sorted(tasks.items(), key=lambda kv: kv[1][2], reverse=True))


def task_id(text):
    """A ledger task cell's id, its first token: "fix-42 (queued after fix-41)" or "fix-42: x" -> "fix-42"."""
    return re.split(r"[\s:]+", text.strip())[0] or "?"


def repo_tag(repo, aliases=None):
    """A short tag for a PR's repo: config's repo_aliases entry, else the first letter of each word of
    its last path segment ("acme/widgets-sdk" -> "ws")."""
    if (aliases or {}).get(repo):
        return aliases[repo]
    words = re.split(r"[-_.\s]+", repo.rsplit("/", 1)[-1])
    return "".join(w[0] for w in words if w).lower() or repo


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


def name_boss_workspace(cfg):
    """Names this boss's own Paradev workspace BOSS, so it stands out in the sidebar. Every session, so a rename back heals."""
    ws = os.environ.get("SUPERSET_WORKSPACE_ID")
    if ws:
        run(["superset", "workspaces", "update", ws, "--host", host(cfg), "--name", BOSS_NAME], timeout=20)


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


def epoch(iso):
    """Seconds since the epoch of an ISO time like GitHub's "2026-01-02T10:31:00Z"; 0 when unparsable."""
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


def day_start(now):
    """Local midnight of the day *now* falls in."""
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def pr_row(repo, p, primary):
    comments = p.get("comments") or []
    text = " ".join([p.get("body") or ""] + [c.get("body") or "" for c in comments])
    return {
        # When the newest comment starting a DONE envelope landed: the screen-free done signal.
        "doneAt": max((epoch(c.get("createdAt", "")) for c in comments if DONE_COMMENT.search(c.get("body") or "")), default=0),
        "proof": proof_links(text),
        "repo": repo, "primary": primary, "num": p["number"], "title": p["title"][:60],
        "draft": p.get("isDraft", False), "review": p.get("reviewDecision") or "",
        "merge": p.get("mergeable") or "", "ci": ci_summary(p.get("statusCheckRollup")),
        "reviewers": [r.get("login") or r.get("name") or "" for r in p.get("reviewRequests") or []],
        "url": p.get("url", ""), "base": p.get("baseRefName", ""), "head": p.get("headRefName", ""),
        "updated": p.get("updatedAt", ""),
    }


def prs(cfg, cache_dir, fresh=False):
    """My open PRs; cached PR_TTL_S unless fresh (right after the boss merged, commented or dispatched)."""
    cache = os.path.join(cache_dir, "deck-prs.json")
    try:
        cached = json.load(open(cache))
        if not fresh and time.time() - cached["at"] < PR_TTL_S:
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


def join(workers, prs):
    """Each worker's open PR, by branch == the PR's head (the project's own repo first), and each joined PR's workspace."""
    by_head = {}
    for p in sorted(prs, key=lambda p: not p.get("primary")):
        by_head.setdefault(p["head"], p)
    for w in workers:
        p = by_head.get(w["branch"]) if w["branch"] else None
        w["pr"] = p
        if p:
            p["ws"] = w["ws"]
            w["prTag"] = f"#{p['num']}" if p.get("primary") else f"{p.get('tag') or p['repo']}#{p['num']}"


def stage(state, ledger, pr, evs, today):
    """A workspace's lane, first match wins: move (its PR approved + green), checking (DONE not yet verified,
    or a ready PR gone red), working (agent busy or blocked, or idle without DONE), review (PR ready), done
    (merged or retired today). Only events since the last dispatch ("sent") count; anything else is working."""
    sent = max((e["at"] for e in evs if e["stage"].lower() == "sent"), default=0)
    at = lambda kinds: max((e["at"] for e in evs if e["at"] >= sent and e["stage"].lower() in kinds), default=0)
    ready = bool(pr) and not pr["draft"]
    pr_done = (pr or {}).get("doneAt", 0)
    done_at = max(at(DONE_EVENTS | END_EVENTS), pr_done if pr_done >= sent else 0)
    # A ready PR was marked ready by the boss (workers never do), so it is done and verified.
    verified = ready or ledger.upper() in VERIFIED_LEDGER or (done_at and at(CHECKED_EVENTS) >= done_at)
    if ready and pr["review"] == "APPROVED" and pr["ci"] == "green":
        return "move"
    if (done_at and not verified) or (ready and pr["ci"] == "red"):
        return "checking"
    if state in ("working", "blocked") or not (done_at or verified):
        return "working"
    if ready:
        return "review"
    if at(END_EVENTS) >= today:
        return "done"
    return "working"


def lanes(workers, archived, evs, today):
    """Stage, since and recent events on each workspace; the open ones, then the newest few done today,
    archived workspaces included."""
    for w in workers + archived:
        mine = evs.get(w["ws"], [])
        w["stage"] = stage(w["state"], w["ledger"], w.get("pr"), mine, today)
        w["since"] = since(mine, w.get("pr"), w["date"])
        w["events"] = [{**e, "hm": time.strftime("%H:%M", time.localtime(e["at"]))} for e in mine[-EVENT_ROWS:]]
    finished = sorted([w for w in workers + archived if w["stage"] == "done"], key=lambda w: w["since"], reverse=True)
    return [w for w in workers if w["stage"] != "done"] + finished[:DONE_TODAY_ROWS]


def since(evs, pr, date):
    """When the workspace's current stage began: its newest event, else its PR's last update, else its ledger date."""
    if evs:
        return evs[-1]["at"]
    if pr and epoch(pr.get("updated", "")):
        return epoch(pr["updated"])
    try:
        return int(time.mktime(time.strptime(date, "%Y-%m-%d")))
    except (ValueError, TypeError):
        return 0


def board(cfg, snapshot):
    """Counts of my open tracker tasks, from boss-tasks.py's snapshot."""
    tracker = cfg.get("tracker") or {}
    me = tracker.get("assignee")
    # A tracker switched off leaves its old snapshot behind; without an assignee, unassigned tasks would count as mine.
    if not isinstance(snapshot, dict) or tracker.get("type") == "none" or not me:
        return {}
    tasks = snapshot.values()
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


def mail(inbox):
    """This boss's unread mail: count plus the newest subjects. Reads the inbox dir only."""
    items = []
    for f in sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []:
        if f.endswith(".json"):
            try:
                m = json.load(open(os.path.join(inbox, f)))
                items.append({"id": m["id"], "kind": m.get("kind", ""), "from": m.get("from_project", ""), "subject": m.get("subject", "")})
            except (OSError, ValueError, KeyError):
                continue
    return {"count": len(items), "dir": inbox, "items": items[-5:]}


def lessons_new(home, bdir, session_start=False):
    """How many shared lessons were added since this boss's previous session."""
    count = len(bosskit.lesson_entries(bosskit._read(os.path.join(home, "lessons.md"))))
    path = os.path.join(bdir, "lessons-seen.json")
    try:
        seen = json.load(open(path))
    except (OSError, ValueError):
        seen = {"base": count, "seen": count}
    if session_start:
        seen = {"base": seen.get("seen", count), "seen": count}
        bosskit.save_json(path, seen)
    elif not os.path.exists(path):
        bosskit.save_json(path, seen)
    return max(0, count - seen.get("base", count))


def others(reg, me, now=None, workspace="", wt=""):
    """One summary per other live boss, for the pane's quiet lines: never this boss (by id, workspace
    or worktree), and one per workspace, its newest heartbeat."""
    best = {}
    for i, b in bosskit.live(reg, now).items():
        if i == me or bosskit.same_boss(b, workspace, wt):
            continue
        k = b.get("workspace") or i
        if k not in best or b.get("heartbeat", 0) > best[k][1].get("heartbeat", 0):
            best[k] = (i, b)
    return [{"id": i, "project": b.get("project", ""), "workspace": b.get("workspace", ""),
             "working": b.get("working", 0), "forYou": b.get("forYou", 0)}
            for i, b in sorted(best.values(), key=lambda ib: ib[0])]


def domain_state(pdir, domain):
    """The first few non-heading lines of <project>/domains/<domain>-state.md; none for the main boss."""
    if not domain:
        return []
    lines = bosskit._read(os.path.join(pdir, "domains", f"{domain}-state.md")).splitlines()
    return [l.strip()[:120] for l in lines if l.strip() and not l.lstrip().startswith("#")][:STATE_LINES]


def bosses(reg, project, me, pdir, now=None, workspace="", wt=""):
    """This project's live bosses, one per workspace: this boss first, then the main boss, then domains by name."""
    now = now or time.time()
    best = {}
    for i, b in bosskit.live(reg, now, project).items():
        k = "" if i == me or bosskit.same_boss(b, workspace, wt) else (b.get("workspace") or i)
        if k not in best or b.get("heartbeat", 0) > best[k][1].get("heartbeat", 0):
            best[k] = (i, b)
    out = [{"id": i, "workspace": b.get("workspace", ""), "domain": b.get("domain", ""), "me": k == "",
            "next": b.get("next", ""), "working": b.get("working", 0), "forYou": b.get("forYou", 0),
            "heartbeat": b.get("heartbeat", 0), "stale": now - b.get("heartbeat", 0) > BOSS_STALE_S,
            "state": domain_state(pdir, b.get("domain", ""))} for k, (i, b) in best.items()]
    return sorted(out, key=lambda b: (not b["me"], b["domain"] != "", b["domain"]))


def arg(name):
    """The value after *name* on the command line, or None."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else None


def main():
    if arg("--workspace"):
        os.environ["SUPERSET_WORKSPACE_ID"] = arg("--workspace")
    ctx = bosskit.load(arg("--cwd"))
    if not bosskit.is_boss(ctx):
        sys.exit(bosskit.not_boss_note(ctx))  # no heartbeat, no rename: another workspace is the boss
    cfg = ctx.cfg
    tasks = ledger_tasks(os.path.join(ctx.pdir, cfg.get("ledger", "ledger.md")))
    # Watchers are host-wide; keep the ones on this boss's dispatches (rows without a Boss belong to every boss).
    mine = {p for p, row in tasks.items() if not row[4] or row[4] == ctx.bid}
    armed = [w for w in watchers() if w["ws"][:8] in mine]
    spaces = snapshot(cfg)
    by_prefix = {w["id"][:8]: w for w in spaces}
    watched = {w["ws"][:8] for w in armed}
    pr_rows = prs(cfg, ctx.cache, "--fresh" in sys.argv)
    for p in pr_rows:
        p["tag"] = repo_tag(p["repo"], cfg.get("repo_aliases"))
    evs = {}
    for e in bosskit.events(ctx.bdir):
        evs.setdefault(e["ws"][:8], []).append(e)
    # Name, branch and PR tag of each workspace seen, so an archived one still reads right as done today.
    seen_path = os.path.join(ctx.cache, "workspaces.json")
    try:
        seen = json.load(open(seen_path))
    except (OSError, ValueError):
        seen = {}
    today = day_start(time.time())
    workers, done = [], []
    for prefix, (task, status, date, proof, boss, text) in list(tasks.items()):
        if boss and boss != ctx.bid:
            continue  # another boss's dispatch
        w = by_prefix.get(prefix)
        archived = w is None and prefix not in watched
        if archived and not any(e["at"] >= today and e["stage"].lower() in END_EVENTS for e in evs.get(prefix, [])):
            continue  # archived, and not today
        if not archived and len(workers) >= MAX_WORKERS and prefix not in watched:
            continue
        old = seen.get(prefix, {})
        agents = [t for t in (w or {}).get("terminals", []) if t.get("agent")]
        agent_states = [t["agent"].get("state") for t in agents]
        state = "working" if "working" in agent_states else (agent_states[0] if agent_states else "gone")
        (done if archived else workers).append({
            "ws": prefix, "id": (w or {}).get("id", ""), "term": agents[0]["id"] if agents else "",
            "name": (w or {}).get("name", old.get("name", task))[:28], "branch": (w or {}).get("branch", old.get("branch", "")),
            "task": task, "taskText": text, "ledger": status, "date": date, "state": state, "watched": prefix in watched,
            "proof": proof, "prTag": old.get("prTag", ""),
        })
    join(workers, pr_rows)
    workers = lanes(workers, done, evs, today)
    for w in workers:
        seen[w["ws"]] = {"name": w["name"], "branch": w["branch"], "prTag": w["prTag"]}
    bosskit.save_json(seen_path, seen)
    states = {w["ws"]: w["state"] for w in workers}
    for w in armed:
        idle = states.get(w["ws"][:8]) not in ("working", None)
        w["stale"] = w["ageS"] > STALE_AGE_S or (idle and w["ageS"] > IDLE_STALE_S)
    try:
        now_line = open(os.path.join(ctx.bdir, "next.txt")).read().strip().splitlines()[0][:120]
    except (OSError, IndexError):
        now_line = ""
    review = None
    rpath = os.path.join(ctx.bdir, "review.txt")
    try:
        url = open(rpath).read().split()[0]
        review = {"url": url, "date": time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(rpath)))}
    except (OSError, IndexError):
        pass
    todo = attention([w for w in workers if w["stage"] != "done"], armed, pr_rows)
    working = sum(w["state"] == "working" for w in workers)
    for_you = sum(a["level"] == "act" for a in todo)
    bosskit.heartbeat(ctx, host(cfg), {"working": working, "forYou": for_you,
                                       "domain": bosskit.boss_domain(ctx.worktree), "next": now_line})
    if "--session-start" in sys.argv:
        name_boss_workspace(cfg)
    print(json.dumps({
        "at": int(time.time()), "me": {"id": ctx.bid, "project": ctx.name}, "next": now_line, "review": review,
        "attention": todo, "workers": workers, "watchers": armed, "prs": pr_rows, "board": board(cfg, bosskit.tracker_snapshot(ctx)),
        "others": others(bosskit.registry(ctx.home), ctx.bid, workspace=ctx.workspace, wt=ctx.worktree), "mail": mail(ctx.inbox),
        "bosses": bosses(bosskit.registry(ctx.home), ctx.name, ctx.bid, ctx.pdir, workspace=ctx.workspace, wt=ctx.worktree),
        "lessonsNew": lessons_new(ctx.home, ctx.bdir, "--session-start" in sys.argv),
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
                                                     [{"label": "page", "url": "https://app.superset.sh/page/p42"}], "", "fix-42: do it")}, ledger_tasks(f.name)
        with open(f.name, "a") as g:  # a newer row with a Boss column, for another boss
            g.write("| 2026-01-03 | fix-43: next | 1a2b3c4d / 5e6f | mid | DISPATCHED | | boss-b |\n")
        assert ledger_tasks(f.name)["1a2b3c4d"][4] == "boss-b"
        with open(f.name, "a") as g:  # a task cell carrying the ledger's note
            g.write("| 2026-01-04 | fix-44 (queued after fix-43) | 1a2b3c4d / 5e6f | mid | QUEUED |\n")
        assert ledger_tasks(f.name)["1a2b3c4d"][0] == "fix-44" and ledger_tasks(f.name)["1a2b3c4d"][5] == "fix-44 (queued after fix-43)"
        assert task_id("") == "?"
        assert repo_tag("acme/widgets-sdk") == "ws" and repo_tag("acme/widgets") == "w" and repo_tag("acme/web_app.v2") == "wav"
        assert repo_tag("acme/widgets-sdk", {"acme/widgets-sdk": "m"}) == "m" and repo_tag("acme/x", {"acme/y": "z"}) == "x"
        now = time.time()
        reg = {"me": {"project": "a", "heartbeat": now}, "b": {"project": "b", "workspace": "ws-b", "heartbeat": now - 60,
               "working": 2, "forYou": 1}, "old": {"project": "c", "heartbeat": now - 4000}}
        assert others(reg, "me", now) == [{"id": "b", "project": "b", "workspace": "ws-b", "working": 2, "forYou": 1}]
        d = tempfile.mkdtemp()
        for i in (1, 2):
            json.dump({"id": f"m{i}", "kind": "fyi", "from_project": "b", "subject": f"s{i}"}, open(os.path.join(d, f"m{i}.json"), "w"))
        open(os.path.join(d, "junk.txt"), "w").write("x")
        got = mail(d)
        assert got["count"] == 2 and [m["subject"] for m in got["items"]] == ["s1", "s2"], got
        print("ok")
    else:
        main()
