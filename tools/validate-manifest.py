#!/usr/bin/env python3
"""Check a pack manifest against what the instrument will actually PLAY.

    python3 tools/validate-manifest.py --manifest snapshot/drone-ambient-manifest.json
    python3 tools/validate-manifest.py --manifest x.json --family drone --verbose

Exit status is 0 when every entry passes and 1 when any check fails, so this
belongs in front of a rebuild the way `docs-gate.py` belongs in front of a
commit.

WHY IT EXISTS. The shipped packs passed every test this repository had, and
they were still wrong: eight channels attacking the same step, a minor second
sustained at 73 Hz, two voices in exact unison, a bass that played the flat
seventh sixteen times a bar and never the root. None of that is a code defect -
each file was exactly what its manifest asked for. **What was missing was a
check on the MUSIC**, and it has to render the notes to find any of it, because
a manifest holds shift registers and a mask, not pitches.

WHAT IT CANNOT DO. It says nothing about whether a preset is any good. It
catches the faults that are arithmetic - collisions, mud, density, a value that
cannot mean what it says - and leaves taste to the ear gate. A clean report is
the floor, not the verdict.

THE CHECKS, and what each one is for:

* **SIMULTANEOUS INTERVALS.** Two notes SOUNDING AT THE SAME TIME closer than
  the critical band at that register are not heard as two notes; they are heard
  as one rough tone beating. Keyed on the LOWER note, because the band widens
  as it descends. An octave or more is always safe.
* **ATTACK COLLISIONS.** Note-ons landing on the same instant weld their
  timbres into one click and put the whole transient budget in one place.
* **UNISONS.** Two channels on the same pitch is not a thicker sound, it is a
  detune artefact and a channel spent for nothing.
* **THE LOW REGISTER.** At most one channel below MIDI 48, plus its own octave.
  Two things fighting for 65-123 Hz is mud and the loser is the kick.
* **ONSET BUDGET.** A 16-step bar over eight channels is 128 slots; above
  about a quarter of them the ear stops tracking parts and hears texture.
* **STEPS INSIDE THE DIVISION.** A step list written for 1/16 lands in the
  wrong bar at 1/4, and 1/8T has twelve steps, not sixteen.
* **KIT NOTE COLLISIONS.** Ten of the 38 usable kits hand two channels the
  same note; two shipped presets play snare and clap as one sample on
  identical steps.
* **A LEVEL MODULATOR AGAINST ITS FADER.** A `level` modulator overwrites the
  mixer strip within 200 ms of load, so its `base` must equal 100x the fader
  or the mix on disk is not the mix you hear.
* **INSERTS THAT SERVE NO ROLE.** A chain whose pair cannot supply a reverb or
  a delay has dead knobs, inert modulators and four dead globals.
* **A MODULATOR ON A VERB THAT REWRITES THE PATTERN**, and one whose rate is
  faster than the ~200 ms poll tick can render.
* **CHORD WHERE IT DRAWS DEAD** - on a sampler, and above the burst cap.
"""

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ctrldev"))

from techno_lib import techno_lib as tlib                 # noqa: E402
from maschine_mk2_lib import maschine_mk2_lib as lib      # noqa: E402

CHANNELS = "ABCDEFGH"
CYCLE_BEATS = 16.0          # four bars, the longest loop a division can make

# Onsets per bar, and the most channels allowed to share one step. Numbers from
# notes/plans/2026-09-04-musical-rebuild-of-the-preset-packs.md, which argues
# each one; they are counted out of a real groove rather than picked.
BUDGET = {
    "house":   {"onsets": 26, "per_step": 3, "low": 1},
    "deep":    {"onsets": 20, "per_step": 3, "low": 1},
    "minimal": {"onsets": 14, "per_step": 2, "low": 1},
    "dub":     {"onsets": 12, "per_step": 2, "low": 1},
    # TRANCE IS FOUR, NOT THREE, and the number was corrected by rendering
    # one. Trance layers its snare and its clap on the backbeat deliberately,
    # and its kick and its bass are both four-on-the-floor - so beats 1 and 3
    # carry kick + snare + clap + bass with nothing wrong. Three was reasoned
    # from the transient budget and is simply not reachable by the genre; the
    # answer is to spread the MELODIC parts off the backbeat, which is what
    # the rebuilt entries do, rather than to thin the drums until it stops
    # sounding like trance.
    "trance":  {"onsets": 30, "per_step": 4, "low": 1},
    "drone":   {"onsets": 6,  "per_step": 1, "low": 1},
    "ambient": {"onsets": 10, "per_step": 2, "low": 1},
    "space":   {"onsets": 8,  "per_step": 2, "low": 1},
}
DEFAULT_BUDGET = {"onsets": 30, "per_step": 3, "low": 1}


