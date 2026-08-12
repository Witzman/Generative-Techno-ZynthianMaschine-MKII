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
}

impl Default for MaschineConfig {
    fn default() -> Self {
        MaschineConfig {
            pad_notes: [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3],
            encoder_ccs: [16, 17, 18, 19, 20, 21, 22, 23],
            external_pad_leds: false,
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
    fn load_returns_default_on_bad_json() {
        let result: Result<MaschineConfig, _> = serde_json::from_str("not json");
        assert!(result.is_err());
    }
}
