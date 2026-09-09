"""The lifecycle rules, tested as rules rather than trusted as prose.

Each case here is a thing that actually happened on 2026-09-09, in the session
that wrote the rule it breaks: a commit that carried the assistant's
attribution trailer into a repo whose CI fails the build over it, a branch
that changed the driver and left the changelog alone, and an issue moved to
the rig stage with nobody's steps written on it.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import release_rules as rr  # noqa: E402


class WhatCountsAsShipped(unittest.TestCase):
    def test_the_driver_and_the_daemon_ship(self):
        self.assertTrue(rr.ships("ctrldev/zynthian_ctrldev_maschine_mk2.py"))
        self.assertTrue(rr.ships("daemon/src/main.rs"))
        self.assertTrue(rr.ships("system/maschine.json"))
        self.assertTrue(rr.ships("snapshot/factory.zss"))

    def test_a_test_is_not_a_feature(self):
        self.assertFalse(rr.ships("ctrldev/tests/test_driver_dispatch.py"))
        self.assertFalse(rr.ships("system/tests/test-dry-run.sh"))

    def test_the_build_scripts_and_the_guide_do_not_ship(self):
        """A reader of the changelog is not looking for either."""
        self.assertFalse(rr.ships("tools/docs-gate.py"))
        self.assertFalse(rr.ships("docs/the-surface.html"))
        self.assertFalse(rr.ships("README.md"))


class RuleSixIsNotAPromise(unittest.TestCase):
    def test_the_trailer_is_refused(self):
        msg = "Fix the thing\n\nCo-Authored-By: Claude Opus 5 <x@y>\n"
        self.assertIn("rule 6", rr.attribution_offence(msg))

    def test_the_session_line_is_refused_too(self):
        """It arrived with the trailer and is the same claim about authorship."""
        self.assertTrue(rr.attribution_offence("x\n\nClaude-Session: https://y"))

    def test_the_generated_with_line_is_refused(self):
        self.assertTrue(rr.attribution_offence("x\n\n🤖 Generated with Claude"))

    def test_an_ordinary_message_passes(self):
        self.assertEqual(rr.attribution_offence("Fix the bracket\n\nBody."), "")

    def test_the_word_claude_in_prose_is_not_a_trailer(self):
        """`hygiene` learned this on its own commit: the message explaining why
        the job exists names the trailer, and matching bare words failed it."""
        self.assertEqual(
            rr.attribution_offence("Explain why Co-Authored-By is refused"), "")


class RuleSevenIsNotAPromise(unittest.TestCase):
    def test_a_driver_change_without_a_changelog_line_is_refused(self):
        offence = rr.changelog_offence(["ctrldev/zynthian_ctrldev_maschine_mk2.py"], "x")
        self.assertIn("rule 7", offence)
        self.assertIn("changelog", offence)

    def test_the_same_change_with_the_line_passes(self):
        self.assertEqual(rr.changelog_offence(
            ["ctrldev/zynthian_ctrldev_maschine_mk2.py", rr.CHANGELOG], "x"), "")

    def test_a_test_only_branch_needs_nothing(self):
        self.assertEqual(rr.changelog_offence(["ctrldev/tests/test_x.py"], "x"), "")

    def test_a_docs_only_branch_needs_nothing(self):
        self.assertEqual(rr.changelog_offence(["docs/saving.html"], "x"), "")

    def test_the_opt_out_is_a_signed_decision_and_excuses_it(self):
        """An exemption somebody wrote in the history is not a hole."""
        msg = "Move a constant\n\nNo-changelog: no player can tell.\n"
        self.assertEqual(rr.changelog_offence(["ctrldev/techno_lib.py"], msg), "")

    def test_a_bare_opt_out_with_no_reason_does_not_excuse_it(self):
        msg = "Move a constant\n\nNo-changelog:\n"
        self.assertIn("rule 7", rr.changelog_offence(["ctrldev/techno_lib.py"], msg))


class TheRunbookIsNotAPromise(unittest.TestCase):
    def test_the_issue_a_branch_closes_is_read_out_of_its_trailer(self):
        msg = "Fix it\n\nFixes Witzman/ZynthianMaschine-Workshop#5\n"
        self.assertEqual(rr.fixed_issues(msg), [5])

    def test_a_branch_closing_nothing_is_not_refused(self):
        self.assertEqual(rr.runbook_offence([], set()), "")

    def test_an_issue_without_a_runbook_is_refused_by_number(self):
        offence = rr.runbook_offence([5, 7], {7})
        self.assertIn("#5", offence)
        self.assertNotIn("#7", offence)

    def test_an_issue_with_one_passes(self):
        self.assertEqual(rr.runbook_offence([5], {5}), "")

    def test_an_unreadable_github_does_not_refuse_the_push(self):
        """A hook that blocks a push because the network is down teaches you
        to pass --no-verify, and a check people route around enforces
        nothing. bin/state is where an unreadable GitHub gets said out loud."""
        self.assertEqual(rr.runbook_offence([5], None), "")


if __name__ == "__main__":
    unittest.main()
