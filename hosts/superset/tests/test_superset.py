"""The superset host plugin: the commands boss-kit has always run, against a fake `superset` on PATH."""
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


class Superset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"BOSS_HOME": os.path.join(self.tmp, "boss"), "BOSS_HOST_PATH": ""})
        self.env.start()
        os.environ.pop("BOSS_HOST", None)
        self.calls = os.path.join(self.tmp, "calls")

    def tearDown(self):
        self.env.stop()

    def host(self, cfg, cases):
        stubs = fake_cli(self.tmp, "superset", cases)
        self.path = mock.patch.dict(os.environ, {"PATH": f"{stubs}:/usr/bin:/bin"})
        self.path.start()
        self.addCleanup(self.path.stop)
        return bosshost.get(cfg, "superset")

    def logged(self):
        return open(self.calls).read().splitlines() if os.path.exists(self.calls) else []

    def test_runs_the_same_commands_as_before(self):
        h = self.host({"superset_host": "h1"}, {  # the older top-level key still names the host
            "snapshot --host h1": json.dumps({"workspaces": [{"id": "w1", "name": "cart", "branch": "fix/a", "terminals": [{"id": "t1", "agent": {"state": "idle"}}]}]}),
            "workspaces list --host": json.dumps([{"id": "w1", "tags": "UI, Infra", "worktreePath": "/wt/w1"}]),
            "workspaces list --local": json.dumps([{"id": "w1", "branch": "fix/a", "worktreePath": "/wt/w1"}])})
        ws = h.workers()
        self.assertEqual((ws[0]["tags"], ws[0]["worktree"], ws[0]["terminals"][0]["agent"]["state"]), (["UI", "Infra"], "/wt/w1", "idle"))
        self.assertEqual(h.by_branch("fix/a"), {"id": "w1", "worktree": "/wt/w1"})
        h.send("w1", "hello", "t1")
        h.rename("w1", "BOSS")
        self.assertIn("superset terminals send --workspace w1 --terminal t1 --local --keys ctrl+u", self.logged())
        self.assertIn("superset terminals send --workspace w1 --terminal t1 --local --text hello", self.logged())
        self.assertIn("superset workspaces update w1 --host h1 --name BOSS", self.logged())
        self.assertEqual(h.archive_cmd("w1"), "superset workspaces archive w1 --local")
        self.assertEqual(bosshost.get({"hosts": {"superset": {"host_id": "h2"}}}, "superset").host_id(), "h2")

    def test_host_defaults_to_the_first_host(self):
        self.assertEqual(self.host({}, {"hosts list": json.dumps([{"id": "first"}, {"id": "second"}])}).host_id(), "first")

    def test_create_finds_the_project_by_repo(self):
        h = self.host({}, {"projects list": json.dumps([{"id": "p-other", "repo": "https://github.com/acme/other"},
                                                        {"id": "p-w", "repo": "https://github.com/acme/widgets.git"}]),
                           "workspaces create": json.dumps({"id": "ws-new"})})
        self.assertEqual(h.create("acme/widgets", "fix/a", "do it", model="opus", folder="UI"), "ws-new")
        self.assertIn("superset workspaces create --local --project p-w --branch fix/a --name fix/a --agent claude --prompt do it --json "
                      "--model opus --tag UI", self.logged())

    def test_dead_panes_and_terminal_prefixes(self):
        Host = bosshost.load(bosshost.plugins()["superset"])
        self.assertEqual(Host.dead_panes([("pane-a", "t-live"), ("pane-b", "t-dead"), ("pane-c", None)], {"t-live"}), ["pane-b"])
        self.assertEqual(Host.resolve("0a41", ["0a419636-x", "0a419636-x", "ffff"]), "0a419636-x")

    def test_the_envelope_alias_and_page_links_are_this_hosts(self):
        h = bosshost.get({}, "superset")
        self.assertEqual(h.envelope_prefixes(), ["BOSS", "SUPERSET"])
        self.assertEqual([l for l, _ in h.proof_links()], ["page"])


if __name__ == "__main__":
    unittest.main()
