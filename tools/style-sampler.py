#!/usr/bin/env python3
"""A style as odds: sample a concrete manifest entry from one written as
distributions, and blend two styles without inventing a value.

    # draw four variants of every style in a file, reproducibly
    python3 tools/style-sampler.py sample --style snapshot/example-style.json \\
        --variants 4 --seed 1234 --out /tmp/sampled-manifest.json

    # blend two styles from an existing pack, halfway
    python3 tools/style-sampler.py blend --manifest snapshot/genre-pack-manifest.json \\
        --a 031-house-classic --b 046-minimal-dry --t 0.5 --seed 7 \\
        --file 900-blend --title "Blend" --out /tmp/blend-manifest.json

The output of either is an ORDINARY manifest - a list of fully explicit
entries - which `tools/build-genre-snapshots.py` turns into `.zss` files with
no change to that script at all. That separation is deliberate: the shipped
pack builder is not touched, so nothing here can regress the 71 snapshots it
already produces.

OFFLINE ONLY. Nothing on the instrument can read a distribution: the driver
round-trips only its own `ctrldev_state`, `set_state`'s globals loop drops
unknown keys in silence, and neither 256x64 screen has a slot that names a
style. Sampling on the rig is a separate, larger feature and is deliberately
not started here.


WHY EACH PART IS THE WAY IT IS
------------------------------

* A PLAIN VALUE STILL MEANS WHAT IT MEANS TODAY. A distribution is a dict
  carrying the single key `odds` and nothing else; everything else is
  copied through untouched. So every existing manifest is already a valid
  style - one whose every distribution is degenerate - and sampling one
  returns it unchanged. That is a test, not a hope.

* SEEDS ARE KEYED BY PATH, not by traversal order. Each draw hashes
  (seed, dotted path, salt), so adding a distribution to one field does NOT
  move every other field's value the way a single sequential `random.Random`
  would. A style is meant to be edited; a sampler that reshuffles the whole
  entry when one line changes is not reproducible in any useful sense.

* THE DRAWS DO NOT GO THROUGH `random`. They are read out of a blake2b
  digest, so the result depends on nothing but the seed and the path - not on
  the Python version's generator, not on process state, not on whether some
  other code touched the global RNG. The modulo bias this leaves is on the
  order of 1e-17 for the ranges a manifest holds.

* SIX OF THE ELEVEN INTERESTING FIELDS CANNOT BE AVERAGED, and the blend rule
  is the part of this that matters. `root` is modular - the mean of 0 and 11
  is 5.5, a key neither parent was in. `scale` is an index into a list of
  interval tuples; index 3 is not between 2 and 4. `kits` and `engines` are
  names. `register` and `rhythm_reg` are bit patterns, and averaging two of
  them gives a third with no relation to either. `steps` is a set. Those are
  taken WHOLE from one parent, chosen by the seed.

* AND THEY ARE TAKEN IN GROUPS, not field by field. Taking `scale` from A and
  `register` from B gives a melody built for a different scale. One coin per
  group in `WHOLE_GROUPS`; the group boundaries are the design.

* THE FX PAIR IS ONE GROUP FOR A SECOND REASON. The insert pair sits on ALL
  EIGHT chains, so an effect costs eight times what it looks like, and six
  plugins are banned at that count - including two Dragonfly reverbs stacked.
  A blend that took slot 1 from A and slot 2 from B could assemble a banned
  pair out of two legal parents. Taken whole, it cannot. `validate_entry`
  refuses the banned set anyway, belt and braces. See notes/traps/PLUGINS.md.

* TEMPO IS THE INTERESTING SCALAR. zynseq truncates frames-per-clock to a
  whole audio frame with no accumulator, so at 48 kHz the tempo error is the
  fractional part of 30000/tempo and is zero only when the tempo divides
  30000. The pack took a DISTANCE rule on 2026-08-22: fifteen snapshots within
  1 BPM of an exact tempo moved, and everything further away stayed on purpose
  because at that distance the tempo is the identity, not a default
  (`057-trance-acid` keeps 137 and its 4,487 ppm). This applies the same rule,
  and only where a blend has INVENTED a number: if both parents name the same
  tempo it is taken whole and never snapped, so blending a style with itself
  cannot move it.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atomic_write  # noqa: E402

# --- what a distribution looks like ----------------------------------------

# ONE wrapper key, and it is not negotiable. The first draft made the kind
# words themselves the markers - and `voices.range` is a real manifest field,
# so every existing entry was misread as a distribution on the first run. A
# marker that can collide with a field name is a marker that will.
DIST_KEY = "odds"
DIST_KINDS = ("range", "choice", "pick")

# zynseq's exact tempi at 48 kHz: the divisors of 30000. Anything else is fast
# by the fractional part of 30000/tempo.
EXACT_TEMPI = tuple(d for d in range(20, 301) if 30000 % d == 0)
SNAP_BPM = 1.0          # the pack's distance rule, 2026-08-22

# Banned at eight instances - the insert pair is on every chain.
# notes/traps/PLUGINS.md, notes/findings/2026-08-18-zynseq-riff-and-snapshot-authoring.md
BANNED_INSERTS = ("Aether", "CHOWTapeModel", "ChowPhaserStereo", "Roboverb", "SO-kl5")


def is_dist(value):
    """True for `{"odds": {...}}` and nothing else.

    A dict that carries `odds` alongside other keys is refused rather than
    guessed at: a silent misread here would ship a wrong snapshot.
    """
    if not isinstance(value, dict) or DIST_KEY not in value:
        return False
    if len(value) != 1:
        raise ValueError(
            f"{DIST_KEY!r} must be the only key of a distribution, got {sorted(value)}")
    spec = value[DIST_KEY]
    if not isinstance(spec, dict):
        raise ValueError(f"{DIST_KEY!r} takes an object, got {type(spec).__name__}")
    found = [k for k in DIST_KINDS if k in spec]
    if len(found) != 1:
        raise ValueError(
            f"a distribution declares exactly one of {DIST_KINDS}, got {found}")
    return True


# --- deterministic draws ----------------------------------------------------

def _digest(seed, path, salt=0):
    h = hashlib.blake2b(digest_size=8)
    h.update(struct.pack(">q", int(seed)))
    h.update(b"\x00")
    h.update(str(path).encode("utf-8"))
    h.update(b"\x00")
    h.update(struct.pack(">Q", salt))
    return struct.unpack(">Q", h.digest())[0]


def _unit(seed, path, salt=0):
    """A float in [0, 1)."""
    return _digest(seed, path, salt) / 2.0 ** 64


def _below(seed, path, n, salt=0):
    """An int in [0, n)."""
    if n <= 0:
        raise ValueError("empty draw")
    return _digest(seed, path, salt) % n


def _shuffled(items, seed, path):
    """Fisher-Yates driven by the same digest, so a pick is reproducible."""
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = _below(seed, path, i + 1, salt=1000 + i)
        out[i], out[j] = out[j], out[i]
    return out


def _triangular(lo, hi, mode, u):
    """The standard inverse-CDF triangular draw. Used when a style says a
    field has a most-likely value as well as bounds."""
    if hi <= lo:
        return lo
    f = (mode - lo) / (hi - lo)
    if u < f:
        return lo + math.sqrt(u * (hi - lo) * (mode - lo))
    return hi - math.sqrt((1.0 - u) * (hi - lo) * (hi - mode))


def draw(value, seed, path):
    """One value from one distribution - `{"odds": {...}}`."""
    dist = value[DIST_KEY]
    if "range" in dist:
        lo, hi = dist["range"]
        if hi < lo:
            raise ValueError(f"{path}: range {lo}..{hi} is empty")
        step = dist.get("step", 1)
        mode = dist.get("mode")
        if mode is not None and not lo <= mode <= hi:
            raise ValueError(f"{path}: mode {mode} outside {lo}..{hi}")
        u = _unit(seed, path)
        whole = all(isinstance(x, int) for x in (lo, hi, step))
        if not whole:
            return (lo + u * (hi - lo) if mode is None
                    else _triangular(lo, hi, mode, u))
        # An integer range is drawn in the CONTINUOUS interval [lo, hi+step)
        # and floored to a step, so the top bucket is as wide as every other
        # one. Drawing over [lo, hi] and flooring instead starves `hi` and
        # drags a mode down by half a bucket - measured, not assumed: mode 9
        # of 0..10 came out with a mean of 5.87 against a flat 5.05.
        top = hi + step
        value = (lo + u * (top - lo) if mode is None
                 else _triangular(lo, top, mode + step / 2.0, u))
        k = min(int((hi - lo) // step), int((value - lo) // step))
        return lo + k * step

    if "choice" in dist:
        options = dist["choice"]
        if not options:
            raise ValueError(f"{path}: choice is empty")
        weights = dist.get("weights")
        if weights is None:
            return copy.deepcopy(options[_below(seed, path, len(options))])
        if len(weights) != len(options):
            raise ValueError(f"{path}: {len(weights)} weights for {len(options)} choices")
        if any(w < 0 for w in weights):
            raise ValueError(f"{path}: a negative weight")
        total = sum(weights)
        if total <= 0:
            raise ValueError(f"{path}: weights sum to zero")
        mark = _unit(seed, path) * total
        run = 0.0
        for option, w in zip(options, weights):
            run += w
            if mark < run:
                return copy.deepcopy(option)
        return copy.deepcopy(options[-1])

    if "pick" in dist:
        pool = list(dist["pick"])
        count = dist.get("count", len(pool))
        if is_dist(count):
            count = draw(count, seed, path + ".count")
        count = int(count)
        if not 0 <= count <= len(pool):
            raise ValueError(f"{path}: cannot pick {count} of {len(pool)}")
        taken = _shuffled(pool, seed, path)[:count]
        try:
            return sorted(taken)
        except TypeError:
            return taken

    raise ValueError(f"{path}: not a distribution")


# --- sampling an entry ------------------------------------------------------

def sample_value(value, seed, path=""):
    """Recurse. A distribution is drawn; anything else is copied through."""
    if is_dist(value):
        return draw(value, seed, path)
    if isinstance(value, dict):
        return {k: sample_value(v, seed, f"{path}.{k}" if path else str(k))
                for k, v in value.items()}
    if isinstance(value, list):
        return [sample_value(v, seed, f"{path}.{i}") for i, v in enumerate(value)]
    return value


def get_path(entry, path):
    node = entry
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def set_path(entry, path, value):
    parts = path.split(".")
    node = entry
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def apply_rules(entry, rules):
    """The hard rules, applied to a SAMPLED entry, in order.

    A rule is `{"path": "...", <one operator>}`:
        require  - these members must be in this list (a step list is a set)
        forbid   - these members must not be
        clamp    - [lo, hi] on a number
        fixed    - this exact value, whatever the odds said

    Odds say what a style tends to do; a rule says what it may never fail to
    do. A kick on step 0 belongs here, not in a distribution that happens to
    make it likely.
    """
    for rule in rules or []:
        path = rule["path"]
        ops = [k for k in ("require", "forbid", "clamp", "fixed") if k in rule]
        if len(ops) != 1:
            raise ValueError(f"{path}: a rule carries one operator, got {ops}")
        op = ops[0]
        if op == "fixed":
            set_path(entry, path, copy.deepcopy(rule["fixed"]))
            continue
        current = get_path(entry, path)
        if op == "require":
            set_path(entry, path, sorted(set(current) | set(rule["require"])))
        elif op == "forbid":
            set_path(entry, path, sorted(set(current) - set(rule["forbid"])))
        elif op == "clamp":
            lo, hi = rule["clamp"]
            if lo > hi:
                raise ValueError(f"{path}: clamp {lo}..{hi} is empty")
            set_path(entry, path, min(hi, max(lo, current)))
    return entry


def sample_entry(style, seed):
    """A concrete manifest entry drawn from a style.

    A style with no distributions and no rules samples to itself - that is the
    guarantee that lets an existing manifest be fed through this path
    untouched.
    """
    rules = style.get("rules")
    entry = sample_value({k: v for k, v in style.items()
                          if k not in ("rules", "variants")}, seed)
    apply_rules(entry, rules)
    return entry


# --- blending ---------------------------------------------------------------

# Taken WHOLE from one parent, one coin per group. Each name is a path prefix:
# a field matches if it is the prefix or sits under it.
WHOLE_GROUPS = {
    # A register is written for a scale. Splitting these two is how a blend
    # produces a melody in a key nothing else in the entry is in.
    "tonality": ("root", "scale", "voices.register"),
    # Step lists and the voice rhythm bits: sets and bit patterns. `hits` and
    # `rotate` join them because a rotation is written FOR its hit count -
    # blending 4 hits with a rotation chosen for 2 moves the groove somewhere
    # neither parent was - and the two registers are masks over that line.
    "rhythm": ("drums.steps", "drums.hits", "drums.rotate",
               "drums.rhythm_reg", "drums.hand_reg", "voices.rhythm_reg"),
    # A DIVISION AND A GATE ARE ONE DECISION. `gate` is hundredths of a STEP,
    # and a step is a 1/16 at one division and a whole beat at another - so
    # taking `div` from A and `gate` from B changes every note length by up to
    # four times, in a file where nothing says why.
    "time": ("div", "voices.gate", "drums.gate", "groove"),
    # The board is one statement about what the record is about; half of one
    # mix and half of another is neither. The level MODULATORS travel with it
    # for a harder reason: a level modulator overwrites its fader within
    # 200 ms of load, so a mix taken from A with modulators from B is a mix
    # that is silently replaced a fifth of a second after it loads.
    "board": ("mix", "main"),
    # Chord shapes are written against a scale's degree count - a triad spans
    # 1.6 octaves in PENT and one in the rest - so they travel with tonality's
    # coin rather than their own.
    "harmony": ("voices.chord", "globals"),
    "kits": ("drums.kits",),
    "engines": ("voices.engines",),
    # One coin, because the pair lands on all eight chains - see the header.
    "fx": ("fx",),
    # A whole alternative channel definition; there is no half of one.
    "overrides": ("overrides",),
    "mods": ("mods",),
}

# Never blended: the blend is a new thing and its caller names it.
IDENTITY_FIELDS = ("file", "title", "genre", "notes")

_GROUP_OF = {prefix: name for name, prefixes in WHOLE_GROUPS.items() for prefix in prefixes}


def group_for(path):
    """The whole-from-one-parent group a path belongs to, or None if the field
    is a scalar on an ordered axis and may be interpolated."""
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        name = _GROUP_OF.get(".".join(parts[:i]))
        if name:
            return name
    return None


def exact_tempo_near(tempo, window=SNAP_BPM):
    """The exact tempo within `window` BPM, or None. Ties go to the lower."""
    best = min(EXACT_TEMPI, key=lambda e: (abs(e - tempo), e))
    return best if abs(best - tempo) <= window else None


def blend_tempo(a, b, t):
    """A blended tempo, snapped only where the blend invented a number.

    Both parents on the same tempo keep it, whatever it is: that number is the
    style's identity and nothing here has any business moving it. A blend that
    lands between two different tempi has invented a value neither parent
    chose, and takes the pack's own distance rule - within 1 BPM of an exact
    tempo, move to it; further away, stay where it is.
    """
    x = a + (b - a) * t
    if x in (a, b):
        # Nothing was invented: the blend landed on a number a parent named.
        # This covers both parents agreeing and t sitting on an endpoint.
        return int(round(x))
    near = exact_tempo_near(x)
    return int(near) if near is not None else int(round(x))


def _interpolate(a, b, t, path):
    if isinstance(a, bool) or isinstance(b, bool):
        raise ValueError(f"{path}: a bool is not on an ordered axis")
    x = a + (b - a) * t
    if isinstance(a, int) and isinstance(b, int):
        return int(round(x))
    return x


def _one_sided_kept(path, side, chosen):
    """A field only one parent has. If it belongs to a whole-from-one-parent
    group, the group's coin decides whether it survives - otherwise a blend
    that reported `overrides<-A` could still come back carrying B's overrides,
    and the report would be a lie. A field in no group has nothing to
    contradict it, so it is kept."""
    group = group_for(path)
    return group is None or chosen[group] == side


def _blend_node(a, b, t, seed, path, chosen):
    group = group_for(path)
    if group is not None:
        return copy.deepcopy(a if chosen[group] == "a" else b)

    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for key in a:
            sub = f"{path}.{key}" if path else str(key)
            if key in b:
                out[key] = _blend_node(a[key], b[key], t, seed, sub, chosen)
            elif _one_sided_kept(sub, "a", chosen):
                out[key] = copy.deepcopy(a[key])
        for key in b:
            if key not in a:
                sub = f"{path}.{key}" if path else str(key)
                if _one_sided_kept(sub, "b", chosen):
                    out[key] = copy.deepcopy(b[key])
        return out

    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            # Two lists of different length are not on an ordered axis either;
            # take one whole rather than invent a length.
            return copy.deepcopy(b if _unit(seed, "len:" + path) < t else a)
        return [_blend_node(a[i], b[i], t, seed, f"{path}.{i}", chosen)
                for i in range(len(a))]

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _interpolate(a, b, t, path)

    # Strings and anything else: no midpoint exists. One coin, per field, and
    # the caller is told in the report which way it went.
    return copy.deepcopy(b if _unit(seed, "whole:" + path) < t else a)


def blend(a, b, t=0.5, seed=0):
    """Blend two concrete manifest entries.

    `t` is how far towards `b`: 0 returns `a`, 1 returns `b`, and every
    non-averageable group is decided by ONE coin whose bias is `t`, so those
    endpoints hold for them too.

    The returned entry carries `blend_of`, `blend_t` and `blend_seed` so a
    produced snapshot can be traced back. `build-genre-snapshots.py` reads
    only the keys it knows and ignores those.
    """
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"t must be 0..1, got {t}")

    chosen = {name: ("b" if _unit(seed, "group:" + name) < t else "a")
              for name in WHOLE_GROUPS}
    out = {}
    for key in a:
        if key in IDENTITY_FIELDS:
            out[key] = copy.deepcopy(a[key])
            continue
        if key == "tempo":
            out[key] = blend_tempo(a["tempo"], b["tempo"], t)
            continue
        if key not in b:
            if _one_sided_kept(key, "a", chosen):
                out[key] = copy.deepcopy(a[key])
            continue
        out[key] = _blend_node(a[key], b[key], t, seed, key, chosen)
    for key in b:
        if key not in a and key not in IDENTITY_FIELDS:
            if _one_sided_kept(key, "b", chosen):
                out[key] = copy.deepcopy(b[key])

    out["blend_of"] = [a.get("file"), b.get("file")]
    out["blend_t"] = t
    out["blend_seed"] = seed
    out["blend_taken_whole"] = dict(chosen)
    return out


# --- validation -------------------------------------------------------------

REQUIRED = ("file", "title", "genre", "tempo", "root", "scale", "drums", "voices", "fx")


def validate_entry(entry):
    """Everything `build-genre-snapshots.py` will reach for, and the two rules
    it does not check itself. Raises with the entry's own name in the message."""
    name = entry.get("file", "<unnamed>")
    for key in REQUIRED:
        if key not in entry:
            raise ValueError(f"{name}: missing {key!r}")

    leftovers = []

    def scan(node, path):
        if is_dist(node):
            leftovers.append(path)
            return
        if isinstance(node, dict):
            for k, v in node.items():
                scan(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                scan(v, f"{path}.{i}")

    scan(entry, "")
    if leftovers:
        raise ValueError(f"{name}: still holds odds at {leftovers} - sample it first")

    d, v = entry["drums"], entry["voices"]

    # TWO DRUM FORMS SINCE 2026-09-04, and `hits` is the switch. The euclid
    # form (hits/rotate/rhythm_reg) is the one the rebuilt packs use, because
    # the packs carried no `drums` block at all and so the panel's HITS and
    # ROT were whatever it last held - the first encoder turn discarded a
    # hand-written step list. The literal `steps` form still builds, so an
    # older style is still a valid style.
    euclid = "hits" in d
    per_channel = ("kits", "velo", "gate") + (
        ("hits",) if euclid else ("steps",))
    for key in per_channel:
        if len(d[key]) != 5:
            raise ValueError(f"{name}: drums.{key} has {len(d[key])}, expected 5")
    for key in ("engines", "rhythm_reg", "register", "length", "octave", "range",
                "velo", "gate"):
        if len(v[key]) != 3:
            raise ValueError(f"{name}: voices.{key} has {len(v[key])}, expected 3")
    # The optional per-voice lists are three long too when present, or the
    # builder reads one voice's value onto another.
    for key in ("chord", "random", "rhythm"):
        if key in v and len(v[key]) != 3:
            raise ValueError(f"{name}: voices.{key} has {len(v[key])}, expected 3")
    if euclid:
        steps_in_bar = 16
        for i, hits in enumerate(d["hits"]):
            if not 0 <= hits <= steps_in_bar:
                raise ValueError(
                    f"{name}: drums.hits.{i} is {hits}, outside 0..{steps_in_bar}")
        for i, rot in enumerate(d.get("rotate") or [0] * 5):
            if not 0 <= rot < steps_in_bar:
                raise ValueError(
                    f"{name}: drums.rotate.{i} is {rot}, outside "
                    f"0..{steps_in_bar - 1}")
    else:
        for i, steps in enumerate(d["steps"]):
            for s in steps:
                if not 0 <= s < 16:
                    raise ValueError(
                        f"{name}: drums.steps.{i} has step {s} outside 0..15")
            if len(set(steps)) != len(steps):
                raise ValueError(f"{name}: drums.steps.{i} repeats a step")
    if not 0 <= entry["root"] <= 11:
        raise ValueError(f"{name}: root {entry['root']} outside 0..11")

    # THE EIGHT-ENTRY LEVERS. `div` and `mix` are per CHANNEL, not per
    # section: the drum five and the voice three take one key between them,
    # and an overridden drum channel is a voice living at its own index.
    for key in ("div", "mix"):
        if key in entry and len(entry[key]) != 8:
            raise ValueError(
                f"{name}: {key} has {len(entry[key])}, expected 8")
    if "mix" in entry:
        for i, level in enumerate(entry["mix"]):
            if not 0.0 <= level <= 1.0:
                raise ValueError(f"{name}: mix.{i} is {level}, outside 0.0..1.0")
    for key in ("swing", "human_time", "human_velo"):
        groove = entry.get("groove") or {}
        if key in groove and len(groove[key]) != 8:
            raise ValueError(
                f"{name}: groove.{key} has {len(groove[key])}, expected 8")
    # A NEGATIVE SWING CANNOT BE WRITTEN. The riff field is unsigned fixed
    # point, so it would land as a very large positive and the pattern would
    # fall apart - the builder refuses it too, and this says so earlier.
    for i, swing in enumerate((entry.get("groove") or {}).get("swing") or ()):
        if swing < 0:
            raise ValueError(
                f"{name}: groove.swing.{i} is {swing} - a negative swing "
                f"cannot be written to the riff")

    if len(entry["fx"]) != 2:
        raise ValueError(f"{name}: fx is a pair, got {entry['fx']}")
    for plugin in entry["fx"]:
        for banned in BANNED_INSERTS:
            if banned.lower() in plugin.lower():
                raise ValueError(
                    f"{name}: {plugin} is banned at eight instances - the insert "
                    f"pair is on every chain. notes/traps/PLUGINS.md")
    if all("dragonfly" in p.lower() for p in entry["fx"]):
        raise ValueError(
            f"{name}: two Dragonfly reverbs stacked is banned at eight instances. "
            f"notes/traps/PLUGINS.md")
    return entry


# --- the command line -------------------------------------------------------

def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _find(manifest, name):
    for entry in manifest:
        if entry.get("file") == name:
            return entry
    raise SystemExit(f"no entry named {name!r} in the manifest")


def cmd_sample(args):
    styles = _load(args.style)
    if isinstance(styles, dict):
        styles = [styles]
    out = []
    for style in styles:
        variants = args.variants or style.get("variants", 1)
        for i in range(variants):
            seed = args.seed + i
            entry = sample_entry(style, seed)
            if variants > 1 or args.stamp:
                entry["file"] = f"{entry['file']}-v{i + 1}"
                entry["title"] = f"{entry['title']} v{i + 1}"
            entry["style_of"] = style.get("file")
            entry["style_seed"] = seed
            validate_entry(entry)
            out.append(entry)
            print(f"  {entry['file']:32} seed {seed:<10} {entry['tempo']:3} BPM")
    _write(out, args.out)


def cmd_blend(args):
    manifest = _load(args.manifest)
    a, b = _find(manifest, args.a), _find(manifest, args.b)
    entry = blend(a, b, args.t, args.seed)
    entry["file"] = args.file
    entry["title"] = args.title or f"{a['title']} x {b['title']}"
    entry["genre"] = args.genre or a.get("genre", "blend")
    validate_entry(entry)
    whole = ", ".join(f"{k}<-{'B' if v == 'b' else 'A'}"
                      for k, v in sorted(entry["blend_taken_whole"].items()))
    print(f"  {entry['file']:32} t={args.t} seed={args.seed} "
          f"{entry['tempo']:3} BPM  ({a['tempo']} / {b['tempo']})")
    print(f"  taken whole: {whole}")
    _write([entry], args.out)


def _write(entries, path):
    if path == "-":
        json.dump(entries, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        atomic_write.write_json(path, entries)
        print(f"{len(entries)} entries -> {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="draw concrete entries from a style file")
    s.add_argument("--style", required=True)
    s.add_argument("--variants", type=int, default=0)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--stamp", action="store_true",
                   help="suffix the file name even for a single variant")
    s.add_argument("--out", default="-")
    s.set_defaults(func=cmd_sample)

    b = sub.add_parser("blend", help="blend two entries of a manifest")
    b.add_argument("--manifest", required=True)
    b.add_argument("--a", required=True)
    b.add_argument("--b", required=True)
    b.add_argument("--t", type=float, default=0.5)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--file", required=True)
    b.add_argument("--title")
    b.add_argument("--genre")
    b.add_argument("--out", default="-")
    b.set_defaults(func=cmd_blend)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
