"""Manual mode: the user works by hand in a worker's session; the boss knows, steers by note, and its watcher waits.

Run: python3 -m unittest discover -s tests
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from test_kit import BIN, Home, deck_json, git, load_script, stub_tools  # noqa: F401
import bosshost  # noqa: E402
import bosskit  # noqa: E402

WS = "1a2b3c4d-0000-4000-8000-000000000001"


HOOK = [sys.executable, os.path.join(BIN, "boss-deck-data.py"), "--prompt"]


def hook_env(t):
    """The hook's env: the test home and fake host, without this machine's own session env."""
    kit_hosts = os.path.join(os.path.dirname(BIN), "hosts")
    with mock.patch.dict(os.environ, {"BOSS_HOST_PATH": kit_hosts}):
        ours = {v for m in bosshost.plugins().values() for v in m["session_env"] + m["terminal_env"]}
    env = {k: v for k, v in stub_tools(t.tmp, t.fixdir).items() if k not in ours | {"BOSS_SESSION_ID"}}
    env["BOSS_HOME"] = t.home
    return env


class ManualHome(Home):
    """widgets with a ledger row for WS (no Boss cell: the live main boss ws-main dispatched it), a worktree, the fake host."""

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        self.deck = load_script("boss-deck-data.py")
        open(os.path.join(self.home, "widgets", "ledger.md"), "w").write(
            "## Dispatches 2026-01-02\n\n| Date | Task | Workspace | Model | Status | Proof | Boss |\n|---|---|---|---|---|---|---|\n"
            f"| 2026-01-02 | fix-42: retry webhooks | {WS[:8]} | mid | DISPATCHED | | |\n")
        bosskit.save_json(os.path.join(self.home, "bosses.json"), {"ws-main": {"project": "widgets", "workspace": "ws-main", "heartbeat": time.time()}})
        self.bdir = os.path.join(self.home, "widgets", "bosses", "ws-main")
        os.makedirs(self.bdir)
        self.boss = bosskit.SimpleNamespace(bdir=self.bdir)
        json.dump([{"id": WS, "worktreePath": self.wt}], open(os.path.join(self.fixdir, "list.json"), "w"))
        json.dump({"workspaces": [{"id": WS, "name": "webhooks", "terminals": []}]}, open(os.path.join(self.fixdir, "snapshot.json"), "w"))

    def row(self, cell=WS[:8], boss=""):
        open(os.path.join(self.home, "widgets", "ledger.md"), "w").write(
            "## Dispatches 2026-01-02\n\n| Date | Task | Workspace | Model | Status | Proof | Boss |\n|---|---|---|---|---|---|---|\n"
            f"| 2026-01-02 | fix-42: retry webhooks | {cell} | mid | DISPATCHED | | {boss} |\n")

    def ev(self, at, stage, note=""):
        bosskit.add_event(self.boss, WS, stage, note, now=at)

    def manual(self):
        return [(e["at"], e["note"]) for e in bosskit.events(self.bdir) if e["stage"] == "manual"]

    def prompt(self, text, at):
        return self.deck.prompt_hook(self.home, WS, text, now=at)

    def dispatch(self, at=900, prompt="Repo acme/widgets. Task id: fix-42 ..."):
        """boss-host create's two events, then the dispatch prompt reaching the hook."""
        self.ev(at, "brief", prompt)
        self.ev(at, "sent", "fix-42")
        self.prompt(prompt, at + 50)

    def status(self):
        return json.load(open(os.path.join(self.wt, ".boss-worker", "status.json")))


