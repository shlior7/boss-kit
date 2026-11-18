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

    DET = {"project": None, "hosts": {"fake": {"description": "test"}, "other": {"description": "o"}}, "detected_host": "fake",
           "git": {"repo": "acme/widgets", "default_branch": "main"}, "gh": {"login": "jane"},
           "boss_home": {"projects": [{"name": "widgets"}]}}

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
                keys = bosskit._keys(q) + [k for o in q.get("options") or [] for k in o.get("sets", {})]
                for key in keys:
                    self.assertTrue(bosskit._dig(bosskit.DEFAULTS, key) is not None or key in ("repo", "me"), key)
        kinds = [v for q in f["questions"] if q.get("key") == "github.comments" for o in q["options"] for v in bosskit._vals(o)]
        self.assertEqual(sorted(kinds), sorted(set(KINDS) - {"marker"}))  # every kind but the marker is asked, once
        (comments,) = [q for q in f["questions"] if q.get("key") == "github.comments"]
        self.assertTrue(comments["multiSelect"])
        self.assertIn("To choose none", comments["question"])
        self.assertEqual(f["expectations"]["question"], "What are your expectations of me as the boss of your project?")
        self.assertNotIn("options", f["expectations"])  # an open question in chat, not a form question
        self.assertEqual(f["closing"], "I'm a mere boss but you are the god. I hope to please you and get things done. "
                                       "Always let me know how I can be better.")
        self.assertTrue(any("never merges" in line for line in f["fixed"]))
        self.assertFalse(any(q.get("key") == "merge_policy" for q in f["questions"]))

    def test_the_form_is_short_and_has_no_model_question(self):
        """23 questions in 6 calls before; now at most 7 in 2 calls (3 in the second), the expectations asked in chat."""
        q = bosskit.onboard_questions(bosskit.DEFAULTS, self.DET, self.wt)
        self.assertLessEqual(len(q["calls"]), 2)
        self.assertTrue(all(1 <= len(c) <= 4 for c in q["calls"]))
        flat = [x for c in q["calls"] for x in c]
        self.assertLessEqual(len(flat), 7)
        self.assertTrue(all(2 <= len(x["options"]) <= 4 for x in flat))
        self.assertEqual([[x["id"] for x in c] for c in q["calls"]],
                         [["comments", "pages", "cleanup", "report"], ["domain", "proof", "wake"]])
        for x in flat:
            self.assertNotRegex(x["id"] + x["question"] + x["header"], r"(?i)model|effort")
        self.assertNotIn("expectations", [x["id"] for x in flat])
        self.assertEqual(q["expectations"], {"question": "What are your expectations of me as the boss of your project?", "ask": True})
        self.assertIn("config set --level project KEY=VALUE", q["defaults_note"])

    def test_questions_are_packed_prefilled_and_derived(self):
        cfg = bosskit.deep_merge(bosskit.DEFAULTS, {"github": {"comments": ["status", "proof", "verify", "merged"]}})
        q = bosskit.onboard_questions(cfg, {**self.DET, "gh": {"login": ""}}, self.wt)
        self.assertEqual(q["derived"], {"host": "fake", "repo": "acme/widgets", "base_branch": "main"})
        self.assertEqual(q["unset"], ["me"])  # derivable but nothing answered: never asked, named
        self.assertEqual([p["id"] for p in q["plain"]], ["name"])  # widgets clashes: asked
        by = {x["id"]: x for c in q["calls"] for x in c}
        self.assertEqual([o["label"] for o in by["comments"]["options"]],
                         ["Status note (current)", "Demo video", "Review replies", "Boss notes (current)"])
        self.assertEqual(by["cleanup"]["options"][0]["label"], "Ask each time (current)")
        self.assertEqual(by["report"]["options"][0]["label"], "Short, action first (current)")
        for gone in ("host", "me", "repo", "base_branch", "name"):
            self.assertNotIn(gone, by)

    def test_a_question_already_set_on_this_machine_is_skipped(self):
        layers = [("kit", "", bosskit.DEFAULTS), ("org", "o", {"pages": {"provider": "acme-pages", "publish": "x <dir>"}}),
                  ("user", "u", {"report": {"style": "voice"}}), ("project", "p", {"cleanup": "auto"})]
        cfg = bosskit.merged(layers)
        q = bosskit.onboard_questions(cfg, {**self.DET, "marker": ""}, self.wt, layers)
        self.assertEqual(q["skipped"], {"pages": "org", "cleanup": "project", "domain": "CLAUDE.local.md"})  # report: verbosity is not set
        self.assertEqual([[x["id"] for x in c] for c in q["calls"]], [["comments", "report", "proof", "wake"]])
        everything = bosskit.onboard_questions(cfg, {**self.DET, "marker": ""}, self.wt, layers, ask_all=True)
        self.assertEqual(everything["skipped"], {})
        self.assertEqual(len([x for c in everything["calls"] for x in c]), 7)
        self.assertFalse(bosskit.onboard_questions(cfg, {**self.DET, "project": "widgets"}, self.wt)["expectations"]["ask"])


