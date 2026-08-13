# SDD ledger — plan: /home/witzman/zynth-docs/docs/superpowers/plans/2026-08-09-maschine-sfz-kits.md

Repo: ~/zynth/zynthian-ui, branch vangelis, base 1ad9c8f0
Hardware: Pi 4 at 192.168.2.123, Maschine MK2 attached. Physical verification
needs the human at the device - subagents can deploy and read logs, but cannot
press buttons, turn encoders or listen.

Task 0: probe deployed (uncommitted, driver only). Pending human button press.
Task 0: plan gap found - snapshot 020 is all FluidSynth, which has no "Drum
  Machines" bank, so the probe measures nothing until one chain is moved to
  LinuxSampler by hand first. Added to the manual steps.
OPEN QUESTION (not blocking): engine_config.json also enables Sfizz ("SF",
  "Sfizz: SFZ"), a dedicated SFZ player, alongside LinuxSampler. Sfizz is LV2
  and may expose real controllers where LinuxSampler exposes none - which is
  the entire reason Task 3 moves volume/pan to the mixer. Evaluate after the
  gate; do not switch mid-Task-0, the spike measured LinuxSampler.
UI paths verified from source: Chain Control long-press -> Chain Options
  (zynthian_gui_control.py:560); tap the synth line -> processor options;
  "Replace" (zynthian_gui_processor_options.py:59-63); engine list is grouped
  by category, LinuxSampler is under "> Sampler" (zynthian_gui_engine.py:247).
UI: the engine list shows ONE category at a time (zynthian_gui_engine.py
  fill_list, cat_index >= 0). Step categories with the on-screen arrows to
  reach "Sampler" - there is no combined list unless cat_index < 0.
Task 0: complete (no commits - probe reverted, tree clean). GATE PASSED.
  41 kits in "Drum Machines"; swaps 0.005/0.010/0.014/0.011/0.043s, all True.
  Human: sound changed 5x, no glitch/dropout, no UI stall. Threshold was 0.3s.
  Confirmed on hardware: encoder 8 does nothing on a LinuxSampler chain - the
  "no engine controllers" symptom Task 3 exists to fix. Design premise holds.
Task 1: implemented 3e2c8c15 (67 tests). Review: spec OK, 2 Important.
Task 1: controller resolved the reviewer's warning - CONFIRMED on real data:
  13 kits have a region with hikey != lokey (Simmons 47/48, Akai XE8 77/96,
  Electro Puff, Lab, Retrobox, Sween, Tama Tech Star 1, Mattel Synsonic 38/40,
  +5). So "key=" in line matching "hikey=" fabricates notes for real.
Task 1: minor (deferred): two different extraction styles in one function
  (character scan for sample=, substring test for keys) - the inconsistency is
  what let the hikey bug in.
NEW FINDING (affects Task 4, not Task 1): "DYNOSAUR-808.sfz" is a DIRECTORY,
  not a file - Zynthian's LS engine supports .sfz directories
  (zynthian_engine_linuxsampler.py:249). _kit_notes() must not assume a file;
  open() on it raises IsADirectoryError.
Task 1: fix round 1/5 (1 addressed, 1 half — commits 3e2c8c15..fdebc990)
Task 1: controller resolved the remaining half of finding 2 from the data:
  the low end is GENUINE - Boss DR55 has exactly 4 regions/4 keys (kick,
  snare, rimshot, hi hat), a real 4-voice box. Akai XR10's 61 is genuine too.
  Corpus check: only "lokey="/"hikey=" occur (853 each) plus bare "key=" in
  a few kits (E Ave, DrumFire, SP 12 use it); NO prefixed variants such as
  sw_lokey=/xfin_lokey= exist, so the reviewer's substring concern about them
  cannot fire on this corpus.
Task 1: minor (deferred): lokey=/key= matching is whole-line substring, not
  token-exact. Safe for this corpus; revisit if user SFZ kits are ever added.
Task 1: minor (deferred): the pitch_keycenter= guard is dead code - "key="
  is not a substring of "pitch_keycenter=" ("keycenter" has no "=" after key).
Task 1: complete (commits 1ad9c8f0..fdebc990, review clean, 2 minors deferred)
Correction for the spec/docs: the folder holds 40 .sfz FILES + 1 .sfz
  DIRECTORY (DYNOSAUR-808.sfz), not "41 kits". Fix the spec wording.
Task 2: implemented 11673ea2 (78 tests). Review: spec OK, 1 Important.
Task 2: PLAN DEFECT (mine): KIT_SHORT_NAMES mapped both "SP 12" and
  "SP1200 1" to "SP12". Owner ruled: SP 12 -> "SP12", SP1200 1 -> "1200",
  SP1200 2 -> "1201". Update the spec's table too.
