"""bin/boss-close-pr against a fake gh on PATH and the fake host: the approved close route. Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import unittest

from test_kit import BIN, Home, git, load_script  # noqa: F401
import bosskit  # noqa: E402

G = load_script("boss-guard")

# gh pr view prints pr.json, with state CLOSED once close.flag exists; gh pr close logs its args and fails when fail.flag exists.
FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "pr view") if [ -f "$FIX/close.flag" ]; then sed 's/"OPEN"/"CLOSED"/' "$FIX/pr.json"; else cat "$FIX/pr.json"; fi;;
  "pr close") echo "$*" >> "$FIX/close.log"
    if [ -f "$FIX/fail.flag" ]; then echo "GraphQL: could not close" >&2; exit 1; fi
    [ -f "$FIX/noop.flag" ] || touch "$FIX/close.flag";;
  *) exit 1;;
esac
"""
REF = "acme/widgets#7"


class ClosePr(Home):
    WS = "7e7e7e7e-0000-4000-8000-000000000007"

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(stubs)
        open(os.path.join(stubs, "gh"), "w").write(FAKE_GH)
        os.chmod(os.path.join(stubs, "gh"), 0o755)
        self.tools = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "FIX": self.fixdir}
        self.worker = os.path.join(self.tmp, "worker")
        os.makedirs(self.worker)
        git(self.worker, "init", "-q", "-b", "feat/x")
        git(self.worker, "-c", "user.name=jane", "-c", "user.email=jane@example.com", "commit", "-q", "--allow-empty", "-m", "x")
        git(self.worker, "update-ref", "refs/remotes/origin/feat/x", "HEAD")
        self.put("list.json", [{"id": self.WS, "branch": "feat/x", "worktreePath": self.worker}])
        self.put("pr.json", {"number": 7, "state": "OPEN", "headRefName": "feat/x", "url": "https://github.com/acme/widgets/pull/7"})
        self.ctx = bosskit.load(self.wt)

    def put(self, name, data):
        json.dump(data, open(os.path.join(self.fixdir, name), "w"))

    def flag(self, name):
        open(os.path.join(self.fixdir, name), "w").close()

    def close(self, *args):
        return subprocess.run([os.path.join(BIN, "boss-close-pr"), "7", *args], cwd=self.wt, env=self.tools, capture_output=True, text=True)

    def closes(self):
        return bosskit._read(os.path.join(self.fixdir, "close.log")).splitlines()

    def stages(self):
        return [(e["stage"], e["note"]) for e in bosskit.events(self.ctx.bdir)]

    def test_guard_still_denies_a_bare_close_and_names_the_route(self):
        for cmd in ("gh pr close 7", "gh pr close 7 --delete-branch", "gh -R acme/widgets pr close 7"):
            self.assertIn("bin/boss-close-pr", G.violation(cmd, "/nonexistent", True, lambda: "main"), cmd)
        self.assertIsNone(G.violation("bin/boss-close-pr 7", "/nonexistent", True, lambda: "main"))

    def test_refused_without_the_close_ok_event_and_prints_the_line_to_log(self):
        r = self.close()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'refused: no close-ok event for {REF}: after the user\'s OK, log it: bin/boss-event {self.WS} close-ok "{REF}"', r.stdout)
        bosskit.add_event(self.ctx, self.WS, "close-ok", "acme/widgets#70")  # another PR's approval does not count
        self.assertEqual(self.close().returncode, 1)
        self.assertEqual((self.closes(), self.stages()), ([], [("close-ok", "acme/widgets#70")]))

    def test_refused_with_work_left_in_a_worktree_and_names_it(self):
        bosskit.add_event(self.ctx, self.WS, "close-ok", REF)
        open(os.path.join(self.worker, "wip.txt"), "w").close()
        r = self.close()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"refused: worktree {self.worker} has work on feat/x: uncommitted: ?? wip.txt", r.stdout)
        os.remove(os.path.join(self.worker, "wip.txt"))
        git(self.worker, "-c", "user.name=jane", "-c", "user.email=jane@example.com", "commit", "-q", "--allow-empty", "-m", "more")
        self.assertIn(f"worktree {self.worker} has work on feat/x: unpushed:", self.close().stdout)
        self.assertEqual(self.closes(), [])

    def test_refused_when_not_open(self):
        bosskit.add_event(self.ctx, self.WS, "close-ok", REF)
        self.put("pr.json", {"number": 7, "state": "MERGED", "headRefName": "feat/x", "url": "https://github.com/acme/widgets/pull/7"})
        r = self.close()
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"refused: {REF} is MERGED", r.stdout)
        self.assertEqual(self.closes(), [])

    def test_closes_confirms_closed_and_logs_closed(self):
        bosskit.add_event(self.ctx, self.WS, "close-ok", REF)
        r = self.close("-R", "acme/widgets", "--comment", "superseded by #9", "--delete-branch")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"closed {REF}", r.stdout)
        self.assertEqual(self.closes(), ["pr close 7 -R acme/widgets --comment superseded by #9 --delete-branch"])
        self.assertEqual(self.stages(), [("close-ok", REF), ("closed", REF)])
        self.assertEqual(self.close().returncode, 1)  # the approval is spent, and the PR is closed now

    def test_a_pr_with_no_workspace_of_ours_closes_too(self):
        self.put("list.json", [])
        r = self.close()
        self.assertIn(f'bin/boss-event pr close-ok "{REF}"', r.stdout)
        bosskit.add_event(self.ctx, "pr", "close-ok", REF)
        self.assertEqual(self.close().returncode, 0)
        self.assertEqual(self.stages()[-1], ("closed", REF))

    def test_a_gh_failure_logs_nothing(self):
        bosskit.add_event(self.ctx, self.WS, "close-ok", REF)
        self.flag("fail.flag")
        r = self.close()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gh pr close failed", r.stderr)
        self.assertEqual(self.stages(), [("close-ok", REF)])

    def test_a_close_that_leaves_the_pr_open_logs_nothing(self):
        bosskit.add_event(self.ctx, self.WS, "close-ok", REF)
        self.flag("noop.flag")
        r = self.close()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is OPEN", r.stderr)
        self.assertEqual(self.stages(), [("close-ok", REF)])


if __name__ == "__main__":
    unittest.main()
