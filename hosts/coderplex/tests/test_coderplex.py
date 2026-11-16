"""The coderplex host plugin: sessions as workers, messages as the envelope channel, against a fake `coderplex-ctl`."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path[:0] = [os.path.join(KIT, "bin"), os.path.join(KIT, "tests")]
import bosshost  # noqa: E402
from kit_testing import fake_cli  # noqa: E402


class Coderplex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"BOSS_HOME": os.path.join(self.tmp, "boss"), "BOSS_HOST_PATH": ""})
        self.env.start()
        self.calls = os.path.join(self.tmp, "calls")

    def tearDown(self):
        self.env.stop()

    def ctl(self, cases):
        stubs = fake_cli(self.tmp, "coderplex-ctl", cases)
        p = mock.patch.dict(os.environ, {"PATH": f"{stubs}:/usr/bin:/bin"})
        p.start()
        self.addCleanup(p.stop)
        return bosshost.get({}, "coderplex")

    def logged(self):
        return open(self.calls).read().splitlines() if os.path.exists(self.calls) else []

    def test_sessions_are_workers(self):
        show = lambda sid, phase, mode="claude": json.dumps({"sessions": [{"id": sid, "title": f"t-{sid}", "branch": f"b-{sid}", "agentMode": mode,
                                                                            "agentPhase": phase, "worktree": f"/wt/{sid}", "section": "UI" if sid == "aaaa1111" else None}]})
        h = self.ctl({"sessions ls": json.dumps({"sessions": [{"id": "aaaa1111", "branch": "b-aaaa1111"}, {"id": "bbbb2222"}, {"id": "cccc3333"}, {"id": "dddd4444"}]}),
                      "sessions show aaaa1111": show("aaaa1111", "working"), "sessions show bbbb2222": show("bbbb2222", "permission"),
                      "sessions show cccc3333": show("cccc3333", None, "shell"), "sessions show dddd4444": show("dddd4444", "review")})
        ws = {w["id"]: w for w in h.workers(["aaaa1111", "bbbb2222", "cccc3333", "dddd4444"])}
        self.assertEqual([w["id"] for w in h.workers(["aaaa1111"])], ["aaaa1111"])  # only the dispatched ones are read in full
        self.assertEqual(h.by_branch("b-aaaa1111"), {"id": "aaaa1111", "worktree": "/wt/aaaa1111"})
        h.send("aaaa1111", "hi there")
        state = lambda sid: ws[sid]["terminals"][0]["agent"]["state"]
        self.assertEqual((state("aaaa1111"), state("bbbb2222"), state("dddd4444")), ("working", "blocked", "idle"))  # review: its turn ended
        self.assertEqual((ws["aaaa1111"]["tags"], ws["aaaa1111"]["worktree"]), (["UI"], "/wt/aaaa1111"))
        self.assertEqual(ws["cccc3333"]["terminals"], [])  # a shell session has no agent
        self.assertIn("coderplex-ctl sessions send aaaa1111 --text hi there", self.logged())
        self.assertNotIn("--ttl", h.archive_cmd("aaaa1111"))
        self.assertIsNone(h.screen("aaaa1111", "agent-1"))

    def test_create_goes_to_the_local_target_and_files_the_folder(self):
        h = self.ctl({"sessions create": json.dumps({"created": {"id": "f00d0001"}})})
        self.assertEqual(h.create("acme/boss-kit", "probe", "do it", model="haiku", name="probe", folder="Ops"), "f00d0001")
        self.assertIn("coderplex-ctl sessions create --target local --repo boss-kit --branch probe --agent claude --prompt do it --json "
                      "--model haiku --name probe", self.logged())
        self.assertIn("coderplex-ctl sessions move f00d0001 --section Ops", self.logged())

    def test_messages_and_the_dispatch_time(self):
        body = os.path.join(self.tmp, "m3.md")
        open(body, "w").write("BOSS_WORKER_DONE\ntask: fix-1\nsummary: ok")
        h = self.ctl({"sessions messages b0550000 --json": json.dumps({"messages": [
            {"messageId": "m0", "from": {"session": "b0550000"}, "to": {"session": "aaaa1111"}, "createdAt": 5_000_000},
            {"messageId": "m1", "from": {"session": "aaaa1111"}, "to": {"session": "ffff0000"}, "body": {"text": "not to me"}},
            {"messageId": "m2", "from": {"session": "cccc2222"}, "to": {"session": "b0550000"}, "body": {"text": "another worker"}},
            {"messageId": "m3", "from": {"session": "aaaa1111"}, "to": {"session": "b0550000"}, "body": {"file": body}, "createdAt": 9_000_000}]}),
            "sessions show aaaa1111": json.dumps({"sessions": [{"id": "aaaa1111", "createdAt": "1970-01-01T00:00:02Z"}]})})
        self.assertEqual(h.messages("b0550000", "aaaa1111"), [("m3", "BOSS_WORKER_DONE\ntask: fix-1\nsummary: ok", 9000)])
        self.assertEqual(h.dispatched_at("b0550000", "aaaa1111"), 5000)  # the boss's last message, not the session's creation


if __name__ == "__main__":
    unittest.main()
