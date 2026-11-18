"""bin/boss-janitor: each rule's positive and negative cases on fixtures. ps, lsof, signals and the host are mocked;
no test touches a real process. Run: python3 -m unittest discover -s tests"""
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
sys.path.insert(0, BIN)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bosskit  # noqa: E402
from test_kit import load_script  # noqa: E402

J = load_script("boss-janitor")
HOUR = 3600


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True)


def proc(pid, ppid=1, cpu=0.0, age=6 * HOUR, args="/usr/local/bin/next dev"):
    return pid, {"pid": pid, "ppid": ppid, "cpu": cpu, "age": age, "args": args}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.tmp, "boss")
        self.pdir = os.path.join(self.home, "widgets")
        os.makedirs(self.pdir)
        json.dump({"repo": "acme/widgets"}, open(os.path.join(self.pdir, "config.json"), "w"))
        self.env = mock.patch.dict(os.environ, {"BOSS_HOME": self.home, "BOSS_KIT_HOME": os.path.join(self.tmp, "kit"),
                                                "BOSS_PROJECT": "widgets", "BOSS_SESSION_ID": "b0551d00-0000"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.wt = os.path.join(self.tmp, "wt-mine")
        self.other = os.path.join(self.tmp, "wt-other")
        os.makedirs(self.wt)
        os.makedirs(self.other)
        self.own = {self.wt: {"id": "aaaa1111", "name": "w", "idle": True}}


class Orphans(Base):
    def test_tool_names(self):
        for args in ("/x/node_modules/.bin/next dev", "next-server (v15.1.0)", "/x/bin/jest-worker",
                     "node /x/node_modules/jest-worker/build/workers/processChild.js", "node /x/node_modules/next/dist/bin/next dev",
                     "/Users/u/Library/Caches/ms-playwright/chromium-1/chrome-mac/chromium", "/usr/local/bin/yarn dev", "tsc -w", "vitest"):
            self.assertTrue(J.tool(args), args)
        for args in ("node server.js", "/bin/zsh", "claude", "/usr/bin/python3 app.py", ""):
            self.assertFalse(J.tool(args), args)

    def test_idle_orphan_in_own_worktree_is_killed_children_first(self):
        table = dict([proc(10), proc(11, ppid=10, args="node /x/jest-worker/child.js"), proc(12, ppid=11, args="chromium")])
        act, keep = J.orphans(table, {10: self.wt + "/apps/web"}, self.own)
        self.assertEqual(keep, [])
        self.assertEqual([(a["pid"], a["pids"], a["owner"]) for a in act], [(10, [12, 11, 10], "aaaa1111")])

    def test_kept_cases(self):
        table = dict([proc(20, age=10 * 60),                       # young
                      proc(21, cpu=4.0),                           # busy
                      proc(22), proc(23, ppid=22, cpu=2.0),        # busy child
                      proc(24),                                    # unknown cwd
                      proc(25),                                    # another project's worktree
                      proc(26),                                    # this boss's worktree, agent working
                      proc(27, ppid=500),                          # not an orphan
                      proc(28, args="node server.js")])            # not a dev tool
        busy_wt = os.path.join(self.tmp, "wt-busy")
        own = {**self.own, busy_wt: {"id": "bbbb2222", "name": "b", "idle": False}}
        cwd = {20: self.wt, 21: self.wt, 22: self.wt, 25: self.other, 26: busy_wt, 27: self.wt, 28: self.wt}
        act, keep = J.orphans(table, cwd, own)
        self.assertEqual(act, [])
        why = dict(keep)
        self.assertIn("young", why[20])
        self.assertIn("busy", why[21])
        self.assertIn("busy", why[22])
        self.assertIn("unknown cwd", why[24])
        self.assertIn("not this boss's worktree", why[25])
        self.assertIn("agent not idle", why[26])
        self.assertNotIn(27, why)
        self.assertNotIn(28, why)

    def test_prefix_sibling_is_not_under_root(self):
        table = dict([proc(30)])
        act, keep = J.orphans(table, {30: self.wt + "-2/app"}, self.own)
        self.assertEqual(act, [])

    def test_roots_idle_only_when_no_agent_works(self):
        r = J.roots([{"id": "aaaa1111xx", "worktree": self.wt, "terminals": [{"agent": {"state": "idle"}}, {"id": "shell"}]},
                     {"id": "bbbb2222xx", "worktree": self.other, "terminals": [{"agent": {"state": "working"}}]},
                     {"id": "cccc3333xx", "worktree": ""}])
        self.assertEqual({k: v["idle"] for k, v in r.items()}, {self.wt: True, self.other: False})

    def test_kill_terms_exact_pids_children_first_then_kills_survivors(self):
        sent, gone = [], set()

        def fake_kill(pid, sig):
            if sig == 0:
                if pid in gone:
                    raise ProcessLookupError
                return
            sent.append((pid, sig))
            if sig == signal.SIGTERM and pid != 10:
                gone.add(pid)  # 10 ignores SIGTERM
        with mock.patch.object(J.os, "kill", fake_kill), mock.patch.object(J.subprocess, "run") as run, \
                mock.patch.object(J, "same", return_value=True):
            J.kill([12, 11, 10], {12: {}, 11: {}, 10: {}}, wait=0.3)
        self.assertEqual(sent, [(12, signal.SIGTERM), (11, signal.SIGTERM), (10, signal.SIGTERM), (10, signal.SIGKILL)])
        run.assert_not_called()  # never pkill or killall

    def test_reused_pid_is_never_signalled(self):
        now = time.time()
        snap = {10: {"start": now - 6 * HOUR, "args": "next dev"}, 11: {"start": now - 6 * HOUR, "args": "chromium"}}
        ps = {"10": "06:00:00 next dev", "11": "00:05 chromium"}  # 11 was reused: it started 5 s ago
        sent = []
        with mock.patch.object(J, "sh", lambda argv, **k: ps[argv[-1]] + "\n"), \
                mock.patch.object(J.os, "kill", lambda pid, sig: sig and sent.append((pid, sig))), \
                mock.patch.object(J, "alive", return_value=False):
            J.kill([11, 10], snap, wait=0)
            self.assertFalse(J.same(10, {"start": now - 6 * HOUR, "args": "next build"}))  # same start, other command
            self.assertTrue(J.same(10, snap[10]))
        self.assertEqual(sent, [(10, signal.SIGTERM)])

    def test_pid_reused_before_sigkill_is_spared(self):
        checks = iter([True, False])  # matches before SIGTERM, changed before SIGKILL
        sent = []
        with mock.patch.object(J, "same", lambda pid, snap: next(checks)), \
                mock.patch.object(J.os, "kill", lambda pid, sig: sig and sent.append((pid, sig))), \
                mock.patch.object(J, "alive", return_value=True):
            J.kill([10], {10: {}}, wait=0)
        self.assertEqual(sent, [(10, signal.SIGTERM)])

    def test_etime(self):
        self.assertEqual(J.etime_s("05:03"), 303)
        self.assertEqual(J.etime_s("02:00:01"), 7201)
        self.assertEqual(J.etime_s("1-00:00:00"), 86400)


class Temp(Base):
    def setUp(self):
        super().setUp()
        self.tmproot = os.path.join(self.tmp, "ptmp")
        os.makedirs(self.tmproot)
        p = mock.patch.object(J, "TMP", self.tmproot)
        p.start()
        self.addCleanup(p.stop)
        self.sess = os.path.join(self.tmproot, f"claude-{os.getuid()}")
        os.makedirs(self.sess)
        p2 = mock.patch.object(J, "temp_roots", lambda: [self.sess])
        p2.start()
        self.addCleanup(p2.stop)

    def review(self, name):
        """A /private/tmp/review-* worktree at a commit origin has."""
        origin, main = os.path.join(self.tmp, "origin.git"), os.path.join(self.tmp, "main")
        if not os.path.isdir(main):
            subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
            subprocess.run(["git", "clone", "-q", origin, main], check=True, capture_output=True)
            git(main, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "c")
            git(main, "push", "-q", "origin", "HEAD:main")
        wt = os.path.join(self.tmproot, name)
        git(main, "worktree", "add", "-q", "--detach", wt, "HEAD")
        return wt

    def old(self, path):
        t = time.time() - 8 * 86400
        for d, dirs, files in os.walk(path):
            for n in dirs + files:
                os.utime(os.path.join(d, n), (t, t), follow_symlinks=False)
        os.utime(path, (t, t))

    def test_review_worktrees(self):
        clean, held, dirty, ahead, fresh = (self.review(f"review-{n}") for n in (1, 2, 3, 4, 5))
        open(os.path.join(dirty, "wip.txt"), "w").write("x")
        git(ahead, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "local")
        for wt in (clean, held, dirty, ahead):
            self.old(wt)
        os.makedirs(os.path.join(self.tmproot, "review-notgit"))
        act, keep = J.temp({held + "/src/a.ts"})
        self.assertEqual([a["path"] for a in act], [clean])
        why = dict(keep)
        self.assertEqual((why[held], why[dirty], why[ahead], why[fresh]),
                         ("held open", "uncommitted work", "unpushed commits", "younger than 7 days"))
        self.assertNotIn(os.path.join(self.tmproot, "review-notgit"), why)
        self.assertEqual(J.remove(act[0]), "")
        self.assertFalse(os.path.exists(clean))

    def test_session_dirs(self):
        for n in ("old", "old2", "young", "held"):
            os.makedirs(os.path.join(self.sess, n, "deep"))
            open(os.path.join(self.sess, n, "deep", "f"), "w").write("x")
            self.old(os.path.join(self.sess, n))
        os.utime(os.path.join(self.sess, "young", "deep", "f"))  # one fresh file keeps the whole dir
        open(os.path.join(self.sess, "loose.log"), "w").close()
        self.old(os.path.join(self.sess, "loose.log"))  # not a dir: never a session dir
        outside = os.path.join(self.tmp, "precious")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.sess, "link"))
        act, keep = J.temp({os.path.join(self.sess, "held", "deep", "f")}, now=time.time())
        self.assertEqual([os.path.basename(a["path"]) for a in act], ["old", "old2"])
        why = dict(keep)
        self.assertEqual(why["1 session dir(s)"], "younger than 7 days")
        self.assertNotIn(os.path.join(self.sess, "loose.log"), why)
        self.assertEqual(why[os.path.join(self.sess, "held")], "held open")
        self.assertEqual(why[os.path.join(self.sess, "link")], "symlink")
        self.assertEqual(J.remove(act[0]), "")
        self.assertFalse(os.path.exists(act[0]["path"]))
        self.assertTrue(os.path.exists(os.path.join(self.sess, "loose.log")))
        # A path that resolves out of its root is refused, even if it got into the plan.
        self.assertEqual(J.remove({"path": os.path.join(self.sess, "link"), "kind": "dir", "root": self.sess}), "outside its root, kept")
        self.assertTrue(os.path.isdir(outside))

    def test_unknown_open_files_hold_everything(self):
        self.old(self.review("review-1"))
        os.makedirs(os.path.join(self.sess, "old"))
        self.old(os.path.join(self.sess, "old"))
        act, keep = J.temp(None)
        self.assertEqual(act, [])
        self.assertEqual({w for _, w in keep}, {"held open"})


