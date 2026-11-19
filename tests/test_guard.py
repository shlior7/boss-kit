"""bin/boss-guard: the boss plugin's PreToolUse hook, on hook input JSON. Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_kit import BIN, load_script  # noqa: E402

G = load_script("boss-guard")
GUARD = os.path.join(BIN, "boss-guard")

DENIED = [
    "gh pr merge 12", "gh pr merge 12 --squash", "gh pr merge --auto 12", "gh -R acme/w pr merge 12",
    "gh pr close 12", "gh pr edit 12 --base dev", "gh pr edit 12 -B dev", "gh pr edit 12 --base=dev",
    "git push -f", "git push --force origin feat/x", "git push --force-with-lease origin feat/x",
    "git push --force-with-lease=feat/x:abc origin feat/x", "git push -fu origin feat/x", "git push origin +feat/x",
    "git push --mirror", "git push origin main", "git push origin HEAD:main", "git push origin feat/x:refs/heads/main",
    "git push origin :main", "git push --all origin",
    "git rebase main", "git rebase -i HEAD~3", "git rebase --continue", "git -C /r rebase origin/main",
    "git log && git push -f", "cd x; gh pr merge 3", "echo $(gh pr merge 3)", "echo `gh pr close 3`",
    "(git rebase main) | cat", "bash -c 'git push --force'", "rtk git push -f", "FOO=1 /usr/bin/git rebase main",
    "git status\ngh pr merge 4",
]
ALLOWED = [
    "gh pr view 12", "gh pr list --state open", "gh pr checks 12", "gh pr ready 12", "gh pr create --draft",
    "gh pr edit 12 --title x", "gh pr merge-queue", "gh api repos/a/b/pulls/12",
    "git log", "git status", "git push origin feat/x", "git push -u origin feat/x", "git push origin HEAD:feat/x",
    "git push origin feat/main-fix", "git push --dry-run origin feat/x", "git rebase --help", "git rebase -h",
    "git merge origin/main", "git pull --ff-only", "git fetch origin main",
    "git commit -m 'never gh pr merge or git rebase'", "echo \"gh pr merge 1\"",
    "git commit -F - <<'EOF'\ngit rebase main\ngh pr merge 3\nEOF", "grep -n 'git push -f' README.md",
    "bin/boss-merge 12", "bin/boss-sync.py --only=12 --push", "gh pr view 12 && git log --oneline",
    "echo 'unbalanced", "",
]


def deny(cmd, bg=True):
    return G.violation(cmd, "/nonexistent", bg, lambda: "main")


class Rules(unittest.TestCase):
    def test_denied(self):
        for cmd in DENIED:
            self.assertTrue(deny(cmd), cmd)

    def test_look_alikes_pass(self):
        for cmd in ALLOWED:
            self.assertIsNone(deny(cmd), cmd)

    def test_watch(self):
        ok = "bin/boss-host watch ws-1 feat/x"
        self.assertIsNone(deny(ok, bg=True))
        self.assertIn("run_in_background", deny(ok, bg=False))
        self.assertIn("run_in_background", deny(ok + " &", bg=True))
        self.assertIn("run_in_background", deny(ok + " > log 2>&1 &", bg=True))
        self.assertIsNone(deny(ok + " > log 2>&1", bg=True))
        self.assertIsNone(deny("bin/boss-host send ws-1 hi", bg=False))

    def test_reasons_name_rule_and_path(self):
        self.assertIn("bin/boss-merge", deny("gh pr merge 1"))
        self.assertIn("--auto", deny("gh pr merge --auto 1"))
        self.assertIn("boss-sync", deny("git rebase main"))
        self.assertIn("section 3", deny("git push -f"))
        self.assertEqual(deny("git push -f").count("\n"), 0)

    def test_base_check_skipped_without_base(self):
        self.assertIsNone(G.violation("git push origin main", "/x", True, lambda: ""))
        self.assertTrue(G.violation("git push -f", "/x", True, lambda: ""))


class Hook(unittest.TestCase):
    """The script end to end: stdin JSON in, a deny JSON or nothing out."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.boss = os.path.join(self.tmp, "boss-wt")
        self.plain = os.path.join(self.tmp, "plain-wt")
        for d in (self.boss, self.plain):
            os.makedirs(d)
        with open(os.path.join(self.boss, "CLAUDE.local.md"), "w") as f:
            f.write("# Boss workspace\n")
        self.env = {k: v for k, v in os.environ.items() if k != "BOSS_KIT_HOME" and not k.startswith("BOSS_SESSION")}
        self.env.update(HOME=self.tmp, BOSS_HOME=os.path.join(self.tmp, "data"))

    def run_hook(self, cwd, cmd, tool="Bash", bg=False):
        data = {"tool_name": tool, "cwd": cwd, "tool_input": {"command": cmd, "run_in_background": bg}}
        r = subprocess.run([sys.executable, GUARD], input=json.dumps(data), capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_denies_in_boss_session(self):
        out = self.run_hook(self.boss, "gh pr merge 5")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("bin/boss-merge", out["permissionDecisionReason"])
        self.assertEqual(self.run_hook(self.boss, "git push origin main")["permissionDecision"], "deny")

    def test_allows_elsewhere_and_look_alikes(self):
        self.assertIsNone(self.run_hook(self.plain, "gh pr merge 5"))
        self.assertIsNone(self.run_hook(self.plain, "git push origin main"))
        self.assertIsNone(self.run_hook(self.boss, "gh pr view 5"))
        self.assertIsNone(self.run_hook(self.boss, "git push origin feat/x"))
        self.assertIsNone(self.run_hook(self.boss, "gh pr merge 5", tool="Read"))
        self.assertIsNone(self.run_hook(self.boss, "bin/boss-host watch ws feat/x", bg=True))

    def test_bad_input_allows(self):
        r = subprocess.run([sys.executable, GUARD], input="not json", capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