Task 2: minor (deferred): nearest_note uses min(sorted(available), ...) -
  the sorted() is redundant, the (abs_diff, n) key already breaks ties.
Task 2: fix round 1/5 (2 addressed: SP12x remap + real fallback assertions;
  commits 11673ea2..867a069a)
Task 2: fix round 2/5 (1 addressed: DRU1/2 + TYS1/2/3 table entries so no
  label is under 3 chars; commits 867a069a..e797e188)
Task 2: re-review clean - all 3 findings ADDRESSED, no new breakage.
Task 2: controller verified independently: 41 names, zero duplicate short
  names, none over 4 chars, "Tama Tech Star 3" -> TTS3.
Task 2: complete (commits fdebc990..e797e188, review clean, 1 minor deferred)
Task 3: complete (commits e797e188..fa3bdabc, review clean - spec OK, quality
  approved, 0 Critical/Important). Hardware-verified by the human: enc 8 = mixer
  level, enc 5 = balance, per-group memory holds, mutes fine, and enc 8 now
  WORKS on a LinuxSampler chain where it previously did nothing.
Task 3: minor (deferred): _group_brightness re-clamps a value _set_mixer
  already clamped; comment does not say CC_ENC_SAMPLE/KIT are undispatched yet.
CORRECTION to the earlier DYNOSAUR-808 note: NO directory handling is needed.
  zynthian_engine_linuxsampler._get_preset_list runs "find -type f -name *.sfz"
  inside a .sfz DIRECTORY and stores the FILE path, so preset_list[0] is
  ".../DYNOSAUR-808.sfz/DYNOSAUR-808.sfz" - a real file - and its title is the
  dirname minus ".sfz" ("DYNOSAUR-808", which the short-name table already has).
  This holds ONLY because the kit list comes from preset_list, not a glob.
Task 4: implemented c7c6fd79. Review: spec faithful to brief BUT the brief had
  a Critical bug. _kit_list() memoises self.kits and nothing invalidates it -
  _resync_all() clears note_cache/keymap_cache/leds but not the kit state.
  Worse: set_bank_by_name() returns False silently when the bank is absent
  (every FluidSynth chain), and _kit_list ignored it and called
  load_preset_list() anyway - so self.kits filled with FLUIDSYNTH's presets,
  logged as "N kits in 'Drum Machines'", cached for the process's life.
  ALSO: the brief's claim "nothing calls _kit_list() until Task 5" is wrong -
  the Step 4 _load_keymap change calls it on every screen render.
  Fix round 1 dispatched. THE SPEC/PLAN NEED THIS FIX TOO.
DEPLOY HAZARD seen this task: the Pi's maschine_mk2_lib.py was STALE - Tasks
  1/2 were committed to git but never scp'd, so the driver threw AttributeError
  on first restart. Committing is not deploying. Verify md5 of BOTH ctrldev
  files on the Pi before any hardware test.
Task 4: fix round 1/5 (1 Critical addressed; commits c7c6fd79..ce16f29d)
  _reset_kit_cache() now called from _resync_all() and refresh(); bank check
  before load_preset_list; nothing caches on failure; warnings deduped by
  reason. Journal: bogus lines gone, warnings 16 -> 2.
Task 4: complete (commits fa3bdabc..ce16f29d, review clean)
CARRY INTO TASK 5 (raised by the re-review): _reset_kit_cache() sets
  kit_index = [0]*8, so after any snapshot load / chain change the first turn
  of encoder 7 computes its delta from index 0 rather than from the kit the
  chain actually has loaded - a small turn could jump to an unrelated kit.
  Task 5 must resolve the group's REAL current kit from the processor's
  preset before applying movement. Dormant until the encoder is wired.
TASK 6 CHANGE OF METHOD: the human does NOT want to build the snapshot by hand
  on the touchscreen. Build 021-maschine-drum-rig-sfz.zss PROGRAMMATICALLY from
  020's JSON. Verified structures (from last_state.zss, which really does hold
  an LS chain today):
  - chain: "slots": [{"<procid>": "LS"}]  (chain 1 "Kick", midi_chan 0,
    mixer_chan 0, proc id 10 after a Replace; other chains use ids 3..9)
  - zs3["zs3-0"]["processors"]["<procid>"] for an LS processor:
      "bank_info":   ["/zynthian/zynthian-data/soundfonts/sfz/Drum Machines",
                      null, "Drum Machines", null, "Drum Machines"]
      "preset_info": ["<abs path>.sfz", <preset index>, "<Title>", "sfz",
                      "<Title>.sfz"]
      "bank_subdir_info": null, "preset_subdir_info": null
  - Patterns live in top-level "zynseq_riff_b64" - copy from 020 UNCHANGED,
    that is the human's drum programming.
  - Build from 020 (the pristine FluidSynth rig), NOT from last_state.
