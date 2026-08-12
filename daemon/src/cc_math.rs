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
