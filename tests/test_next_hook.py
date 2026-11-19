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
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(inp), capture_output=True, text=True, env=env)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        return json.loads(out.stdout) if out.stdout.strip() else None

    def test_a_shorthand_last_your_move_blocks_with_the_reason(self):
        got = self.run_hook("Checking.", "## Status\n- CI green on #57\n\n**Your move:** merge #57 then #63")
        self.assertEqual(got["decision"], "block")
        self.assertIn("merge #57 then #63", got["reason"])
        self.assertIn("4 words", got["reason"])
        self.assertEqual(self.run_hook("- Your move: (0)")["decision"], "block")

    def test_a_standalone_or_nothing_needed_line_and_no_line_pass(self):
        self.assertIsNone(self.run_hook("Status...", GOOD))
        self.assertIsNone(self.run_hook("Your move: nothing needed."))
        self.assertIsNone(self.run_hook("All quiet.\nYour move: nothing for you now, both workers are still running."))
        self.assertIsNone(self.run_hook("Done, no decisions open."))  # the old reply's "go 1" is not this reply

    def test_only_the_last_your_move_line_counts(self):
        self.assertIsNone(self.run_hook("Your move: go 1", GOOD))
        self.assertEqual(self.run_hook(GOOD, "Your move: go 1")["decision"], "block")

    def test_the_hook_field_wins_over_the_transcript(self):
        self.assertEqual(self.run_hook(GOOD, last_assistant_message="Your move: kit #34")["decision"], "block")

    def test_not_a_boss_a_second_stop_or_bad_input_allows(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.assertIsNone(self.run_hook("Your move: go 1", cwd=other))
        self.assertIsNone(self.run_hook("Your move: go 1", stop_hook_active=True))
        out = subprocess.run([sys.executable, HOOK], input="{", capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