class PromptHook(ManualHome):
    def test_the_boss_prompts_are_told_from_the_users_own(self):
        self.dispatch()  # the dispatch prompt matches create's `brief`
        self.ev(1000, "msg", "also cover 429 retries, then rebase on main")
        self.prompt("also cover  429 retries,\nthen rebase on main", 1001)  # boss-host send's text, as typed
        self.assertEqual(self.manual(), [])
        self.assertNotIn("mode", self.status())
        self.prompt("why does the retry loop spin on a 500?", 1100)
        self.assertEqual(self.manual(), [(1100, "why does the retry loop spin on a 500?")])
        self.assertEqual(self.status()["mode"], "manual")

    def test_one_manual_event_per_burst(self):
        self.dispatch()
        for at in (1000, 1300, 2000):  # under 30 min apart: one burst
            self.prompt(f"look at line {at}", at)
        self.prompt("back after lunch: try the queue", 2000 + self.deck.BURST_S + 1)
        self.ev(5000, "msg", "status?")
        self.prompt("status?", 5001)  # a boss prompt ends the burst
        self.prompt("one more thing", 5100)
        self.assertEqual([at for at, _ in self.manual()], [1000, 2000 + self.deck.BURST_S + 1, 5100])

    def test_status_keeps_the_panes_progress_and_the_pane_keeps_the_mode(self):
        self.dispatch()
        self.deck.write_status(self.wt, json.dumps({"tasks_done": 1, "tasks_total": 3, "current": "tests"}), now=960)
        self.prompt("hand-check the parser", 1000)
        self.deck.write_status(self.wt, json.dumps({"tasks_done": 2, "tasks_total": 3, "current": "tests"}), now=1010)
        s = self.status()
        self.assertEqual((s["mode"], s["tasks_done"]), ("manual", 2))

    def test_the_pane_and_the_hook_take_turns_on_status_json(self):
        self.dispatch()
        path = os.path.join(self.wt, ".boss-worker", "status.json")
        for write in (lambda: self.deck.write_status(self.wt, json.dumps({"tasks_done": 1, "tasks_total": 3}), now=960),
                      lambda: self.prompt("hand-check the parser", 1000)):
            with bosskit.locked(path):  # the other writer is mid read-modify-replace
                t = threading.Thread(target=write)
                t.start()
                t.join(0.3)
                self.assertTrue(t.is_alive(), "wrote status.json without the lock")
            t.join()
        self.assertEqual((self.status()["mode"], self.status()["tasks_done"]), ("manual", 1))

    def test_the_worktree_lookup_is_short_and_cached(self):
        host = bosshost.get({}, "fake")
        real, got = host.worktree, []
        host.worktree = lambda ws, timeout=None: got.append(timeout) or real(ws)
        with mock.patch.object(self.deck.bosshost, "get", lambda *a: host):
            self.dispatch()
            os.remove(os.path.join(self.fixdir, "list.json"))  # the host stops answering
            self.prompt("hand-check the parser", 1000)
        self.assertEqual(got, [self.deck.HOOK_HOST_S])  # one capped call, then the cache
        self.assertEqual(self.status()["mode"], "manual")

    def test_only_the_dispatched_terminal_counts(self):
        self.row(f"{WS[:8]} / 5e6f")
        w = load_script("boss-host")
        with mock.patch("sys.stdout"):
            w.main(["note", WS, "--text", "fyi"])
        env = {**hook_env(self), "FAKE_SESSION": WS}
        hook = lambda term, text: subprocess.run(HOOK, input=json.dumps({"prompt": text}), capture_output=True, text=True,
                                                 env={**env, "FAKE_TERMINAL": term} if term else env)
        self.assertEqual(hook("9a9a0000-0000", "an unrelated session in the same workspace").stdout, "")
        self.assertEqual(self.manual(), [])
        self.assertIn("fyi", hook("5e6f0000-0000", "the worker's own session").stdout)
        self.assertEqual([n for _, n in self.manual()], ["the worker's own session"])
        self.assertEqual(hook("", "no terminal id: today's behaviour").returncode, 0)

    def test_no_dispatch_row_does_nothing(self):
        self.assertEqual(self.deck.prompt_hook(self.home, "9f9f9f9f-0000", "hi", now=1000), "")
        self.assertFalse(os.path.exists(os.path.join(self.wt, ".boss-worker")))

    def test_the_dispatch_prompt_that_beat_the_ledger_row_leaves_the_users_first_prompt_manual(self):
        # create starts the agent before it writes the row: the dispatch prompt's hook found no row and did nothing
        self.ev(900, "brief", "Repo acme/widgets. Task id: fix-42 ...")
        self.ev(900, "sent", "fix-42")
        self.prompt("what is this repo's test command?", 2000)  # the user's own first prompt
        self.assertEqual(self.manual(), [(2000, "what is this repo's test command?")])

    def test_a_boss_message_counts_once_and_not_days_later(self):
        self.dispatch()
        self.ev(1000, "msg", "status?")
        self.prompt("status?", 1001)
        self.prompt("status?", 1100)  # the user typing the same words: the message was already used
        self.assertEqual([at for at, _ in self.manual()], [1100])
        self.ev(5000, "msg", "rebase on main")
        self.prompt("rebase on main", 5000 + self.deck.MSG_TTL_S + 1)  # never delivered as a prompt; the user, a day on
        self.assertEqual([at for at, _ in self.manual()], [1100, 5000 + self.deck.MSG_TTL_S + 1])

    def test_an_event_after_the_burst_starts_a_new_one(self):
        self.dispatch()
        self.prompt("dig into the parser", 1000)
        self.ev(1200, "BLOCKED", "waiting on input")  # the watcher fired: the newest event is no longer manual
        self.prompt("yes, allow it", 1300)  # within 30 min, but the re-armed watcher needs a fresh manual event
        self.assertEqual([at for at, _ in self.manual()], [1000, 1300])

    def test_the_status_check_is_the_boss_prompt(self):
        self.dispatch()
        ask = load_script("boss-status-ask")
        host = bosshost.get({}, "fake")
        with mock.patch.object(ask.bosshost, "get", lambda *a: host):
            ask.main([WS, "-"])
        self.prompt(ask.text(), int(time.time()))  # as typed into the worker
        self.assertEqual(self.manual(), [])

    def test_the_worktree_is_the_hosts_never_the_prompts_cwd(self):
        self.dispatch()
        other = os.path.join(self.tmp, "other")  # another checkout the session cd'd into
        os.makedirs(other)
        git(other, "init", "-q")
        env = hook_env(self)
        out = subprocess.run(HOOK, input=json.dumps({"prompt": "hand-check", "cwd": other}), capture_output=True, text=True,
                             env={**env, "FAKE_SESSION": WS})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.status()["mode"], "manual")
        self.assertFalse(os.path.exists(os.path.join(other, ".boss-worker")))
        self.assertNotIn(".boss-worker", open(os.path.join(other, ".git", "info", "exclude")).read())


