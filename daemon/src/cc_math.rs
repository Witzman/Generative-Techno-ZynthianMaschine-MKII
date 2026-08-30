pub fn normalize_encoder(raw_status: i32, roller_state: usize) -> u8 {
    let accumulated = raw_status / 4 + roller_state as i32 * 64;
    accumulated.clamp(0, 127) as u8
}

/// Where an encoder's reported CC lands after moving by `delta`.
///
/// The encoders are endless, so the hardware only ever gives a counter. The
/// reported value has to be carried as state and moved by the difference,
/// not recomputed from that counter: recomputing pins the reported position
/// to the physical counter, so a host cannot re-centre a knob it has
/// repointed at a different parameter, and the knob sits against an end stop
/// with no way off it.
pub fn accumulate_encoder(current: i32, delta: i32) -> u8 {
    (current + delta).clamp(0, 127) as u8
}

/// The most an encoder can genuinely move between two reports.
///
/// Measured on the hardware at ~750 reports/s: real movement is 0-4 units per
/// report, while a wrap of the hardware counter shows up as -38 to -40. The
/// original guard of 40 caught only the largest of those, so a wrap every ~40
/// units of travel reached the host as a real backwards movement and yanked
/// whatever parameter the knob was driving.
pub const ENC_MAX_DELTA: i32 = 8;

pub fn is_encoder_jump(delta: i32) -> bool {
    delta.abs() >= ENC_MAX_DELTA
}

/// How far the reported value moves per detent of the BIG encoder.
///
/// The big encoder is coarse - a revolution is detents, not the ~1024 steps
/// the other eight report - and the path this replaces sent `counter * 8` as
/// an absolute value, so one revolution was a full 0-127 sweep. Keeping the
/// scale at 8 keeps that feel exactly while removing the wrap.
pub const BIG_ENC_SCALE: i32 = 8;

/// The big encoder's new reported value, or None when the report was a wrap.
///
/// THE BUG THIS FIXES: the big encoder never went through `send_encoder_cc`
/// like the other eight. It sent its raw counter times eight as an ABSOLUTE
/// value on every detent, so when the counter rolled over the target snapped
/// from 120 to 0 - once per revolution, on whatever the knob was driving.
///
/// A wrap is REJECTED rather than decoded, deliberately. Decoding it needs the
/// counter's modulus, and the width of that counter is not established from
/// the source: byte 7 is *named* as eight buttons A1-A8, and this project's
/// own rule is that a token name is never evidence about the hardware. The
/// caller resyncs its baseline on a rejection exactly as `send_encoder_cc`
/// does, so the cost is ONE LOST DETENT per revolution instead of a yank.
/// If a capture ever establishes the modulus, this becomes wrap arithmetic
/// and the tests above already say what it must do.
pub fn big_encoder_value(prev_counter: i32, cur_counter: i32, current: i32) -> Option<u8> {
    let delta = cur_counter - prev_counter;
    if is_encoder_jump(delta) {
        return None;
    }
    Some(accumulate_encoder(current, delta * BIG_ENC_SCALE))
}

pub fn button_cc_value(is_down: bool) -> u8 {
    if is_down { 127 } else { 0 }
}

pub fn group_cc(group_idx: usize) -> u16 {
    80 + (group_idx.min(7) as u16)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encoder_zero() {
        assert_eq!(normalize_encoder(0, 0), 0);
    }

    #[test]
    fn encoder_mid_range() {
        assert_eq!(normalize_encoder(128, 1), 96);
    }

    #[test]
    fn encoder_clamps_high() {
        assert_eq!(normalize_encoder(252, 3), 127);
    }

    #[test]
    fn encoder_clamps_low() {
        assert_eq!(normalize_encoder(-100, 0), 0);
    }

    #[test]
    fn accumulate_moves_by_the_delta() {
        assert_eq!(accumulate_encoder(60, 3), 63);
        assert_eq!(accumulate_encoder(60, -3), 57);
    }

    #[test]
    fn accumulate_clamps_at_both_ends() {
        assert_eq!(accumulate_encoder(127, 5), 127);
        assert_eq!(accumulate_encoder(0, -5), 0);
    }

    #[test]
    fn accumulate_leaves_an_end_stop_immediately() {
        // The point of holding the value as state: one step back off the top
        // has to register, not be swallowed by an overshoot.
        assert_eq!(accumulate_encoder(127, -1), 126);
    }

    #[test]
    fn real_movement_is_not_a_jump() {
        // Every per-report delta seen in the hardware capture.
        for d in [-1, 0, 1, 2, 3, 4] {
            assert!(!is_encoder_jump(d), "delta {} should pass", d);
        }
    }

    #[test]
    fn counter_wraps_are_jumps() {
        for d in [-38, -39, -40] {
            assert!(is_encoder_jump(d), "delta {} should be rejected", d);
        }
    }

    #[test]
    fn big_encoder_still_reports_when_it_has_not_moved() {
        // A repeated report is not a wrap and must not be swallowed as one.
        assert_eq!(big_encoder_value(7, 7, 64), Some(64));
    }

    #[test]
    fn big_encoder_one_detent_moves_by_the_scale() {
        assert_eq!(big_encoder_value(7, 8, 64), Some(72));
        assert_eq!(big_encoder_value(8, 7, 64), Some(56));
    }

    #[test]
    fn big_encoder_one_revolution_covers_the_whole_range() {
        // The feel this replaces: the old absolute path sent counter*8, so a
        // revolution was a full sweep. Sixteen detents must still be one.
        let mut value = 0i32;
        for c in 0..16 {
            value = big_encoder_value(c, c + 1, value).unwrap() as i32;
        }
        assert_eq!(value, 127);
    }

    #[test]
    fn big_encoder_rejects_the_counter_wrap() {
        // THE BUG. The old path sent 15*8=120 then 0*8=0, so whatever the knob
        // was driving snapped to zero once per revolution.
        assert_eq!(big_encoder_value(15, 0, 120), None);
    }

    #[test]
    fn big_encoder_rejects_the_wrap_in_both_directions() {
        assert_eq!(big_encoder_value(0, 15, 8), None);
    }

    #[test]
    fn big_encoder_clamps_at_both_ends() {
        assert_eq!(big_encoder_value(0, 1, 125), Some(127));
        assert_eq!(big_encoder_value(1, 0, 2), Some(0));
    }

    #[test]
    fn big_encoder_leaves_an_end_stop_immediately() {
        assert_eq!(big_encoder_value(1, 0, 127), Some(119));
    }

    #[test]
    fn big_encoder_a_rejected_wrap_costs_one_detent_and_nothing_else() {
        // What the player actually experiences after this fix: the wrap is
        // dropped, the caller resyncs the baseline, and the very next detent
        // moves normally. One lost detent per revolution instead of a yank.
        assert_eq!(big_encoder_value(15, 0, 100), None);
        assert_eq!(big_encoder_value(0, 1, 100), Some(108));
    }

    #[test]
    fn button_press_gives_127() {
        assert_eq!(button_cc_value(true), 127);
    }

    #[test]
    fn button_release_gives_0() {
        assert_eq!(button_cc_value(false), 0);
    }

    #[test]
    fn group_cc_maps_a_to_80_and_h_to_87() {
        assert_eq!(group_cc(0), 80);
        assert_eq!(group_cc(7), 87);
    }

    #[test]
    fn group_cc_clamps_above_h() {
        assert_eq!(group_cc(99), 87);
    }
}
