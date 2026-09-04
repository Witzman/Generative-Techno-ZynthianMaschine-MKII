"""Tests for the style sampler: odds, hard rules, the seed, and the blend.

Pure and offline. The two manifest files and the base snapshot are read from
the repository because the strongest tests here are about the SHIPPED data -
that every existing entry survives the new code path untouched, and that a
blend of two real styles never invents a value for a field that cannot be
averaged.
"""

import copy
import importlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

ss = importlib.import_module("style-sampler")

GENRE = os.path.join(REPO, "snapshot", "genre-pack-manifest.json")
DRONE = os.path.join(REPO, "snapshot", "drone-ambient-manifest.json")
EXAMPLE = os.path.join(REPO, "snapshot", "example-style.json")


def load(path):
    with open(path) as fh:
        return json.load(fh)


def odds(**kind):
    return {"odds": dict(kind)}


def leaf_paths(node, path=""):
    """Every leaf, as a dotted path - the same addressing `group_for` uses."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaf_paths(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from leaf_paths(v, f"{path}.{i}")
    else:
        yield path, node


# --- the promise that every existing manifest keeps working -----------------

class TheShippedManifestsAreUnchanged(unittest.TestCase):

    def test_every_genre_pack_entry_samples_to_itself(self):
        # A plain value still means what it means today. If this fails, the
        # new code path has started reading a field as odds.
        for entry in load(GENRE):
            for seed in (0, 1, 12345, -7):
                self.assertEqual(ss.sample_entry(entry, seed), entry, entry["file"])

    def test_every_drone_pack_entry_samples_to_itself(self):
        # This pack is the awkward one: it carries `overrides` and `mods`,
        # which the genre pack does not.
        for entry in load(DRONE):
            for seed in (0, 99):
                self.assertEqual(ss.sample_entry(entry, seed), entry, entry["file"])

    def test_every_shipped_entry_validates(self):
        for path in (GENRE, DRONE):
            for entry in load(path):
                ss.validate_entry(entry)

    def test_a_field_called_range_is_not_a_distribution(self):
        # `voices.range` is a real manifest field. The first draft made the
        # kind words themselves the markers and misread all 71 entries on the
        # first run - this is that regression, pinned.
        self.assertFalse(ss.is_dist({"range": [1, 2, 1], "octave": [-1, 0, 1]}))
        self.assertFalse(ss.is_dist({"choice": ["a"], "pick": [1]}))


# --- what a distribution is -------------------------------------------------

class RecognisingOdds(unittest.TestCase):

    def test_the_wrapper_key_alone_marks_a_distribution(self):
        self.assertTrue(ss.is_dist(odds(range=[1, 4])))
        self.assertFalse(ss.is_dist(4))
        self.assertFalse(ss.is_dist([1, 2]))
        self.assertFalse(ss.is_dist({"velo": 100}))

    def test_odds_beside_another_key_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            ss.is_dist({"odds": {"range": [1, 4]}, "velo": 100})

    def test_two_kinds_in_one_distribution_are_refused(self):
        with self.assertRaises(ValueError):
            ss.is_dist({"odds": {"range": [1, 4], "choice": [1, 2]}})

    def test_no_kind_at_all_is_refused(self):
        with self.assertRaises(ValueError):
            ss.is_dist({"odds": {"mode": 3}})

    def test_odds_must_take_an_object(self):
        with self.assertRaises(ValueError):
            ss.is_dist({"odds": [1, 2, 3]})


class DrawingFromOdds(unittest.TestCase):

    def test_a_range_stays_inside_its_bounds_and_reaches_both_ends(self):
        seen = {ss.draw(odds(range=[3, 5]), s, "hits") for s in range(400)}
        self.assertTrue(seen <= {3, 4, 5})
        self.assertEqual(seen, {3, 4, 5})

    def test_an_integer_range_draws_integers(self):
        for s in range(50):
            self.assertIsInstance(ss.draw(odds(range=[100, 120]), s, "velo"), int)

    def test_a_float_range_draws_floats_inside_the_bounds(self):
        for s in range(50):
            v = ss.draw(odds(range=[0.0, 1.0]), s, "phase0")
            self.assertIsInstance(v, float)
            self.assertTrue(0.0 <= v < 1.0)

    def test_a_step_is_honoured(self):
        seen = {ss.draw(odds(range=[0, 12], step=4), s, "x") for s in range(200)}
        self.assertEqual(seen, {0, 4, 8, 12})

    def test_a_mode_biases_the_draw_towards_it(self):
        flat = [ss.draw(odds(range=[0, 10]), s, "x") for s in range(600)]
        peaked = [ss.draw(odds(range=[0, 10], mode=9), s, "x") for s in range(600)]
        self.assertGreater(sum(peaked) / len(peaked), sum(flat) / len(flat) + 1.0)

    def test_a_mode_outside_the_range_is_refused(self):
        with self.assertRaises(ValueError):
            ss.draw(odds(range=[0, 4], mode=9), 1, "x")

    def test_an_inverted_range_is_refused(self):
        with self.assertRaises(ValueError):
            ss.draw(odds(range=[9, 2]), 1, "x")

    def test_a_choice_only_ever_returns_a_listed_option(self):
        opts = ["Roland TR909", "Roland TR808", "Roland TR707"]
        seen = {ss.draw(odds(choice=opts), s, "kit") for s in range(300)}
        self.assertEqual(seen, set(opts))

    def test_a_zero_weight_option_is_never_drawn(self):
        seen = {ss.draw(odds(choice=["a", "b"], weights=[1, 0]), s, "x")
                for s in range(300)}
        self.assertEqual(seen, {"a"})

    def test_weights_shift_the_proportions(self):
        draws = [ss.draw(odds(choice=["a", "b"], weights=[9, 1]), s, "x")
                 for s in range(1000)]
        self.assertGreater(draws.count("a"), 800)

    def test_a_mismatched_weight_list_is_refused(self):
        with self.assertRaises(ValueError):
            ss.draw(odds(choice=["a", "b"], weights=[1]), 1, "x")

    def test_weights_that_sum_to_zero_are_refused(self):
        with self.assertRaises(ValueError):
            ss.draw(odds(choice=["a", "b"], weights=[0, 0]), 1, "x")

    def test_a_pick_returns_that_many_distinct_members_sorted(self):
        for s in range(50):
            got = ss.draw(odds(pick=[0, 2, 4, 6, 8, 10, 12, 14], count=5), s, "steps")
            self.assertEqual(len(got), 5)
            self.assertEqual(len(set(got)), 5)
            self.assertEqual(got, sorted(got))
            self.assertTrue(set(got) <= {0, 2, 4, 6, 8, 10, 12, 14})

    def test_a_pick_count_may_itself_be_odds(self):
        counts = {len(ss.draw(odds(pick=[0, 1, 2, 3], count=odds(range=[1, 3])),
                              s, "steps")) for s in range(200)}
        self.assertEqual(counts, {1, 2, 3})

    def test_picking_more_than_the_pool_is_refused(self):
        with self.assertRaises(ValueError):
            ss.draw(odds(pick=[0, 1], count=3), 1, "steps")

    def test_a_pick_of_the_whole_pool_is_the_whole_pool(self):
        self.assertEqual(ss.draw(odds(pick=[4, 0, 8]), 1, "steps"), [0, 4, 8])


# --- the seed ---------------------------------------------------------------

class TheSeedIsTheWholePoint(unittest.TestCase):

    def setUp(self):
        self.style = load(EXAMPLE)[0]

    def test_the_same_seed_reproduces_the_same_snapshot(self):
        for seed in (0, 1, 1234, 99999):
            self.assertEqual(ss.sample_entry(self.style, seed),
                             ss.sample_entry(self.style, seed))

    def test_the_same_seed_reproduces_it_across_a_fresh_import(self):
        # An unreproducible generator is a dice roll. Nothing here may depend
        # on process state, import order or the global RNG.
        first = ss.sample_entry(self.style, 4242)
        again = importlib.reload(importlib.import_module("style-sampler"))
        self.assertEqual(again.sample_entry(self.style, 4242), first)

    def test_a_different_seed_gives_a_different_snapshot(self):
        drawn = [json.dumps(ss.sample_entry(self.style, s), sort_keys=True)
                 for s in range(20)]
        self.assertGreater(len(set(drawn)), 15)

    def test_a_draw_depends_on_the_path_so_editing_one_field_does_not_move_the_rest(self):
        # Seeds keyed by path, not by traversal order: adding a distribution
        # must not reshuffle every other field.
        base = ss.sample_entry(self.style, 7)
        edited = copy.deepcopy(self.style)
        edited["scale"] = odds(choice=[0, 1, 2])
        after = ss.sample_entry(edited, 7)
        moved = [p for (p, x), (_, y) in zip(leaf_paths(base), leaf_paths(after))
                 if x != y]
        self.assertEqual(moved, ["scale"])

    def test_two_identical_distributions_at_different_paths_draw_apart(self):
        # The draw is keyed by (seed, path). Two fields declaring the same
        # odds must be able to disagree - if they cannot, the path is not in
        # the hash and a style is really one number wearing many names.
        style = {"drums": {"velo": [{"odds": {"range": [0, 1000]}},
                                    {"odds": {"range": [0, 1000]}}]}}
        got = [ss.sample_entry(style, s)["drums"]["velo"] for s in range(30)]
        self.assertTrue(any(pair[0] != pair[1] for pair in got))
        self.assertGreater(len({tuple(pair) for pair in got}), 25)

    def test_the_shipped_example_style_samples_to_something_valid(self):
        for seed in range(30):
            ss.validate_entry(ss.sample_entry(self.style, seed))


# --- the hard rules ---------------------------------------------------------

class HardRules(unittest.TestCase):

    def _style(self, rules):
        return {"tempo": odds(range=[100, 140]),
                "drums": {"steps": [odds(pick=[0, 2, 4, 6, 8, 10, 12, 14], count=3)]},
                "rules": rules}

    def test_require_puts_a_missing_step_back(self):
        # The kick on step 0, which is the entry's own example.
        for seed in range(60):
            got = ss.sample_entry(self._style(
                [{"path": "drums.steps.0", "require": [0]}]), seed)
            self.assertIn(0, got["drums"]["steps"][0])

    def test_forbid_removes_a_step_the_odds_produced(self):
        for seed in range(60):
            got = ss.sample_entry(self._style(
                [{"path": "drums.steps.0", "forbid": [0, 2, 4]}]), seed)
            self.assertFalse({0, 2, 4} & set(got["drums"]["steps"][0]))

    def test_a_rule_leaves_the_list_sorted_and_without_repeats(self):
        got = ss.sample_entry(self._style(
            [{"path": "drums.steps.0", "require": [0, 4]}]), 3)
        steps = got["drums"]["steps"][0]
        self.assertEqual(steps, sorted(set(steps)))

    def test_clamp_bounds_a_scalar_the_odds_overshot(self):
        for seed in range(60):
            got = ss.sample_entry(self._style(
                [{"path": "tempo", "clamp": [120, 125]}]), seed)
            self.assertTrue(120 <= got["tempo"] <= 125)

    def test_fixed_wins_over_the_odds(self):
        for seed in range(20):
            got = ss.sample_entry(self._style([{"path": "tempo", "fixed": 125}]), seed)
            self.assertEqual(got["tempo"], 125)

    def test_a_rule_carrying_two_operators_is_refused(self):
        with self.assertRaises(ValueError):
            ss.apply_rules({"tempo": 120},
                           [{"path": "tempo", "clamp": [1, 2], "fixed": 3}])

    def test_a_rule_carrying_no_operator_is_refused(self):
        with self.assertRaises(ValueError):
            ss.apply_rules({"tempo": 120}, [{"path": "tempo"}])

    def test_an_empty_clamp_is_refused(self):
        with self.assertRaises(ValueError):
            ss.apply_rules({"tempo": 120}, [{"path": "tempo", "clamp": [130, 120]}])

    def test_rules_and_variants_do_not_reach_the_sampled_entry(self):
        # They are style bookkeeping. The builder must never see them.
        got = ss.sample_entry({"tempo": 125, "variants": 4,
                               "rules": [{"path": "tempo", "fixed": 120}]}, 1)
        self.assertEqual(got, {"tempo": 120})

    def test_a_rule_addresses_a_list_by_index(self):
        got = ss.apply_rules({"voices": {"velo": [10, 20, 30]}},
                             [{"path": "voices.velo.1", "fixed": 99}])
        self.assertEqual(got["voices"]["velo"], [10, 99, 30])


# --- the blend, which is the part that matters ------------------------------

class WhatMayNotBeAveraged(unittest.TestCase):

    def test_the_table_matches_the_engineering_verdict(self):
        for path in ("root", "scale", "voices.register", "voices.register.0",
                     "drums.steps", "drums.steps.2.0", "voices.rhythm_reg.1",
                     "drums.kits.0", "voices.engines.2", "fx.0",
                     "overrides.0.engine", "mods.3.depth"):
            self.assertIsNotNone(ss.group_for(path), path)

    def test_the_ordered_scalars_are_averageable(self):
        # `drums.gate` and `voices.gate` LEFT this list on 2026-09-04 - they
        # travel with `div` now, because a step is not a fixed length any more.
        for path in ("tempo", "drums.velo.0", "voices.velo.1",
                     "voices.octave.0", "voices.range.1",
                     "voices.length.0"):
            self.assertIsNone(ss.group_for(path), path)

    def test_a_field_is_not_grouped_by_a_partial_name_match(self):
        # "root" must not capture "rootless"; matching is per path segment.
        self.assertIsNone(ss.group_for("rootless"))
        self.assertIsNone(ss.group_for("drums.stepsize"))


class TheBlendNeverInventsAValue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.genre = load(GENRE)
        cls.drone = load(DRONE)

    def _pairs(self):
        g, d = self.genre, self.drone
        return [(g[0], g[7]), (g[3], g[20]), (g[11], g[40]),
                (g[0], d[0]), (d[2], d[9]), (d[0], g[30])]

    def test_no_non_averageable_field_is_ever_a_new_value(self):
        # The headline. Every leaf under a whole-from-one-parent group must be
        # BYTE-equal to one parent, at every t and every seed.
        for a, b in self._pairs():
            for t in (0.0, 0.2, 0.5, 0.8, 1.0):
                for seed in (0, 1, 5, 41):
                    out = ss.blend(a, b, t, seed)
                    for path, value in leaf_paths(out):
                        if path.startswith("blend_"):
                            continue
                        group = ss.group_for(path)
                        if group is None:
                            continue
                        parent = a if out["blend_taken_whole"][group] == "a" else b
                        self.assertEqual(value, self._at(parent, path),
                                         f"{path} at t={t} seed={seed}")

    @staticmethod
    def _at(entry, path):
        node = entry
        for part in path.split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node

    def test_a_whole_group_comes_from_ONE_parent_together(self):
        # scale from A and register from B gives a melody built for a
        # different scale. The group boundary is the design.
        a, b = self.genre[0], self.genre[25]
        self.assertNotEqual((a["root"], a["scale"]), (b["root"], b["scale"]))
        for seed in range(40):
            out = ss.blend(a, b, 0.5, seed)
            parent = a if out["blend_taken_whole"]["tonality"] == "a" else b
            self.assertEqual(out["root"], parent["root"])
            self.assertEqual(out["scale"], parent["scale"])
            self.assertEqual(out["voices"]["register"], parent["voices"]["register"])

    def test_the_insert_pair_is_never_mixed_from_two_parents(self):
        # The pair sits on ALL EIGHT chains and six plugins are banned at that
        # count, two Dragonfly reverbs stacked among them. A per-slot coin
        # could assemble a banned pair out of two legal parents.
        # EVERY SHIPPED ENTRY IS TAP + TAP SINCE 2026-09-04 - the role change
        # made the whole plugin palette reachable and the rebuild took the one
        # pair that supplies both roles on every chain - so no two shipped
        # entries differ in either slot and this has to build its parents.
        # That is the point of the test, not a weakness of it: the coin must
        # hold for pairs a future style could produce.
        left = ["JV/TAP Stereo Echo", "JV/Modulay", "JV/GxEcho-Stereo"]
        right = ["JV/TAP Reverberator", "JV/Tal-Reverb-III",
                 "JV/Dragonfly Room Reverb"]
        pairs = [({"fx": [la, ra]}, {"fx": [lb, rb]})
                 for la in left for ra in right
                 for lb in left for rb in right
                 if la != lb and ra != rb]
        self.assertGreater(len(pairs), 20)
        for a, b in pairs:
            for seed in (0, 3, 8):
                out = ss.blend(a, b, 0.5, seed)
                self.assertIn(out["fx"], (a["fx"], b["fx"]))

    def test_a_groove_is_taken_whole_not_unioned_or_averaged(self):
        # THE SHIPPED PACKS CARRY THE EUCLID FORM SINCE 2026-09-04 - hits and
        # rotate rather than a literal step list - so this is the same
        # assertion on the field that now holds the groove. A rotation is
        # written FOR its hit count, which is why they share one coin.
        a, b = self.genre[0], self.genre[6]
        for seed in range(30):
            out = ss.blend(a, b, 0.5, seed)
            self.assertIn(out["drums"]["hits"],
                          (a["drums"]["hits"], b["drums"]["hits"]))
            self.assertIn(out["drums"]["rotate"],
                          (a["drums"]["rotate"], b["drums"]["rotate"]))

    def test_a_literal_step_list_is_still_taken_whole(self):
        # The legacy form still builds, so it still has to blend correctly.
        a = {"drums": {"steps": [[0, 4], [], [], [], []]}}
        b = {"drums": {"steps": [[2, 6, 10], [], [], [], []]}}
        for seed in range(30):
            out = ss.blend(a, b, 0.5, seed)
            self.assertIn(out["drums"]["steps"],
                          (a["drums"]["steps"], b["drums"]["steps"]))

    def test_a_register_is_taken_whole_not_bit_mixed(self):
        a, b = self.genre[0], self.genre[9]
        for seed in range(30):
            out = ss.blend(a, b, 0.5, seed)
            self.assertIn(out["voices"]["rhythm_reg"],
                          (a["voices"]["rhythm_reg"], b["voices"]["rhythm_reg"]))

    def test_a_field_only_one_parent_has_obeys_that_group_s_coin(self):
        # The drone pack carries `overrides` and `mods`; the genre pack does
        # not. A blend that reports `overrides<-A` must not come back holding
        # B's overrides, or the report is a lie.
        a, b = self.genre[0], self.drone[0]
        self.assertNotIn("overrides", a)
        self.assertIn("overrides", b)
        for seed in range(30):
            out = ss.blend(a, b, 0.5, seed)
            self.assertEqual("overrides" in out,
                             out["blend_taken_whole"]["overrides"] == "b")

    def test_a_nested_field_only_one_parent_has_obeys_its_group_coin(self):
        # The same rule one level down. No shipped pair exercises this - the
        # packs agree on the shape of `drums` and `voices` - so it is proved
        # here rather than left as unreachable code.
        a = {"voices": {"rhythm_reg": [1, 2, 3], "velo": [10, 10, 10]}}
        b = {"voices": {"velo": [20, 20, 20]}}
        outcomes = set()
        for seed in range(40):
            out = ss.blend(a, b, 0.5, seed)
            self.assertEqual("rhythm_reg" in out["voices"],
                             out["blend_taken_whole"]["rhythm"] == "a")
            outcomes.add(out["blend_taken_whole"]["rhythm"])
        self.assertEqual(outcomes, {"a", "b"})

    def test_a_blend_of_two_shipped_styles_still_validates(self):
        for a, b in self._pairs():
            for seed in (0, 6):
                out = ss.blend(a, b, 0.5, seed)
                out["file"], out["title"] = "900-x", "X"
                ss.validate_entry(out)


class TheBlendEndpointsAndTheAverages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.genre = load(GENRE)

    def _core(self, entry):
        return {k: v for k, v in entry.items() if not k.startswith("blend_")}

    def test_t_zero_returns_the_first_parent_exactly(self):
        a, b = self.genre[0], self.genre[30]
        for seed in (0, 4, 77):
            self.assertEqual(self._core(ss.blend(a, b, 0.0, seed)), a)

    def test_t_one_returns_the_second_parent_exactly_but_for_its_name(self):
        a, b = self.genre[0], self.genre[30]
        out = self._core(ss.blend(a, b, 1.0, 4))
        for key in ss.IDENTITY_FIELDS:
            out.pop(key, None)
        self.assertEqual(out, {k: v for k, v in b.items()
                               if k not in ss.IDENTITY_FIELDS})

    def test_blending_a_style_with_itself_is_that_style(self):
        for entry in self.genre[:10]:
            for t in (0.0, 0.5, 1.0):
                out = self._core(ss.blend(entry, entry, t, 11))
                for key in ss.IDENTITY_FIELDS:
                    out.setdefault(key, entry.get(key))
                self.assertEqual(out, entry, entry["file"])

    def test_an_ordered_scalar_lands_between_the_parents(self):
        a = {"drums": {"velo": [100]}, "voices": {"octave": [0]}}
        b = {"drums": {"velo": [80]}, "voices": {"octave": [2]}}
        out = ss.blend(a, b, 0.5, 0)
        self.assertEqual(out["drums"]["velo"], [90])
        self.assertEqual(out["voices"]["octave"], [1])

    def test_a_gate_travels_with_its_division(self):
        # GATE STOPPED BEING AVERAGEABLE ON 2026-09-04, when `div` became a
        # manifest field. `gate` is hundredths of a STEP, and a step is a 1/16
        # at one division and a whole BEAT at another - so taking `div` from
        # one parent and averaging `gate` between two changes every note
        # length by up to four times, in a file where nothing says why. They
        # share one coin now, which is the same argument the module already
        # makes for a register and its scale.
        a = {"div": ["1/16"] * 8, "voices": {"gate": [40, 40, 40]}}
        b = {"div": ["1/4"] * 8, "voices": {"gate": [800, 800, 800]}}
        for seed in range(20):
            out = ss.blend(a, b, 0.5, seed)
            self.assertIn((out["div"], out["voices"]["gate"]),
                          ((a["div"], a["voices"]["gate"]),
                           (b["div"], b["voices"]["gate"])))

    def test_an_interpolated_integer_stays_an_integer(self):
        out = ss.blend({"drums": {"velo": [100]}}, {"drums": {"velo": [81]}}, 0.5, 0)
        self.assertIsInstance(out["drums"]["velo"][0], int)

    def test_the_blend_records_where_every_whole_group_came_from(self):
        out = ss.blend(self.genre[0], self.genre[1], 0.5, 3)
        self.assertEqual(set(out["blend_taken_whole"]), set(ss.WHOLE_GROUPS))
        self.assertTrue(set(out["blend_taken_whole"].values()) <= {"a", "b"})
        self.assertEqual(out["blend_of"],
                         [self.genre[0]["file"], self.genre[1]["file"]])

    def test_t_outside_zero_to_one_is_refused(self):
        for t in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                ss.blend(self.genre[0], self.genre[1], t, 0)


class TheTempoIsTheInterestingCase(unittest.TestCase):

    def test_the_exact_tempi_are_the_divisors_of_thirty_thousand(self):
        # zynseq truncates frames-per-clock with no accumulator; at 48 kHz the
        # error is the fractional part of 30000/tempo.
        for tempo in ss.EXACT_TEMPI:
            self.assertEqual(30000 % tempo, 0)
        for tempo in (50, 60, 75, 80, 100, 120, 125):
            self.assertIn(tempo, ss.EXACT_TEMPI)
        for tempo in (124, 126, 137, 139, 119, 121):
            self.assertNotIn(tempo, ss.EXACT_TEMPI)

    def test_two_parents_on_one_tempo_keep_it_even_when_it_is_inexact(self):
        # 057-trance-acid keeps 137 and its 4,487 ppm on purpose: at that
        # distance the tempo is the identity, not a default. Nothing was
        # invented here, so nothing may be snapped.
        self.assertEqual(ss.blend_tempo(137, 137, 0.5), 137)
        self.assertEqual(ss.blend_tempo(124, 124, 0.5), 124)

    def test_an_invented_tempo_within_a_bpm_of_an_exact_one_snaps_to_it(self):
        # The pack's own distance rule, 2026-08-22.
        self.assertEqual(ss.blend_tempo(124, 126, 0.5), 125)
        self.assertEqual(ss.blend_tempo(119, 121, 0.5), 120)

    def test_an_invented_tempo_further_away_is_left_where_it_landed(self):
        self.assertEqual(ss.blend_tempo(125, 137, 0.5), 131)
        self.assertEqual(ss.blend_tempo(130, 140, 0.5), 135)

    def test_an_endpoint_keeps_the_parent_s_own_tempo_unsnapped(self):
        # t=0 must give back A untouched, even when A is 1 BPM off exact.
        self.assertEqual(ss.blend_tempo(124, 137, 0.0), 124)
        self.assertEqual(ss.blend_tempo(137, 124, 1.0), 124)

    def test_a_blended_tempo_is_always_a_whole_number(self):
        for t in (0.1, 0.33, 0.5, 0.67, 0.9):
            self.assertIsInstance(ss.blend_tempo(122, 139, t), int)

    def test_the_snap_window_is_a_distance_rule_not_a_ppm_rule(self):
        self.assertEqual(ss.exact_tempo_near(124.6), 125)
        self.assertIsNone(ss.exact_tempo_near(123.0))
        self.assertIsNone(ss.exact_tempo_near(137.0))


# --- validation -------------------------------------------------------------

class Validation(unittest.TestCase):

    def setUp(self):
        self.entry = copy.deepcopy(load(GENRE)[0])

    def legacy(self):
        """The same entry in the pre-2026-09-04 literal-step form. The shipped
        packs are all euclid now, so a test about `steps` has to build one."""
        e = copy.deepcopy(self.entry)
        d = e["drums"]
        for key in ("hits", "rotate", "rhythm_reg", "hand_reg"):
            d.pop(key, None)
        d["steps"] = [[0, 4, 8, 12], [4, 12], [4, 12], [2, 6, 10, 14], [6, 14]]
        return e

    def test_a_banned_insert_is_refused(self):
        # Six plugins are banned at eight instances and the pair is on every
        # chain. notes/traps/PLUGINS.md
        for banned in ("JV/Aether", "JV/CHOWTapeModel", "JV/ChowPhaserStereo",
                       "JV/Roboverb", "JV/SO-kl5"):
            self.entry["fx"] = [banned, "JV/TAP Reverberator"]
            with self.assertRaises(ValueError, msg=banned):
                ss.validate_entry(self.entry)

    def test_two_dragonfly_reverbs_stacked_are_refused(self):
        self.entry["fx"] = ["JV/Dragonfly Hall Reverb", "JV/Dragonfly Room Reverb"]
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_one_dragonfly_is_fine(self):
        self.entry["fx"] = ["JV/Calf Vinyl", "JV/Dragonfly Hall Reverb"]
        ss.validate_entry(self.entry)

    def test_an_entry_still_holding_odds_is_refused(self):
        # Sampling is not optional; a distribution reaching the builder would
        # be written into a .zss as a dict.
        self.entry["tempo"] = odds(range=[120, 130])
        with self.assertRaisesRegex(ValueError, "odds"):
            ss.validate_entry(self.entry)

    def test_a_missing_required_field_is_refused(self):
        del self.entry["voices"]
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_wrong_channel_count_is_refused(self):
        self.entry["drums"]["velo"] = [100, 100]
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_step_outside_the_sixteen_is_refused(self):
        e = self.legacy()
        e["drums"]["steps"][0] = [0, 16]
        with self.assertRaises(ValueError):
            ss.validate_entry(e)

    def test_a_repeated_step_is_refused(self):
        e = self.legacy()
        e["drums"]["steps"][0] = [0, 0, 4]
        with self.assertRaises(ValueError):
            ss.validate_entry(e)

    def test_a_hit_count_past_the_bar_is_refused(self):
        self.entry["drums"]["hits"][0] = 17
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_rotation_past_the_bar_is_refused(self):
        self.entry["drums"]["rotate"][0] = 16
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_negative_swing_is_refused(self):
        self.entry.setdefault("groove", {})["swing"] = [-0.1] + [0.0] * 7
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_mix_that_is_not_eight_long_is_refused(self):
        self.entry["mix"] = [0.5] * 7
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_fader_outside_unity_is_refused(self):
        self.entry["mix"] = [1.4] + [0.5] * 7
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_a_root_outside_the_octave_is_refused(self):
        self.entry["root"] = 12
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)

    def test_an_fx_list_that_is_not_a_pair_is_refused(self):
        self.entry["fx"] = ["JV/TAP Stereo Echo"]
        with self.assertRaises(ValueError):
            ss.validate_entry(self.entry)


# --- it has to reach a .zss -------------------------------------------------

class TheOutputIsAnOrdinaryManifest(unittest.TestCase):
    """The deliverable is only real if the existing builder eats it unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.builder = importlib.import_module("build-genre-snapshots")
        with open(os.path.join(REPO, "snapshot", "017-generative-techno.zss")) as fh:
            cls.base = json.load(fh)
        with open(os.path.join(TOOLS, "drum-kit-notes.json")) as fh:
            cls.kits = json.load(fh)["notes"]

    def test_a_sampled_entry_builds_a_snapshot(self):
        entry = ss.sample_entry(load(EXAMPLE)[0], 1234)
        entry["file"] = "900-style-house-v1"
        built = self.builder.build_one(self.base, entry, self.kits)
        blocks = self.builder.parse_blocks(
            __import__("base64").b64decode(built["zynseq_riff_b64"]))
        self.assertEqual(len([b for b in blocks if b[0] == "patn"]), 8)
        self.assertEqual(
            built["zs3"]["zs3-0"]["midi_capture"][self.builder.CTRLDEV_PORT]
                 ["ctrldev_state"]["globals"]["bpm"], entry["tempo"])

    def test_every_kit_a_style_can_draw_is_a_kit_that_exists(self):
        # A kit the scan does not know is a silent channel.
        for seed in range(30):
            entry = ss.sample_entry(load(EXAMPLE)[0], seed)
            for kit in entry["drums"]["kits"]:
                self.assertIn(kit, self.kits)

    def test_a_blend_builds_a_snapshot_too(self):
        genre = load(GENRE)
        out = ss.blend(genre[0], genre[30], 0.5, 5)
        out["file"], out["title"] = "901-blend", "Blend"
        built = self.builder.build_one(self.base, out, self.kits)
        self.assertEqual(built["zs3"]["zs3-0"]["title"], "Blend")

    def test_the_sampled_entry_carries_the_seed_that_made_it(self):
        # Traceability: a produced .zss must be re-derivable from its manifest.
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ss.main(["sample", "--style", EXAMPLE, "--variants", "2",
                     "--seed", "500", "--out", "-"])
        entries = json.loads(buf.getvalue()[buf.getvalue().index("["):])
        self.assertEqual([e["style_seed"] for e in entries], [500, 501])
        self.assertEqual([e["style_of"] for e in entries],
                         ["900-style-house", "900-style-house"])
        self.assertEqual(entries[0], {**ss.sample_entry(load(EXAMPLE)[0], 500),
                                      "file": "900-style-house-v1",
                                      "title": "House, as odds v1",
                                      "style_of": "900-style-house",
                                      "style_seed": 500})


if __name__ == "__main__":
    unittest.main()