class Answers(Home):
    """Answers become config per level and BOSS.md's ## Expectations, written only with apply."""

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        os.environ["FAKE_SESSION"] = "ws-1"

    def test_none_and_labels_and_option_values(self):
        ctx = bosskit.load(self.wt)
        ch, _ = bosskit.onboard_changes({"comments": "none"}, ctx.layers)
        self.assertEqual(ch, {"project": {"github": {"comments": []}}})
        ch, _ = bosskit.onboard_changes({"comments": ["Boss notes"]}, ctx.layers)  # one option stands for two kinds
        self.assertEqual(ch["project"]["github"]["comments"], ["verify", "merged"])
        ch, _ = bosskit.onboard_changes({"comments": ["Status note (current)", "Demo video (current)"]}, ctx.layers)
        self.assertEqual(ch["project"]["github"]["comments"], ["status", "proof", "demo"])
        ch, _ = bosskit.onboard_changes({"cleanup": "Archive, then tell me", "wake": "Yes", "report": "Voice"}, ctx.layers)
        self.assertEqual(ch, {"project": {"cleanup": "auto"}, "boss": {"wake": True}, "user": {"report": {"style": "voice"}}})
        ch, _ = bosskit.onboard_changes({"report": "Detailed"}, ctx.layers)  # style is already action-first: only verbosity differs
        self.assertEqual(ch, {"user": {"report": {"verbosity": "detailed"}}})
        _, ex = bosskit.onboard_changes({"domain": "Main boss (current)"}, ctx.layers)
        self.assertNotIn("domain", ex)  # kept as it is: the main boss writes no Domain line
        self.assertEqual(bosskit.onboard_changes({"domain": "Main boss"}, ctx.layers)[1]["domain"], "")
        self.assertNotIn("Domain:", bosskit.onboard_apply({"domain": "Main boss"}, cwd=self.wt))
        self.assertEqual(bosskit.onboard_changes({"domain": "billing"}, ctx.layers)[1]["domain"], "billing")
        ch, _ = bosskit.onboard_changes({"cleanup": "auto", "report": "Voice"}, ctx.layers, level="boss")
        self.assertEqual(ch, {"boss": {"cleanup": "auto", "report": {"style": "voice"}}})

    def test_apply_writes_config_expectations_the_domain_and_the_marker(self):
        boss_md = os.path.join(self.home, "widgets", "BOSS.md")
        open(boss_md, "w").write("# Facts\n\n## Expectations\n\nold\n\n## Project notes\n\nkeep me\n")
        answers = {"comments": "none", "domain": "billing", "folder": "Billing & Pay",
                   "expectations": "Ship small PRs.\nTell me what needs me first."}
        before = bosskit._read(boss_md)
        dry = bosskit.onboard_apply(answers, cwd=self.wt)
        self.assertIn("dry run", dry)
        self.assertEqual(bosskit._read(boss_md), before)
        self.assertFalse(os.path.exists(os.path.join(self.wt, "CLAUDE.local.md")))
        out = bosskit.onboard_apply(answers, apply=True, cwd=self.wt, now=5)
        cfg_path = os.path.join(self.home, "widgets", "config.json")
        self.assertIn(f"{cfg_path}  (github.comments)  backup {cfg_path}.bak-5", out)
        self.assertEqual(json.load(open(cfg_path))["github"], {"comments": []})
        self.assertEqual(bosskit._read(boss_md), "# Facts\n\n## Expectations\n\nShip small PRs.\nTell me what needs me first.\n\n"
                                                 "## Project notes\n\nkeep me\n")
        self.assertTrue(os.path.exists(boss_md + ".bak-5"))
        self.assertEqual(bosskit._read(os.path.join(self.wt, "CLAUDE.local.md")),
                         "Domain: billing\nFolder: Billing & Pay\n# Boss workspace ws-1\n")
        text = bosskit.instructions(bosskit.load(self.wt))
        self.assertIn("## Expectations\n\nShip small PRs.", text)  # every later session reads it
        self.assertIn("- PR comments allowed: none.", text)

    def test_apply_writes_after_the_answers_with_no_confirm_and_one_summary(self):
        """Answering is the consent: one call writes everything, backs each existing file up, and prints one short summary."""
        open(os.path.join(self.home, "widgets", "BOSS.md"), "w").write("# Facts\n")
        answers = {"cleanup": "auto", "expectations": "Be careful.", "report": "Voice"}
        out = bosskit.onboard_apply(answers, apply=True, cwd=self.wt, now=7)
        cfg_path = os.path.join(self.home, "widgets", "config.json")
        self.assertTrue(out.startswith("Onboarded widgets. Wrote:"))
        self.assertLess(len(out.splitlines()), 10)  # a summary, not the resolved config
        self.assertNotIn("would write", out)
        self.assertNotRegex(out, r"(?i)write it\?|confirm")
        self.assertIn("Undo: copy a .bak-<time> over its file.", out)
        self.assertIn("bosskit.py config set --level project KEY=VALUE", out)
        for path in (cfg_path, os.path.join(self.home, "widgets", "BOSS.md")):
            self.assertTrue(os.path.exists(path + ".bak-7"), path)  # an existing file is copied before it changes
        self.assertTrue(os.path.exists(os.path.join(self.home, "config.json")))  # the user layer: report.style
        self.assertEqual(json.load(open(cfg_path))["cleanup"], "auto")
        self.assertEqual(bosskit.boss_marker(self.wt), "ws-1")
        again = bosskit.onboard_apply(answers, apply=True, cwd=self.wt, now=8)  # the same answers: nothing left to write
        self.assertIn("Nothing to write", again)
        self.assertFalse(os.path.exists(cfg_path + ".bak-8"))

    def test_dropped_questions_keep_their_values(self):
        """Models, effort, merge, draft, body, style, ready, deck buttons, boss name and tracker are not asked any more:
        an older answers file that holds them is ignored, with a note, and each keeps its current value."""
        keep = {"github": {"merge": "rebase", "draft": False, "body": [], "style": "detailed", "ready": "never"},
                "tracker": {"type": "http"}}
        json.dump(keep, open(os.path.join(self.home, "widgets", "config.json"), "w"))
        json.dump({"models": {"strong": "custom-1", "mid": "custom-2", "cheap": "custom-3"}, "effort": "high", "deck_buttons": [],
                   "deck_worker_buttons": [], "boss_name": "Chief"}, open(os.path.join(self.home, "config.json"), "w"))
        before = bosskit.load(self.wt).cfg
        old = {"models_strong": "fable", "models_mid": "opus", "models_cheap": "sonnet", "effort": "xhigh", "merge": "Squash",
               "draft": "Draft", "body": ["Tracker link"], "style": "Short", "ready": "The boss", "deck": "On", "boss_name": "BOSS",
               "tracker": "None", "report_style": "Voice", "report_verbosity": "Detailed",
               "comments_worker": ["Status comment"], "comments_boss": "none", "cleanup": "auto"}
        out = bosskit.onboard_apply(old, apply=True, cwd=self.wt)
        self.assertIn("ignored, no longer asked (each keeps its current value):", out)
        self.assertIn("models_strong", out)
        after = bosskit.load(self.wt).cfg
        self.assertEqual(after["cleanup"], "auto")  # the one id still asked is honoured
        for key in ("github", "tracker", "models", "effort", "deck_buttons", "deck_worker_buttons", "boss_name", "report"):
            self.assertEqual(after[key], before[key], key)

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
        for want in ("comments  [github.comments, project, any of]", '["status", "proof"]', "expectations  [BOSS.md ## Expectations]",
                     "report  [report.style, report.verbosity, user]",
                     "I'm a mere boss but you are the god."):
            self.assertIn(want, r.stdout)
        self.assertEqual(sorted(os.listdir(self.home)), ["gadgets", "widgets"])  # nothing written

    def test_answers_scaffold_the_project_with_its_config_and_expectations(self):
        path = os.path.join(self.tmp, "answers.json")
        words = "Small PRs. Never push to main.\nTell me what needs me first."
        json.dump({"repo": "acme/gizmos", "me": "jane", "base_branch": "main", "comments": ["Status note"], "cleanup": "Ask each time",
                   "models_mid": "opus", "comments_boss": "none", "ready": "Never", "expectations": words}, open(path, "w"))
        r = subprocess.run([os.path.join(BIN, "boss-init"), "gizmos", "--answers", path], cwd=self.wt, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)  # no stdin: it must not ask anything
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = json.load(open(os.path.join(self.home, "gizmos", "config.json")))
        self.assertEqual((cfg["repo"], cfg["me"], cfg["github"]), ("acme/gizmos", "jane", {"comments": ["status", "proof"]}))
        self.assertNotIn("models", json.load(open(os.path.join(self.home, "config.json"))) if os.path.exists(os.path.join(self.home, "config.json")) else {})
        self.assertEqual(bosskit._read(os.path.join(self.home, "gizmos", "BOSS.md")).split("## Expectations\n\n")[1].split("\n\n")[0], words)
        self.assertIn("ignored, no longer asked (each keeps its current value): comments_boss, models_mid, ready", r.stdout)
        self.assertIn("Undo: copy a .bak-<time> over its file.", r.stdout)
        self.assertIn("backup " + os.path.join(self.home, "gizmos", "config.json.bak-"), r.stdout)
        self.assertNotIn("Next:", r.stdout)
        self.assertIsNotNone(bosskit.boss_marker(self.wt))  # the marker is written, not left as a step
        self.assertIn("I'm a mere boss but you are the god.", r.stdout)
        self.assertNotEqual(self.init("gizmos", "--answers", path).returncode, 0)  # never over an existing project