class Notes(ManualHome):
    def note(self, text):
        w = load_script("boss-host")
        with mock.patch("sys.stdout"):
            self.assertEqual(w.main(["note", WS, "--text", text]), 0)

    def test_a_note_reaches_the_next_prompt_once_and_is_marked_read(self):
        self.dispatch()
        self.note("fix-43 changes the retry table: keep the old column")
        time.sleep(0.001)
        self.note("no rush")
        box = os.path.join(self.wt, ".boss-worker", "inbox")
        self.assertEqual(len([f for f in os.listdir(box) if f.endswith(".md")]), 2)
        ctx = self.prompt("let's dig into the queue", 1000)
        self.assertTrue(ctx.startswith("2 notes from boss"), ctx)
        self.assertIn("the user's own instructions in this session win", ctx)
        self.assertLess(ctx.index("keep the old column"), ctx.index("no rush"))  # oldest first
        self.assertEqual(sorted(os.listdir(box)), ["read"])
        self.assertEqual(len(os.listdir(os.path.join(box, "read"))), 2)
        self.assertEqual(self.prompt("next", 1010), "")
        self.assertEqual(bosskit.events(self.bdir)[-1]["stage"], "manual")  # a note is no event: the newest stays manual

    def test_a_note_never_types_into_the_terminal(self):
        self.note("fyi")
        self.assertFalse(os.path.exists(os.path.join(self.fixdir, "calls")))  # the fake host logs every send there

    def test_a_note_resolves_the_worktree_from_the_listing_not_the_hosts_worker(self):
        host = bosshost.get({}, "fake")
        host.worker = lambda wid: {"id": WS, "name": "webhooks", "terminals": []}  # superset's snapshot: no worktree in it
        w = load_script("boss-host")
        with mock.patch.object(w.bosshost, "get", lambda *a: host), mock.patch("sys.stdout"):
            self.assertEqual(w.main(["note", WS, "--text", "fyi"]), 0)
        self.assertEqual(len(os.listdir(os.path.join(self.wt, ".boss-worker", "inbox"))), 1)

    def test_a_note_another_prompt_took_first_is_skipped(self):
        self.note("first")
        time.sleep(0.001)
        self.note("second")
        box = os.path.join(self.wt, ".boss-worker", "inbox")
        real, calls = os.replace, []

        def racing(src, dst):  # the other prompt's hook takes "second" while this one moves "first"
            calls.append(src)
            if len(calls) == 1:
                b = sorted(f for f in os.listdir(box) if f.endswith(".md"))[1]
                real(os.path.join(box, b), os.path.join(box, "read", b))
            real(src, dst)
        with mock.patch.object(self.deck.os, "replace", racing):
            ctx = self.deck.take_notes(self.wt)
        self.assertTrue(ctx.startswith("1 note from boss"), ctx)
        self.assertIn("first", ctx)
        self.assertEqual(len(os.listdir(os.path.join(box, "read"))), 2)

    def test_bad_inbox_entries_are_skipped_and_the_rest_delivered(self):
        box = os.path.join(self.wt, ".boss-worker", "inbox")
        os.makedirs(os.path.join(box, "2.md"))  # a directory
        for n, body in (("1.md", "first"), ("3.md", "locked"), ("4.md", "last")):
            open(os.path.join(box, n), "w").write(body)
        os.chmod(os.path.join(box, "3.md"), 0)
        self.addCleanup(os.chmod, os.path.join(box, "3.md"), 0o644)
        ctx = self.deck.take_notes(self.wt)
        self.assertTrue(ctx.startswith("2 notes from boss"), ctx)
        self.assertIn("first | last", ctx)
        self.assertEqual(sorted(os.listdir(box)), ["2.md", "3.md", "read"])

    def test_a_short_prefix_is_resolved_before_the_owner_check(self):
        self.row(boss="ws-other")  # another boss dispatched it
        w = load_script("boss-host")
        with self.assertRaises(SystemExit) as e, mock.patch("sys.stdout"):
            w.main(["note", WS[:4], "--text", "fyi"])
        self.assertIn("owned by ws-other", str(e.exception))
        self.assertFalse(os.path.exists(os.path.join(self.wt, ".boss-worker", "inbox")))

    def test_the_hook_prints_the_notes_as_context_and_stays_quiet_outside_a_worker(self):
        self.note("fyi: CI is flaky on node 20")
        env = hook_env(self)
        hook = HOOK
        inp = json.dumps({"prompt": "hi", "cwd": self.wt})
        quiet = subprocess.run(hook, input=inp, capture_output=True, text=True, env=env)  # no host session: nothing
        self.assertEqual((quiet.returncode, quiet.stdout), (0, ""))
        out = subprocess.run(hook, input=inp, capture_output=True, text=True, env={**env, "FAKE_SESSION": WS})
        got = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(got["hookEventName"], "UserPromptSubmit")
        self.assertIn("CI is flaky on node 20", got["additionalContext"])
        bad = subprocess.run(hook, input="not json", capture_output=True, text=True, env={**env, "FAKE_SESSION": WS})
        self.assertEqual((bad.returncode, bad.stdout), (0, ""))  # never fails the prompt