def min_interval(lower):
    """Minimum safe gap in semitones for two SUSTAINED notes, keyed on the
    lower one. Only consulted below an octave - an octave or wider is always
    safe, and a first version that returned a huge number down low flagged
    notes four octaves apart as a clash."""
    if lower < 36:
        return 12
    if lower < 48:
        return 7
    if lower < 60:
        return 3
    if lower < 72:
        return 2
    return 1


def note_name(note):
    return f"{tlib.NOTE_NAMES[note % 12]}{note // 12 - 1}"


def div_index(name):
    if isinstance(name, int):
        return name
    for i, (label, _spb, _beats) in enumerate(lib.DIVISIONS):
        if label == name:
            return i
    raise ValueError(f"unknown division {name!r}")


class Channel:
    """One channel as the instrument will play it."""

    def __init__(self, index, kind, div_idx):
        self.index = index
        self.name = CHANNELS[index]
        self.kind = kind                  # "drum" or "voice"
        self.div = div_idx
        label, self.spb, self.beats = lib.DIVISIONS[div_idx]
        self.div_label = label
        self.steps = self.spb * self.beats
        self.mask = [False] * self.steps
        self.notes = [()] * self.steps    # a tuple per step
        self.gate = 0
        self.velo = 0
        self.engine = None


def _voice_channel(index, div_idx, params, root, scale, is_sampler=False):
    ch = Channel(index, "voice", div_idx)
    reg = int(params["register"])
    length = int(params["length"])
    shape = 0 if is_sampler else int(params.get("chord", 0) or 0)
    rr = int(params["rhythm_reg"])
    ch.mask = [bool(rr >> s & 1) for s in range(ch.steps)]
    ch.notes = list(tlib.chord_line(reg, length, ch.steps, root, scale,
                                    int(params["octave"]),
                                    int(params["range"]), shape))
    ch.gate = int(params["gate"])
    ch.velo = int(params["velo"])
    return ch


def _drum_channel(index, div_idx, entry, note, drums_euclid):
    ch = Channel(index, "drum", div_idx)
    if drums_euclid is not None:
        pattern = lib.rotate(lib.euclid(ch.steps, drums_euclid[index]["hits"]),
                             drums_euclid[index]["rotate"])
        rr = drums_euclid[index]["rhythm_reg"]
        hand = drums_euclid[index]["hand_reg"]
        steps = [s for s in range(ch.steps)
                 if (pattern[s] and rr >> s & 1) or (hand >> s & 1)]
    else:
        steps = entry["drums"]["steps"][index]
    for s in steps:
        if not 0 <= s < ch.steps:
            raise ValueError(
                f"channel {CHANNELS[index]} step {s} outside 0..{ch.steps - 1} "
                f"at {ch.div_label}")
        ch.mask[s] = True
        ch.notes[s] = (note,) if note is not None else ()
    ch.gate = entry["drums"]["gate"][index]
    ch.velo = entry["drums"]["velo"][index]
    return ch


