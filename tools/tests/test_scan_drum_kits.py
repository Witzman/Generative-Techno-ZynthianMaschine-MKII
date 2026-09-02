"""Tests for the drum-kit classifier's name normalisation.

Pure and offline: `normalise` takes a string and returns a string, and the
whole point of it is that the SEPARATOR is not reliable in NI's filenames.

Written 2026-09-02, when the U+00A0 hole was finally closed. The hole was
recorded as debt in `todo.md` rather than fixed at the time because kit import
does not exist yet - but a classifier that silently misses a word boundary is
the shape of bug this project keeps paying for, so it is closed with a test
around it rather than a comment.
"""

import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

sdk = importlib.import_module("scan-drum-kits")


class NormaliseFoldsEverySeparatorTheFilenamesUse(unittest.TestCase):

    def test_underscores_and_hyphens_still_fold(self):
        # The behaviour that shipped, unchanged.
        self.assertEqual(sdk.normalise("hat_closed"), "hat closed")
        self.assertEqual(sdk.normalise("hat-open"), "hat open")
        self.assertEqual(sdk.normalise("kick__2"), "kick 2")

    def test_a_NO_BREAK_SPACE_folds_too(self):
        # WRITTEN AS AN ESCAPE, NOT AS THE CHARACTER. A literal U+00A0 in a
        # source file is invisible to every reader and to most diffs, and a
        # test whose whole subject cannot be SEEN is a test the next person
        # through quietly "tidies" into a plain space. It also cannot survive
        # a round trip through a shell heredoc, which is how it was written
        # here the first time and how it was silently turned back into a
        # plain space three times running.
        # THE DEFECT. NI's filenames carry U+00A0, and a classifier looking for
        # the word "closed" after a boundary never found one.
        self.assertEqual(sdk.normalise("hat\u00a0closed"), "hat closed")

    def test_a_run_of_MIXED_separators_becomes_ONE_space(self):
        # A run has always collapsed to a single space; the no-break space
        # joining the run must not break that, or the tokens gain padding.
        self.assertEqual(sdk.normalise("hat_\u00a0-closed"), "hat closed")

    def test_a_plain_space_is_left_as_a_plain_space(self):
        self.assertEqual(sdk.normalise("hat closed"), "hat closed")

    def test_a_name_with_no_separator_at_all_is_untouched(self):
        self.assertEqual(sdk.normalise("kick"), "kick")

    def test_the_fold_is_not_a_strip(self):
        # Leading and trailing separators become spaces rather than vanishing.
        # Nothing depends on stripping today and quietly adding it here would
        # change what every caller's `in` test matches against.
        self.assertEqual(sdk.normalise("_kick_"), " kick ")


if __name__ == "__main__":
    unittest.main()
