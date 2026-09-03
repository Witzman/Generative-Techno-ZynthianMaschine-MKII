#!/usr/bin/env python3
"""Clone channel A's insert pair onto the other chains of the techno machine
snapshot, offline, on the .zss JSON.

Why this shape: there is no CUIA that executes code, so a script cannot reach
Zynthian's live state_manager from outside the UI process. Building the whole
snapshot offline is equally wrong - it would mean hand-maintaining `fader_pos`,
which the prototype spec explicitly forbids. So one channel is built by hand on
the touchscreen, and Zynthian - not this script - decides slots, fader_pos and
processor state. This only replicates that structure with fresh processor ids.

    scp tools/build-techno-snapshot.py root@<pi>:/root/
    ssh root@<pi> 'python3 /root/build-techno-snapshot.py [path/to/snapshot.zss]'

Then load the snapshot on the touchscreen and save it again, so what is on disk
is Zynthian's own output rather than this script's.
"""

import copy
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atomic_write  # noqa: E402

SNAP = sys.argv[1] if len(sys.argv) > 1 else \
    "/zynthian/zynthian-my-data/snapshots/000/017-generative-techno.zss"
REVERB = "JV/TAP Reverberator"
DELAY = "JV/TAP Stereo Echo"


def slot_codes(chain):
    return [code for slot in chain["slots"] for code in slot.values()]


def main():
    try:
        d = json.load(open(SNAP))
    except FileNotFoundError:
        sys.exit(f"{SNAP} not found - save it from the touchscreen first")

    shutil.copy(SNAP, SNAP + ".bak")
    chains = d["chains"]
    procs = d["zs3"]["zs3-0"]["processors"]

    template_id = None
    for cid, chain in chains.items():
        codes = slot_codes(chain)
        if REVERB in codes and DELAY in codes:
            template_id = cid
            break
    if template_id is None:
        sys.exit("no chain carries both inserts - build channel A by hand first")

    template = chains[template_id]
    print(f"template: chain {template_id} '{template['title']}', "
          f"fader_pos {template['fader_pos']}, {len(template['slots'])} slots")

    fx_slots = [s for s in template["slots"]
                if any(c in (REVERB, DELAY) for c in s.values())]
    for s in fx_slots:
        (pid, code), = s.items()
        print(f"   insert slot: processor {pid} = {code}")

    next_id = max(int(p) for p in procs) + 1
    cloned = 0

    for cid, chain in sorted(chains.items(), key=lambda kv: int(kv[0])):
        if cid == template_id or chain.get("midi_chan") is None:
            continue
        if REVERB in slot_codes(chain):
            print(f"chain {cid} '{chain['title']}': already has inserts, skipped")
            continue
        for slot in fx_slots:
            (old_id, code), = slot.items()
            chain["slots"].append({str(next_id): code})
            procs[str(next_id)] = copy.deepcopy(procs[str(old_id)])
            next_id += 1
        chain["fader_pos"] = template["fader_pos"]
        cloned += 1
        print(f"chain {cid} '{chain['title']}': inserts cloned, "
              f"fader_pos {chain['fader_pos']}")

    atomic_write.write_json(SNAP, d)
    print(f"\n{cloned} chains cloned. Backup at {SNAP}.bak")
    print("Now load the snapshot on the touchscreen and save it again.")


if __name__ == "__main__":
    main()