NOTE, worth checking later: that LS processor's zs3 still carries
  controllers {volume, pan, expression}. That does NOT contradict Task 3 -
  the human verified on hardware that encoder 8 did nothing on an LS chain
  before the mixer change - but it suggests the values are carried over from
  the replaced FluidSynth processor rather than provided by LS itself.
Task 5: implemented 826489c8 (hardware-verified by the human, incl. LIVE kit
  cycling on a LinuxSampler chain - enc 6 samples, enc 7 kits, deferred load,
  preview and nearest-note landing all working).
Task 5: fix round 1/5 (1 Important addressed; commits 826489c8..a218899e) -
  kit_pending is now a single (group, index, due) tuple written atomically,
  _commit_kit clears only on an identity check, kit_due removed. Both the
  lost-change and defeated-debounce interleavings are closed.
Task 5: minor (deferred): kit_pending is ONE global slot, not per group -
  nudging group B within the 150ms window of an unfired group A change drops
  A's change. Narrow, and the display self-corrects because _columns resolves
  the real loaded kit. Pre-existing, not introduced by the fix.
Task 5: complete (commits ce16f29d..a218899e, review clean, 1 minor deferred)
Task 6: complete (no repo commits - the artifact is a snapshot on the Pi).
  Built 021-maschine-drum-rig-sfz.zss programmatically from 020's JSON. Preset
  indices derived by reproducing _get_preset_list's UNSORTED glob traversal
  (it numbers during the walk then sorts for display without renumbering, so
  an alphabetical guess is wrong): TR808=33 TR909=0 LINN9000-1=16 SP1200-1=22
  Simmons=24 CR78=29 HR16=38 RX11=1. zynseq_riff_b64 byte-identical to 020;
  020 untouched (md5 verified).
Task 6 HARDWARE VERIFIED by the human: 8 different machines, kit-specific
  sample names on the tabs, enc 7 kits + enc 6 samples per group, patterns
  intact, kit switching WHILE JAMMING works.
Task 6 measured during a 180s jam: system CPU avg 6.2% peak 15% (of 400%),
  linuxsampler 2.2% CPU / 249.5 MB RSS (the spike predicted 248 MB), 3011 MB
  RAM free, ZERO xruns, 1612 MIDI CC events. Note the jam exercised CC 16-19
  and the F-buttons only - CC 20-23 saw zero events, so the encoder-under-load
  case was covered separately by the human confirming kit switching mid-jam.
Task 6 PERSISTENCE VERIFIED: read live kit per channel over LSCP (port 6688),
  restarted zynthian, re-read - all 8 kits identical afterwards.
Task 6 side finding, now resolved: before the restart LinuxSampler had NINE
  channels - a leftover chan 0 on midi_ch 0 holding Roland TR727 from the
  morning gate test, duplicating group A's MIDI channel. Silent only because
  its audio outs were unconnected. The restart cleared it; 8 channels now.
FINAL whole-branch review (opus, 1ad9c8f0..a218899e): 1 Critical, 2 Important,
  several minors. All fixed in one wave, commit 75572577, scoped re-review
  verdict SHIP - all 6 addressed, no regressions.
  - CRITICAL (plan's own bug): _apply_kit called _preview() - a libseq
    playNote - OUTSIDE self.lock from the playhead thread, on every kit
    commit. Same unsynchronised-libseq pattern that SIGSEGV'd the UI before.
  - IMPORTANT: _load_keymap used the raw kit_index, which _reset_kit_cache
    zeroes on snapshot load / chain change / sleep-wake, so every group would
    read kit 0's notes and encoder 6 could rewrite a pattern onto a note the
    real kit lacks -> silent group.
  - IMPORTANT: _cycle_sample raised IndexError on an empty keymap; the
    exception escapes to zynthian_state_manager's catch-all around
    zynmidi_read, which DISCARDS THE REST OF THAT MIDI BATCH (incl. a
    keyboard's notes) and repeats every detent.
  - Minors fixed: stale encoder comment, fabricated PAN 0/VOL 0 for a
    chainless group (now "-"), debounce moved to time.monotonic().
  All 7 deferred minors triaged as safe to ship. Sfizz-vs-LinuxSampler stays
  parked - it would only revisit the mixer decision, now hardware-proven.