def render(entry, kit_notes):
    """Every channel of one manifest entry, as notes on a grid."""
    root, scale = int(entry["root"]), int(entry["scale"])
    overrides = {int(k): v for k, v in (entry.get("overrides") or {}).items()}
    divs = entry.get("div")
    divs = ([div_index(x) for x in divs] if divs is not None
            else [div_index("1/16")] * 8)
    drums = entry.get("drums") or {}
    drums_euclid = None
    if "hits" in drums:
        drums_euclid = [{
            "hits": drums["hits"][i],
            "rotate": (drums.get("rotate") or [0] * 5)[i],
            "rhythm_reg": (drums.get("rhythm_reg") or [0xFFFF] * 5)[i],
            "hand_reg": (drums.get("hand_reg") or [0] * 5)[i],
        } for i in range(5)]

    out = []
    for i in range(5):
        over = overrides.get(i)
        if over:
            # An overridden channel that keeps LinuxSampler is a SAMPLER walked
            # by a register, and a note number there picks a DRUM - so chord
            # draws dead and the pitches are kit notes, not scale degrees. We
            # cannot resolve a kit walk offline (it needs the .sfz keymap), so
            # such a channel contributes onsets but no pitches.
            sampler = not over.get("engine")
            ch = _voice_channel(i, divs[i], over, root, scale, sampler)
            ch.engine = over.get("engine")
            if sampler:
                ch.notes = [() for _ in range(ch.steps)]
            out.append(ch)
            continue
        kit = drums["kits"][i]
        note = (kit_notes.get(kit) or [None] * 5)[i]
        out.append(_drum_channel(i, divs[i], entry, note, drums_euclid))
    v = entry["voices"]
    for i in range(3):
        params = {k: v[k][i] for k in ("register", "length", "rhythm_reg",
                                       "octave", "range", "velo", "gate")}
        if "chord" in v:
            params["chord"] = v["chord"][i]
        ch = _voice_channel(5 + i, divs[5 + i], params, root, scale)
        ch.engine = v["engines"][i]
        out.append(ch)
    return out


def events(channels, pitched_only=False):
    """(start_beat, end_beat, channel, note) over the four-bar cycle.

    `pitched_only` drops the drum channels, and it is not an optimisation.
    **A DRUM CHANNEL'S NOTE NUMBER IS A SAMPLE SELECTOR, NOT A PITCH** - the
    SFZ kits map key= to different drums, so a closed hat is "note 42" and is
    not a 93 Hz tone. Comparing it against a bass note as if both were pitches
    is arithmetic on two different units, and the first version of this file
    did exactly that: every CR78 kit has its percussion on notes 36-44, so a
    hat "clashed" with the bass on thirteen of twenty entries and the fix
    would have been to move a bassline that was already right.

    Density, attacks and kit-note collisions still count every channel - those
    are about WHEN a channel fires, which is the same question for both kinds.
    """
    out = []
    for ch in channels:
        if pitched_only and ch.kind == "drum":
            continue
        for rep in range(max(1, int(round(CYCLE_BEATS / ch.beats)))):
            for step in range(ch.steps):
                if not ch.mask[step]:
                    continue
                start = rep * ch.beats + step / ch.spb
                dur = tlib.note_duration(ch.gate, step, ch.steps,
                                         ch.mask) / ch.spb
                for note in ch.notes[step]:
                    out.append((start, start + dur, ch, note))
    return out


