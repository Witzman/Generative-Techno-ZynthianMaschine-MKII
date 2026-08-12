use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DeviceEvent {
    PadPressed { pad: usize, velocity: u8 },
    PadReleased { pad: usize },
    ButtonDown { button: String },
    ButtonUp { button: String },
    Encoder { idx: usize, value: u8 },
    ConfigSnapshot { pad_notes: Vec<u8>, encoder_ccs: Vec<u16> },
    ClockBpm { bpm: f32 },
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum WsCommand {
    SetPadColor { pad: usize, color: u32, brightness: f32 },
    SetButtonColor { button: String, brightness: f32 },
    SetNoteBase { base: u8 },
    SetPadNote { pad: usize, note: u8 },
    #[serde(rename = "set_encoder_cc")]
    SetEncoderCC { encoder: usize, cc: u16 },
    RequestConfig,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pad_pressed_serializes() {
        let ev = DeviceEvent::PadPressed { pad: 3, velocity: 100 };
        let json = serde_json::to_string(&ev).unwrap();
        assert!(json.contains("\"type\":\"pad_pressed\""));
        assert!(json.contains("\"pad\":3"));
        assert!(json.contains("\"velocity\":100"));
    }

    #[test]
    fn encoder_serializes() {
        let ev = DeviceEvent::Encoder { idx: 2, value: 64 };
        let json = serde_json::to_string(&ev).unwrap();
        assert!(json.contains("\"type\":\"encoder\""));
        assert!(json.contains("\"idx\":2"));
        assert!(json.contains("\"value\":64"));
    }

    #[test]
    fn set_pad_color_deserializes() {
        let json = r#"{"type":"set_pad_color","pad":0,"color":16711680,"brightness":0.8}"#;
        let cmd: WsCommand = serde_json::from_str(json).unwrap();
        match cmd {
            WsCommand::SetPadColor { pad, color, brightness } => {
                assert_eq!(pad, 0);
                assert_eq!(color, 16711680);
                assert!((brightness - 0.8).abs() < 0.001);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn set_note_base_deserializes() {
        let json = r#"{"type":"set_note_base","base":48}"#;
        let cmd: WsCommand = serde_json::from_str(json).unwrap();
        match cmd {
            WsCommand::SetNoteBase { base } => assert_eq!(base, 48),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn set_pad_note_deserializes() {
        let json = r#"{"type":"set_pad_note","pad":3,"note":60}"#;
        let cmd: WsCommand = serde_json::from_str(json).unwrap();
        match cmd {
            WsCommand::SetPadNote { pad, note } => {
                assert_eq!(pad, 3);
                assert_eq!(note, 60);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn set_encoder_cc_deserializes() {
        let json = r#"{"type":"set_encoder_cc","encoder":2,"cc":74}"#;
        let cmd: WsCommand = serde_json::from_str(json).unwrap();
        match cmd {
            WsCommand::SetEncoderCC { encoder, cc } => {
                assert_eq!(encoder, 2);
                assert_eq!(cc, 74);
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn request_config_deserializes() {
        let json = r#"{"type":"request_config"}"#;
        let cmd: WsCommand = serde_json::from_str(json).unwrap();
        assert!(matches!(cmd, WsCommand::RequestConfig));
    }

    #[test]
    fn config_snapshot_serializes() {
        let ev = DeviceEvent::ConfigSnapshot {
            pad_notes: vec![12,13,14,15,8,9,10,11,4,5,6,7,0,1,2,3],
            encoder_ccs: vec![16,17,18,19,20,21,22,23],
        };
        let json = serde_json::to_string(&ev).unwrap();
        assert!(json.contains("\"type\":\"config_snapshot\""));
        assert!(json.contains("\"pad_notes\""));
        assert!(json.contains("\"encoder_ccs\""));
    }

    #[test]
    fn clock_bpm_serializes() {
        let ev = DeviceEvent::ClockBpm { bpm: 120.5 };
        let json = serde_json::to_string(&ev).unwrap();
        assert!(json.contains("\"type\":\"clock_bpm\""));
        assert!(json.contains("\"bpm\""));
    }
}
