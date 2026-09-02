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

/// The counter behind the big encoder is FOUR BITS, so sixteen detents.
///
/// MEASURED 2026-08-31, on the rig, over 117 monotonic detents: the counter is
/// the LOW nibble of byte 8 of the 0x01 report - which is the descriptor's byte
/// 7, because the descriptor numbers from after the report id and this project
/// had been reading the raw offset. Every transition was +1 and the sequence
/// wrapped 15 -> 0. The high nibble never moved.
pub const BIG_ENC_MOD: i32 = 16;
const BIG_ENC_HALF: i32 = BIG_ENC_MOD / 2;

/// The big encoder's new reported value. It WRAPS; it does not clamp.
///
/// This knob drives a RING - the page ring of whatever mode you are in - and
/// the driver reads this value as a wrapping position: `big_delta` is
/// `((cur - prev + 64) % 128) - 64`. Both halves have to agree about what
/// happens at the top, and until 2026-08-31 they did not.
///
/// TWO BUGS, ONE AFTER THE OTHER, AND THIS IS THE SECOND FIX:
///
/// The first was a yank. The big encoder never went through `send_encoder_cc`
/// and sent its raw counter times eight as an ABSOLUTE value, so the counter
/// rolling over snapped the target from 120 to 0 once per revolution. MOD depth
/// rides this knob, so it was audible.
///
/// The fix for that rejected the wrap and accumulated through
/// `accumulate_encoder`, which CLAMPS to 0-127. At eight units per detent the
/// value therefore pinned after sixteen detents - one revolution - and the ring
/// went dead until the knob was turned back. The owner found it on the first
/// turn of this knob at the rig: "encoder cycled pages but it stopped - turning
/// back cycled back". 122 daemon tests passed on that build, because nothing in
/// the suite turned a knob more than once around.
///
/// The rejection was deliberate and its author wrote down what would lift it:
/// "Decoding it needs the counter's modulus... If a capture ever establishes
/// the modulus, this becomes wrap arithmetic and the tests above already say
/// what it must do." The capture happened an hour before the end-stop was
/// found. This is that arithmetic.
///
/// The scale stays at eight, so a revolution is still a full sweep and the feel
/// is unchanged. `is_encoder_jump` is not consulted: a wrap is now decoded
/// rather than detected, so there is nothing left for it to catch here.
pub fn big_encoder_value(prev_counter: i32, cur_counter: i32, current: i32) -> u8 {
    let delta =
        (cur_counter - prev_counter + BIG_ENC_HALF).rem_euclid(BIG_ENC_MOD) - BIG_ENC_HALF;
    (current + delta * BIG_ENC_SCALE).rem_euclid(128) as u8
}

/// What a pad actually reaches under a firm hit, as a fraction of its 12-bit
/// range.
///
/// MEASURED 2026-08-31, all sixteen pads, one firm press each with the daemon
/// stopped and the raw stream at 749 reports/s: **3101 to 3479** against a
/// nominal 4095. The highest pad reaches 85% of the range and the mean is 82%.
/// Nothing gets near full scale, so `pressure / 4095.0` throws away the top
/// fifth of the control.
///
/// 3500 rather than the 3479 measured: just above the highest reading, so the
/// hardest pad reaches full without a player having to beat the exact maximum
/// somebody once recorded.
///
/// THE PER-PAD SPREAD IS NOT USED, deliberately. It looks like hardware and it
/// is mostly the player: the maxima correlate +0.79 with the ORDER the pads
/// were pressed - the first ones pressed are the weakest - and only -0.17 and
/// -0.08 with feature reports 0xDA and 0xDB, which had been the standing
/// hypothesis for a per-pad calibration table. One ceiling for all sixteen is
/// what the data supports.
pub const PAD_FULL_SCALE: f32 = 3500.0 / 4095.0;