class Sweep(Base):
    def setUp(self):
        super().setUp()
        self.plan = {"workers": ["aaaa1111"], "keep": [(99, "next: young")],
                     "orphans": [{"pid": 10, "pids": [11, 10], "owner": "aaaa1111", "age": 7 * HOUR, "reason": "idle orphan next",
                                  "snap": {10: {}, 11: {}}}],
                     "temp": []}
        for name, val in (("plan", lambda ctx: self.plan), ("close_dead", mock.Mock(return_value=["would close 0 dead pane(s)"]))):
            p = mock.patch.object(J, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.kill = mock.patch.object(J, "kill").start()
        self.addCleanup(mock.patch.stopall)
        open(os.path.join(self.pdir, "ledger.md"), "w").write("# ledger\n\n| Date | a | b | c | d | e | Boss |\n")

    def run_main(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = J.main(list(argv))
        return code, buf.getvalue()

    def log(self):
        return bosskit._read(os.path.join(self.pdir, "janitor.log"))

    def test_default_is_dry_run_even_with_apply(self):
        self.assertEqual(bosskit.DEFAULTS["janitor"], "dry-run")
        code, out = self.run_main("sweep", "--apply", "--reason", "queue")
        self.assertEqual(code, 0)
        self.kill.assert_not_called()
        self.assertIn("dry run: config janitor is 'dry-run'", out)
        self.assertIn("would kill pid=10 owner=widgets/aaaa1111 age=7h00m", out)
        self.assertIn("would kill pid=10", self.log())
        self.assertIn("reason=queue", self.log())
        self.assertNotIn("janitor:", bosskit._read(os.path.join(self.pdir, "ledger.md")))
        J.close_dead.assert_called_with(["aaaa1111"], False)

    def test_apply_needs_both_flag_and_config(self):
        json.dump({"repo": "acme/widgets", "janitor": "apply"}, open(os.path.join(self.pdir, "config.json"), "w"))
        self.run_main("sweep")
        self.kill.assert_not_called()
        code, out = self.run_main("sweep", "--apply", "--reason", "queue")
        self.kill.assert_called_once_with([11, 10], {10: {}, 11: {}})
        self.assertIn("kill pid=10", out)
        self.assertNotIn("would kill", out)
        ledger = bosskit._read(os.path.join(self.pdir, "ledger.md"))
        self.assertIn("janitor: 1 cleanup action(s)", ledger)
        self.assertIn("\n\n- ", ledger)  # a blank line ends the table first
        self.assertEqual(ledger.count("janitor:"), 1)
        J.close_dead.assert_called_with(["aaaa1111"], True)

    def test_kill_switch(self):
        open(os.path.join(self.home, "janitor.off"), "w").close()
        code, out = self.run_main("sweep", "--apply")
        self.assertEqual((code, out.strip()), (0, "off"))
        self.kill.assert_not_called()
        self.assertEqual(self.log(), "")

    def test_status_writes_nothing(self):
        with mock.patch.object(J, "memory", return_value={"level": "1", "free": "40", "swap": 90, "swap_gb": 23.0}):
            code, out = self.run_main("status")
        self.assertIn("memory: pressure_level=1 free=40% swap=90% (23.0 GB)", out)
        self.assertIn("would kill pid=10", out)
        self.assertEqual(self.log(), "")
        self.kill.assert_not_called()


class Whose(Base):
    def test_own_workers_reads_only_this_boss_rows(self):
        open(os.path.join(self.pdir, "ledger.md"), "w").write(
            "| Date | Task | Workspace / terminal | Model | Status | Proof | Boss |\n|---|---|---|---|---|---|---|\n"
            "| 2026-11-18 | mine: x | aaaa1111 / 1234 | m | DONE | | b0551d00-0000 |\n"
            "| 2026-11-18 | theirs: y | bbbb2222 / 1234 | m | DONE | | 0ther000-0000 |\n")
        host = mock.Mock()
        host.workers.return_value = [{"id": "aaaa1111-full", "worktree": self.wt}, {"id": "bbbb2222-full", "worktree": self.other}]
        ctx = bosskit.load(make=False, resolve_host=False)
        with mock.patch.object(J.bosshost, "get", return_value=host):
            got = J.own_workers(ctx)
        host.workers.assert_called_once_with(["aaaa1111"])
        self.assertEqual([w["id"] for w in got], ["aaaa1111-full"])

    def test_unreadable_host_acts_on_nothing(self):
        open(os.path.join(self.pdir, "ledger.md"), "w").write("| 2026-11-18 | mine: x | aaaa1111 / 1 | m | DONE | | |\n")
        ctx = bosskit.load(make=False, resolve_host=False)
        with mock.patch.object(J.bosshost, "get", side_effect=SystemExit("no host")), redirect_stdout(io.StringIO()):
            self.assertEqual(J.own_workers(ctx), [])

    def test_plan_hands_full_workspace_ids_to_the_host(self):
        full = "756fc5fa-1111-2222-3333-444455556666"
        stubs = {"own_workers": lambda ctx: [{"id": full, "worktree": self.wt}], "procs": dict, "cwds": lambda pids: {},
                 "open_paths": set, "temp": lambda opened: ([], [])}
        with mock.patch.multiple(J, **stubs):
            p = J.plan(None)
        self.assertEqual(p["workers"], [full])
        with mock.patch.object(J.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            J.close_dead(p["workers"], False)
        self.assertEqual(run.call_args[0][0][-1], full)

    def test_close_dead_runs_boss_close_for_own_workers(self):
        with mock.patch.object(J.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "would close 1 dead pane(s)\n", "")) as run:
            self.assertEqual(J.close_dead(["aaaa1111"], False), ["would close 1 dead pane(s)"])
            self.assertEqual(run.call_args[0][0][1:], [os.path.join(BIN, "boss-close"), "--dry-run", "--dead", "aaaa1111"])
            J.close_dead(["aaaa1111"], True)
            self.assertEqual(run.call_args[0][0][2:], ["--dead", "aaaa1111"])
            run.reset_mock()
            self.assertEqual(J.close_dead([], True), [])
            run.assert_not_called()  # never --all


if __name__ == "__main__":
    unittest.main()
