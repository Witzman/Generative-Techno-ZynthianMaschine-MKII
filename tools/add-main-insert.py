#!/usr/bin/env python3
"""Put one insert on the Main chain of a snapshot, OFFLINE.

The processor is placed in the FILE, never by add_processor() at runtime.
`add_processor` -> `rebuild_graph()` is seconds of work and an xrun risk, and
this instrument's founding rule is that nothing is created or torn down while
playing - the same reason SP7's crossfade review rejected building a chain at
switch time: "creating the chain at switch time is the drop, moved."

WHY EVERY CONTROLLER VALUE IS WRITTEN OUT
-----------------------------------------
MDA RezFilter's factory defaults are NOT neutral, and three of them are
actively dangerous on a master bus. Measured with lv2info on the rig,
2026-08-20:

    freq      default 33   <-- BELOW the digital-silence floor of 35
    res       default 70
    env_vcf   default 70
    lfo_vcf   default 40
    max_freq  default 75

A RezFilter dropped on Main at its defaults MUTES THE WHOLE INSTRUMENT, with
every engine healthy and nothing on the surface saying why - and if it did
pass sound it would duck and wobble by itself. So the snapshot authors all ten
values, and the insert loads WIDE OPEN and inaudible.

The plugin was chosen because it is the only filter this project has MEASURED
as safe: Calf Filter corrupts the heap and TAL Filter ignores every control
port while still passing a "does it run" check.

Usage:
    python3 tools/add-main-insert.py IN.zss OUT.zss
    python3 tools/add-main-insert.py --check OUT.zss
"""

import json
import sys

ENGINE = "JV/MDA RezFilter"
MAIN_CHAIN = "0"

# Wide open, dry, still. Every port the plugin publishes except its audio
# ports, so nothing is left to a default.
NEUTRAL = {
    "freq": 100.0,      # fully open. 35 is the silence floor, 33 is the default
    "res": 0.0,
    "output": 0.0,
    "env_vcf": 0.0,     # no envelope duck
    "attack": 0.0,
    "release": 7250.0,  # inert while env_vcf is 0; the plugin's own default
    "lfo_vcf": 0.0,     # no wobble
    "lfo_rate": 40.0,   # inert while lfo_vcf is 0
    "trigger": -37.0,   # its minimum, which is "never"
    "max_freq": 100.0,  # do not cap the sweep the player is being given
}


def _free_processor_id(snapshot):
    """The lowest id no zs3 already uses.

    Ids are shared across every zs3 in the file, so this scans all of them
    rather than the first - a snapshot with two scenes would otherwise get a
    collision that only shows up on the second load.
    """
    used = set()
    for zs3 in (snapshot.get("zs3") or {}).values():
        used.update(int(k) for k in (zs3.get("processors") or {}))
    for chain in (snapshot.get("chains") or {}).values():
        for slot in chain.get("slots") or []:
            used.update(int(k) for k in slot)
    candidate = 1
    while candidate in used:
        candidate += 1
    return str(candidate)


def add_main_insert(snapshot):
    """Returns (snapshot, processor id). Raises if Main is not as expected."""

    chains = snapshot.get("chains") or {}
    main = chains.get(MAIN_CHAIN)
    if main is None:
        raise SystemExit("no chain 0 in this snapshot")
    if main.get("mixer_chan") != 16:
        raise SystemExit(
            f"chain 0 is on mixer_chan {main.get('mixer_chan')}, not 16 - "
            "this is not the Main chain")
    if main.get("slots"):
        raise SystemExit("chain 0 already carries a processor; refusing to "
                         "add a second. Remove it first if that is the intent")

    pid = _free_processor_id(snapshot)
    main["slots"] = [{pid: ENGINE}]

    for zs3 in (snapshot.get("zs3") or {}).values():
        procs = zs3.setdefault("processors", {})
        # THE SHAPE IS COPIED FROM A SHIPPED LV2 ENTRY, not invented. The
        # first attempt used `"bank_info": None` and omitted the two subdir
        # keys, and the processor was silently dropped on load - no error in
        # the journal, chain 0 simply came back with no slots. Every other
        # LV2 effect in the factory snapshot carries exactly these four keys
        # with exactly these values, so this one does too.
        procs[pid] = {
            "bank_info": ["", None, "None", None],
            "bank_subdir_info": None,
            "preset_info": None,
            "preset_subdir_info": None,
            "controllers": {k: {"value": v} for k, v in NEUTRAL.items()},
        }
    return snapshot, pid


def check(path):
    snapshot = json.load(open(path))
    main = (snapshot.get("chains") or {}).get(MAIN_CHAIN) or {}
    slots = main.get("slots") or []
    if not slots:
        raise SystemExit("FAIL: chain 0 has no processor")
    pid, engine = next(iter(slots[0].items()))
    if engine != ENGINE:
        raise SystemExit(f"FAIL: chain 0 carries {engine}, not {ENGINE}")
    problems = []
    for name, zs3 in (snapshot.get("zs3") or {}).items():
        ctrls = ((zs3.get("processors") or {}).get(pid) or {}).get(
            "controllers") or {}
        for symbol, want in NEUTRAL.items():
            got = (ctrls.get(symbol) or {}).get("value")
            if got is None:
                problems.append(f"{name}: {symbol} missing")
            elif float(got) != float(want):
                problems.append(f"{name}: {symbol} is {got}, want {want}")
    if problems:
        raise SystemExit("FAIL:\n  " + "\n  ".join(problems))
    print(f"ok: chain 0 carries {ENGINE} as processor {pid}, "
          f"all {len(NEUTRAL)} controllers authored")


def main(argv):
    if len(argv) == 3 and argv[1] == "--check":
        return check(argv[2])
    if len(argv) != 3:
        raise SystemExit(__doc__)
    snapshot = json.load(open(argv[1]))
    snapshot, pid = add_main_insert(snapshot)
    with open(argv[2], "w") as handle:
        json.dump(snapshot, handle, indent=2)
    print(f"wrote {argv[2]}: {ENGINE} on chain 0 as processor {pid}")


if __name__ == "__main__":
    main(sys.argv)
