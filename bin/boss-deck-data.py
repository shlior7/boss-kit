#!/usr/bin/env python3
"""Boss deck data: one JSON snapshot of what the boss manages, for the boss-deck mod.

Read-only. Sources: the project ledger's dispatch rows (task per workspace), the host's workers (bin/bosshost.py:
each worker's agent state, tags and worktree), the armed watchers (`boss-host watch` leaves one file each in cache/watchers/), `gh` for my
open PRs (cached 5 min so a 60 s refresh stays cheap), this boss's events.jsonl (each workspace's
stage log, from bin/boss-event and the watcher), the tracker snapshot boss-tasks.py writes,
this boss's inbox, and the registry of bosses (this project's: the main boss and its domain
bosses). Each run is also this boss's heartbeat, carrying its domain and next line.
Each workspace joins its PR by branch and gets a stage: move, waiting, checking, working, review or done
(merged or retired today, archived workspaces included). In boss mode the boss's own workspace is never a worker: its
other agent terminals (research and ops sessions) are rows of its BOSSES entry instead.
Paths and project resolution: bin/bosskit.py.

Worker mode (--worker): the same pane in a dispatched worker's own session. It finds the workspace's newest
dispatch row across every project's ledger, its boss, its PR (the boss's fetch and cache), pushed commits, its
events and the messages the boss sent it, and keeps the worktree's .boss-worker/ (notes.md, status.json, pages.jsonl) git-ignored.
Every worker appends one {url, title, at} line per page it publishes to .boss-worker/pages.jsonl; the boss keeps its own
in its boss folder. Both panes list them, and the header names config's page provider when `pages` sets one.

usage: boss-deck-data.py [--session-start] [--fresh] [--workspace ID] [--host-kind K] [--terminal ID] [--cwd DIR] [--selftest]
       boss-deck-data.py --worker --workspace ID [--host-kind K] [--cwd DIR] [--status JSON]
  --fresh: skip the PR cache (the pane passes it right after the boss merges, comments or dispatches)
  --session-start: also mark this boss's new session (the base for "N new shared lessons"), and
                   rename this boss's own workspace or session to config's boss_name (BOSS)
  --workspace, --cwd: the session's id on its host and its directory, which the mod passes so its
                      process resolves the same boss as the session's shell
  --host-kind: the host plugin the session runs in (the mod passes it; config's host still wins)
  --terminal: the session's own terminal id (else the host's terminal env var), left out of this boss's sessions list
  --status: the worker pane's task progress, {tasks_done, tasks_total, current}, written to .boss-worker/status.json
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosshost  # noqa: E402
import bosskit  # noqa: E402

PR_TTL_S = 300
MAX_WORKERS = 8
DONE_TODAY_ROWS = 5
EVENT_ROWS = 8  # a workspace's newest events, for its timeline
# Event stages, lower-cased. DONE_EVENTS: the worker finished; END_EVENTS: the work is over; CHECKED_EVENTS: the boss verified it.
DONE_EVENTS = {"done", "pr ready"}
END_EVENTS = {"merged", "retired"}
CHECKED_EVENTS = {"checked", "ready"}
# Ledger status words that mean the boss verified the row's work, or that the worker reported DONE.
VERIFIED_LEDGER = {"VERIFIED", "CHECKED", "READY", "MERGED", "ARCHIVED"}
DONE_LEDGER = {"DONE"}
# A PR comment that starts a DONE envelope, or carries its hidden marker (<!-- BOSS_WORKER_DONE task: x -->);
# use_host() adds the host's older envelope tokens.
DONE_COMMENT = re.compile(r"(^|\n)[ \t>`]*(?:<!--[ \t]*)?BOSS_WORKER_DONE\s+task:[ \t]*[A-Za-z0-9._-]")
# A boss refreshes every minute; past this its heartbeat age shows (bosskit.live drops it after STALE_S).
BOSS_STALE_S = 300
STATE_LINES = 3  # a domain boss's state file, in its details
# ponytail: a watcher is "stale" by age or an idle worker; a real liveness probe would read the terminal
STALE_AGE_S = 7200
IDLE_STALE_S = 1800
# Worker mode: rows per section, and the event stages DELIVERED lists ("msg" goes to FROM BOSS instead).
DELIVERED_ROWS = 5
MSG_ROWS = 10
NOTE_ROWS = 4
PAGE_ROWS = 8
# A Boss cell that can be a boss id; anything else (a dash, a note) counts as any boss, never as another one.
BOSS_CELL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{3,}")
BOSS_NOTE_ROWS = 2
DELIVERED_EVENTS = {"sent", "pr ready", "done", "checked", "ready", "merged"}
PR_FIELDS = ("number,title,isDraft,reviewDecision,mergeable,mergeStateStatus,statusCheckRollup,reviewRequests,"
             "url,baseRefName,headRefName,headRefOid,updatedAt,body,comments")
BEHIND_PRS = 20  # PRs per fetch that get a compare call for "N behind <base>"
# Proof links a PR or a ledger row can carry: a published page, an artifact, a demo video.
URL_RE = re.compile(r"https?://[^\s)<>\]\"']+")
PROOF_KINDS = (
    ("artifact", re.compile(r"^https://claude\.ai/(?:code/)?artifact/")),
    ("demo", re.compile(r"(?:\.(?:mp4|webm|mov|gif)(?:\?|$))|^https://github\.com/user-attachments/assets/|^https://(?:www\.)?loom\.com/share/")),
)


def use_host(host):
    """The host's proof links (its pages) and older envelope tokens count too; another host's never do."""
    global DONE_COMMENT, PROOF_KINDS
    DONE_COMMENT = re.compile(r"(^|\n)[ \t>`]*(?:<!--[ \t]*)?(?:" + "|".join(host.envelope_prefixes()) + r")_WORKER_DONE\s+task:[ \t]*[A-Za-z0-9._-]")
    PROOF_KINDS = tuple((label, re.compile(pat)) for label, pat in host.proof_links()) + PROOF_KINDS[-2:]


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


def cells(line):
    """A ledger row's cells, stripped; an escaped pipe (\\|) stays inside its cell."""
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def is_mine(boss, bid):
    """Whether a row's Boss cell names boss *bid*: empty (every boss), its id, or its id's 8-character prefix."""
    return not boss or boss in (bid, bid[:8])


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
        cols = cells(line)
        if len(cols) < 7 or not re.match(r"\d{4}-\d{2}-\d{2}", cols[1]):
            continue
        # Bosses write the cell as "<id>…", "NEW <id>" or "ws <id> term <id>, branch …".
        ws = re.match(r"(?:NEW\s+|ws\s+)?([0-9a-f]{8})", cols[3], re.I)
        if not ws:
            continue
        text = cols[2].strip()
        status = (cols[5].split()[0] if cols[5] else "?").rstrip(",:")
        # A Proof column (6th), or "proof: <url>" anywhere in the row.
        # Optional columns: Proof (6th), Boss (7th). Old rows have neither and still parse.
        proof = proof_links(" ".join(cols[6:7]) + " " + " ".join(re.findall(r"proof:\s*(\S+)", line)))
        boss = cols[7] if len(cols) >= 9 and BOSS_CELL.fullmatch(cols[7]) else ""
        rows.append(((cols[1], prepends, -i if prepends else i), ws.group(1), text, status, cols[1], proof, boss))
    tasks = {}
    for _, prefix, text, status, date, proof, boss in sorted(rows, reverse=True, key=lambda r: r[0]):
        tasks.setdefault(prefix, (task_id(text), status, date, proof, boss, text))
    return dict(sorted(tasks.items(), key=lambda kv: kv[1][2], reverse=True))