class CurrentMeansKeep(Home):
    """Review round 1: a "(current)" choice always keeps the value, whatever its label; labels stay short; every question
    has 2 to 4 options and says when Other must carry one that did not fit."""

    PAGES = {"provider": "acme-pages", "publish": "acme-pages deploy <dir> --json --a-long-flag-that-makes-it-long"}

    def setUp(self):
        super().setUp()
        os.environ["BOSS_PROJECT"] = "widgets"
        os.environ["FAKE_SESSION"] = "ws-1"
        json.dump({"pages": self.PAGES}, open(os.path.join(self.home, "org.json"), "w"))
        json.dump({"repo": "acme/widgets", "me": "jane", "models": {"strong": "a-custom-model-id-that-is-long-1"}},
                  open(os.path.join(self.home, "widgets", "config.json"), "w"))
        bdir = os.path.join(self.home, "widgets", "bosses", "ws-1")
        os.makedirs(bdir)
        json.dump({"effort": "max"}, open(os.path.join(bdir, "config.json"), "w"))
        self.det = {"project": "widgets", "hosts": {"fake": {"ok": True}, "other": {"ok": True}}, "detected_host": "fake",
                    "git": {"repo": "acme/widgets", "default_branch": "main"}, "gh": {"login": "jane"}, "boss_home": {"projects": []}}

    def asked(self, det=None):
        cfg = bosskit.load(self.wt, make=False).cfg
        return {x["id"]: x for call in bosskit.onboard_questions(cfg, det or self.det, self.wt)["calls"] for x in call}

    def snapshot(self):
        return {os.path.join(d, f): open(os.path.join(d, f)).read() for d, _, fs in os.walk(self.home) for f in fs}

    def test_a_custom_current_value_gets_a_short_label_and_is_kept(self):
        by = self.asked()
        self.assertEqual(by["pages"]["options"][0]["label"], "acme-pages (current)")
        self.assertEqual(len(by["pages"]["options"]), 4)  # the three options and the current one
        before = self.snapshot()
        out = bosskit.onboard_apply({"pages": "acme-pages (current)"}, apply=True, cwd=self.wt)
        self.assertNotIn("config.json", out)
        self.assertEqual(self.snapshot(), before)  # the org's provider stays, nothing restated in the user layer
        self.assertEqual(bosskit.load(self.wt).cfg["pages"], self.PAGES)

    def test_picking_every_current_option_writes_no_config_file(self):
        by, before = self.asked(), self.snapshot()
        answers = {}
        for qid, x in by.items():
            if x["multiSelect"]:
                continue
            cur = [o["label"] for o in x["options"] if o["label"].endswith("(current)")]
            self.assertEqual(len(cur), 1, qid)  # every single-select question shows what is set now
            answers[qid] = cur[0]
        self.assertEqual(sorted(answers), ["cleanup", "domain", "pages", "proof", "report", "wake"])
        out = bosskit.onboard_apply(answers, apply=True, cwd=self.wt)
        self.assertNotIn("config.json", out)
        self.assertEqual(self.snapshot(), before)

    def test_host_is_derived_or_left_unset_never_asked(self):
        one = {**self.det, "project": None, "detected_host": "", "hosts": {"fake": {"ok": True}, "other": {"ok": False}}}
        q = bosskit.onboard_questions(bosskit.DEFAULTS, one, self.wt)
        self.assertEqual(q["derived"]["host"], "fake")  # one installed plugin: derived
        many = {**one, "hosts": {f"h{i}": {"ok": True} for i in range(6)}}
        for det in (many, {**one, "hosts": {}}):
            q = bosskit.onboard_questions(bosskit.DEFAULTS, det, self.wt)
            self.assertIn("host", q["unset"])  # nothing answers: named in the summary, set later with config set
            self.assertNotIn("host", [x["id"] for c in q["calls"] for x in c] + [p["id"] for p in q["plain"]])
            self.assertTrue(len(q["calls"]) <= 2 and all(2 <= len(x["options"]) <= 4 for c in q["calls"] for x in c))
