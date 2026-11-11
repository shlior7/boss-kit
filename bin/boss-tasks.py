#!/usr/bin/env python3
"""boss-tasks: read-only tracker sync for the boss. Zero LLM, never writes to the tracker.

Pulls every task, saves a snapshot, and prints what changed since
the last run plus the open work that matters: my open tasks, P0/P1 across the team, In Review.
The snapshot is per boss: $BOSS_HOME/<project>/bosses/<id>/cache/tracker.json.

Configured by `tracker` in $BOSS_HOME/<project>/config.json:
  {"type": "none"}                          -> prints a note and exits 0
  {"type": "http", "url_env": "...", "token_env": "...", "assignee": "Your Name"}
      POSTs {"limit": 500} to the URL in $url_env with "Authorization: Bearer $token_env" and
      expects {"tasks": [{id, title, status, priority, assignee, onRoadmap?, description?, body?}]}
      (PR links found in description or body show as PR#N).
      Any tracker you can expose as one JSON endpoint of that shape works.
usage: boss-tasks.py [--quiet]   (--quiet = changes only)
"""
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosskit  # noqa: E402

TRACKED = ("status", "priority", "assignee", "onRoadmap", "title")
RANK = {"P0": 0, "P1": 1, "P2": 2}


def fetch_http(tr):
    url, token = os.environ.get(tr.get("url_env", "")), os.environ.get(tr.get("token_env", ""))
    if not url or not token:
        sys.exit(f"boss-tasks: set ${tr.get('url_env')} and ${tr.get('token_env')}; tracker not synced")
    req = urllib.request.Request(url, data=b'{"limit":500}', method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))["tasks"]
    except Exception as e:
        sys.exit(f"boss-tasks: tracker fetch failed: {e}")


def main():
    ctx = bosskit.load()
    tr = ctx.cfg.get("tracker") or {"type": "none"}
    if tr.get("type", "none") == "none":
        print("boss-tasks: no tracker configured (tracker.type = none)")
        return
    if tr["type"] != "http":
        sys.exit(f"boss-tasks: tracker type {tr['type']!r} has no adapter yet (supported: none, http)")
    tasks = fetch_http(tr)
    me, quiet = tr.get("assignee", ""), "--quiet" in sys.argv
    state = os.path.join(ctx.cache, "tracker.json")

    now = {t["id"]: {k: t.get(k) for k in TRACKED} | {
        "prs": sorted(set(re.findall(r"pull/(\d+)", (t.get("description") or "") + (t.get("body") or ""))))}
        for t in tasks}
    try:
        before = json.load(open(state))
    except (OSError, ValueError):
        before = None

    def line(i, t):
        prs = f" PR#{',#'.join(t['prs'])}" if t["prs"] else ""
        road = " [roadmap]" if t.get("onRoadmap") else ""
        return f"  {t['priority']} {t['status']:<11} {(t['assignee'] or 'unassigned')[:18]:<18} {t['title'][:80]}{road}{prs} ({i[:8]})"

    changes = []
    if before is not None:
        for i, t in now.items():
            old = before.get(i)
            if old is None:
                changes.append(f"  NEW   {line(i, t).strip()}")
                continue
            diff = [f"{k}: {old.get(k)} -> {t[k]}" for k in TRACKED if old.get(k) != t[k]]
            if diff:
                changes.append(f"  MOVED {t['title'][:60]} ({i[:8]}): " + "; ".join(diff))
        changes += [f"  GONE  {o['title'][:70]} ({i[:8]})" for i, o in before.items() if i not in now]

    open_ = {i: t for i, t in now.items() if t["status"] != "Done"}
    key = lambda it: (RANK.get(it[1]["priority"], 9), it[1]["status"] != "In Progress", it[1]["title"])
    print(f"Tracker: {len(now)} tasks, {len(open_)} open" + ("" if before is not None else " (first sync, no diff)"))
    if changes:
        print(f"Changed since last sync ({len(changes)}):")
        print("\n".join(changes[:25]))
    elif before is not None:
        print("No tracker changes since last sync.")
    if not quiet:
        sections = [
            (f"Mine ({me}), open", [x for x in open_.items() if x[1]["assignee"] == me]),
            ("Team P0/P1, open", [x for x in open_.items() if x[1]["priority"] in ("P0", "P1") and x[1]["assignee"] != me]),
            ("In Review", [x for x in open_.items() if x[1]["status"] == "In Review"]),
        ]
        for name, rows in sections:
            if rows:
                print(f"{name} ({len(rows)}):")
                print("\n".join(line(i, t) for i, t in sorted(rows, key=key)))
    json.dump(now, open(state, "w"))


if __name__ == "__main__":
    main()