def ledger_terms(path, ws_prefix):
    """Terminal-id prefix -> task cell text, the newest row, for the rows of workspace *ws_prefix* that name a
    terminal ("1a2b3c4d / 5e6f"): what a boss workspace's research and ops sessions are for. Ranked as
    ledger_tasks does: by date, then by section order (the first table appends, each dated section prepends)."""
    best = {}
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return {}
    prepends = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            prepends = line.startswith("## Dispatches")
        cols = cells(line)
        if len(cols) < 7 or not re.match(r"\d{4}-\d{2}-\d{2}", cols[1]):
            continue
        m = re.match(r"(?:NEW )?([0-9a-f]{8})\s*/\s*([0-9a-f]{4,})", cols[3])
        key = (cols[1], prepends, -i if prepends else i)
        if m and m.group(1) == ws_prefix and (m.group(2) not in best or key > best[m.group(2)][0]):
            best[m.group(2)] = (key, cols[2])
    return {k: v[1] for k, v in best.items()}


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


def watchers(cache):
    """Armed watchers: the files `boss-host watch` leaves in cache/watchers/, one per live process; a dead one's file is removed."""
    d = os.path.join(cache, "watchers")
    found = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        path = os.path.join(d, f)
        try:
            w = json.load(open(path))
            os.kill(int(w["pid"]), 0)
        except (OSError, ValueError, KeyError, TypeError):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        found.append({"ws": str(w["ws"]), "term": str(w.get("term") or ""), "ageS": max(0, int(time.time()) - int(w.get("at") or 0))})
    return found


def etime_s(etime):
    days, _, rest = etime.rpartition("-")
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + s


def name_boss_workspace(host, cfg):
    """Names this boss's own workspace or session after config's boss_name (BOSS), so it stands out in the sidebar.
    Every session, so a rename back heals; boss_name "" leaves it alone."""
    if host.self_id() and cfg.get("boss_name"):
        host.rename(host.self_id(), cfg["boss_name"])


def in_folder(tags, folder):
    """Whether a workspace's tags hold *folder*, case-insensitively; with no folder (the main boss) every workspace does."""
    return not folder or folder.lower() in (t.lower() for t in tags or [])


def notes_tail(wt, n=NOTE_ROWS):
    """The last few lines of the worktree's .boss-worker/notes.md, which its worker keeps: decisions and open questions."""
    lines = bosskit._read(os.path.join(wt, ".boss-worker", "notes.md")).splitlines() if wt else []
    return [l.strip()[:120] for l in lines if l.strip() and not l.lstrip().startswith("#")][-n:]