def check(entry, kit_notes, budget=None):
    """[(severity, message), ...] - empty when the entry is clean."""
    problems = []

    def bad(msg):
        problems.append(("FAIL", msg))

    def warn(msg):
        problems.append(("WARN", msg))

    try:
        channels = render(entry, kit_notes)
    except ValueError as exc:
        return [("FAIL", str(exc))]

    limits = budget or BUDGET.get(entry.get("genre"), DEFAULT_BUDGET)
    mix = entry.get("mix")
    evs = events(channels)
    pitched = events(channels, pitched_only=True)

    # --- simultaneous intervals, unisons included -------------------------
    # PITCHED CHANNELS ONLY - see events(). A drum's note number is a sample
    # selector and has no register.
    seen = set()
    for a in range(len(pitched)):
        s1, e1, c1, n1 = pitched[a]
        for b in range(a + 1, len(pitched)):
            s2, e2, c2, n2 = pitched[b]
            if c1 is c2:
                continue
            if min(e1, e2) - max(s1, s2) <= 1e-9:
                continue
            lo, hi = sorted((n1, n2))
            gap = hi - lo
            if gap >= 12:
                continue
            if gap < min_interval(lo):
                key = (c1.name, n1, c2.name, n2, gap)
                if key in seen:
                    continue
                seen.add(key)
                what = "UNISON" if gap == 0 else f"gap {gap}"
                bad(f"{c1.name} {note_name(n1)} vs {c2.name} {note_name(n2)}: "
                    f"{what}, need {min_interval(lo)} at this register")

    # --- attacks ----------------------------------------------------------
    #
    # A CARPET DOES NOT COUNT, and this exclusion was forced by rendering real
    # grooves rather than reasoning about them. A channel sounding on half its
    # steps or more - a straight eighth hat, a sixteenth shaker - already
    # occupies a slot on EVERY beat, so counting it leaves the budget one
    # smaller everywhere and the classic house bar (kick, rimshot and clap
    # together on the four, with a hat running underneath) reads as four
    # simultaneous attacks when musically it is three plus texture.
    #
    # The budget is about TRANSIENTS competing for the same instant. A hat is
    # high, short and quiet; it is not what makes a downbeat a thud. So a
    # carpet is excluded here and still counted in full by the onset budget
    # below, which is the check that actually cares about density.
    carpets = {ch.name for ch in channels
               if sum(1 for s in range(ch.steps) if ch.mask[s]) * 2 >= ch.steps
               and any(ch.mask)}
    attacks = collections.defaultdict(set)
    for start, _end, ch, _note in evs:
        attacks[round(start, 4)].add(ch.name)
    for moment, names in sorted(attacks.items()):
        counted = names - carpets
        if len(counted) > limits["per_step"]:
            bad(f"beat {moment:g}: {len(counted)} channels attack together "
                f"({''.join(sorted(counted))}), budget {limits['per_step']}"
                + (f" [{''.join(sorted(names & carpets))} is a carpet]"
                   if names & carpets else ""))

    # --- onsets per bar ---------------------------------------------------
    onsets = sum(1 for ch in channels for s in range(ch.steps) if ch.mask[s]
                 for _ in range(max(1, int(round(CYCLE_BEATS / ch.beats)))))
    per_bar = onsets / (CYCLE_BEATS / 4.0)
    if per_bar > limits["onsets"]:
        bad(f"{per_bar:.1f} onsets/bar over budget {limits['onsets']}")

    # --- the low register -------------------------------------------------
    # Pitched only, for the same reason: a kick IS meant to be down there and
    # its note number says nothing about where.
    low = sorted({ch.name for _s, _e, ch, note in pitched if note < 48})
    if len(low) > limits["low"] + 1:
        bad(f"{len(low)} channels below MIDI 48 ({''.join(low)}), "
            f"budget {limits['low']} plus its octave")

    # --- the board -------------------------------------------------------
    # A FLAT MIX IS NOT NEUTRAL, IT IS THE ABSENCE OF A DECISION, and it is
    # what all 71 shipped presets had: every fader at 0.19, inherited from the
    # base and never touched. Eight things at one loudness is resolved by the
    # ear as whichever is spectrally busiest, which is why the packs sounded
    # like hats over mud.
    if mix is None:
        bad("no `mix` - every fader inherits the base's, which is how 71 "
            "presets shipped with a flat board")
    elif len(set(round(m, 3) for m in mix)) == 1:
        bad(f"every fader is {mix[0]:.2f} - a flat board is the absence of a "
            f"decision, not a neutral starting point")

    # --- does anything outlive a bar? -------------------------------------
    # For a drone or an ambient piece this is THE fault. `note_duration`
    # clamps a note to the loop point, so at 1/16 the longest note the
    # instrument can hold is 8 of 16 steps - half a bar. All twenty shipped
    # drone presets sat at gate 800 on a 1/16 grid and therefore played half a
    # bar of sound, half a bar of hole, and then re-attacked: a pulse wearing
    # a drone's name. The lever is DIVISION, and it was unreachable from a
    # manifest until the builder grew it.
    if entry.get("genre") in ("drone", "ambient"):
        longest = max((ch.beats for ch in channels
                       if any(ch.mask) and ch.kind == "voice"), default=0)
        if longest < 8:
            bad("no pitched layer outlives one bar - at 1/16 a note cannot "
                "sustain past half a bar, so this is a pulse, not a drone. "
                "Give a layer 1/8 (two bars) or 1/4 (four)")

    # --- kit note collisions ----------------------------------------------
    drums = entry.get("drums") or {}
    overrides = {int(k) for k in (entry.get("overrides") or {})}
    for i in range(5):
        for j in range(i + 1, 5):
            if i in overrides or j in overrides:
                continue
            kits = drums.get("kits") or []
            if len(kits) <= max(i, j) or kits[i] != kits[j]:
                continue
            notes = kit_notes.get(kits[i])
            if not notes or notes[i] != notes[j]:
                continue
            shared = sorted(set(s for s in range(channels[i].steps)
                                if channels[i].mask[s])
                            & set(s for s in range(channels[j].steps)
                                  if channels[j].mask[s]))
            if shared:
                bad(f"{CHANNELS[i]} and {CHANNELS[j]} are both note "
                    f"{notes[i]} on {kits[i]} and share steps {shared} - "
                    f"one sample played twice")

    # --- a level modulator against its fader ------------------------------
    for mod in entry.get("mods") or ():
        chan, verb = int(mod["channel"]), mod["verb"]
        # MOD_TIMBRE is the set that does NOT rewrite a pattern. A DRIFT verb
        # is legal too but only at the wrap, and no shipped manifest uses one -
        # so anything outside MOD_TIMBRE here is a modulator that would thrash
        # zynseq under a lock, or a verb that does not exist at all.
        if verb not in tlib.MOD_TIMBRE:
            bad(f"modulator on {verb!r}, which rewrites the pattern or does "
                f"not exist - allowed: {sorted(tlib.MOD_TIMBRE)}")
        rate = int(mod.get("rate", 0))
        if not 0 <= rate < len(tlib.MOD_RATES):
            bad(f"{CHANNELS[chan]}|{verb} rate index {rate} out of range")
        if verb == "level" and mix is not None:
            want = round(mix[chan] * 100)
            if abs(want - int(mod["base"])) > 1:
                bad(f"{CHANNELS[chan]}|level base {mod['base']} but fader "
                    f"{mix[chan]:.2f} (= {want}) - the modulator overwrites "
                    f"the fader within 200 ms, so the mix on disk is not the "
                    f"mix you hear")

    # --- inserts ----------------------------------------------------------
    roles = set()
    for plugin in entry.get("fx") or ():
        bare = str(plugin).split("/")[-1]
        found = tlib.fx_role_of(bare)
        if found is None:
            if bare not in tlib.FX_NO_ROLE:
                bad(f"insert {bare!r} is in neither FX_ROLES nor FX_NO_ROLE")
            continue
        roles.add(found[1]["role"])
    for role in ("reverb", "delay"):
        if role not in roles:
            warn(f"no insert can serve as a {role} - that verb, its "
                 f"modulators and its globals are dead on all eight chains")

    # --- chord and gate ---------------------------------------------------
    for ch in channels:
        if ch.gate > tlib.GATE_MAX:
            warn(f"{ch.name} gate {ch.gate} above GATE_MAX "
                 f"{tlib.GATE_MAX} - the encoder cannot restore it once "
                 f"a player touches GATE")
        sounding = sum(1 for s in range(ch.steps) if ch.mask[s])
        widest = max(len(n) for n in ch.notes) if ch.notes else 0
        if sounding * widest > 80:
            warn(f"{ch.name} writes {sounding * widest} notes in one lock "
                 f"hold - the documented worst case is 80")

    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--kits", default=os.path.join(HERE, "drum-kit-notes.json"))
    ap.add_argument("--verbose", action="store_true",
                    help="print a line per entry even when it passes")
    args = ap.parse_args()

    with open(args.kits) as fh:
        kit_notes = json.load(fh)["notes"]
    with open(args.manifest) as fh:
        doc = json.load(fh)
    entries = doc if isinstance(doc, list) else [doc]

    failed = warned = 0
    for entry in entries:
        problems = check(entry, kit_notes)
        fails = [m for sev, m in problems if sev == "FAIL"]
        warns = [m for sev, m in problems if sev == "WARN"]
        failed += bool(fails)
        warned += bool(warns)
        if fails or warns or args.verbose:
            mark = "FAIL" if fails else ("warn" if warns else "ok  ")
            print(f"{mark}  {entry.get('file')}")
            for m in fails:
                print(f"        FAIL  {m}")
            for m in warns:
                print(f"        warn  {m}")
    print(f"\n{len(entries)} entries: {failed} failed, {warned} with warnings")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
