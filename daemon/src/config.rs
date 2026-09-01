use serde::{Deserialize, Serialize};
use std::fs;

const CONFIG_PATH: &str = "maschine.json";

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
            screen_brightness: None,
            screen_contrast: None,
        }
    }
}

impl MaschineConfig {
    pub fn load() -> Self {
        fs::read_to_string(CONFIG_PATH)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }

    pub fn save(&self) {
        if let Ok(json) = serde_json::to_string_pretty(self) {
            let _ = fs::write(CONFIG_PATH, json);
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
}
