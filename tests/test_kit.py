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


class Init(Home):
    def test_a_flag_in_the_name_slot_scaffolds_nothing(self):
        init = os.path.join(BIN, "boss-init")
        out = subprocess.run([init, "--help"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("usage: boss-init <project>", out.stdout)
        out = subprocess.run([init, "--repo", "acme/widgets"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("bad project name: --repo", out.stderr)
        self.assertEqual(sorted(os.listdir(self.home)), ["gadgets", "widgets"])  # nothing new
        out = subprocess.run([init, "gizmos", "--repo", "acme/gizmos"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.load(open(os.path.join(self.home, "gizmos", "config.json")))["repo"], "acme/gizmos")


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

    def test_only_the_bound_workspace_on_a_checkout_is_the_boss(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        local = os.path.join(self.wt, "CLAUDE.local.md")
        os.environ["SUPERSET_WORKSPACE_ID"] = "ws-a"
        self.assertFalse(bosskit.is_boss(bosskit.load(self.wt)))  # no marker
        open(local, "w").write("# Boss workspace\n")
        self.assertTrue(bosskit.is_boss(bosskit.load(self.wt)))  # a bare marker: any session here
        open(local, "w").write("# Boss workspace ws-a\n")
        self.assertTrue(bosskit.is_boss(bosskit.load(self.wt)))
        os.environ["SUPERSET_WORKSPACE_ID"] = "ws-b"  # a second workspace on the checkout, or a copied file
        other = bosskit.load(self.wt)
        self.assertFalse(bosskit.is_boss(other))
        self.assertIn("binds the boss to workspace ws-a", bosskit.not_boss_note(other))
        out = subprocess.run([sys.executable, os.path.join(BIN, "boss-deck-data.py"), "--cwd", self.wt],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(bosskit.registry(), {})  # it never heartbeats

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

    def test_a_boss_that_never_wrote_a_heartbeat_still_gets_its_mail(self):
        mail = load_script("boss-mail")
        a = self.boss("widgets", self.wt)
        self.assertEqual(bosskit.registry(), {a.bid: bosskit.registry()[a.bid]})
        json.dump({}, open(os.path.join(self.home, "bosses.json"), "w"))  # nobody registered
        with self.assertRaises(SystemExit):
            mail.send(a, "gadgets", "fyi", "x", "")  # no bosses/ dir yet: still an error
        bdir = os.path.join(self.home, "gadgets", "bosses")
        os.makedirs(bdir)
        with self.assertRaises(SystemExit):
            mail.send(a, "gadgets", "fyi", "x", "")  # an empty bosses/ dir has nobody to deliver to
        for b in ("ws-x", "ws-y"):
            os.makedirs(os.path.join(bdir, b, "inbox"))
        open(os.path.join(bdir, "stray-file"), "w").close()
        mid, sent = mail.send(a, "gadgets", "question", "is #42 safe?", "body")
        self.assertEqual(sent, ["gadgets/ws-x", "gadgets/ws-y"])
        for b in ("ws-x", "ws-y"):
            self.assertEqual(json.load(open(os.path.join(bdir, b, "inbox", mid + ".json")))["subject"], "is #42 safe?")
        with self.assertRaises(SystemExit):
            mail.send(a, "../gadgets", "fyi", "x", "")  # a project name is a name, not a path


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


class DomainBoss(Home):
    def test_domain_boss_loads_charter_and_state(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        os.makedirs(os.path.join(self.home, "widgets", "domains"), exist_ok=True)
        open(os.path.join(self.home, "widgets", "domains", "studio.md"), "w").write("studio charter")
        open(os.path.join(self.home, "widgets", "domains", "studio-state.md"), "w").write("studio state")
        self.assertEqual(bosskit.boss_domain(self.wt), "")
        self.assertNotIn("studio charter", bosskit.instructions(bosskit.load(self.wt)))
        with open(os.path.join(self.wt, "CLAUDE.local.md"), "a") as f:
            f.write("\nDomain: studio\n")
        self.assertEqual(bosskit.boss_domain(self.wt), "studio")
        text = bosskit.instructions(bosskit.load(self.wt))
        for part in ("domain studio", "studio charter", "studio state"):
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



class Lanes(Home):
    """Each workspace's lane (stage), its PR joined by branch, the stage log, DONE TODAY and the fallback age."""

    def setUp(self):
        super().setUp()
        self.deck = load_script("boss-deck-data.py")
        self.now = int(time.mktime((2026, 1, 2, 12, 0, 0, 0, 0, -1)))  # midday: no event lands on another day; boundaries are in test_done_today_cutoff
        self.today = self.deck.day_start(self.now)

    def pr(self, **kw):
        return {"draft": True, "review": "", "ci": "pending", "doneAt": 0, **kw}

    def ev(self, stage, ago=0):
        return {"at": self.now - ago, "ws": "1a2b3c4d", "stage": stage, "note": ""}

    def test_each_lane_first_match_wins(self):
        stage, pr, ev, today = self.deck.stage, self.pr, self.ev, self.today
        approved = pr(draft=False, review="APPROVED", ci="green")
        self.assertEqual(stage("idle", "DISPATCHED", approved, [], today), "move")
        self.assertEqual(stage("working", "DISPATCHED", approved, [], today), "move")  # your move beats working
        # checking: a DONE on the screen (the watcher's event) or in a PR comment, not yet verified
        self.assertEqual(stage("idle", "DISPATCHED", pr(), [ev("sent", 600), ev("DONE", 60)], today), "checking")
        self.assertEqual(stage("idle", "DISPATCHED", pr(doneAt=self.now - 60), [], today), "checking")
        self.assertEqual(stage("idle", "DISPATCHED", pr(draft=False, ci="red"), [], today), "checking")  # ready, CI went red
        # verified, by the ledger or a later checked event: no longer the boss's move
        self.assertEqual(stage("idle", "VERIFIED", pr(doneAt=self.now - 60), [], today), "working")
        # no DONE event logged: a DONE ledger row still means the boss checks it, a draft PR or none
        self.assertEqual(stage("idle", "DONE", pr(), [ev("sent", 600)], today), "checking")
        self.assertEqual(stage("working", "DONE", None, [], today), "checking")
        self.assertEqual(stage("idle", "DONE", None, [ev("sent", 600), ev("checked", 30)], today), "waiting")  # verified, nothing left but the user
        self.assertNotEqual(stage("idle", "DISPATCHED", pr(), [ev("DONE", 60), ev("checked", 30)], today), "checking")
        # a DONE from before the last dispatch does not count
        self.assertEqual(stage("idle", "DISPATCHED", pr(doneAt=self.now - 900), [ev("sent", 600)], today), "working")
        self.assertEqual(stage("working", "DISPATCHED", None, [], today), "working")
        self.assertEqual(stage("blocked", "DISPATCHED", None, [ev("BLOCKED")], today), "working")
        self.assertEqual(stage("idle", "DISPATCHED", None, [ev("sent", 60)], today), "working")  # idle without DONE
        self.assertEqual(stage("idle", "READY", pr(draft=False, ci="green"), [ev("DONE", 90), ev("ready", 30)], today), "review")
        self.assertEqual(stage("working", "READY", pr(draft=False, ci="green"), [], today), "working")  # fixing review notes
        self.assertEqual(stage("gone", "ARCHIVED", None, [ev("merged", 120), ev("retired", 60)], today), "done")

    def test_checked_with_a_draft_or_no_pr_is_waiting_on_you(self):
        stage, pr, ev, today = self.deck.stage, self.pr, self.ev, self.today
        checked = [ev("sent", 900), ev("DONE", 600), ev("checked", 300)]
        self.assertEqual(stage("idle", "DISPATCHED", pr(), checked, today), "waiting")  # the PR stays draft by project rule
        self.assertEqual(stage("idle", "DISPATCHED", None, checked, today), "waiting")  # no PR at all
        self.assertEqual(stage("idle", "DISPATCHED", pr(), [ev("sent", 900), ev("DONE", 600), ev("ready", 300)], today), "waiting")
        self.assertEqual(stage("working", "DISPATCHED", pr(), checked, today), "working")  # the agent picked it up again
        self.assertEqual(stage("idle", "DISPATCHED", pr(), [ev("sent", 900), ev("DONE", 600)], today), "checking")  # not checked yet
        self.assertEqual(stage("idle", "DISPATCHED", pr(), [ev("sent", 900), ev("checked", 300)], today), "working")  # no DONE
        self.assertEqual(stage("idle", "DISPATCHED", pr(), checked + [ev("sent", 60)], today), "working")  # re-dispatched since
        self.assertEqual(stage("idle", "DISPATCHED", pr(draft=False, ci="green"), checked, today), "review")  # a ready PR is review
        self.assertEqual(stage("gone", "ARCHIVED", None, checked + [ev("merged", 60)], today), "done")  # merged today is done

    def test_done_today_cutoff(self):
        stage, today = self.deck.stage, self.today
        at = lambda t, s: {"at": t, "ws": "1a2b3c4d", "stage": s, "note": ""}
        self.assertEqual(stage("gone", "MERGED", None, [at(today + 1, "merged")], today), "done")
        self.assertEqual(stage("gone", "MERGED", None, [at(today - 1, "merged")], today), "working")  # yesterday's
        self.assertEqual(stage("idle", "DISPATCHED", None, [at(today + 1, "merged"), at(today + 2, "sent")], today), "working")
        self.assertEqual(self.deck.day_start(today + 3600), today)

    def test_done_today_keeps_archived_workspaces_and_the_newest_five(self):
        row = lambda ws, state="gone": {"ws": ws, "state": state, "ledger": "ARCHIVED", "date": "2026-01-01"}
        evs = {f"d{i}": [{"at": self.today + 60 * i, "ws": f"d{i}", "stage": "retired", "note": ""}] for i in range(7)}
        evs["old"] = [{"at": self.today - 60, "ws": "old", "stage": "retired", "note": ""}]
        got = self.deck.lanes([row("live", "working")], [row(f"d{i}") for i in range(7)] + [row("old")], evs, self.today)
        self.assertEqual([(w["ws"], w["stage"]) for w in got], [("live", "working")] + [(f"d{i}", "done") for i in (6, 5, 4, 3, 2)])
        self.assertEqual(got[1]["events"][0]["hm"], time.strftime("%H:%M", time.localtime(self.today + 360)))

    def test_branch_join_prefers_the_projects_repo(self):
        workers = [{"ws": "aaaaaaaa", "branch": "fix/a"}, {"ws": "bbbbbbbb", "branch": ""}, {"ws": "cccccccc", "branch": "fix/c"}]
        prs = [{"repo": "acme/widgets-sdk", "tag": "ws", "primary": False, "num": 7, "head": "fix/a"},
               {"repo": "acme/widgets", "primary": True, "num": 57, "head": "fix/a"},
               {"repo": "acme/widgets-sdk", "tag": "ws", "primary": False, "num": 8, "head": "fix/c"},
               {"repo": "acme/widgets", "primary": True, "num": 60, "head": "other"}]
        self.deck.join(workers, prs)
        self.assertEqual([(w["pr"] or {}).get("num") for w in workers], [57, None, 8])
        self.assertEqual([w.get("prTag") for w in workers], ["#57", None, "ws#8"])
        self.assertEqual([p.get("ws") for p in prs], [None, "aaaaaaaa", "cccccccc", None])  # #60 is a PR-only row

    def test_done_comment_and_its_time(self):
        p = {"number": 61, "title": "x", "comments": [
            {"body": "SUPERSET_WORKER_DONE task: fix-61\nsummary: done", "createdAt": "2026-01-02T10:31:00Z"},
            {"body": "Will post the SUPERSET_WORKER_DONE envelope later", "createdAt": "2026-01-03T10:31:00Z"},
            {"body": "SUPERSET_WORKER_DONE task: <id>", "createdAt": "2026-01-04T10:31:00Z"}]}
        self.assertEqual(self.deck.pr_row("acme/widgets", p, True)["doneAt"], self.deck.epoch("2026-01-02T10:31:00Z"))
        self.assertEqual(self.deck.pr_row("acme/widgets", {"number": 1, "title": "x"}, True)["doneAt"], 0)

    def test_since_falls_back_to_the_pr_then_the_ledger(self):
        since = self.deck.since
        self.assertEqual(since([self.ev("sent", 300), self.ev("DONE", 60)], None, "2026-01-02"), self.now - 60)
        self.assertEqual(since([], {"updated": "2026-01-02T10:31:00Z"}, "2026-01-01"), self.deck.epoch("2026-01-02T10:31:00Z"))
        self.assertEqual(since([], {"updated": ""}, "2026-01-01"), int(time.mktime(time.strptime("2026-01-01", "%Y-%m-%d"))))
        self.assertEqual(since([], None, "?"), 0)

    def test_events_round_trip_and_the_cli(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        ctx = bosskit.load(self.wt)
        bosskit.add_event(ctx, "1a2b3c4d-full-id", "sent", "watcher armed", now=200)
        bosskit.add_event(ctx, "1a2b3c4d-full-id", "DONE", "fix-42: did it", now=100)
        with open(os.path.join(ctx.bdir, "events.jsonl"), "a") as f:
            f.write("not json\n{\"at\": 1}\n")
        got = bosskit.events(ctx.bdir)
        self.assertEqual([(e["at"], e["stage"], e["note"]) for e in got], [(100, "DONE", "fix-42: did it"), (200, "sent", "watcher armed")])
        out = subprocess.run([os.path.join(BIN, "boss-event"), "1a2b3c4d", "checked", "head", "8c41d2e", "ok"],
                             cwd=self.wt, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(bosskit.events(ctx.bdir)[-1]["note"], "head 8c41d2e ok")
        self.assertNotEqual(subprocess.run([os.path.join(BIN, "boss-event"), "1a2b3c4d"], cwd=self.wt, capture_output=True).returncode, 0)



class Bosses(Home):
    """The BOSSES section: this project's live bosses from the registry, and the heartbeat that feeds it."""

    def test_this_projects_bosses_this_one_first(self):
        deck = load_script("boss-deck-data.py")
        now = int(time.time())
        ddir = os.path.join(self.home, "widgets", "domains")
        os.makedirs(ddir)
        open(os.path.join(ddir, "checkout-state.md"), "w").write("# Checkout state\n\n## Now\n- cart totals PR #61 in review\n- refund flow next\n\n- a\n- b\n")
        reg = {"ws-co": {"project": "widgets", "workspace": "ws-co", "worktree": "/w/co", "domain": "checkout", "next": "merge #61",
                         "heartbeat": now - 600, "working": 1, "forYou": 2},
               "ws-me": {"project": "widgets", "workspace": "ws-me", "worktree": "/w/me", "domain": "", "next": "say merge 57",
                         "heartbeat": now, "working": 2, "forYou": 1},
               "ws-g": {"project": "gadgets", "workspace": "ws-g", "heartbeat": now},  # another project
               "ws-gone": {"project": "widgets", "workspace": "ws-gone", "domain": "search", "heartbeat": now - bosskit.STALE_S - 1}}
        got = deck.bosses(reg, "widgets", "ws-me", os.path.join(self.home, "widgets"), now, workspace="ws-me", wt="/w/me")
        self.assertEqual([(b["domain"], b["me"], b["stale"]) for b in got], [("", True, False), ("checkout", False, True)])
        self.assertEqual(got[1]["state"], ["- cart totals PR #61 in review", "- refund flow next", "- a"])
        self.assertEqual((got[0]["state"], got[0]["next"], got[1]["forYou"]), ([], "say merge 57", 2))
        # the current boss leads even when it is a domain boss
        got = deck.bosses(reg, "widgets", "ws-co", os.path.join(self.home, "widgets"), now, workspace="ws-co", wt="/w/co")
        self.assertEqual([b["domain"] for b in got], ["checkout", ""])

    def test_heartbeat_carries_domain_and_next(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        json.dump({"repo": "acme/widgets", "me": "octocat", "superset_host": "h"}, open(os.path.join(self.home, "widgets", "config.json"), "w"))
        open(os.path.join(self.wt, "CLAUDE.local.md"), "w").write("# Boss workspace\nDomain: checkout\n")
        ctx = bosskit.load(self.wt)
        open(os.path.join(ctx.bdir, "next.txt"), "w").write("Your move: merge #61\nmore\n")
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(stubs)
        for tool in ("gh", "superset"):  # no network, no Paradev
            path = os.path.join(stubs, tool)
            open(path, "w").write("#!/bin/sh\nexit 1\n")
            os.chmod(path, 0o755)
        out = subprocess.run([sys.executable, os.path.join(BIN, "boss-deck-data.py"), "--cwd", self.wt], capture_output=True, text=True,
                             env={**os.environ, "PATH": f"{stubs}:/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        entry = bosskit.registry()[ctx.bid]
        self.assertEqual((entry["domain"], entry["next"]), ("checkout", "Your move: merge #61"))
        self.assertEqual([(b["domain"], b["me"]) for b in json.loads(out.stdout)["bosses"]], [("checkout", True)])


def stub_tools(tmp, fix):
    """gh and superset stubs that print fixtures from *fix*: no network, no Paradev."""
    stubs = os.path.join(tmp, "stubs")
    os.makedirs(stubs, exist_ok=True)
    scripts = {"superset": 'case "$1 $2" in\n  "snapshot "*) cat "$FIX/snapshot.json";;\n  "workspaces list") cat "$FIX/list.json";;\n  *) exit 1;;\nesac\n',
               "gh": 'case "$1 $2" in\n  "pr list") cat "$FIX/prs.json";;\n  *) exit 1;;\nesac\n'}
    for tool, body in scripts.items():
        path = os.path.join(stubs, tool)
        open(path, "w").write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)
    return {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "FIX": fix}


def deck_json(wt, env, *args):
    out = subprocess.run([sys.executable, os.path.join(BIN, "boss-deck-data.py"), "--cwd", wt, *args], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


class WorkerView(Home):
    """The pane in a worker's own session: its dispatch row in any project, its PR, delivered work, notes, the boss's messages."""

    WS = "1a2b3c4d-0000-4000-8000-000000000001"

    def setUp(self):
        super().setUp()
        self.deck = load_script("boss-deck-data.py")
        self.fix = os.path.join(self.tmp, "fix")
        os.makedirs(self.fix)
        self.tools = stub_tools(self.tmp, self.fix)

    def ledger(self, project, row):
        open(os.path.join(self.home, project, "ledger.md"), "w").write(
            "## Dispatches 2026-01-02\n\n| Date | Task | Workspace | Model | Status | Proof | Boss |\n|---|---|---|---|---|---|---|\n" + row)

    def test_the_row_is_found_in_any_project_and_no_row_is_no_pane(self):
        self.assertIsNone(self.deck.find_dispatch(self.home, self.WS))
        self.assertIsNone(deck_json(self.wt, self.tools, "--worker", "--workspace", self.WS)["worker"])
        self.ledger("gadgets", "| 2026-01-02 | fix-42: retry webhooks | 1a2b3c4d / 5e6f | mid | DISPATCHED | | ws-boss |\n")
        self.ledger("widgets", "| 2026-01-01 | fix-9: older | 1a2b3c4d / 5e6f | mid | MERGED | | |\n")  # an older dispatch elsewhere
        project, _, row = self.deck.find_dispatch(self.home, self.WS)
        self.assertEqual((project, row[0], row[4]), ("gadgets", "fix-42", "ws-boss"))
        self.assertIsNone(self.deck.find_dispatch(self.home, "9f9f9f9f-0000"))

    def test_the_boss_is_the_boss_column_else_the_live_main_boss(self):
        now = time.time()
        reg = {"ws-co": {"project": "widgets", "domain": "checkout", "heartbeat": now},
               "ws-main": {"project": "widgets", "domain": "", "heartbeat": now - 60},
               "ws-g": {"project": "gadgets", "heartbeat": now}}
        self.assertEqual(self.deck.worker_boss(reg, "widgets", "ws-named"), "ws-named")
        self.assertEqual(self.deck.worker_boss(reg, "widgets", ""), "ws-main")
        self.assertEqual(self.deck.worker_boss({}, "widgets", ""), "")

    def test_a_boss_hint_file_and_the_worker_files_live_side_by_side(self):
        open(os.path.join(self.wt, ".boss"), "w").write("project: widgets\n")  # bosskit's project hint, a file
        self.ledger("widgets", "| 2026-01-02 | fix-42: retry webhooks | 1a2b3c4d | mid | DISPATCHED | | |\n")
        json.dump([], open(os.path.join(self.fix, "prs.json"), "w"))
        os.makedirs(os.path.join(self.wt, ".boss-worker"))
        open(os.path.join(self.wt, ".boss-worker", "notes.md"), "w").write("- open: retry 4xx?\n")
        status = json.dumps({"tasks_done": 2, "tasks_total": 4, "current": "run the tests"})
        w = deck_json(self.wt, self.tools, "--worker", "--workspace", self.WS, "--status", status)["worker"]
        self.assertEqual(w["notes"], ["- open: retry 4xx?"])
        self.assertEqual((self.deck.read_status(self.wt)["done"], self.deck.read_status(self.wt)["total"]), (2, 4))
        self.assertEqual(bosskit.project_name(self.wt), "widgets")  # the hint still resolves

    def test_the_view_joins_pr_commits_events_messages_and_keeps_boss_dir_ignored(self):
        origin = os.path.join(self.tmp, "origin.git")
        git(self.tmp, "init", "-q", "--bare", origin)
        git(self.wt, "remote", "add", "origin", origin)
        git(self.wt, "checkout", "-q", "-b", "fix/retry")
        for i, subject in enumerate(["add retry queue", "add backoff"]):
            subprocess.run(["git", "-C", self.wt, "-c", "user.name=jane", "-c", "user.email=jane@example.com", "commit", "-q", "--allow-empty",
                            "-m", subject], check=True, capture_output=True, env={**os.environ, "GIT_COMMITTER_DATE": f"@{1000 + i * 100} +0000"})
        git(self.wt, "push", "-q", "origin", "fix/retry")
        self.ledger("widgets", "| 2026-01-02 | fix-42: retry webhooks | 1a2b3c4d | mid | DISPATCHED | | |\n")
        bosskit.save_json(os.path.join(self.home, "bosses.json"), {"ws-main": {"project": "widgets", "workspace": "ws-main", "heartbeat": time.time()}})
        bdir = os.path.join(self.home, "widgets", "bosses", "ws-main")
        os.makedirs(os.path.join(bdir, "cache"))
        with open(os.path.join(bdir, "events.jsonl"), "w") as f:
            for at, stage, note in ((900, "sent", "fix-42"), (2000, "msg", "also cover 429"), (2100, "msg", "rebase on main"),
                                    (2200, "DONE", "fix-42: done"), (2300, "msg", "thanks")):
                f.write(json.dumps({"at": at, "ws": self.WS, "stage": stage, "note": note}) + "\n")
            f.write(json.dumps({"at": 2400, "ws": "ffffffff", "stage": "msg", "note": "not mine"}) + "\n")
        json.dump([{"number": 61, "title": "Retry webhooks", "isDraft": True, "headRefName": "fix/retry", "baseRefName": "main",
                    "mergeable": "MERGEABLE", "statusCheckRollup": [{"name": "ci", "conclusion": "SUCCESS"}], "comments": []}],
                  open(os.path.join(self.fix, "prs.json"), "w"))
        json.dump({"workspaces": [{"id": self.WS, "name": "webhook-retries", "terminals": []}]}, open(os.path.join(self.fix, "snapshot.json"), "w"))
        status = json.dumps({"tasks_done": 1, "tasks_total": 3, "current": "run the tests"})
        w = deck_json(self.wt, self.tools, "--worker", "--workspace", self.WS, "--status", status)["worker"]
        self.assertEqual((w["project"], w["task"], w["goal"], w["name"], w["branch"]), ("widgets", "fix-42", "retry webhooks", "webhook-retries", "fix/retry"))
        self.assertEqual((w["pr"]["num"], w["pr"]["draft"], w["pr"]["ci"], w["boss"]["workspace"]), (61, True, "green", "ws-main"))
        self.assertEqual([m["text"] for m in w["msgs"]], ["thanks", "rebase on main", "also cover 429"])  # newest first
        self.assertEqual([d["kind"] for d in w["delivered"]], ["DONE", "commit", "commit", "sent"])
        self.assertTrue(w["delivered"][1]["text"].endswith("add backoff"))
        self.assertEqual((w["stage"]["stage"], w["sentAt"]), ("DONE", 900))
        self.assertTrue(os.path.exists(os.path.join(bdir, "cache", "deck-prs.json")))  # the boss's PR cache
        exclude = subprocess.run(["git", "-C", self.wt, "rev-parse", "--git-path", "info/exclude"], capture_output=True, text=True).stdout.strip()
        self.assertIn(".boss-worker/", open(os.path.join(self.wt, exclude)).read().split())
        self.assertEqual(self.deck.read_status(self.wt)["total"], 3)
        self.assertEqual(subprocess.run(["git", "-C", self.wt, "status", "--porcelain"], capture_output=True, text=True).stdout, "")
        deck_json(self.wt, self.tools, "--worker", "--workspace", self.WS)  # exclude is added once
        self.assertEqual(open(os.path.join(self.wt, exclude)).read().split().count(".boss-worker/"), 1)


class Folders(Home):
    """A domain boss covers only the workspaces in its sidebar folder; the main boss covers all."""

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        json.dump({"repo": "acme/widgets", "me": "octocat", "superset_host": "h"}, open(os.path.join(self.home, "widgets", "config.json"), "w"))
        self.fix = os.path.join(self.tmp, "fix")
        os.makedirs(self.fix)
        self.tools = stub_tools(self.tmp, self.fix)
        self.worker_wt = os.path.join(self.tmp, "worker-a")
        os.makedirs(os.path.join(self.worker_wt, ".boss-worker"))
        json.dump({"tasks_done": 3, "tasks_total": 5, "current": "run the http tests", "at": 1},
                  open(os.path.join(self.worker_wt, ".boss-worker", "status.json"), "w"))
        open(os.path.join(self.worker_wt, ".boss-worker", "notes.md"), "w").write("- decided: cap at 5\n- open: retry 4xx?\n- open: log drops?\n")
        ids = {"a": "aaaaaaaa-0000-4000-8000-000000000001", "b": "bbbbbbbb-0000-4000-8000-000000000002"}
        open(os.path.join(self.home, "widgets", "ledger.md"), "w").write(
            "## Dispatches 2026-01-02\n\n| Date | Task | Workspace | Model | Status |\n|---|---|---|---|---|\n"
            "| 2026-01-02 | fix-1: a | aaaaaaaa | mid | DISPATCHED |\n| 2026-01-02 | fix-2: b | bbbbbbbb | mid | DISPATCHED |\n")
        agent = [{"id": "t", "agent": {"state": "working"}}]
        json.dump({"workspaces": [{"id": ids["a"], "name": "cart-totals", "branch": "fix/a", "terminals": agent},
                                  {"id": ids["b"], "name": "search-ui", "branch": "fix/b", "terminals": agent}]},
                  open(os.path.join(self.fix, "snapshot.json"), "w"))
        json.dump([{"id": ids["a"], "tags": "Checkout Flow", "worktreePath": self.worker_wt}, {"id": ids["b"], "tags": "UI", "worktreePath": ""}],
                  open(os.path.join(self.fix, "list.json"), "w"))
        pr = lambda n, head: {"number": n, "title": "x", "isDraft": False, "headRefName": head, "baseRefName": "main",
                              "statusCheckRollup": [{"name": "ci", "conclusion": "FAILURE"}]}
        json.dump([pr(1, "fix/a"), pr(2, "fix/b"), pr(3, "loose")], open(os.path.join(self.fix, "prs.json"), "w"))

    def local(self, text):
        open(os.path.join(self.wt, "CLAUDE.local.md"), "w").write(text)

    def test_folder_parse_and_default(self):
        self.local("# Boss workspace\n")
        self.assertEqual(bosskit.boss_folder(self.wt), "")  # the main boss: every folder
        self.local("# Boss workspace\nDomain: checkout\n")
        self.assertEqual(bosskit.boss_folder(self.wt), "checkout")
        self.local("# Boss workspace\nDomain: checkout\nFolder:  Checkout Flow  \n")
        self.assertEqual(bosskit.boss_folder(self.wt), "Checkout Flow")
        self.assertIn("Paradev workspaces tagged 'Checkout Flow'", bosskit.instructions(bosskit.load(self.wt)))

    def test_domain_boss_sees_only_its_folder(self):
        self.local("# Boss workspace\nDomain: checkout\nFolder: checkout flow\n")
        d = deck_json(self.wt, self.tools)
        self.assertEqual([w["name"] for w in d["workers"]], ["cart-totals"])
        self.assertEqual([p["num"] for p in d["prs"]], [1])  # its workspace's PR; no PR-only rows
        self.assertEqual([a["text"] for a in d["attention"]], ["#1 CI red"])
        self.assertEqual(bosskit.registry()[bosskit.load(self.wt).bid]["working"], 1)

    def test_main_boss_sees_everything_and_reads_each_workers_status_and_notes(self):
        self.local("# Boss workspace\n")
        d = deck_json(self.wt, self.tools)
        self.assertEqual([w["name"] for w in d["workers"]], ["cart-totals", "search-ui"])
        self.assertEqual(sorted(p["num"] for p in d["prs"]), [1, 2, 3])
        self.assertEqual(len(d["attention"]), 3)
        a, b = d["workers"]
        self.assertEqual((a["tasks"]["done"], a["tasks"]["total"], a["tasks"]["current"]), (3, 5, "run the http tests"))
        self.assertEqual(a["notes"], ["- open: retry 4xx?", "- open: log drops?"])
        self.assertEqual((b["tasks"], b["notes"]), (None, []))


class BossSessions(Home):
    """A boss's own workspace is never a worker; its other agent terminals are rows of its BOSSES entry."""

    BOSS = "bbbbbbbb-0000-4000-8000-000000000009"
    WORKER = "aaaaaaaa-0000-4000-8000-000000000001"

    def test_same_day_dispatches_of_one_terminal_take_the_newest_row(self):
        deck = load_script("boss-deck-data.py")
        led = os.path.join(self.tmp, "ledger.md")
        row = lambda task, status: f"| 2026-01-02 | {task} | bbbbbbbb / ab12 | mid | {status} |\n"
        head = "| Date | Task | Workspace | Model | Status |\n|---|---|---|---|---|\n"
        # the first table appends: the later row is the newer one
        open(led, "w").write(head + row("old-1: first", "DONE") + row("new-1: second", "DISPATCHED"))
        self.assertEqual(deck.ledger_terms(led, "bbbbbbbb"), {"ab12": "new-1: second"})
        # a "## Dispatches" section prepends: the earlier row is the newer one
        open(led, "w").write("## Dispatches 2026-01-02\n\n" + head + row("new-1: second", "DISPATCHED") + row("old-1: first", "DONE"))
        self.assertEqual(deck.ledger_terms(led, "bbbbbbbb"), {"ab12": "new-1: second"})
        # a later date still wins over either order
        open(led, "w").write(head + row("old-1: first", "DONE").replace("01-02", "01-03") + row("x-1: earlier day", "DONE"))
        self.assertEqual(deck.ledger_terms(led, "bbbbbbbb"), {"ab12": "old-1: first"})

    def test_own_workspace_is_sessions_not_a_worker(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        json.dump({"repo": "acme/widgets", "me": "octocat", "superset_host": "h"}, open(os.path.join(self.home, "widgets", "config.json"), "w"))
        open(os.path.join(self.wt, "CLAUDE.local.md"), "w").write("# Boss workspace\n")
        fix = os.path.join(self.tmp, "fix")
        os.makedirs(fix)
        tools = {**stub_tools(self.tmp, fix), "SUPERSET_WORKSPACE_ID": self.BOSS, "SUPERSET_TERMINAL_ID": "boss-term-0000"}
        open(os.path.join(self.home, "widgets", "ledger.md"), "w").write(
            "## Dispatches 2026-01-02\n\n| Date | Task | Workspace | Model | Status |\n|---|---|---|---|---|\n"
            "| 2026-01-02 | research-1: map the api | bbbbbbbb / ab12 | mid | DISPATCHED |\n"
            "| 2026-01-02 | fix-1: a | aaaaaaaa | mid | DISPATCHED |\n")
        agent = lambda state: {"state": state}
        json.dump({"workspaces": [
            {"id": self.BOSS, "name": "BOSS", "branch": "main", "terminals": [
                {"id": "boss-term-0000", "title": "boss", "agent": agent("working")},
                {"id": "ab120000-0000", "title": "api research", "agent": agent("idle")},
                {"id": "cd340000-0000", "title": "ops: deploy check", "agent": agent("working")},
                {"id": "sh000000-0000", "title": "zsh"}]},
            {"id": self.WORKER, "name": "cart-totals", "branch": "fix/a", "terminals": [{"id": "t", "agent": agent("working")}]}]},
            open(os.path.join(fix, "snapshot.json"), "w"))
        json.dump([], open(os.path.join(fix, "list.json"), "w"))
        json.dump([], open(os.path.join(fix, "prs.json"), "w"))
        d = deck_json(self.wt, tools)
        self.assertEqual([w["name"] for w in d["workers"]], ["cart-totals"])  # never "BOSS"
        me = next(b for b in d["bosses"] if b["me"])
        self.assertEqual([(s["title"], s["state"], s["task"]) for s in me["sessions"]],
                         [("api research", "idle", "research-1: map the api"), ("ops: deploy check", "working", "")])
        self.assertTrue(all(s["ageS"] >= 0 for s in me["sessions"]))
        self.assertEqual(d["workers"][0]["ws"], "aaaaaaaa")


class StatusAsk(unittest.TestCase):
    def test_dry_run_text_has_all_six_questions_and_no_new_work(self):
        out = subprocess.run([os.path.join(BIN, "boss-status-ask"), "--dry-run", "--as", "Studio 2 boss"],
                             capture_output=True, text=True, check=True).stdout
        for n in range(1, 7):
            self.assertIn(f"({n})", out)
        self.assertIn("do NOT start new work", out)
        self.assertIn("Studio 2 boss", out)

    def test_odd_pair_args_exit_with_usage(self):
        r = subprocess.run([os.path.join(BIN, "boss-status-ask"), "only-a-workspace"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


FAKE_GH = """#!/bin/sh
case "$1 $2" in
  "pr view") if [ -f "$FIX/merged" ]; then cat "$FIX/pr-merged.json"; else cat "$FIX/pr.json"; fi;;
  "api graphql") cat "$FIX/threads.json";;
  "pr merge") echo "$*" >> "$FIX/merge.log"
    case "$*" in *--admin*) ;; *) if [ -f "$FIX/policy" ]; then
      echo "X Pull request acme/widgets#7 is not mergeable: the base branch policy prohibits the merge." >&2; exit 1; fi;; esac
    touch "$FIX/merged";;
  "api repos/"*"/rules/branches/"*) cat "$FIX/rules.json";;
  "api repos/"*"/rulesets/"*) cat "$FIX/ruleset.json";;
  *) exit 1;;
esac
"""


class Merge(Home):
    """boss-merge against a fake gh and superset on PATH: what it refuses, what it merges, and the --admin retry."""

    WS = "7e7e7e7e-0000-4000-8000-000000000007"
    HEAD = "a1b2c3d4e5" + "0" * 30

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        self.fix = os.path.join(self.tmp, "fix")
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(self.fix)
        os.makedirs(stubs)
        for tool, body in (("gh", FAKE_GH), ("superset", '#!/bin/sh\n[ "$1 $2" = "workspaces list" ] && cat "$FIX/list.json"\n')):
            open(os.path.join(stubs, tool), "w").write(body)
            os.chmod(os.path.join(stubs, tool), 0o755)
        self.tools = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "FIX": self.fix}
        self.worker = os.path.join(self.tmp, "worker")
        os.makedirs(self.worker)
        git(self.worker, "init", "-q", "-b", "feat/x")
        git(self.worker, "-c", "user.name=jane", "-c", "user.email=jane@example.com", "commit", "-q", "--allow-empty", "-m", "x")
        git(self.worker, "update-ref", "refs/remotes/origin/feat/x", "HEAD")
        self.put("list.json", [{"id": self.WS, "branch": "feat/x", "worktreePath": self.worker}])
        pr = {"number": 7, "state": "OPEN", "headRefOid": self.HEAD, "headRefName": "feat/x", "baseRefName": "main",
              "mergeable": "MERGEABLE", "statusCheckRollup": [{"name": "ci", "conclusion": "SUCCESS"}], "author": {"login": "jane"}}
        self.put("pr.json", pr)
        self.put("pr-merged.json", {**pr, "state": "MERGED", "mergeCommit": {"oid": "f" * 40}})
        self.threads()
        self.ctx = bosskit.load(self.wt)

    def put(self, name, data):
        json.dump(data, open(os.path.join(self.fix, name), "w"))

    def threads(self, *threads):
        self.put("threads.json", {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
            {"isResolved": resolved, "path": "src/cart.py", "line": 3,
             "comments": {"nodes": [{"author": {"login": who}, "body": body} for who, body in comments]}}
            for resolved, comments in threads]}}}}})

    def merge(self, *args):
        return subprocess.run([os.path.join(BIN, "boss-merge"), "7", *args], cwd=self.wt, env=self.tools, capture_output=True, text=True)

    def merges(self):
        return bosskit._read(os.path.join(self.fix, "merge.log")).splitlines()

    def test_head_mismatch_and_no_verified_sha_are_refused(self):
        r = self.merge("--sha", "9999999")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused: head a1b2c3d4e500 is not the verified 9999999", r.stdout)
        self.assertIn("no verified sha", self.merge().stdout)  # no --sha and no checked event
        bosskit.add_event(self.ctx, self.WS, "checked", "0123abcd tests green")  # checked an older head
        self.assertIn("is not the verified 0123abcd", self.merge().stdout)
        self.assertEqual(self.merges(), [])

    def test_unanswered_thread_is_refused_and_listed(self):
        self.threads((False, [("rev", "please rename this")]), (False, [("rev", "why?"), ("jane", "because")]))
        r = self.merge("--sha", self.HEAD[:10])
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "refused: unanswered thread: src/cart.py:3 rev: please rename this")
        self.assertEqual(self.merges(), [])

    def test_answered_threads_pass_and_the_merge_is_logged_and_checked_for_leftovers(self):
        self.threads((False, [("rev", "why?"), ("jane", "because")]), (True, [("rev", "nit")]))
        bosskit.add_event(self.ctx, self.WS, "checked", f"{self.HEAD[:10]} tests green")
        r = self.merge()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.merges(), [f"pr merge 7 --squash --match-head-commit {self.HEAD}"])
        self.assertIn("merged PR #7: " + "f" * 40, r.stdout)
        self.assertIn("leftovers: none", r.stdout)
        self.assertIn(f"superset workspaces archive {self.WS} --local", r.stdout)
        self.assertEqual([(e["ws"], e["stage"], e["note"]) for e in bosskit.events(self.ctx.bdir)][-1], (self.WS, "merged", "PR #7"))

    def test_failing_or_pending_checks_and_conflicts_are_refused(self):
        self.put("pr.json", {**json.load(open(os.path.join(self.fix, "pr.json"))), "mergeable": "CONFLICTING",
                             "statusCheckRollup": [{"name": "ci", "conclusion": "FAILURE"}, {"context": "lint", "state": "PENDING"}]})
        out = self.merge("--sha", self.HEAD).stdout
        for want in ("mergeable is CONFLICTING", "failing check: ci", "pending check: lint"):
            self.assertIn(want, out)
        self.assertEqual(self.merges(), [])

    def test_policy_refusal_is_retried_with_admin_only_when_bypass_is_allowed(self):
        open(os.path.join(self.fix, "policy"), "w").close()
        self.put("rules.json", [{"type": "pull_request", "ruleset_id": 5}])
        self.put("ruleset.json", {"id": 5, "current_user_can_bypass": "never"})
        r = self.merge("--sha", self.HEAD)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot bypass", r.stderr)
        self.assertEqual(self.merges(), [f"pr merge 7 --squash --match-head-commit {self.HEAD}"])
        os.remove(os.path.join(self.fix, "merge.log"))
        self.put("ruleset.json", {"id": 5, "current_user_can_bypass": "always"})
        r = self.merge("--sha", self.HEAD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("retrying with --admin", r.stdout)
        self.assertEqual(self.merges(), [f"pr merge 7 --squash --match-head-commit {self.HEAD}",
                                         f"pr merge 7 --squash --match-head-commit {self.HEAD} --admin"])

    def test_leftovers_are_local_changes_unpushed_commits_and_ignored_files_beyond_rebuildable_output(self):
        self.assertEqual(bosskit.leftovers(self.worker, "feat/x"), [])
        open(os.path.join(self.worker, ".gitignore"), "w").write("node_modules/\n.env\n")
        git(self.worker, "add", ".gitignore")
        git(self.worker, "-c", "user.name=jane", "-c", "user.email=jane@example.com", "commit", "-q", "-m", "ignore")
        os.makedirs(os.path.join(self.worker, "node_modules", "left-pad"))
        open(os.path.join(self.worker, "node_modules", "left-pad", "index.js"), "w").close()
        open(os.path.join(self.worker, ".env"), "w").write("TOKEN=x\n")
        open(os.path.join(self.worker, "notes.txt"), "w").close()
        got = bosskit.leftovers(self.worker, "feat/x")
        self.assertEqual([g.split(" ")[0] for g in got], ["uncommitted:", "ignored:", "unpushed:"])
        self.assertIn("ignored: .env", got)
        self.assertIn("?? notes.txt", got[0])
        self.assertIn("unpushed: origin/gone not found, cannot tell", bosskit.leftovers(self.worker, "gone"))


class Verify(unittest.TestCase):
    def test_junk_guard_flags_committed_junk_only(self):
        verify = load_script("verify")
        repo = tempfile.mkdtemp()
        git(repo, "init", "-q")
        for path in ("ok.py", ".DS_Store", "pkg/__pycache__/m.cpython-312.pyc", "default.profraw", "docs/a.tmp", "docs/tmp.md"):
            os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
            open(os.path.join(repo, path), "w").close()
        git(repo, "add", "-f", ".")
        self.assertEqual(sorted(verify.junk(verify.git(repo, "ls-files").splitlines())),
                         [".DS_Store", "default.profraw", "docs/a.tmp", "pkg/__pycache__/m.cpython-312.pyc"])
        self.assertEqual(verify.junk(["bin/verify", "README.md"]), [])


if __name__ == "__main__":
    unittest.main()


class Close(unittest.TestCase):
    def test_dead_panes_are_terminal_panes_whose_session_ended(self):
        mod = load_script("boss-close")
        panes = [("pane-a", "t-live"), ("pane-b", "t-dead"), ("pane-c", None)]
        self.assertEqual(mod.dead_panes(panes, {"t-live"}), ["pane-b"])

    def test_resolve_counts_a_terminal_listed_as_session_and_pane_once(self):
        mod = load_script("boss-close")
        self.assertEqual(mod.resolve("0a41", ["0a419636-x", "0a419636-x", "ffff"]), "0a419636-x")

    def test_no_args_prints_usage_and_fails(self):
        r = subprocess.run([os.path.join(BIN, "boss-close")], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Session ended", r.stdout)

