use midi::Message;
use midi::Channel::Ch1;

pub fn parse(buf: &[u8]) -> Vec<Message> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < buf.len() {
        let b = buf[i];
        match b & 0xF0 {
            0x90 if i + 2 < buf.len() => {
                let note = buf[i + 1];
                let vel  = buf[i + 2];
                if vel == 0 {
                    out.push(Message::NoteOff(Ch1, note, 0));
                } else {
                    out.push(Message::NoteOn(Ch1, note, vel));
                }
                i += 3;
            }
            0x80 if i + 2 < buf.len() => {
                out.push(Message::NoteOff(Ch1, buf[i + 1], buf[i + 2]));
                i += 3;
            }
            0xB0 if i + 2 < buf.len() => {
                out.push(Message::RPN7(Ch1, buf[i + 1] as u16, buf[i + 2]));
                i += 3;
            }
            0xF0 => match b {
                0xF8 => { out.push(Message::TimingClock); i += 1; }
                0xFA => { out.push(Message::Start);       i += 1; }
                0xFC => { out.push(Message::Stop);        i += 1; }
                _    => { i += 1; }
            }
            _ => { i += 1; }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use midi::Message;
    use midi::Channel::Ch1;

    #[test]
    fn note_on_parsed() {
        let msgs = parse(&[0x90, 60, 100]);
        assert_eq!(msgs.len(), 1);
        assert!(matches!(msgs[0], Message::NoteOn(Ch1, 60, 100)));
    }

    #[test]
    fn note_on_vel_zero_becomes_note_off() {
        let msgs = parse(&[0x90, 60, 0]);
        assert_eq!(msgs.len(), 1);
        assert!(matches!(msgs[0], Message::NoteOff(Ch1, 60, 0)));
    }

    #[test]
    fn note_off_parsed() {
        let msgs = parse(&[0x80, 48, 64]);
        assert_eq!(msgs.len(), 1);
        assert!(matches!(msgs[0], Message::NoteOff(Ch1, 48, 64)));
    }

    #[test]
    fn cc_parsed_as_rpn7() {
        let msgs = parse(&[0xB0, 7, 100]);
        assert_eq!(msgs.len(), 1);
        assert!(matches!(msgs[0], Message::RPN7(Ch1, 7, 100)));
    }

    #[test]
    fn clock_parsed() {
        let msgs = parse(&[0xF8]);
        assert_eq!(msgs.len(), 1);
        assert!(matches!(msgs[0], Message::TimingClock));
    }

    #[test]
    fn start_stop_parsed() {
        let msgs = parse(&[0xFA, 0xFC]);
        assert_eq!(msgs.len(), 2);
        assert!(matches!(msgs[0], Message::Start));
        assert!(matches!(msgs[1], Message::Stop));
    }

    #[test]
    fn multi_message_packet() {
        let msgs = parse(&[0xF8, 0x90, 36, 80, 0x80, 36, 0]);
        assert_eq!(msgs.len(), 3);
        assert!(matches!(msgs[0], Message::TimingClock));
        assert!(matches!(msgs[1], Message::NoteOn(Ch1, 36, 80)));
        assert!(matches!(msgs[2], Message::NoteOff(Ch1, 36, 0)));
    }

    #[test]
    fn truncated_message_skipped() {
        let msgs = parse(&[0x90, 60]);
        assert!(msgs.is_empty());
    }

    #[test]
    fn unknown_bytes_skipped() {
        let msgs = parse(&[0xFE, 0xF8]);
        assert_eq!(msgs.len(), 1);
        assert!(matches!(msgs[0], Message::TimingClock));
    }
}
