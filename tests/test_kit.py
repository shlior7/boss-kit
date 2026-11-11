"""Kit tests: project resolution, boss id, registry, mail, migrate, lessons and the loader.

Run: python3 -m unittest discover -s tests   (stdlib only; every test uses a temp $BOSS_HOME)
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
sys.path.insert(0, BIN)
import bosskit  # noqa: E402


def load_script(name):
    """Import an extension-less bin/ script as a module."""
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), os.path.join(BIN, name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True)


class Home(unittest.TestCase):
    """A temp $BOSS_HOME with two projects, and a temp git worktree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "boss")
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)
        git(self.wt, "init", "-q")
        for name, repo in (("widgets", "acme/widgets"), ("gadgets", "acme/gadgets")):
            os.makedirs(os.path.join(self.home, name))
            json.dump({"repo": repo, "me": "octocat"}, open(os.path.join(self.home, name, "config.json"), "w"))
        self.env = mock.patch.dict(os.environ, {"BOSS_HOME": self.home}, clear=False)
        self.env.start()
        for k in ("BOSS_PROJECT", "SUPERSET_WORKSPACE_ID"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()


class Resolution(Home):
    def test_order_env_then_boss_file_then_remote_then_only(self):
        with self.assertRaises(SystemExit):  # two projects, no hint
            bosskit.project_name(self.wt)
        git(self.wt, "remote", "add", "origin", "git@github.com:acme/gadgets.git")
        self.assertEqual(bosskit.project_name(self.wt), "gadgets")
        open(os.path.join(self.wt, ".boss"), "w").write("project: widgets\n")
        self.assertEqual(bosskit.project_name(self.wt), "widgets")
        os.environ["BOSS_PROJECT"] = "gadgets"
        self.assertEqual(bosskit.project_name(self.wt), "gadgets")

    def test_https_remote_and_the_only_project(self):
        git(self.wt, "remote", "add", "origin", "https://github.com/acme/widgets")
        self.assertEqual(bosskit.project_name(self.wt), "widgets")
        os.remove(os.path.join(self.home, "gadgets", "config.json"))
        git(self.wt, "remote", "remove", "origin")
        self.assertEqual(bosskit.project_name(self.wt), "widgets")

    def test_boss_id_is_the_workspace_or_a_stable_worktree_hash(self):
        a = bosskit.boss_id(self.wt)
        self.assertTrue(a.startswith("wt-") and len(a) == 11)
        self.assertEqual(a, bosskit.boss_id(self.wt))
        other = os.path.join(self.tmp, "wt2"); os.makedirs(other)
        self.assertNotEqual(a, bosskit.boss_id(other))
        os.environ["SUPERSET_WORKSPACE_ID"] = "ws-123"
        self.assertEqual(bosskit.boss_id(self.wt), "ws-123")
        del os.environ["SUPERSET_WORKSPACE_ID"]


class Registry(Home):
    def test_heartbeat_and_staleness(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        ctx = bosskit.load(self.wt)
        now = time.time()
        bosskit.heartbeat(ctx, "h1", {"working": 2}, now=now - 3600)
        self.assertEqual(bosskit.live(bosskit.registry(), now), {})
        bosskit.heartbeat(ctx, "h1", {"working": 2}, now=now - 60)
        reg = bosskit.registry()
        self.assertEqual(list(bosskit.live(reg, now)), [ctx.bid])
        self.assertEqual(reg[ctx.bid]["project"], "widgets")
        self.assertEqual(bosskit.live(reg, now, project="gadgets"), {})

    def test_a_process_without_the_workspace_env_is_the_same_boss(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        stray = bosskit.load(self.wt)  # a mod's process before 0.5.1: no workspace id, a wt- hash
        self.assertTrue(stray.bid.startswith("wt-"))
        bosskit.heartbeat(stray)
        os.environ["SUPERSET_WORKSPACE_ID"] = "ws-a"
        shell = bosskit.load(self.wt)
        bosskit.heartbeat(shell)
        self.assertEqual(list(bosskit.registry()), ["ws-a"])  # the wt- duplicate is pruned on write
        del os.environ["SUPERSET_WORKSPACE_ID"]
        mod = bosskit.load(self.wt)
        self.assertEqual((mod.bid, mod.workspace), ("ws-a", "ws-a"))  # found by worktree in the registry
        bosskit.heartbeat(mod)
        self.assertEqual(list(bosskit.registry()), ["ws-a"])

    def test_heartbeat_prunes_entries_silent_for_a_week(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        now = time.time()
        json.dump({"old": {"project": "x", "heartbeat": now - bosskit.PRUNE_S - 1}, "recent": {"project": "y", "heartbeat": now - 3600}},
                  open(os.path.join(self.home, "bosses.json"), "w"))
        ctx = bosskit.load(self.wt)
        bosskit.heartbeat(ctx, now=now)
        self.assertEqual(sorted(bosskit.registry()), sorted(["recent", ctx.bid]))


class Mail(Home):
    def boss(self, project, wt):
        os.environ["BOSS_PROJECT"] = project
        ctx = bosskit.load(wt)
        bosskit.heartbeat(ctx)
        return ctx

    def test_send_inbox_reply_done_round_trip(self):
        mail = load_script("boss-mail")
        wt_b = os.path.join(self.tmp, "wt-b"); os.makedirs(wt_b)
        a, b = self.boss("widgets", self.wt), self.boss("gadgets", wt_b)
        mid, sent = mail.send(a, "gadgets", "question", "is #42 safe?", "body")  # by project
        self.assertEqual(sent, [f"gadgets/{b.bid}"])
        inbox = mail.unread(b)
        self.assertEqual([(m["id"], m["kind"], m["from_project"]) for m in inbox], [(mid, "question", "widgets")])
        rid, _ = mail.send(b, inbox[0]["from_boss"], "fyi", "Re: is #42 safe?", "yes", mid)  # what reply does
        back = mail.unread(a)
        self.assertEqual((back[0]["id"], back[0]["reply_to"]), (rid, mid))
        os.replace(mail.find(b, mid), os.path.join(b.inbox, "done", mid + ".json"))
        self.assertEqual(mail.unread(b), [])
        self.assertTrue(os.path.exists(os.path.join(b.inbox, "done", mid + ".json")))
        with self.assertRaises(SystemExit):
            mail.send(a, "gadgets", "order", "x", "")  # unknown kind
        with self.assertRaises(SystemExit):
            mail.send(a, "nobody", "fyi", "x", "")  # unknown target


class Migrate(unittest.TestCase):
    def test_dry_run_changes_nothing_apply_moves_and_links(self):
        tmp = tempfile.mkdtemp()
        kit, home = os.path.join(tmp, "kit"), os.path.join(tmp, "boss")
        for d in ("projects/widgets/prompts", "projects/_template", "state/widgets", "legacy", "bin"):
            os.makedirs(os.path.join(kit, d))
        open(os.path.join(kit, "projects/widgets/BOSS.md"), "w").write("w")
        open(os.path.join(kit, "state/widgets/next.txt"), "w").write("go")
        open(os.path.join(kit, "legacy/BOSS.md"), "w").write("l")
        mig = load_script("boss-migrate")
        ops = mig.plan(kit, home, "b1")
        self.assertEqual(sorted((os.path.relpath(s, kit), os.path.relpath(d, home)) for s, d in ops), [
            ("legacy", "legacy"), ("projects/widgets", "widgets"), ("state/widgets", "widgets/bosses/b1")])
        run = lambda *a: subprocess.run([sys.executable, os.path.join(BIN, "boss-migrate"), "--kit", kit, "--boss", "b1", *a],
                                        env={**os.environ, "BOSS_HOME": home}, capture_output=True, text=True)
        out = run()
        self.assertIn("dry run", out.stdout)
        self.assertFalse(os.path.exists(home))
        run("--apply")
        self.assertEqual(open(os.path.join(home, "widgets/BOSS.md")).read(), "w")
        self.assertEqual(open(os.path.join(home, "widgets/bosses/b1/next.txt")).read(), "go")
        self.assertTrue(os.path.islink(os.path.join(kit, "projects/widgets")))
        self.assertEqual(open(os.path.join(kit, "state/widgets/next.txt")).read(), "go")  # old path still works
        self.assertIn("nothing to move", run("--apply").stdout)


class Lessons(Home):
    def lesson(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["boss-lesson", *args]), redirect_stdout(out):
            load_script("boss-lesson").main()
        return out.getvalue()

    def test_add_list_promote_and_dedupe(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        self.assertIn("lesson #1 added", self.lesson("add", "Deploys follow a merge by about seven minutes", "--why", "measured"))
        self.assertIn("lesson #2 added", self.lesson("add", "CI's lint job is flaky on Mondays"))
        with self.assertRaises(SystemExit):
            self.lesson("add", "Deploys follow a merge by about   seven minutes")  # exact, modulo spacing
        self.assertIn("lesson #3 added", self.lesson("add", "Deploys follow a merge by about ten minutes on Fridays"))
        listed = self.lesson("list")
        self.assertIn("1. Deploys follow a merge", listed)
        self.assertIn("widgets #1 promoted to shared #1", self.lesson("promote", "1"))
        shared = open(os.path.join(self.home, "lessons.md")).read()
        self.assertIn("from widgets #1", shared)
        self.assertIn("Why: measured", shared)
        self.assertIn("[promoted to shared #1]", open(os.path.join(self.home, "widgets", "lessons.md")).read())
        with self.assertRaises(SystemExit):
            self.lesson("promote", "1")  # already promoted
        self.assertIn("shared lesson #2 added", self.lesson("add", "A restart kills every watcher", "--shared"))
        self.assertIn("(2)", self.lesson("list", "--shared"))

    def test_loader_budget(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        short = "# Shared\n\n" + "\n\n".join(f"## {i}. lesson {i} (2026-01-01, from x)\nbody" for i in range(1, 4))
        self.assertEqual(bosskit.shared_view(short), short)
        long = "# Shared\n\n" + "\n\n".join(f"## {i}. lesson {i} (2026-01-01, from x)\nline a\nline b" for i in range(1, 61))
        view = bosskit.shared_view(long)
        self.assertIn("over the 150-line budget", view)
        self.assertIn("- 1. lesson 1", view)
        self.assertIn("## 60. lesson 60", view)
        self.assertIn("## 41. lesson 41", view)
        self.assertNotIn("## 40. lesson 40", view)  # titles only below the 20 newest
        open(os.path.join(self.home, "widgets", "BOSS.md"), "w").write("widgets facts")
        open(os.path.join(self.home, "widgets", "lessons.md"), "w").write("## 1. widgets lesson (2026-01-01)")
        open(os.path.join(self.home, "lessons.md"), "w").write(long)
        text = bosskit.instructions(bosskit.load(self.wt))
        for part in ("BOSS — orchestrator", "widgets facts", "widgets lesson", "over the 150-line budget"):
            self.assertIn(part, text)


class Deck(Home):
    def test_other_bosses_and_mail_count(self):
        deck = load_script("boss-deck-data.py")
        now = time.time()
        reg = {"me": {"project": "widgets", "heartbeat": now},
               "b": {"project": "gadgets", "workspace": "ws-b", "heartbeat": now - 120, "working": 1, "forYou": 2},
               "gone": {"project": "gizmos", "heartbeat": now - 7200}}
        self.assertEqual([o["project"] for o in deck.others(reg, "me", now)], ["gadgets"])

    def test_others_never_lists_self_and_lists_each_workspace_once(self):
        deck = load_script("boss-deck-data.py")
        now = time.time()
        reg = {"ws-me": {"project": "widgets", "workspace": "ws-me", "worktree": "/w/me", "heartbeat": now},
               "wt-1234abcd": {"project": "widgets", "workspace": "", "worktree": "/w/me", "heartbeat": now},
               "ws-b": {"project": "gadgets", "workspace": "ws-b", "worktree": "/w/b", "heartbeat": now - 30, "working": 1},
               "ws-b-old": {"project": "gadgets", "workspace": "ws-b", "worktree": "/w/b", "heartbeat": now - 300},
               "wt-99": {"project": "gizmos", "workspace": "", "worktree": "/w/c", "heartbeat": now}}
        got = deck.others(reg, "wt-5678", now, workspace="ws-me", wt="/w/me")  # self by workspace and worktree
        self.assertEqual([(o["id"], o["project"], o["working"]) for o in got], [("ws-b", "gadgets", 1), ("wt-99", "gizmos", 0)])
        os.environ["BOSS_PROJECT"] = "widgets"
        ctx = bosskit.load(self.wt)
        for i in range(3):
            json.dump({"id": f"m{i}", "kind": "fyi", "from_project": "gadgets", "subject": f"s{i}"},
                      open(os.path.join(ctx.inbox, f"m{i}.json"), "w"))
        self.assertEqual(deck.mail(ctx.inbox)["count"], 3)

    def test_board_reads_the_tracker_snapshot_or_the_migrated_one(self):
        deck = load_script("boss-deck-data.py")
        os.environ["BOSS_PROJECT"] = "widgets"
        ctx = bosskit.load(self.wt)
        cfg = {"tracker": {"assignee": "Me"}}
        self.assertEqual(deck.board(cfg, bosskit.tracker_snapshot(ctx)), {})
        task = lambda pri, st: {"assignee": "Me", "priority": pri, "status": st}
        json.dump({"a": task("P1", "In Progress"), "b": task("P2", "Todo"), "c": task("P1", "Done")},
                  open(os.path.join(ctx.bdir, "tracker.json"), "w"))  # where boss-migrate left it
        self.assertEqual(deck.board(cfg, bosskit.tracker_snapshot(ctx)), {"mine": 2, "p1": 1, "inProgress": 1})
        json.dump({"a": task("P0", "Todo")}, open(os.path.join(ctx.cache, "tracker.json"), "w"))  # boss-tasks.py's
        self.assertEqual(deck.board(cfg, bosskit.tracker_snapshot(ctx)), {"mine": 1, "p1": 1, "inProgress": 0})
        snap = bosskit.tracker_snapshot(ctx)  # a tracker switched off, or no assignee: no counts from the old snapshot
        self.assertEqual(deck.board({"tracker": {"type": "none", "assignee": "Me"}}, snap), {})
        self.assertEqual(deck.board({"tracker": {}}, snap), {})

    def test_repo_tag_and_task_id(self):
        deck = load_script("boss-deck-data.py")
        self.assertEqual(deck.repo_tag("acme/widgets-sdk"), "ws")
        self.assertEqual(deck.repo_tag("acme/widgets"), "w")
        self.assertEqual(deck.repo_tag("acme/widgets-sdk", {"acme/widgets-sdk": "m"}), "m")
        self.assertEqual(deck.task_id("retry-43 (queued after fix-42)"), "retry-43")
        self.assertEqual(deck.task_id("fix-42: retry"), "fix-42")

    def test_lessons_counter_moves_only_at_session_start(self):
        deck = load_script("boss-deck-data.py")
        os.environ["BOSS_PROJECT"] = "widgets"
        ctx = bosskit.load(self.wt)
        shared = os.path.join(self.home, "lessons.md")
        open(shared, "w").write("## 1. a (x)\n")
        self.assertEqual(deck.lessons_new(self.home, ctx.bdir, True), 0)
        open(shared, "a").write("\n## 2. b (x)\n\n## 3. c (x)\n")
        self.assertEqual(deck.lessons_new(self.home, ctx.bdir), 2)   # new since this session's base
        self.assertEqual(deck.lessons_new(self.home, ctx.bdir, True), 2)  # next session: base was last session's count
        self.assertEqual(deck.lessons_new(self.home, ctx.bdir, True), 0)


if __name__ == "__main__":
    unittest.main()
