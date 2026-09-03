use serde::{Deserialize, Serialize};
use std::fs;

const CONFIG_PATH: &str = "maschine.json";

/// Unchanged from every previous version of this daemon. See `ws_bind`.
fn default_ws_bind() -> String {
    "0.0.0.0".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MaschineConfig {
    pub pad_notes: [u8; 16],
    pub encoder_ccs: [u16; 8],

    /// Hand pad LEDs over to whoever drives the daemon over OSC.
    ///
    /// The daemon normally lights a pad on press and dims it on release, all
    /// in one global pad colour. That is right for standalone use, but it
    /// fights any external controller that paints per-pad state: the first
    /// touch repaints the pad in the daemon's colour and the external picture
    /// is lost until the next full redraw. Set this when something else owns
    /// the pad LEDs. Defaults to false so standalone behaviour is unchanged.
    #[serde(default)]
    pub external_pad_leds: bool,

    /// Emit polyphonic aftertouch from pad pressure.
    ///
    /// The MK2's pads stream 12-bit continuous pressure at roughly 750 reports
    /// a second, and `pad_aftertouch` turns each one into a
    /// `PolyphonicPressure` message. The driver's `midi_event` holds its lock
    /// for the whole event, so an unthrottled 750 msg/s is a hazard rather
    /// than a feature — the send is therefore rate-limited and
    /// change-gated in `pad_aftertouch`, not here.
    ///
    /// Defaults to false: this was hardcoded false from the daemon's first
    /// commit until 2026-08-30, so every existing rig behaves exactly as
    /// before until someone sets it.
    #[serde(default)]
    pub send_aftertouch: bool,

    /// Panel brightness, 0-100, applied to BOTH screens at start-up.
    ///
    /// `None` — the field absent, or explicitly `null` — means the daemon does
    /// not read and does not write the screen configuration at all, which is
    /// how every rig behaved before this key existed. That is deliberate: HID
    /// feature reports on this device are declared **Non-volatile**, so a write
    /// survives a power cycle and a bad one cannot be undone by unplugging.
    /// A rig that never asked for a setting never gets one written.
    ///
    /// The factory value on both screens is 72, measured 2026-08-31. Set both
    /// keys back to 72 / 50 and restart the daemon to recover a dark panel.
    /// The write is skipped entirely when the device already holds the
    /// requested values, so shipping the factory pair costs no write cycles.
    #[serde(default)]
    pub screen_brightness: Option<u8>,

    /// Where the WebSocket editor listens.
    ///
    /// **This socket has no authentication and the daemon runs as root.** Its
    /// commands remap the pads' MIDI notes and the encoders' CC numbers and
    /// SAVE THAT TO DISK, so anything that can reach the port owns the
    /// instrument's mapping.
    ///
    /// The default is `0.0.0.0`, which is what the daemon has always done and
    /// what the web editor at `http://<pi-ip>:9000` needs in order to be
    /// reachable from a laptop. Set it to `127.0.0.1` to close the port to
    /// everything but the Pi itself; the editor then works only in a browser
    /// running ON the Pi. The daemon prints a warning on every start that is
    /// not loopback, because a default nobody is told about is not a decision.
    #[serde(default = "default_ws_bind")]
    pub ws_bind: String,

    /// Enable the daemon's OWN step sequencer, reached with SHIFT + PAD MODE.
    ///
    /// **Defaults to false, and that is a change of behaviour made on
    /// 2026-09-03.** It used to be unconditional, and entering it is a silent
    /// way to lose the instrument: in padmode 2 the pads stop sending notes to
    /// the host and edit the daemon's own sixteen steps instead, PLAY and STOP
    /// drive the daemon's transport rather than reaching the driver, the Group
    /// buttons switch its pages instead of the pad octave, and it repaints
    /// every pad LED in its own colour. Nothing on the panel says so, the
    /// driver cannot see it, and getting out takes three more presses of the
    /// same chord.
    ///
    /// This instrument's sequencer is zynseq, driven by the ctrldev driver. Set
    /// this to true only for standalone use of the daemon with no host.
    ///
    /// Its step rate is fixed at the built-in 100 ms. The only thing that ever
    /// set it was SHIFT + the first encoder, and that arm was one of the eight
    /// in main.rs found unreachable on 2026-09-03 - so the tempo has never
    /// actually been adjustable, and the setter went with the arms.
    #[serde(default)]
    pub internal_sequencer: bool,

    /// Panel contrast, 0-100, applied to BOTH screens at start-up. Factory
    /// value 50. See `screen_brightness` for why this is an `Option`.
    ///
    /// Which of the two device bytes is brightness and which is contrast is
    /// still unproven — the descriptor lists the usages out of order and only
    /// a write settles it. Both are recovered the same way, so a swapped guess
    /// costs nothing.
    #[serde(default)]
    pub screen_contrast: Option<u8>,
}

impl Default for MaschineConfig {
    fn default() -> Self {
        MaschineConfig {
            pad_notes: [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3],
            encoder_ccs: [16, 17, 18, 19, 20, 21, 22, 23],
            external_pad_leds: false,
            send_aftertouch: false,
            ws_bind: default_ws_bind(),
            internal_sequencer: false,
            screen_brightness: None,
            screen_contrast: None,
        }
    }
}

impl MaschineConfig {
    /// Read the config, and SAY SO when it cannot be read.
    ///
    /// This used to be `.ok().and_then(...).ok().unwrap_or_default()`: a
    /// missing file, a syntax error and a wrong type all landed on the
    /// defaults in complete silence. The defaults include
    /// `external_pad_leds: false`, which is the flag whose absence lets the
    /// first pad touch repaint the driver's LED picture in the daemon's own
    /// colour - so one stray comma in maschine.json broke the panel and
    /// explained nothing. A file that exists and does not parse is a mistake
    /// somebody made and wants to hear about.
    pub fn load() -> Self {
        let raw = match fs::read_to_string(CONFIG_PATH) {
            Ok(raw) => raw,
            Err(err) => {
                println!(
                    "config: no {} ({}) - using defaults, external_pad_leds is OFF",
                    CONFIG_PATH, err);
                return Self::default();
            }
        };
        match serde_json::from_str(&raw) {
            Ok(cfg) => cfg,
            Err(err) => {
                println!(
                    "config: {} DOES NOT PARSE ({}) - using defaults, which \
                     means external_pad_leds is OFF and the pad LEDs will \
                     fight the driver. Fix the file and restart.",
                    CONFIG_PATH, err);
                Self::default()
            }
        }
    }

    /// Write the config, atomically.
    ///
    /// Temp file plus rename, because the old form was a bare `fs::write`:
    /// a truncated file is one that no longer parses, and until the branch
    /// above existed that failed silently into the defaults. The WebSocket
    /// editor calls this on every single pad-note change.
    pub fn save(&self) {
        let json = match serde_json::to_string_pretty(self) {
            Ok(json) => json,
            Err(err) => {
                println!("config: cannot serialise ({}), not written", err);
                return;
            }
        };
        let tmp = format!("{}.tmp", CONFIG_PATH);
        if let Err(err) = fs::write(&tmp, json) {
            println!("config: cannot write {} ({}), not saved", tmp, err);
            return;
        }
        if let Err(err) = fs::rename(&tmp, CONFIG_PATH) {
            println!("config: cannot replace {} ({}), not saved", CONFIG_PATH, err);
            let _ = fs::remove_file(&tmp);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_pad_notes() {
        let c = MaschineConfig::default();
        assert_eq!(c.pad_notes, [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3]);
    }

    #[test]
    fn default_encoder_ccs() {
        let c = MaschineConfig::default();
        assert_eq!(c.encoder_ccs, [16, 17, 18, 19, 20, 21, 22, 23]);
    }

    #[test]
    fn json_round_trip() {
        let mut c = MaschineConfig::default();
        c.pad_notes[0] = 60;
        c.encoder_ccs[2] = 74;
        let json = serde_json::to_string(&c).unwrap();
        let loaded: MaschineConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(loaded.pad_notes[0], 60);
        assert_eq!(loaded.encoder_ccs[2], 74);
    }

    #[test]
    fn external_pad_leds_defaults_off() {
        assert!(!MaschineConfig::default().external_pad_leds);
    }

    #[test]
    fn external_pad_leds_absent_from_json_parses_as_off() {
        // Existing maschine.json files predate the field; they must still load.
        let json = r#"{"pad_notes":[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
                       "encoder_ccs":[16,17,18,19,20,21,22,23]}"#;
        let loaded: MaschineConfig = serde_json::from_str(json).unwrap();
        assert!(!loaded.external_pad_leds);
    }

    #[test]
    fn external_pad_leds_round_trips() {
        let mut c = MaschineConfig::default();
        c.external_pad_leds = true;
        let loaded: MaschineConfig =
            serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
        assert!(loaded.external_pad_leds);
    }

    #[test]
    fn send_aftertouch_defaults_off() {
        assert!(!MaschineConfig::default().send_aftertouch);
    }

    #[test]
    fn send_aftertouch_absent_from_json_parses_as_off() {
        // Every maschine.json in the field predates this field. The pads must
        // not silently start emitting 750 msg/s of aftertouch on upgrade.
        let json = r#"{"pad_notes":[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
                       "encoder_ccs":[16,17,18,19,20,21,22,23],
                       "external_pad_leds":true}"#;
        let loaded: MaschineConfig = serde_json::from_str(json).unwrap();
        assert!(loaded.external_pad_leds);
        assert!(!loaded.send_aftertouch);
    }

    #[test]
    fn send_aftertouch_round_trips() {
        let mut c = MaschineConfig::default();
        c.send_aftertouch = true;
        let loaded: MaschineConfig =
            serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
        assert!(loaded.send_aftertouch);
    }

    #[test]
    fn saving_preserves_both_flags() {
        // The WS config-save path rebuilds MaschineConfig from handler state.
        // A field missed there is a silent downgrade of a live rig.
        let mut c = MaschineConfig::default();
        c.external_pad_leds = true;
        c.send_aftertouch = true;
        let json = serde_json::to_string_pretty(&c).unwrap();
        assert!(json.contains("external_pad_leds"));
        assert!(json.contains("send_aftertouch"));
    }

    #[test]
    fn screen_settings_default_to_absent() {
        // Absent, not 72/50: a default that carries values would make every
        // existing rig issue a non-volatile HID write on its next restart.
        let c = MaschineConfig::default();
        assert!(c.screen_brightness.is_none());
        assert!(c.screen_contrast.is_none());
    }

    #[test]
    fn screen_settings_absent_from_json_stay_absent() {
        // Every maschine.json in the field predates these fields, including
        // the one install.sh has already placed on the rig.
        let json = r#"{"pad_notes":[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
                       "encoder_ccs":[16,17,18,19,20,21,22,23],
                       "external_pad_leds":true}"#;
        let loaded: MaschineConfig = serde_json::from_str(json).unwrap();
        assert!(loaded.external_pad_leds);
        assert!(loaded.screen_brightness.is_none());
        assert!(loaded.screen_contrast.is_none());
    }

    #[test]
    fn screen_settings_round_trip() {
        let mut c = MaschineConfig::default();
        c.screen_brightness = Some(72);
        c.screen_contrast = Some(50);
        let loaded: MaschineConfig =
            serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
        assert_eq!(loaded.screen_brightness, Some(72));
        assert_eq!(loaded.screen_contrast, Some(50));
    }

    #[test]
    fn an_explicit_null_reads_as_absent() {
        // A maschine.json written back out by save() carries nulls rather than
        // dropping the keys; reloading it must not start writing to the panel.
        let json = r#"{"pad_notes":[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
                       "encoder_ccs":[16,17,18,19,20,21,22,23],
                       "screen_brightness":null,"screen_contrast":null}"#;
        let loaded: MaschineConfig = serde_json::from_str(json).unwrap();
        assert!(loaded.screen_brightness.is_none());
        assert!(loaded.screen_contrast.is_none());
    }

    #[test]
    fn saving_preserves_the_screen_settings() {
        // save() serialises the whole struct from handler state; a field
        // missed at a rebuild site is a silent downgrade of a live rig.
        let mut c = MaschineConfig::default();
        c.screen_brightness = Some(72);
        c.screen_contrast = Some(50);
        let json = serde_json::to_string_pretty(&c).unwrap();
        assert!(json.contains("screen_brightness"));
        assert!(json.contains("screen_contrast"));
    }

    #[test]
    fn load_returns_default_on_bad_json() {
        let result: Result<MaschineConfig, _> = serde_json::from_str("not json");
        assert!(result.is_err());
    }

    #[test]
    fn ws_bind_defaults_to_what_the_daemon_always_did() {
        // 0.0.0.0, unchanged: the web editor at http://<pi-ip>:9000 is only
        // reachable from a laptop while this is wide. The daemon warns on
        // every start that is not loopback instead of quietly narrowing.
        assert_eq!(MaschineConfig::default().ws_bind, "0.0.0.0");
    }

    #[test]
    fn ws_bind_absent_from_json_keeps_the_old_behaviour() {
        // Every maschine.json in the field predates the key, including the one
        // install.sh has already placed on the rig. Absent must not mean "".
        let json = r#"{"pad_notes":[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
                       "encoder_ccs":[16,17,18,19,20,21,22,23]}"#;
        let loaded: MaschineConfig = serde_json::from_str(json).unwrap();
        assert_eq!(loaded.ws_bind, "0.0.0.0");
    }

    #[test]
    fn ws_bind_round_trips_a_narrowed_socket() {
        let mut c = MaschineConfig::default();
        c.ws_bind = "127.0.0.1".to_string();
        let loaded: MaschineConfig =
            serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
        assert_eq!(loaded.ws_bind, "127.0.0.1");
    }

    #[test]
    fn the_internal_sequencer_is_off_unless_asked_for() {
        // SHIFT + PAD MODE used to enter it unconditionally, which takes the
        // pads, the transport and the Group buttons away from the host with
        // nothing on the panel to say so.
        assert!(!MaschineConfig::default().internal_sequencer);
        let json = r#"{"pad_notes":[12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
                       "encoder_ccs":[16,17,18,19,20,21,22,23]}"#;
        let loaded: MaschineConfig = serde_json::from_str(json).unwrap();
        assert!(!loaded.internal_sequencer);
    }

    #[test]
    fn the_internal_sequencer_can_be_turned_back_on() {
        let mut c = MaschineConfig::default();
        c.internal_sequencer = true;
        let loaded: MaschineConfig =
            serde_json::from_str(&serde_json::to_string(&c).unwrap()).unwrap();
        assert!(loaded.internal_sequencer);
    }

    #[test]
    fn saving_preserves_every_key_including_the_new_ones() {
        // The WS save path holds the loaded config and overwrites only the two
        // arrays it owns, so this can no longer be missed at a rebuild site -
        // but the serialised form still has to carry them.
        let c = MaschineConfig::default();
        let json = serde_json::to_string_pretty(&c).unwrap();
        for key in ["pad_notes", "encoder_ccs", "external_pad_leds",
                    "send_aftertouch", "ws_bind", "internal_sequencer",
                    "screen_brightness", "screen_contrast"] {
            assert!(json.contains(key), "save() dropped {}", key);
        }
    }
}
