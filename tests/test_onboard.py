"""GitHub posting settings and the onboarding form: config github reaching the instructions, done detection without a
status comment, the question data, boss-init --answers and the expectations in BOSS.md.

Run: python3 -m unittest discover -s tests
"""
import itertools
import json
import os
import subprocess
import sys
from unittest import mock

from test_kit import BIN, Home, git, load_script  # noqa: F401  (Home: a temp $BOSS_HOME with widgets and gadgets)

import bosshost  # noqa: E402
import bosskit  # noqa: E402

KINDS = list(bosskit.COMMENT_KINDS)
MARKER = "`<!-- BOSS_WORKER_DONE task: <id> -->`"


def cfg_with(**github):
    return bosskit.deep_merge(bosskit.DEFAULTS, {"github": github})


class GithubComments(Home):
    """Every subset of the comment kinds, [] included, is stated in plain words, in the boss's block and the worker's line."""

    def test_each_combination_reaches_the_instructions_text(self):
        host = bosshost.get({}, "other")
        for n in range(len(KINDS) + 1):
            for on in itertools.combinations(KINDS, n):
                with self.subTest(comments=on):
                    cfg = cfg_with(comments=list(on))
                    text, line = bosskit.github_text(cfg, host), bosskit.worker_github_line(cfg)
                    if on:
                        self.assertIn("- PR comments allowed: " + ", ".join(on) + ".", text)
                        off = [k for k in KINDS if k not in on]
                        if off:
                            self.assertIn("- Not allowed: " + ", ".join(off) + ".", text)
                    else:
                        self.assertIn("- PR comments allowed: none.", text)
                    for k in KINDS:
                        self.assertEqual(f"  - `{k}` (" in text, k in on, k)
                    self.assertEqual("post ONE short plain-English status comment" in line, "status" in on)
                    self.assertEqual("holding only the line" in line, "marker" in on and "status" not in on)
                    self.assertEqual("Post no status comment on the PR." in line, not {"status", "marker"} & set(on))
                    self.assertEqual(", the proof links)" in line, {"status", "proof"} <= set(on))
                    self.assertEqual("Attach the demo video to the PR." in line, "demo" in on)
                    self.assertEqual("You may reply on the PR's review threads." in line, "review_replies" in on)
                    self.assertIn(f'"GitHub: {line}"', text)
                    self.assertTrue(line.endswith("Post nothing else on GitHub."))

    def test_the_kit_default_is_todays_behaviour(self):
        line = bosskit.worker_github_line(bosskit.DEFAULTS)
        self.assertEqual(bosskit.DEFAULTS["github"]["comments"], ["status", "proof", "demo", "review_replies"])
        self.assertIn(f"status comment on the PR (what changed, the checks you ran, the proof links) ending with the line {MARKER}", line)
        self.assertIn("draft PR", line)
        text = bosskit.github_text(bosskit.DEFAULTS, bosshost.get({}, "other"))
        for want in ("--squash", "you mark a verified PR ready", "the tracker link and the proof links", "a recorded demo, mandatory",
                     "ask before archiving each", "action-first (section 9), short"):
            self.assertIn(want, text)

    def test_unknown_kinds_are_named_and_ignored(self):
        text = bosskit.github_text(cfg_with(comments=["status", "tweet"]), bosshost.get({}, "other"))
        self.assertIn("Ignored, not a comment kind: tweet", text)
        self.assertIn("- PR comments allowed: status.", text)

    def test_the_other_knobs(self):
        cfg = bosskit.deep_merge(cfg_with(draft=False, body=[], ready="never", merge="rebase", style="detailed"),
                                 {"proof": "screenshots", "cleanup": "auto", "report": {"style": "voice", "verbosity": "detailed"}})
        text, line = bosskit.github_text(cfg, bosshost.get({}, "other")), bosskit.worker_github_line(cfg)
        for want in ("Workers open a ready PR", "what changed only", "Ready: never", "--rebase", "screenshots of each step",
                     "a standing OK", "voice: plain sentences", "reasons and evidence"):
            self.assertIn(want, text)
        self.assertIn("(not a draft)", line)
        self.assertIn("a short table of checks and the files changed", line)
        self.assertNotIn("tracker link", line)

    def test_the_loader_states_it_and_the_hosts_pr_line_follows_it(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        open(os.path.join(self.wt, "CLAUDE.local.md"), "w").write("# Boss workspace\n")
        json.dump({"repo": "acme/widgets", "github": {"comments": []}}, open(os.path.join(self.home, "widgets", "config.json"), "w"))
        kit_hosts = os.path.join(os.path.dirname(BIN), "hosts")
        for name in sorted(os.listdir(kit_hosts)):  # the kit's own plugins carry a PR-comment line in their dispatch text
            with self.subTest(host=name):
                os.environ["BOSS_HOST_PATH"] = kit_hosts
                os.environ["BOSS_HOST_KIND"] = name
                text = bosskit.instructions(bosskit.load(self.wt))
                self.assertNotIn("post one short plain-English status comment", text.split("<!-- settings in effect")[0].split("<!-- host plugin")[1])
                self.assertIn("GitHub: Push and open a draft PR", text)
                self.assertIn("- PR comments allowed: none. Neither you nor any worker posts", text)


class DoneWithoutStatus(Home):
    """With status off the envelope still reaches the boss on a host that has a screen or message path; a host that has
    neither is told so, and offered the marker-only comment."""

    def test_a_host_with_messages_names_them(self):
        text = bosskit.github_text(cfg_with(comments=[]), bosshost.get({}, "other"))
        self.assertIn("Done comes from the envelope message the worker sends you", text)
        self.assertIn("The envelope stays mandatory", text)

    def test_a_host_with_its_own_watcher_names_it(self):
        os.environ["BOSS_HOST_PATH"] = os.path.join(os.path.dirname(BIN), "hosts")
        host = next(bosshost.get({}, n) for n in bosshost.plugins() if bosshost.get({}, n).watch_script())
        self.assertIn("Done comes from the host's own watcher", bosskit.github_text(cfg_with(comments=[]), host))

    def test_a_pr_only_host_warns_and_offers_the_marker(self):
        fake = bosshost.get({}, "fake")
        self.assertEqual(bosskit.done_paths(fake), [])
        text = bosskit.github_text(cfg_with(comments=[]), fake)
        self.assertIn("Done detection, warning: this host gives the watcher no screen or message path", text)
        self.assertIn("allow `marker`", text)
        marker = bosskit.github_text(cfg_with(comments=["marker"]), fake)
        self.assertIn("the hidden marker in the marker-only comment", marker)
        self.assertIn(f"holding only the line {MARKER}", bosskit.worker_github_line(cfg_with(comments=["marker"])))

    def test_the_watcher_still_fires_on_the_envelope_message(self):
        os.environ["BOSS_PROJECT"] = "widgets"
        os.environ["OTHER_SESSION"] = "b0550000"
        json.dump({"repo": "acme/widgets", "github": {"comments": []}}, open(os.path.join(self.home, "widgets", "config.json"), "w"))
        w, ctx, host, out = load_script("boss-host"), bosskit.load(self.wt), bosshost.get({}, "other"), []
        msgs = iter([[], [], [("m1", "BOSS_WORKER_DONE\ntask: fix-1\nsummary: no comment posted", 0)]])
        host.messages = lambda boss, wid: next(msgs)
        host.worker = lambda wid: {"terminals": [{"agent": {"state": "working"}}]}
        draft = [{"number": 7, "state": "OPEN", "isDraft": True, "comments": []}]  # no marker ever lands on the PR
        with mock.patch.object(w, "pr_list", lambda b: draft), mock.patch.object(w.time, "sleep", lambda s: None):
            w.watch(ctx, host, "aaaa1111", "fix/x", polls=5, out=out.append)
        self.assertEqual(out[0], "ENVELOPE DONE|fix-1|no comment posted")

    def test_with_drafts_off_an_open_pr_is_no_done_signal(self):
        w, host = load_script("boss-host"), bosshost.get({}, "other")
        prs = [{"number": 7, "state": "OPEN", "isDraft": False, "comments": []}, {"number": 8, "state": "MERGED", "comments": []}]
        self.assertEqual(w.ready(host, prs), {7, 8})
        self.assertEqual(w.ready(host, prs, draft=False), {8})


class QuestionData(Home):
    """skills/boss/questions.json: the AskUserQuestion limits, real config keys, and the form's fixed lines."""

    def test_the_form_fits_the_tool_and_names_real_keys(self):
        f = bosskit.form()
        qs = f["questions"] + f["followups"] + [f["expectations"]]
        self.assertEqual(len({q["id"] for q in f["questions"]}), len(f["questions"]))
        for q in qs:
            with self.subTest(q=q["id"]):
                self.assertLessEqual(len(q["header"]), 12)
                self.assertTrue(q["question"].strip())
                if not q.get("free") and not q.get("options_from"):
                    self.assertTrue(2 <= len(q["options"]) <= 4)
                    self.assertEqual(len({o["label"] for o in q["options"]}), len(q["options"]))
                for key in bosskit._keys(q):
                    self.assertTrue(bosskit._dig(bosskit.DEFAULTS, key) is not None or key in ("repo", "me"), key)
        kinds = [o["value"] for q in f["questions"] if q.get("key") == "github.comments" for o in q["options"]]
        self.assertEqual(sorted(kinds), sorted(KINDS))  # every kind is asked, once
        for q in f["questions"]:
            if q.get("key") == "github.comments":
                self.assertTrue(q["multiSelect"])
                self.assertIn("To choose none", q["question"])
        self.assertEqual(f["expectations"]["question"], "What are your expectations of me as the boss of your project?")
        self.assertEqual(f["closing"], "I'm a mere boss but you are the god. I hope to please you and get things done. "
                                       "Always let me know how I can be better.")
        self.assertTrue(any("never merges" in line for line in f["fixed"]))
        self.assertFalse(any(q.get("key") == "merge_policy" for q in f["questions"]))

    def test_questions_are_packed_prefilled_and_derived(self):
        det = {"project": None, "hosts": {"fake": {"description": "test"}, "other": {"description": "o"}}, "detected_host": "fake",
               "git": {"repo": "acme/widgets", "default_branch": "main"}, "gh": {"login": "jane"},
               "boss_home": {"projects": [{"name": "widgets"}]}}
        cfg = bosskit.deep_merge(bosskit.DEFAULTS, {"github": {"comments": ["status", "verify"]}, "models": {"strong": "custom-1"}})
        q = bosskit.onboard_questions(cfg, det, self.wt)
        self.assertEqual(q["derived"], {"host": "fake", "repo": "acme/widgets", "base_branch": "main", "me": "jane"})
        self.assertEqual([p["id"] for p in q["plain"]], ["name"])  # widgets clashes: asked
        flat = [x for call in q["calls"] for x in call]
        self.assertTrue(all(1 <= len(c) <= 4 for c in q["calls"]))
        self.assertEqual([x["id"] for x in q["calls"][0][:2]], ["comments_worker", "comments_boss"])  # GitHub first
        by = {x["id"]: x for x in flat}
        self.assertEqual([o["label"] for o in by["comments_worker"]["options"]][:2], ["Status comment (current)", "Proof links"])
        self.assertIn("Verify note (current)", [o["label"] for o in by["comments_boss"]["options"]])
        self.assertEqual(by["models_strong"]["options"][0]["label"], '"custom-1" (current)')
        self.assertEqual(by["merge"]["options"][0]["label"], "Squash (current)")
        self.assertTrue(all(len(x["options"]) <= 4 for x in flat))
        self.assertNotIn("host", by)


class Answers(Home):
    """Answers become config per level and BOSS.md's ## Expectations, written only with apply."""

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        os.environ["FAKE_SESSION"] = "ws-1"

    def test_none_and_labels_and_shared_keys(self):
        ctx = bosskit.load(self.wt)
        ch, _ = bosskit.onboard_changes({"comments_worker": "none", "comments_boss": []}, ctx.layers)
        self.assertEqual(ch, {"project": {"github": {"comments": []}}})
        ch, _ = bosskit.onboard_changes({"comments_boss": ["Verify note (current)"]}, ctx.layers)  # the other part keeps its value
        self.assertEqual(ch["project"]["github"]["comments"], ["status", "proof", "demo", "verify"])
        ch, _ = bosskit.onboard_changes({"merge": "Rebase", "wake": "Yes", "models_strong": "opus", "deck": "Off"}, ctx.layers)
        self.assertEqual(ch, {"project": {"github": {"merge": "rebase"}}, "boss": {"wake": True},
                              "user": {"deck_buttons": [], "deck_worker_buttons": []}})  # opus is already the value
        ch, _ = bosskit.onboard_changes({"merge": "rebase", "effort": "high"}, ctx.layers, level="boss")
        self.assertEqual(ch, {"boss": {"github": {"merge": "rebase"}, "effort": "high"}})

    def test_apply_writes_config_expectations_and_the_domain(self):
        boss_md = os.path.join(self.home, "widgets", "BOSS.md")
        open(boss_md, "w").write("# Facts\n\n## Expectations\n\nold\n\n## Project notes\n\nkeep me\n")
        answers = {"comments_worker": "none", "comments_boss": "none", "domain": "billing", "folder": "Billing & Pay",
                   "expectations": "Ship small PRs.\nTell me what needs me first."}
        before = bosskit._read(boss_md)
        dry = bosskit.onboard_apply(answers, cwd=self.wt)
        self.assertIn("dry run", dry)
        self.assertEqual(bosskit._read(boss_md), before)
        out = bosskit.onboard_apply(answers, apply=True, cwd=self.wt, now=5)
        self.assertIn("wrote " + os.path.join(self.home, "widgets", "config.json"), out)
        self.assertEqual(json.load(open(os.path.join(self.home, "widgets", "config.json")))["github"], {"comments": []})
        self.assertEqual(bosskit._read(boss_md), "# Facts\n\n## Expectations\n\nShip small PRs.\nTell me what needs me first.\n\n"
                                                 "## Project notes\n\nkeep me\n")
        self.assertTrue(os.path.exists(boss_md + ".bak-5"))
        self.assertEqual(bosskit._read(os.path.join(self.wt, "CLAUDE.local.md")), "Domain: billing\nFolder: Billing & Pay\n")
        open(os.path.join(self.wt, "CLAUDE.local.md"), "a").write("# Boss workspace\n")
        text = bosskit.instructions(bosskit.load(self.wt))
        self.assertIn("## Expectations\n\nShip small PRs.", text)  # every later session reads it
        self.assertIn("- PR comments allowed: none.", text)

    def test_set_section_appends_when_missing(self):
        self.assertEqual(bosskit.set_section("# Facts\n", "## Expectations", "be quick"), "# Facts\n\n## Expectations\n\nbe quick\n")
        self.assertEqual(bosskit.set_section("## Expectations\n\nold\n", "## Expectations", "new"), "## Expectations\n\nnew\n")


class BossInitAnswers(Home):
    """bin/boss-init takes the form's answers from a file, or prints the form."""

    def init(self, *args):
        return subprocess.run([os.path.join(BIN, "boss-init"), *args], cwd=self.wt, capture_output=True, text=True)

    def test_questions_print_the_form(self):
        r = self.init("--questions")
        self.assertEqual(r.returncode, 0, r.stderr)
        for want in ("comments_worker  [github.comments, project, any of]", '"status"', "expectations  [BOSS.md ## Expectations]",
                     "I'm a mere boss but you are the god."):
            self.assertIn(want, r.stdout)
        self.assertEqual(sorted(os.listdir(self.home)), ["gadgets", "widgets"])  # nothing written

    def test_answers_scaffold_the_project_with_its_config_and_expectations(self):
        path = os.path.join(self.tmp, "answers.json")
        json.dump({"repo": "acme/gizmos", "me": "jane", "base_branch": "main", "comments_worker": ["Status comment"],
                   "comments_boss": "none", "ready": "Never", "models_mid": "opus",
                   "expectations": ["Be careful", "Keep me informed"]}, open(path, "w"))
        r = self.init("gizmos", "--answers", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = json.load(open(os.path.join(self.home, "gizmos", "config.json")))
        self.assertEqual((cfg["repo"], cfg["me"], cfg["github"]), ("acme/gizmos", "jane", {"comments": ["status"], "ready": "never"}))
        self.assertEqual(json.load(open(os.path.join(self.home, "config.json")))["models"], {"mid": "opus"})
        md = bosskit._read(os.path.join(self.home, "gizmos", "BOSS.md"))
        self.assertIn("## Expectations\n\n- Be careful: verify everything twice, ask when unsure.\n- Keep me informed:", md)
        self.assertIn("I'm a mere boss but you are the god.", r.stdout)
        self.assertNotEqual(self.init("gizmos", "--answers", path).returncode, 0)  # never over an existing project