class SendLogsFirst(ManualHome):
    def stages(self):
        return [e["stage"] for e in bosskit.events(bosskit.load().bdir)]  # main() resolves the boss from the cwd

    def test_the_msg_event_is_logged_before_the_text_is_typed(self):
        w = load_script("boss-host")
        host = bosshost.get({}, "fake")
        seen = []
        host.send = lambda wid, text, term=None: seen.append(self.stages())
        with mock.patch.object(w.bosshost, "get", lambda *a: host):
            self.assertEqual(w.main(["send", WS, "--text", "also cover 429"]), 0)
        self.assertEqual(seen, [["msg"]])

    def test_a_failed_send_takes_its_msg_back(self):
        w, ask = load_script("boss-host"), load_script("boss-status-ask")
        host = bosshost.get({}, "fake")
        host.send = mock.Mock(side_effect=bosshost.Unsupported("fake: the terminal is gone"))
        bosskit.add_event(bosskit.load(), WS, "sent", "fix-42")
        with mock.patch.object(w.bosshost, "get", lambda *a: host), mock.patch("sys.stderr"):
            self.assertEqual(w.main(["send", WS, "--text", "also cover 429"]), 3)
        with mock.patch.object(ask.bosshost, "get", lambda *a: host), self.assertRaises(bosshost.Unsupported):
            ask.main([WS, "-"])
        self.assertEqual(self.stages(), ["sent"])

    def test_an_unwritable_event_log_never_stops_the_send(self):
        os.makedirs(os.path.join(bosskit.load().bdir, "events.jsonl"))  # an event log that cannot be appended to
        w, ask = load_script("boss-host"), load_script("boss-status-ask")
        host = bosshost.get({}, "fake")
        host.send = mock.Mock()
        with mock.patch.object(w.bosshost, "get", lambda *a: host):
            self.assertEqual(w.main(["send", WS, "--text", "also cover 429"]), 0)
        with mock.patch.object(ask.bosshost, "get", lambda *a: host):
            ask.main([WS, "-"])
        self.assertEqual(host.send.call_count, 2)

    def test_create_logs_the_prompts_head_before_sent(self):
        w = load_script("boss-host")
        with mock.patch("sys.stdout"):
            w.main(["create", "--repo", "acme/widgets", "--branch", "fix/42", "--task", "fix-42", "--prompt", "Repo acme/widgets.\n  Task id: fix-42"])
        evs = [(e["stage"], e["note"]) for e in bosskit.events(bosskit.load().bdir)]
        self.assertEqual(evs, [("brief", "Repo acme/widgets. Task id: fix-42"), ("sent", "fix-42")])


