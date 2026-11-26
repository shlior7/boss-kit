"""The boss plugin's Stop hook (bin/boss-next-hook) on transcript JSON: a shorthand "Your move" line blocks, others pass.

Run: python3 -m unittest discover -s tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "boss-next-hook")
GOOD = 'Your move: reply "merge 38" to merge the janitor cleanup PR (#38), which is verified; on no it stays open.'


class NextHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wt = os.path.join(self.tmp, "wt")
        os.makedirs(self.wt)
        subprocess.run(["git", "-C", self.wt, "init", "-q"], check=True)
        with open(os.path.join(self.wt, "CLAUDE.local.md"), "w") as f:
            f.write("# Boss workspace\n")
        self.transcript = os.path.join(self.tmp, "t.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, *replies, cwd=None, **extra):
        """Write a transcript: a prompt, an old reply, a new prompt, then *replies* split by a tool round trip."""
        entries = [{"type": "user", "message": {"role": "user", "content": "status"}},
                   {"type": "assistant", "message": {"content": [{"type": "text", "text": "Your move: go 1"}]}},
                   {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "status again"}]}}]
        for r in replies:
            entries += [{"type": "assistant", "message": {"content": [{"type": "text", "text": r}, {"type": "tool_use", "id": "t"}]}},
                        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}]
        with open(self.transcript, "w") as f:
            f.write("\n".join(json.dumps(e) for e in entries) + "\nnot json\n")
        inp = {"hook_event_name": "Stop", "transcript_path": self.transcript, "cwd": cwd or self.wt, "stop_hook_active": False, **extra}
        env = {k: v for k, v in os.environ.items() if k != "BOSS_KIT_HOME"}
        env.update(getattr(self, "extra_env", {}))
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(inp), capture_output=True, text=True, env=env)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        return json.loads(out.stdout) if out.stdout.strip() else None

    def test_a_shorthand_last_your_move_blocks_with_the_reason(self):
        got = self.run_hook("Checking.", "## Status\n- CI green on #57\n\n**Your move:** merge #57 then #63")
        self.assertEqual(got["decision"], "block")
        self.assertIn("merge #57 then #63", got["reason"])
        self.assertIn("4 words", got["reason"])
        self.assertIn("whole reply again", got["reason"])  # a resend that is only the line drops the report
        self.assertEqual(self.run_hook("- Your move: (0)")["decision"], "block")

    def test_a_standalone_or_nothing_needed_line_and_no_line_pass(self):
        self.assertIsNone(self.run_hook("Status...", GOOD))
        self.assertIsNone(self.run_hook("Your move: nothing needed."))
        self.assertIsNone(self.run_hook("All quiet.\nYour move: nothing for you now, both workers are still running."))
        self.assertIsNone(self.run_hook("Done, no decisions open."))  # the old reply's "go 1" is not this reply

    def test_only_the_final_assistant_message_is_linted(self):
        # an earlier message's line, then a tool result, then a final message without one: nothing to check
        self.assertIsNone(self.run_hook("Your move: go 1", "Done, no decisions open."))
        self.assertEqual(self.run_hook("Checking.", "Your move: go 1")["decision"], "block")

    def test_entries_of_one_message_are_read_together(self):
        entries = [{"type": "user", "message": {"content": "status"}},
                   {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Your move: go 1"}]}},
                   {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "More on that."}]}}]
        with open(self.transcript, "w") as f:
            f.write("\n".join(json.dumps(e) for e in entries) + "\n")
        out = subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                             input=json.dumps({"transcript_path": self.transcript, "cwd": self.wt}))
        self.assertEqual(json.loads(out.stdout)["decision"], "block")

    def test_only_the_last_your_move_line_counts(self):
        self.assertIsNone(self.run_hook("Your move: go 1", GOOD))
        self.assertEqual(self.run_hook(GOOD, "Your move: go 1")["decision"], "block")

    def test_the_hook_field_wins_over_the_transcript(self):
        self.assertEqual(self.run_hook(GOOD, last_assistant_message="Your move: kit #34")["decision"], "block")

    def test_not_a_boss_or_bad_input_allows(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.assertIsNone(self.run_hook("Your move: go 1", cwd=other))

    def test_a_rewrite_is_checked_again_up_to_three_blocks_then_allowed(self):
        sid = {"session_id": f"t{os.getpid()}"}
        self.assertEqual(self.run_hook("Your move: go 1", **sid)["decision"], "block")
        self.assertEqual(self.run_hook("Your move: go 2", stop_hook_active=True, **sid)["decision"], "block")
        self.assertEqual(self.run_hook("Your move: go 3", stop_hook_active=True, **sid)["decision"], "block")
        self.assertIsNone(self.run_hook("Your move: go 4", stop_hook_active=True, **sid))
        self.assertEqual(self.run_hook("Your move: go 5", **sid)["decision"], "block")  # a new reply starts over
        self.assertIsNone(self.run_hook(GOOD, stop_hook_active=True, **sid))
        out = subprocess.run([sys.executable, HOOK], input="{", capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, ""))


class UnreadMail(NextHook):
    """A mail that landed while the boss was busy (its wake skipped) blocks the next stop once, never twice for one id."""

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, "boss")
        self.inbox = os.path.join(self.home, "widgets", "bosses", "b1", "inbox")
        os.makedirs(os.path.join(self.inbox, "done"))
        with open(os.path.join(self.home, "widgets", "config.json"), "w") as f:
            json.dump({"repo": "acme/widgets"}, f)
        self.extra_env = {"BOSS_HOME": self.home, "BOSS_PROJECT": "widgets", "BOSS_SESSION_ID": "b1"}
        for k in ("BOSS_HOST_KIND",):
            self.extra_env.setdefault(k, "")

    def mail(self, mid, kind="question", frm="gadgets", **extra):
        with open(os.path.join(self.inbox, mid + ".json"), "w") as f:
            json.dump({"id": mid, "kind": kind, "from_project": frm, "from_boss": "x", "subject": "secret subject",
                       "body": "secret body", **extra}, f)

    def test_unread_mail_blocks_once_with_the_count_and_not_again_for_the_same_id(self):
        self.mail("20260101-000000-aaaaaa")
        self.mail("20260101-000001-bbbbbb", kind="fyi", frm="kit")
        got = self.run_hook("Done.")
        self.assertEqual(got["decision"], "block")
        self.assertEqual(got["reason"], "2 unread boss mail: question from gadgets, fyi from kit; read it with boss-mail inbox and handle it")
        self.assertNotIn("secret", got["reason"])  # no subject or body
        self.assertIsNone(self.run_hook("Done."))  # same ids, read but never marked done: not trapped
        self.mail("20260101-000002-cccccc", frm="gadgets")
        self.assertIn("1 unread boss mail: question from gadgets", self.run_hook("Done.")["reason"])  # a new id raises again

    def test_never_a_second_block_in_the_same_stop_and_read_mail_is_not_raised(self):
        self.mail("20260101-000000-aaaaaa")
        self.assertIsNone(self.run_hook("Done.", stop_hook_active=True))
        self.assertEqual(self.run_hook("Done.")["decision"], "block")  # a stop that is not a re-run does raise it
        self.mail("20260101-000001-bbbbbb", read_at="2026-01-01T00:00:00+0000")
        self.assertIsNone(self.run_hook("Done."))

    def test_no_mail_or_not_a_boss_allows(self):
        self.assertIsNone(self.run_hook("Done."))
        self.mail("20260101-000000-aaaaaa")
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.assertIsNone(self.run_hook("Done.", cwd=other))


if __name__ == "__main__":
    unittest.main()
