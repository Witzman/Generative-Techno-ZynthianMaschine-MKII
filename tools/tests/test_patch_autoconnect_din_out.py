"""tools/patch-autoconnect-din-out.py - the DIN OUT route (issue 28).

Three layers, because a green suite over a hole is this project's commonest
failure and a patch to someone else's file has two ways to be wrong:

* the TEXT: it applies once, applies nothing the second time, and refuses an
  anchor it cannot find rather than guessing;
* the BEHAVIOUR: the inserted lines are EXECUTED against fake ports, because a
  test that only finds the string would pass on a snippet that routes nothing;
* the REAL FILE, when the reference checkout is present: the anchor is read
  against Zynthian's own source, which is what a Zynthian update changes.
"""
import collections
import importlib.util
import os
import sys
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
spec = importlib.util.spec_from_file_location(
    "patch_din", os.path.join(ROOT, "tools", "patch-autoconnect-din-out.py"))
patch_din = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch_din)

REFERENCE = os.path.join(
    os.path.dirname(ROOT), "zynth-repos", "zynthian-ui", "zynautoconnect",
    "zynthian_autoconnect.py")

SHAPE = patch_din.ANCHOR  # what the real function holds, at its indentation


class Port:
    def __init__(self, name, *aliases):
        self.name, self.aliases = name, list(aliases)


def run_snippet(devices_out, src_ports):
    """Execute the inserted lines the way autoconnect would."""
    required_routes = collections.defaultdict(set)
    body = textwrap.dedent(patch_din.SNIPPET)
    exec(compile(body, "snippet", "exec"),
         {"devices_out": devices_out, "src_ports": src_ports,
          "required_routes": required_routes})
    return required_routes


class TheTextCase(unittest.TestCase):
    SOURCE = ("def f():\n    for chain in chains:\n        if chain.is_midi():\n"
              + SHAPE + "                pass\n")

    def test_it_inserts_once_before_the_anchor(self):
        out = patch_din.patch(self.SOURCE)
        self.assertEqual(out.count(patch_din.MARKER), 1)
        self.assertLess(out.index(patch_din.MARKER), out.index("Connect to first"))

    def test_a_second_run_changes_nothing(self):
        once = patch_din.patch(self.SOURCE)
        self.assertEqual(patch_din.patch(once), once)

    def test_a_missing_anchor_refuses_rather_than_guessing(self):
        with self.assertRaises(SystemExit):
            patch_din.patch("def f():\n    pass\n")

    def test_an_ambiguous_anchor_refuses(self):
        with self.assertRaises(SystemExit):
            patch_din.patch(self.SOURCE + self.SOURCE)

    def test_the_result_is_valid_python(self):
        compile(patch_din.patch(self.SOURCE), "patched", "exec")


class TheBehaviourCase(unittest.TestCase):
    DIN = Port("system:midi_playback_1",
               "USB:1.1.2/Maschine Controller MK2 OUT 1", "Maschine Controller MK2")

    def test_a_chain_output_is_routed_to_the_din_port(self):
        routes = run_snippet([self.DIN], [Port("ZynMidiRouter:ch3_out")])
        self.assertEqual(routes["system:midi_playback_1"],
                         {"ZynMidiRouter:ch3_out"})

    def test_it_is_matched_by_alias_not_by_port_number(self):
        other = Port("system:midi_playback_2", "USB:f_midi IN 1 OUT 1", "USB HOST")
        routes = run_snippet([other, self.DIN], [Port("ZynMidiRouter:ch0_out")])
        self.assertNotIn("system:midi_playback_2", routes)
        self.assertIn("system:midi_playback_1", routes)

    def test_the_usb_path_may_move_and_it_still_matches(self):
        moved = Port("system:midi_playback_1",
                     "USB:1.1.3/Maschine Controller MK2 OUT 1")
        routes = run_snippet([moved], [Port("ZynMidiRouter:ch1_out")])
        self.assertIn("system:midi_playback_1", routes)

    def test_nothing_is_routed_for_a_chain_with_no_router_output(self):
        self.assertEqual(run_snippet([self.DIN], []), {})

    def test_an_empty_slot_and_an_unaliased_port_are_survived(self):
        routes = run_snippet([None, Port("x:y"), self.DIN],
                             [Port("ZynMidiRouter:ch2_out")])
        self.assertEqual(list(routes), ["system:midi_playback_1"])

    def test_the_controllers_input_side_is_never_a_destination(self):
        """DIN IN is a SOURCE (system:midi_capture_N). Routing a chain into
        it would be a connection JACK refuses and a loop if it did not."""
        capture = Port("system:midi_capture_1",
                       "USB:1.1.2/Maschine Controller MK2 IN 1")
        self.assertEqual(run_snippet([capture], [Port("ZynMidiRouter:ch0_out")]), {})


@unittest.skipUnless(os.path.exists(REFERENCE),
                     "the zynth-repos reference checkout is not here (CI)")
class TheRealFileCase(unittest.TestCase):
    def test_the_anchor_is_in_zynthians_own_source_exactly_once(self):
        with open(REFERENCE) as fh:
            src = fh.read()
        self.assertEqual(src.count(patch_din.ANCHOR), 1)

    def test_the_patched_real_file_still_compiles(self):
        with open(REFERENCE) as fh:
            src = fh.read()
        compile(patch_din.patch(src), "zynthian_autoconnect.py", "exec")


if __name__ == "__main__":
    unittest.main()