/// Aftertouch only. Note velocity keeps the old scaling on purpose.
///
/// The divisor feeds BOTH, and velocity is shipped and already gated while
/// pressure is new and ungated - so correcting the shared constant would
/// change how hard every pad hits across the whole instrument, which is a
/// bigger change than the bug and would need everything re-gated against it.
/// Owner's decision, 2026-08-31: "scale aftertouch only, leave velocity
/// alone."
pub fn aftertouch_scale(pressure: f32) -> f32 {
    (pressure / PAD_FULL_SCALE).clamp(0.0, 1.0)
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
        assert_eq!(big_encoder_value(7, 7, 64), 64);
    }

    #[test]
    fn big_encoder_one_detent_moves_by_the_scale() {
        assert_eq!(big_encoder_value(7, 8, 64), 72);
        assert_eq!(big_encoder_value(8, 7, 64), 56);
    }

    #[test]
    fn big_encoder_one_revolution_covers_the_whole_range() {
        // The feel this preserves: the old absolute path sent counter*8, so a
        // revolution was a full sweep. Sixteen detents is still one.
        let mut value = 0i32;
        for c in 0..16 {
            value = big_encoder_value(c, c + 1, value) as i32;
        }
        assert_eq!(value, 0);           // 16 * 8 = 128, which is 0 again
    }

    #[test]
    fn the_counter_wrap_is_one_detent_FORWARD() {
        // Measured 2026-08-31: the counter is the LOW nibble of byte 8,
        // modulus 16, over 117 monotonic detents. Rejecting this wrap cost one
        // detent per revolution; decoding it costs nothing.
        assert_eq!(big_encoder_value(15, 0, 64), 72);
    }

    #[test]
    fn the_counter_wrap_is_one_detent_BACKWARD_the_other_way() {
        assert_eq!(big_encoder_value(0, 15, 64), 56);
    }

    #[test]
    fn turning_past_a_revolution_KEEPS_MOVING() {
        // THE BUG THE OWNER FOUND, 2026-08-31, first turn of this knob on the
        // rig: "encoder cycled pages but it stopped - turning back cycled
        // back". accumulate_encoder clamps to 0-127, so at eight units per
        // detent the value pinned after sixteen detents and the ring went
        // dead. A ring control cannot have an end stop.
        let mut value = 0i32;
        let mut seen = 0;
        for step in 0..64 {
            let c = step % 16;
            let next = big_encoder_value(c, (c + 1) % 16, value) as i32;
            if next != value {
                seen += 1;
            }
            value = next;
        }
        assert_eq!(seen, 64, "every detent of four revolutions must move it");
    }

    #[test]
    fn the_value_wraps_rather_than_clamping() {
        // The driver reads this as a WRAPPING position - big_delta is
        // ((cur - prev + 64) % 128) - 64 - so the two halves have to agree
        // about what happens at the top. Clamping here is what broke the ring.
        assert_eq!(big_encoder_value(0, 1, 124), 4);
        assert_eq!(big_encoder_value(1, 0, 4), 124);
    }

    #[test]
    fn the_other_nibble_of_byte_seven_cannot_move_the_knob() {
        // THE DESCRIPTOR SAYS THIS BYTE IS TWO 4-BIT COUNTERS, and the
        // capture of 2026-08-31 measured which one is the big encoder: the
        // LOW nibble ran all sixteen values across 117 transitions, every one
        // +1, while the high nibble stayed at zero.
        //
        // The 2026-08-31 finding warned that reading the WHOLE byte "works by
        // accident" and would break when the other nibble started moving.
        // Checked on 2026-09-02 and the warning was wrong: the delta is taken
        // modulo BIG_ENC_MOD, which is 16, so a change of exactly one nibble
        // step in the high half folds to nothing. The mask added the same day
        // makes the intent explicit; it does not change a single value, and
        // these two assertions are what proves that.
        assert_eq!(big_encoder_value(0x00, 0x10, 64), 64);
        assert_eq!(big_encoder_value(0x30, 0x00, 64), 64);
    }

    #[test]
    fn masking_the_low_nibble_changes_no_value_at_all() {
        // Same input read both ways, across every pair of counters and a
        // foreign nibble on top. If these ever disagree the mask is doing
        // something and somebody has to decide what.
        for high in [0x00u8, 0x10, 0x70, 0xF0] {
            for prev in 0..16i32 {
                for cur in 0..16i32 {
                    let whole = big_encoder_value(
                        prev | high as i32, cur | high as i32, 64);
                    let masked = big_encoder_value(prev, cur, 64);
                    assert_eq!(whole, masked, "high {high:#x} {prev}->{cur}");
                }
            }
        }
    }

    #[test]
    fn many_revolutions_never_stall_in_either_direction() {
        for dir in [1i32, -1i32] {
            let mut value = 64i32;
            let mut moves = 0;
            for step in 0..160 {
                let c = (step * dir).rem_euclid(16);
                let n = (c + dir).rem_euclid(16);
                let next = big_encoder_value(c, n, value) as i32;
                if next != value {
                    moves += 1;
                }
                value = next;
            }
            assert_eq!(moves, 160, "direction {dir} stalled");
        }
    }

    #[test]
    fn aftertouch_zero_stays_zero() {
        assert_eq!(aftertouch_scale(0.0), 0.0);
    }

    #[test]
    fn a_pad_at_its_measured_ceiling_reaches_full() {
        // The highest of the sixteen measured on 2026-08-31.
        assert!(aftertouch_scale(3479.0 / 4095.0) > 0.99);
    }

    #[test]
    fn even_the_weakest_measured_pad_gets_close_to_full() {
        // The lowest of the sixteen. Under the old scaling it reached 0.757.
        let weakest = aftertouch_scale(3101.0 / 4095.0);
        assert!(weakest > 0.88, "weakest pad only reached {weakest}");
    }

    #[test]
    fn it_clamps_rather_than_overshooting() {
        // A pad harder than anything measured must not produce a value above
        // full - pressure_to_vel multiplies by 127 and casts.
        assert_eq!(aftertouch_scale(1.0), 1.0);
        assert_eq!(aftertouch_scale(2.0), 1.0);
    }

    #[test]
    fn it_is_a_boost_not_a_cut() {
        // The whole point: 4095 was unreachable, so the scale must be < 1.
        assert!(PAD_FULL_SCALE < 1.0);
        assert!(aftertouch_scale(0.5) > 0.5);
    }

    #[test]
    fn the_old_scaling_left_a_fifth_of_the_range_unreachable() {
        // Documents what was wrong, in the numbers that were measured.
        let hardest_before = 3479.0 / 4095.0;
        assert!(hardest_before < 0.86);
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