def read_status(wt):
    """The worker pane's task progress in <worktree>/.boss-worker/status.json, or None (also with no worktree:
    a relative path would read the current directory's)."""
    if not wt:
        return None
    try:
        s = json.load(open(os.path.join(wt, ".boss-worker", "status.json")))
        return {"done": int(s["tasks_done"]), "total": int(s["tasks_total"]), "current": str(s.get("current") or "")[:80],
                "at": int(s.get("at") or 0)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_pages(path):
    """The pages in a pages.jsonl (one {url, title, at} per line), newest first, each URL once; bad lines are skipped."""
    out = {}
    for line in bosskit._read(path).splitlines() if path else []:
        try:
            p = json.loads(line)
            url = str(p["url"])
            if url.startswith(("http://", "https://")):
                out[url] = {"url": url, "title": str(p.get("title") or url)[:80], "at": int(p.get("at") or 0)}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return sorted(out.values(), key=lambda p: p["at"], reverse=True)[:PAGE_ROWS]


def worker_pages(wt):
    """The pages a worktree's worker published: <worktree>/.boss-worker/pages.jsonl."""
    return read_pages(os.path.join(wt, ".boss-worker", "pages.jsonl") if wt else "")


def page_provider(cfg):
    """Config's page provider when `pages` names one, else ''."""
    p = cfg.get("pages")
    return str(p.get("provider") or "") if isinstance(p, dict) else ""


def exclude_boss_dir(wt):
    """Adds .boss-worker/ to the worktree's .git/info/exclude once, so its notes, status and pages are never committed."""
    path = bosskit._git(wt, "rev-parse", "--git-path", "info/exclude")
    if not path:
        return
    path = os.path.join(wt, path)
    if ".boss-worker/" not in bosskit._read(path).split():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write("\n.boss-worker/\n")


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


def kit_head():
    """The installed kit's short HEAD, "" when the kit is not a git checkout. The pane compares it with the one it loaded."""
    return bosskit._git(bosskit.KIT, "rev-parse", "--short", "HEAD")


def behind_by(repo, base, head):
    """How many commits *base* has that *head* (a sha) lacks, by GitHub's compare; 0 when it cannot say."""
    out = run(["gh", "api", f"repos/{repo}/compare/{base}...{head}", "--jq", ".behind_by"], timeout=20).strip()
    return int(out) if out.isdigit() else 0


def pr_row(repo, p, primary, behind=0):
    comments = p.get("comments") or []
    text = " ".join([p.get("body") or ""] + [c.get("body") or "" for c in comments])
    return {
        # When the newest comment starting a DONE envelope landed: the screen-free done signal.
        "doneAt": max((epoch(c.get("createdAt", "")) for c in comments if DONE_COMMENT.search(c.get("body") or "")), default=0),
        "proof": proof_links(text),
        "repo": repo, "primary": primary, "num": p["number"], "title": p["title"][:60],
        "draft": p.get("isDraft", False), "review": p.get("reviewDecision") or "",
        # Drift from its base: commits it lacks, and a merge conflict (GitHub's CONFLICTING, or mergeStateStatus DIRTY).
        "behind": behind, "conflicts": p.get("mergeable") == "CONFLICTING" or p.get("mergeStateStatus") == "DIRTY",
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
    for n, p in enumerate(json.loads(raw or "[]")):
        behind = behind_by(cfg["repo"], p.get("baseRefName"), p["headRefOid"]) if n < BEHIND_PRS and p.get("headRefOid") else 0
        rows.append(pr_row(cfg["repo"], p, True, behind))
    for ref in cfg.get("extra_prs", []):  # "owner/repo#123"
        repo, _, num = ref.partition("#")
        raw = run(["gh", "pr", "view", num, "--repo", repo, "--json", PR_FIELDS + ",state"], timeout=60)
        if raw and json.loads(raw).get("state") == "OPEN":
            x = json.loads(raw)
            rows.append(pr_row(repo, x, repo == cfg["repo"], behind_by(repo, x.get("baseRefName"), x["headRefOid"]) if x.get("headRefOid") else 0))
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
    (merged or retired today), waiting (checked or ready, yet its PR is still a draft or it has none: the next
    move is the user's). Only events since the last dispatch ("sent") count; anything else is working."""
    sent = max((e["at"] for e in evs if e["stage"].lower() == "sent"), default=0)
    at = lambda kinds: max((e["at"] for e in evs if e["at"] >= sent and e["stage"].lower() in kinds), default=0)
    ready = bool(pr) and not pr["draft"]
    pr_done = (pr or {}).get("doneAt", 0)
    # No DONE event (the watcher missed it, or could not log it): the PR's DONE comment, else a DONE ledger row
    # (the newest row, so this dispatch's), which carries no time and so counts as at the last dispatch.
    done_at = max(at(DONE_EVENTS | END_EVENTS), pr_done if pr_done >= sent else 0, sent or 1 if ledger.upper() in DONE_LEDGER else 0)
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
    if done_at and not at(END_EVENTS) and at(CHECKED_EVENTS) >= done_at:
        return "waiting"
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


MAIL_STAMP = "%Y-%m-%dT%H:%M:%S%z"  # boss-mail's created_at / read_at
MAIL_STALE_MIN = 10


def mail_age(m, now=None):
    """Minutes since a message was sent, 0 when its stamp does not parse."""
    try:
        return int(((now or time.time()) - datetime.strptime(m.get("created_at") or "", MAIL_STAMP).timestamp()) // 60)
    except (TypeError, ValueError):
        return 0


def mail(inbox, now=None):
    """This boss's unread mail: count plus the newest subjects, and how long the oldest has waited. Reads the inbox dir only."""
    items, oldest = [], 0
    for f in sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []:
        if f.endswith(".json"):
            try:
                m = json.load(open(os.path.join(inbox, f)))
                items.append({"id": m["id"], "kind": m.get("kind", ""), "from": m.get("from_project", ""), "subject": m.get("subject", "")})
                oldest = max(oldest, 0 if m.get("read_at") or m.get("done_at") else mail_age(m, now))  # read is not waiting
            except (OSError, ValueError, KeyError):
                continue
    return {"count": len(items), "dir": inbox, "items": items[-5:], "oldestMin": oldest}


def sent_unread(home, bdir, now=None):
    """Minutes the oldest of this boss's last 20 sent messages has waited unread by a recipient, else 0."""
    recs = []
    for line in bosskit._read(os.path.join(bdir, "sent.jsonl")).splitlines():
        r = bosshost._json(line, None)
        if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("to"), list):
            recs.append(r)
    worst = 0
    for r in recs[-20:]:  # as boss-mail sent counts them: a bad line takes no slot
        for to in r["to"]:
            project, _, boss = str(to).partition("/")
            m = bosshost._json(bosskit._read(os.path.join(home, project, "bosses", boss, "inbox", r["id"] + ".json")), {})
            if isinstance(m, dict) and m and not (m.get("read_at") or m.get("done_at")):
                worst = max(worst, mail_age(m, now))
    return worst


def mail_lines(box, sent_min):
    """The pane's quiet mail lines: mail waiting here, or mail this boss sent waiting there, 10 min or more."""
    out, age = [], lambda n: f"{n} min" if n < 24 * 60 else ">24h"
    if box["count"] and box["oldestMin"] >= MAIL_STALE_MIN:
        out.append({"level": "check", "text": f"mail unread {age(box['oldestMin'])} · boss-mail inbox"})
    if sent_min >= MAIL_STALE_MIN:
        out.append({"level": "check", "text": f"sent mail unread {age(sent_min)} · boss-mail sent"})
    return out


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


def bosses(reg, project, me, pdir, now=None, workspace="", wt="", sessions=()):
    """This project's live bosses, one per workspace: this boss first, then the main boss, then domains by name.
    *sessions* (see boss_sessions) belong to this boss's entry."""
    now = now or time.time()
    best = {}
    for i, b in bosskit.live(reg, now, project).items():
        k = "" if i == me or bosskit.same_boss(b, workspace, wt) else (b.get("workspace") or i)
        if k not in best or b.get("heartbeat", 0) > best[k][1].get("heartbeat", 0):
            best[k] = (i, b)
    out = [{"id": i, "workspace": b.get("workspace", ""), "domain": b.get("domain", ""), "me": k == "",
            "next": b.get("next", ""), "working": b.get("working", 0), "forYou": b.get("forYou", 0),
            "heartbeat": b.get("heartbeat", 0), "stale": now - b.get("heartbeat", 0) > BOSS_STALE_S,
            "state": domain_state(pdir, b.get("domain", "")), "sessions": list(sessions) if k == "" else [],
            "pages": read_pages(os.path.join(pdir, "bosses", i, "pages.jsonl"))}
           for k, (i, b) in best.items()]
    return sorted(out, key=lambda b: (not b["me"], b["domain"] != "", b["domain"]))


def boss_sessions(space, own_term, tasks, seen, now):
    """The boss workspace's other agent terminals, for its BOSSES row: [{id, title, state, ageS, task}].
    *space* is the workspace's snapshot entry, *own_term* the boss's own terminal id ('' when unknown), *tasks* the
    ledger text per terminal prefix, *seen* {terminal id: first seen} (updated). The snapshot has no terminal age, so
    it counts from the first refresh that saw the terminal."""
    out = []
    for t in (space or {}).get("terminals", []):
        if not t.get("agent") or t["id"] == own_term:
            continue
        first = seen.setdefault(t["id"], int(now))
        task = next((v for k, v in tasks.items() if t["id"].startswith(k)), "")
        out.append({"id": t["id"], "title": str(t.get("title") or "")[:40], "state": t["agent"].get("state") or "?",
                    "ageS": max(0, int(now) - first), "task": task[:80]})
    for k in [k for k in seen if k not in {s["id"] for s in out}]:  # a closed terminal is forgotten
        del seen[k]
    return out


# ---- worker mode: the pane in a dispatched worker's own session -------------------------------

def find_dispatch(home, ws):
    """The newest ledger row for workspace *ws* in any project: (project, cfg, row), or None when no boss dispatched it."""
    best = None
    for name in bosskit.projects(home):
        pdir = os.path.join(home, name)
        try:
            cfg = json.load(open(os.path.join(pdir, "config.json")))
        except (OSError, ValueError):
            continue
        row = ledger_tasks(os.path.join(pdir, cfg.get("ledger", "ledger.md"))).get(ws[:8])
        if row and (best is None or row[2] > best[2][2]):
            best = (name, cfg, row)
    return best


def worker_boss(reg, project, named):
    """A dispatch's boss: the row's Boss column, else the project's live main boss, else its newest live boss."""
    if named:  # its full id, or the 8-character prefix of a registered one
        return named if named in reg else next((i for i in reg if i[:8] == named), named)
    live = sorted(bosskit.live(reg, project=project).items(), key=lambda ib: (ib[1].get("domain", "") != "", -ib[1].get("heartbeat", 0)))
    return live[0][0] if live else ""


def project_events(pdir, ws):
    """Workspace *ws*'s events from every boss of the project, oldest first."""
    bdirs = os.path.join(pdir, "bosses")
    evs = [e for b in (sorted(os.listdir(bdirs)) if os.path.isdir(bdirs) else []) for e in bosskit.events(os.path.join(bdirs, b))
           if e["ws"][:8] == ws[:8]]
    return sorted(evs, key=lambda e: e["at"])


def hm(at):
    return time.strftime("%H:%M", time.localtime(at))


def pushed(wt, branch, n=DELIVERED_ROWS):
    """The newest commits on origin/<branch>: [{sha, at, subject}]."""
    out = bosskit._git(wt, "log", f"origin/{branch}", f"-{n}", "--format=%H%x1f%ct%x1f%s") if branch else ""
    rows = [l.split("\x1f") for l in out.splitlines()]
    return [{"sha": r[0], "at": int(r[1]), "subject": r[2][:80]} for r in rows if len(r) == 3]


def delivered(commits, evs, n=DELIVERED_ROWS):
    """Pushed commits merged with the workspace's milestone events, newest first."""
    rows = [{"at": c["at"], "kind": "commit", "text": f"{c['sha'][:7]} {c['subject']}"} for c in commits]
    rows += [{"at": e["at"], "kind": e["stage"], "text": e["note"]} for e in evs if e["stage"].lower() in DELIVERED_EVENTS]
    rows.sort(key=lambda r: r["at"], reverse=True)
    return [{**r, "hm": hm(r["at"])} for r in rows[:n]]


def write_status(wt, status, now=None):
    """Writes the worker pane's task progress to <worktree>/.boss-worker/status.json, which the boss's row reads."""
    try:
        s = json.loads(status)
        os.makedirs(os.path.join(wt, ".boss-worker"), exist_ok=True)
        bosskit.save_json(os.path.join(wt, ".boss-worker", "status.json"),
                          {"tasks_done": int(s["tasks_done"]), "tasks_total": int(s["tasks_total"]),
                           "current": str(s.get("current") or "")[:80], "at": int(now or time.time())})
    except (OSError, ValueError, KeyError, TypeError):
        pass  # an unwritable worktree, or a bad --status: progress just does not reach the boss


def worker_view(home, ws, cwd, status=None, fresh=False):
    """This workspace's own view: its dispatch, boss, PR, delivered work, notes and the boss's messages; None without a row."""
    found = find_dispatch(home, ws)
    if not found:
        return None
    project, _, (_, _, _, _, named, _) = found
    pdir = os.path.join(home, project)
    reg = bosskit.registry(home)
    bid = worker_boss(reg, project, named)
    cfg = bosskit.config_for(home, project, bid)  # the dispatching boss's layer too
    host = bosshost.get(cfg)
    use_host(host)
    _, _, (task, ledger, date, proof, named, text) = find_dispatch(home, ws)  # again: the host's proof links now count
    wt = bosskit.worktree(cwd)
    exclude_boss_dir(wt)
    if status:
        write_status(wt, status)
    cache = os.path.join(pdir, "bosses", bid, "cache") if bid else ""
    if not os.path.isdir(cache):
        cache = os.path.join(wt, ".boss-worker")
        os.makedirs(cache, exist_ok=True)
    branch = bosskit._git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    pr = next((p for p in sorted(prs(cfg, cache, fresh), key=lambda p: not p.get("primary")) if branch and p["head"] == branch), None)
    base = (pr or {}).get("base") or cfg.get("base_branch") or "main"
    behind = bosskit._git(wt, "rev-list", "--count", f"HEAD..origin/{base}")
    evs = project_events(pdir, ws)
    me = host.worker(ws) or {}
    msgs = [e for e in evs if e["stage"].lower() == "msg"]
    stages = [e for e in evs if e["stage"].lower() != "msg"]
    return {
        "project": project, "task": task, "goal": re.sub(r"^\S+?(?::\s*|\s+|$)", "", text, count=1) or text, "ledger": ledger, "date": date,
        "ws": ws, "name": (me.get("name") or task)[:28], "branch": branch, "base": base, "behind": int(behind or 0),
        "pr": pr, "proof": proof, "boss": {"id": bid, "workspace": (reg.get(bid) or {}).get("workspace") or ("" if bid.startswith("wt-") else bid)},
        "stage": {**stages[-1], "hm": hm(stages[-1]["at"])} if stages else None,
        "sentAt": max((e["at"] for e in stages if e["stage"].lower() == "sent"), default=0),
        "delivered": delivered(pushed(wt, branch), stages), "notes": notes_tail(wt), "pages": worker_pages(wt), "pagesTo": page_provider(cfg),
        "msgs": [{"at": e["at"], "hm": hm(e["at"]), "text": e["note"]} for e in reversed(msgs[-MSG_ROWS:])],
    }


def arg(name):
    """The value after *name* on the command line, or None."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else None


def main():
    if arg("--host-kind") in bosshost.plugins():
        os.environ["BOSS_HOST_KIND"] = arg("--host-kind")
    if arg("--workspace"):
        os.environ["BOSS_SESSION_ID"] = arg("--workspace")
    if "--worker" in sys.argv:
        ws = bosskit.self_id()
        view = worker_view(bosskit.home(), ws, arg("--cwd"), arg("--status"), "--fresh" in sys.argv) if ws else None
        print(json.dumps({"at": int(time.time()), "worker": view, "kit": kit_head()}))
        return
    ctx = bosskit.load(arg("--cwd"))
    if not bosskit.is_boss(ctx):
        sys.exit(bosskit.not_boss_note(ctx))  # no heartbeat, no rename: another workspace is the boss
    cfg = ctx.cfg
    host = bosshost.get(cfg, ctx.host)
    use_host(host)
    tasks = ledger_tasks(os.path.join(ctx.pdir, cfg.get("ledger", "ledger.md")))
    # Watchers are host-wide; keep the ones on this boss's dispatches (rows without a Boss belong to every boss).
    mine = {p for p, row in tasks.items() if is_mine(row[4], ctx.bid)}
    armed = [w for w in watchers(ctx.cache) if w["ws"][:8] in mine]
    spaces = host.workers(list(tasks) + ([ctx.workspace] if ctx.workspace else []))
    by_prefix = {w["id"][:8]: w for w in spaces}
    # A domain boss covers only the workspaces in its sidebar folder; the main boss ('' folder) covers all.
    folder = bosskit.boss_folder(ctx.worktree)
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
        if not is_mine(boss, ctx.bid):
            continue  # another boss's dispatch
        if ctx.workspace and prefix == ctx.workspace[:8]:
            continue  # this boss's own workspace (a research or ops session's row): sessions below, never a worker
        w = by_prefix.get(prefix)
        archived = w is None and prefix not in watched
        if archived and not any(e["at"] >= today and e["stage"].lower() in END_EVENTS for e in evs.get(prefix, [])):
            continue  # archived, and not today
        if not archived and len(workers) >= MAX_WORKERS and prefix not in watched:
            continue
        old = seen.get(prefix, {})
        info = w or {}
        tags = info["tags"] if w else old.get("tags", [])
        if not in_folder(tags, folder):
            continue  # another folder's workspace: its domain boss's, or the main boss's
        agents = [t for t in (w or {}).get("terminals", []) if t.get("agent")]
        agent_states = [t["agent"].get("state") for t in agents]
        state = "working" if "working" in agent_states else (agent_states[0] if agent_states else "gone")
        (done if archived else workers).append({
            "ws": prefix, "id": (w or {}).get("id", ""), "term": agents[0]["id"] if agents else "",
            "name": (w or {}).get("name", old.get("name", task))[:28], "branch": (w or {}).get("branch", old.get("branch", "")),
            "task": task, "taskText": text, "ledger": status, "date": date, "state": state, "watched": prefix in watched,
            "proof": proof, "prTag": old.get("prTag", ""), "tags": tags,
            "tasks": read_status(info.get("worktree", "")), "notes": notes_tail(info.get("worktree", ""), BOSS_NOTE_ROWS),
            "pages": worker_pages(info.get("worktree", "")),
        })
    join(workers, pr_rows)
    if folder:  # only this folder's workspaces, their watchers and their PRs; no PR-only rows
        kept = {w["ws"] for w in workers + done}
        armed = [w for w in armed if w["ws"][:8] in kept]
        pr_rows = [p for p in pr_rows if p.get("ws")]
    workers = lanes(workers, done, evs, today)
    for w in workers:
        seen[w["ws"]] = {"name": w["name"], "branch": w["branch"], "prTag": w["prTag"], "tags": w["tags"]}
    bosskit.save_json(seen_path, seen)
    sessions_path = os.path.join(ctx.cache, "sessions.json")
    try:
        first_seen = json.load(open(sessions_path))
    except (OSError, ValueError):
        first_seen = {}
    own_term = arg("--terminal") or host.terminal_id()
    sessions = boss_sessions(next((w for w in spaces if w.get("id") == ctx.workspace), None) if ctx.workspace else None,
                             own_term,
                             ledger_terms(os.path.join(ctx.pdir, cfg.get("ledger", "ledger.md")), ctx.workspace[:8]) if ctx.workspace else {},
                             first_seen, time.time())
    bosskit.save_json(sessions_path, first_seen)
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
    box = mail(ctx.inbox)
    todo = attention([w for w in workers if w["stage"] != "done"], armed, pr_rows) + mail_lines(box, sent_unread(ctx.home, ctx.bdir))
    working = sum(w["state"] == "working" for w in workers)
    for_you = sum(a["level"] == "act" for a in todo)
    bosskit.heartbeat(ctx, host.host_id(), {"working": working, "forYou": for_you, "terminal": own_term,
                                       "domain": bosskit.boss_domain(ctx.worktree), "next": now_line})
    if "--session-start" in sys.argv:
        name_boss_workspace(host, cfg)
    print(json.dumps({
        "at": int(time.time()), "kit": kit_head(), "me": {"id": ctx.bid, "project": ctx.name}, "next": now_line, "review": review,
        "pagesTo": page_provider(cfg),
        "attention": todo, "workers": workers, "watchers": armed, "prs": pr_rows, "board": board(cfg, bosskit.tracker_snapshot(ctx)),
        "others": others(bosskit.registry(ctx.home), ctx.bid, workspace=ctx.workspace, wt=ctx.worktree), "mail": box,
        "bosses": bosses(bosskit.registry(ctx.home), ctx.name, ctx.bid, ctx.pdir, workspace=ctx.workspace, wt=ctx.worktree, sessions=sessions),
        "lessonsNew": lessons_new(ctx.home, ctx.bdir, "--session-start" in sys.argv),
        "buttons": bosskit.pane_buttons(ctx.layers), "workerButtons": bosskit.pane_buttons(ctx.layers, "worker"),
    }))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # a host whose pages live at pages.example.com
        PROOF_KINDS = (("page", re.compile(r"^https://pages\.example\.com/p/")),) + PROOF_KINDS
        assert etime_s("01:19") == 79 and etime_s("1:02:03") == 3723 and etime_s("2-00:00:01") == 172801
        assert ci_summary([{"name": "Ownership approval", "conclusion": "FAILURE"}, {"name": "x", "conclusion": "SUCCESS"}]) == "green"
        assert ci_summary([{"name": "x", "status": "IN_PROGRESS"}]) == "pending"
        assert ci_summary([{"name": "x", "conclusion": "FAILURE"}]) == "red"
        w = {"name": "pr-1", "task": "t", "state": "idle", "ledger": "DISPATCHED", "watched": False}
        p = {"num": 9, "repo": "acme/widgets", "primary": True, "ci": "green", "review": "APPROVED", "draft": False}
        got = [i["text"] for i in attention([w], [], [p])]
        assert got == ["#9 approved + green: ready to merge (no proof)", "pr-1: idle, t has no watcher"], got
        p["proof"] = [{"label": "page", "url": "https://pages.example.com/p/x"}]
        assert attention([], [], [p])[0]["text"] == "#9 approved + green: ready to merge"
        text = ("Demo: https://github.com/user-attachments/assets/ab12 and page https://pages.example.com/p/fix-42-ab3d. "
                "Also (https://claude.ai/code/artifact/9f2e), a clip https://cdn.example.com/run.mp4?x=1, "
                "plus junk: https://github.com/acme/widgets/pull/42 https://example.com/img.png and again "
                "https://pages.example.com/p/fix-42-ab3d.")
        assert [(x["label"], x["url"]) for x in proof_links(text)] == [
            ("demo", "https://github.com/user-attachments/assets/ab12"),
            ("page", "https://pages.example.com/p/fix-42-ab3d"),
            ("artifact", "https://claude.ai/code/artifact/9f2e"),
            ("demo", "https://cdn.example.com/run.mp4?x=1"),
        ], proof_links(text)
        assert proof_links("") == [] and proof_links(None) == []
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("## Dispatches 2026-01-02\n\n| Date | Task | WS | Model | Status |\n|---|---|---|---|---|\n"
                    "| 2026-01-02 | fix-42: do it | 1a2b3c4d / 5e6f | mid | DISPATCHED, watcher armed | https://pages.example.com/p/p42 |\n"
                    "| 2026-01-01 | old-41: older | 1a2b3c4d / 5e6f | mid | DONE |\n")
        assert ledger_tasks(f.name) == {"1a2b3c4d": ("fix-42", "DISPATCHED", "2026-01-02",
                                                     [{"label": "page", "url": "https://pages.example.com/p/p42"}], "", "fix-42: do it")}, ledger_tasks(f.name)
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
        # stale mail: here (unread 10 min+) and sent from here (a recipient has not read it); a read one is quiet
        home = tempfile.mkdtemp()
        sent_at = time.strftime(MAIL_STAMP, time.localtime(now - 16 * 60))
        for b, extra in (("r1", {}), ("r2", {"read_at": sent_at})):
            os.makedirs(os.path.join(home, "widgets", "bosses", b, "inbox"))
            json.dump({"id": "m9", "created_at": sent_at, **extra}, open(os.path.join(home, "widgets", "bosses", b, "inbox", "m9.json"), "w"))
        open(os.path.join(home, "sent.jsonl"), "w").write(json.dumps({"id": "m9", "to": ["widgets/r1"], "created_at": sent_at}) + "\nnot json\n")
        assert sent_unread(home, home, now) == 16
        open(os.path.join(home, "sent.jsonl"), "w").write(json.dumps({"id": "m9", "to": ["widgets/r2"], "created_at": sent_at}) + "\n")
        assert sent_unread(home, home, now) == 0
        box = mail(os.path.join(home, "widgets", "bosses", "r1", "inbox"), now)
        assert [i["text"] for i in mail_lines(box, 12)] == ["mail unread 16 min · boss-mail inbox", "sent mail unread 12 min · boss-mail sent"], box
        assert mail_lines({**box, "oldestMin": 9}, 0) == []
        # worker mode: the dispatch row in whichever project has it, DELIVERED newest first, .boss-worker/ files
        home = tempfile.mkdtemp()
        for name, row in (("gadgets", ""), ("widgets", "| 2026-01-02 | fix-42: retry webhooks | 1a2b3c4d | mid | DISPATCHED |\n")):
            os.makedirs(os.path.join(home, name))
            json.dump({"repo": f"acme/{name}"}, open(os.path.join(home, name, "config.json"), "w"))
            open(os.path.join(home, name, "ledger.md"), "w").write(row)
        assert find_dispatch(home, "1a2b3c4d-full")[0] == "widgets" and find_dispatch(home, "9f9f9f9f") is None
        evs = [{"at": 100, "stage": "sent", "note": "go"}, {"at": 300, "stage": "DONE", "note": "fix-42"}, {"at": 250, "stage": "msg", "note": "x"}]
        got = delivered([{"sha": "8c41d2e07", "at": 200, "subject": "add backoff"}], evs)
        assert [(r["kind"], r["text"]) for r in got] == [("DONE", "fix-42"), ("commit", "8c41d2e add backoff"), ("sent", "go")], got
        wt = tempfile.mkdtemp()
        assert notes_tail(wt) == [] and read_status(wt) is None and read_status("") is None
        write_status(wt, json.dumps({"tasks_done": 3, "tasks_total": 5, "current": "run tests"}), now=7)
        open(os.path.join(wt, ".boss-worker", "notes.md"), "w").write("# Notes\n\n- decided: cap at 5\n- open: retry 4xx?\n")
        assert read_status(wt) == {"done": 3, "total": 5, "current": "run tests", "at": 7} and notes_tail(wt, 1) == ["- open: retry 4xx?"]
        led = os.path.join(home, "widgets", "ledger.md")
        open(led, "w").write("| 2026-01-02 | research-1: map the api | 1a2b3c4d / 5e6f | mid | DISPATCHED |\n"
                             "| 2026-01-01 | old-1: older | 1a2b3c4d / 5e6f | mid | DONE |\n"
                             "| 2026-01-02 | fix-9: x | 1a2b3c4d | mid | DISPATCHED |\n")  # no terminal: not a session's row
        assert ledger_terms(led, "1a2b3c4d") == {"5e6f": "research-1: map the api"} and ledger_terms(led, "9f9f9f9f") == {}
        open(led, "w").write("| 2026-01-02 | first-1: a | 1a2b3c4d / 5e6f | mid | DONE |\n| 2026-01-02 | second-1: b | 1a2b3c4d / 5e6f | mid | DISPATCHED |\n"
                             "## Dispatches 2026-01-02\n\n| 2026-01-02 | new-1: c | 1a2b3c4d / 5e6f | mid | DISPATCHED |\n| 2026-01-02 | old-1: d | 1a2b3c4d / 5e6f | mid | DONE |\n")
        assert ledger_terms(led, "1a2b3c4d") == {"5e6f": "new-1: c"}, ledger_terms(led, "1a2b3c4d")
        space = {"terminals": [{"id": "me00", "title": "boss", "agent": {"state": "working"}},
                               {"id": "5e6f0000", "title": "api research", "agent": {"state": "idle"}}, {"id": "sh00", "title": "zsh"}]}
        first = {"gone": 1}
        got = boss_sessions(space, "me00", {"5e6f": "research-1: map the api"}, first, 1000)
        assert got == [{"id": "5e6f0000", "title": "api research", "state": "idle", "ageS": 0, "task": "research-1: map the api"}], got
        assert first == {"5e6f0000": 1000} and boss_sessions(space, "me00", {}, first, 1090)[0]["ageS"] == 90
        assert in_folder(["Checkout Flow"], "checkout flow") and not in_folder(["UI"], "checkout") and in_folder([], "")
        row = pr_row("acme/widgets", {"number": 3, "title": "t", "mergeable": "MERGEABLE", "mergeStateStatus": "BEHIND"}, True, 3)
        assert row["behind"] == 3 and not row["conflicts"], row
        assert pr_row("acme/widgets", {"number": 3, "title": "t", "mergeable": "CONFLICTING"}, True)["conflicts"]
        assert pr_row("acme/widgets", {"number": 3, "title": "t", "mergeable": "UNKNOWN", "mergeStateStatus": "DIRTY"}, True)["conflicts"]
        assert not pr_row("acme/widgets", {"number": 3, "title": "t"}, True)["conflicts"]
        print("ok")
    else:
        main()