class WatchManual(ManualHome):
    """boss-host watch: one wake per manual burst, no idle fire while the newest event is manual, envelope/blocked still fire."""

    def setUp(self):
        super().setUp()
        self.w = load_script("boss-host")
        self.ctx = bosskit.load(self.wt)
        self.mine = bosskit.SimpleNamespace(bdir=self.ctx.bdir)
        self.host = bosshost.get({}, "other")

    def run_watch(self, states, on_poll=None, polls=20):
        st, n = iter(states), [0]

        def worker(wid):
            n[0] += 1
            if on_poll:
                on_poll(n[0])
            s = next(st)
            return {} if s == "gone" else {"terminals": [{"agent": {"state": s}}]}
        self.host.messages = lambda boss, wid: []
        self.host.worker = worker
        out = []
        with mock.patch.object(self.w.time, "sleep", lambda s: None):
            self.w.watch(self.ctx, self.host, WS, "", polls=polls, out=out.append)
        return out[0]

    def test_a_new_manual_burst_wakes_the_boss_once(self):
        bosskit.add_event(self.mine, WS, "sent", "fix-42", now=100)
        got = self.run_watch(["working"] * 20, lambda i: i == 2 and bosskit.add_event(self.mine, WS, "manual", "why does it spin?", now=200))
        self.assertTrue(got.startswith("WORKER MANUAL"), got)
        self.assertIn("why does it spin?", got)
        # re-armed: the same burst never fires again, and an idle user session is not "idle without envelope"
        self.assertEqual(self.run_watch(["idle"] * 20), "TIMEOUT")

    def test_a_burst_at_the_baselines_second_or_before_the_watcher_started_still_wakes(self):
        bosskit.add_event(self.mine, WS, "sent", "fix-42", now=100)
        got = self.run_watch(["working"] * 20, lambda i: i == 2 and bosskit.add_event(self.mine, WS, "manual", "same second", now=100))
        self.assertTrue(got.startswith("WORKER MANUAL"), got)
        bosskit.add_event(self.mine, WS, "msg", "status?", now=200)
        bosskit.add_event(self.mine, WS, "manual", "landed while the boss re-armed", now=300)
        self.assertTrue(self.run_watch(["working"] * 20).startswith("WORKER MANUAL"))
        self.assertEqual(self.run_watch(["idle"] * 20), "TIMEOUT")

    def test_blocked_gone_and_idle_after_the_burst_still_fire(self):
        bosskit.add_event(self.mine, WS, "manual", "dig in", now=200)
        bosskit.manual_wake(self.ctx, WS)  # an earlier watcher woke the boss for it
        self.assertTrue(self.run_watch(["idle", "blocked"]).startswith("AGENT BLOCKED"))
        bosskit.add_event(self.mine, WS, "manual", "dig in", now=300)
        bosskit.manual_wake(self.ctx, WS)
        self.assertTrue(self.run_watch(["gone"]).startswith("WORKER GONE"))
        bosskit.add_event(self.mine, WS, "msg", "status?", now=400)  # the boss spoke since: idle counts again
        self.assertTrue(self.run_watch(["idle"] * 20).startswith("AGENT IDLE WITHOUT ENVELOPE"))

    def test_boss_event_manual_says_new_once_then_on(self):
        bosskit.add_event(self.mine, WS, "sent", "fix-42", now=100)
        bosskit.add_event(self.mine, WS, "manual", "dig in", now=200)
        bosskit.add_event(self.mine, "ffffffff", "sent", "other", now=300)
        ask = lambda ws: subprocess.run([os.path.join(BIN, "boss-event"), "--manual", ws], cwd=self.wt, capture_output=True, text=True)
        self.assertEqual([ask(WS[:8]).stdout, ask(WS[:8]).stdout, ask("ffffffff").stdout], ["new dig in\n", "on\n", ""])


class DeckStage(unittest.TestCase):
    def setUp(self):
        self.deck = load_script("boss-deck-data.py")

    def stage(self, *evs, ledger="DISPATCHED", state="idle"):
        return self.deck.stage(state, ledger, None, [{"at": a, "stage": s, "note": ""} for a, s in evs], 0)

    def test_the_newest_manual_event_is_the_manual_stage(self):
        self.assertEqual(self.stage((100, "sent"), (200, "manual")), "manual")
        self.assertEqual(self.stage((100, "sent"), (200, "manual"), state="working"), "manual")
        self.assertEqual(self.stage((100, "sent"), (200, "manual"), (300, "msg")), "working")
        self.assertEqual(self.stage((100, "sent"), (200, "manual"), (300, "DONE")), "checking")
        self.assertEqual(self.stage((200, "manual"), (300, "sent")), "working")  # a manual burst before this dispatch


if __name__ == "__main__":
    unittest.main()
