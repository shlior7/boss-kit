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

    def test_worktree_comes_from_the_workspaces_list_not_the_snapshot(self):
        h = self.host({"host_id": "h1"}, {
            "snapshot": json.dumps({"workspaces": [{"id": "w1", "name": "cart", "terminals": []}]}),  # no worktree path in it
            "workspaces list --local": json.dumps([{"id": "w1", "worktreePath": "/wt/w1"},
                                                   {"id": "w2", "worktreePath": "/wt/w2", "archivedAt": "2026-01-02"}])})
        self.assertNotIn("worktree", h.worker("w1"))
        self.assertEqual((h.worktree("w1"), h.worktree("w2"), h.worktree("w9")), ("/wt/w1", "", ""))  # archived: its folder is gone
        got = []
        h.sh = lambda *a, timeout=40: got.append(timeout) or ""  # a host that does not answer
        self.assertEqual((h.worktree("w1", timeout=3), got), ("", [3]))  # the prompt hook's lookup is capped

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


    def test_config_host_id_beats_the_env_and_the_watcher_gets_what_the_adapter_resolved(self):
        os.environ["BOSS_HOST"] = "env-host"
        h = self.host({"hosts": {"superset": {"host_id": "cfg-host"}}}, {})
        self.assertEqual(h.host_id(), "cfg-host")
        self.assertEqual(h.watch_env(), {"BOSS_HOST": "cfg-host", "BOSS_HOST_CLI": os.path.join(self.tmp, "stubs", "superset")})
        self.assertEqual(bosshost.get({}, "superset").host_id(), "env-host")  # no host_id: the env, as before

    def test_a_repo_match_beats_a_project_name_match(self):
        h = self.host({}, {"projects list": json.dumps([{"id": "p-fork", "name": "widgets", "repo": "https://github.com/jane/widgets"},
                                                        {"id": "p-w", "name": "acme-widgets", "repo": "git@github.com:acme/widgets.git"},
                                                        {"id": "p-scp", "name": "gadgets", "repo": "git@example.com:other.git"},
                                                        {"id": "p-bare", "name": "gizmos", "repo": None}]),
                           "workspaces create": json.dumps({"id": "ws-new"})})
        h.create("acme/widgets", "fix/a", "do it")
        h.create("acme/gizmos", "fix/b", "do it")  # a project without a repo still matches by name
        made = [c for c in self.logged() if "workspaces create" in c]
        self.assertIn("--project p-w ", made[0])
        self.assertIn("--project p-bare ", made[1])
        with self.assertRaises(bosshost.Unsupported):
            h.create("acme/fork-of-nothing", "fix/c", "do it")
        with self.assertRaises(bosshost.Unsupported):  # a repo that names something else never falls back to the name
            h.create("acme/gadgets", "fix/d", "do it")
        slug = h.slug
        self.assertEqual([slug("https://github.com/acme/widgets.git/"), slug("git@github.com:acme/widgets.git"),
                          slug("ssh://git@github.com/acme/widgets"), slug("acme/widgets"), slug("git@example.com:other.git"), slug("")],
                         ["acme/widgets"] * 4 + ["", ""])


if __name__ == "__main__":
    unittest.main()
