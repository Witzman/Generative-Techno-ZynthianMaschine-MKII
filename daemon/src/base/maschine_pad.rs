//  maschine.rs: user-space drivers for native instruments USB HIDs
//  Copyright (C) 2015 William Light <wrl@illest.net>
//
//  This program is free software: you can redistribute it and/or modify
//  it under the terms of the GNU Lesser General Public License as
//  published by the Free Software Foundation, either version 3 of the
//  License, or (at your option) any later version.
//
//  This program is distributed in the hope that it will be useful,
//  but WITHOUT ANY WARRANTY; without even the implied warranty of
//  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//  GNU Lesser General Public License for more details.
//
//  You should have received a copy of the GNU Lesser General Public
//  License along with this program.  If not, see
//  <http://www.gnu.org/licenses/>.

use std::collections::VecDeque;
use std::cmp::Ordering::Equal;

// Pressure thresholds, in fractions of the pad's 12-bit range (0-4095, and the
// HID descriptor declares the field as 16-bit with a maximum of 65534).
//
// ARM. Unchanged from wrl's 2015 original at 32/4096 = 0.0078. Ctlra arms at
// 550/4096 = 0.134 — SEVENTEEN TIMES higher — which is the difference the
// 2026-08-30 project survey pointed at as the ghost-hit gap. It was NOT adopted
// here, deliberately: no ghost hit has ever been reported on this rig, the
// number governs how light a tap registers, and raising it by seventeen times
// on no evidence would make the pads feel dead on a control the owner plays
// constantly. It is a named constant now so the gate can try a value and hear
// the difference, which is the only way this number can honestly be chosen.
const PRESS_THRESHOLD: f32 = 32.0 / 4096.0;

// RELEASE, and this one WAS a real defect. The original required the filtered
// pressure to be EXACTLY 0.0 to release a pad — a float equality on sensor
// data. Any resting noise floor at all and the pad never releases: no note-off,
// a stuck note, forever.
//
// It would also have been nearly invisible. Four of this instrument's eight
// channels are drums, and a LinuxSampler one-shot plays to the end whether or
// not a note-off arrives, so a stuck note only ever shows on the three voices.
//
// 8/4096 = 0.002 is a quarter of the arm threshold, so there is a genuine
// hysteresis band between them: a pad held anywhere between 0.002 and 0.0078
// stays held rather than chattering.
const RELEASE_THRESHOLD: f32 = 8.0 / 4096.0;

const MEDIAN_KERNEL_LENGTH: usize = 15;

#[derive(Copy, Clone, Debug)]
enum MaschinePadState {
    Unpressed = 0,
    PressedBelowThreshold,
    PressedAboveThreshold
}

#[derive(Copy, Clone, Debug)]
pub enum MaschinePadStateTransition {
    AtRest,
    Pressed,
    Aftertouch,
    Released
}

#[derive(Clone)]
pub struct MaschinePad {
    state: MaschinePadState,
    pressure: VecDeque<f32>
}

impl Default for MaschinePad {
    fn default() -> Self {
        let mut _self = MaschinePad {
            state: MaschinePadState::Unpressed,
            pressure: VecDeque::with_capacity(MEDIAN_KERNEL_LENGTH)
        };

        for _ in 0..MEDIAN_KERNEL_LENGTH {
            _self.pressure.push_back(0.0);
        }

        _self
    }
}

impl MaschinePad {
    /// The median of the last MEDIAN_KERNEL_LENGTH samples.
    ///
    /// On a fixed array rather than a Vec since 2026-08-30. This runs once per
    /// pressure report per pad — the device streams ~750 reports/s — so the
    /// original allocated and freed a small Vec thousands of times a second on
    /// the very thread whose starvation is this project's central fault. The
    /// arithmetic is unchanged.
    fn filtered_pressure(&self) -> f32 {
        let mut vals = [0.0f32; MEDIAN_KERNEL_LENGTH];
        for (slot, v) in vals.iter_mut().zip(self.pressure.iter()) {
            *slot = *v;
        }
        vals.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Equal));

        let middle = MEDIAN_KERNEL_LENGTH / 2;

        if (MEDIAN_KERNEL_LENGTH & 1) == 1 {
            // odd
            vals[middle]
        } else {
            // even
            (vals[middle] + vals[middle + 1]) / 2.0
        }
    }

    pub fn pressure_val(&mut self, pressure: f32) -> MaschinePadStateTransition {
        self.pressure.pop_front();
        self.pressure.push_back(pressure);

        let pressure = self.filtered_pressure();

        match self.state {
            MaschinePadState::Unpressed =>
                if pressure > PRESS_THRESHOLD {
                    self.state = MaschinePadState::PressedAboveThreshold;
                    return MaschinePadStateTransition::Pressed;
                } else if pressure > RELEASE_THRESHOLD {
                    self.state = MaschinePadState::PressedBelowThreshold;
                },

            MaschinePadState::PressedBelowThreshold =>
                if pressure <= RELEASE_THRESHOLD {
                    self.state = MaschinePadState::Unpressed;
                } else if pressure > PRESS_THRESHOLD {
                    // A press that crossed the arm threshold on its way up
                    // rather than in one report. The original could only reach
                    // PressedAboveThreshold from Unpressed, so a slow press
                    // that paused in this state was swallowed entirely and the
                    // pad never sounded until it was fully released first.
                    self.state = MaschinePadState::PressedAboveThreshold;
                    return MaschinePadStateTransition::Pressed;
                },

            MaschinePadState::PressedAboveThreshold =>
                if pressure <= RELEASE_THRESHOLD {
                    // NOT `== 0.0`. See RELEASE_THRESHOLD: a float equality on
                    // sensor data meant any resting noise floor left the pad
                    // held forever with no note-off.
                    self.state = MaschinePadState::Unpressed;
                    return MaschinePadStateTransition::Released;
                } else {
                    return MaschinePadStateTransition::Aftertouch;
                },
        }

        return MaschinePadStateTransition::AtRest;
    }

    #[allow(dead_code)]
    pub fn is_pressed(&self) -> bool {
        match self.state {
            MaschinePadState::PressedAboveThreshold => true,
            _ => false
        }
    }

    #[allow(dead_code)]
    pub fn get_pressure(&self) -> f32 {
        match self.state {
            MaschinePadState::PressedAboveThreshold => self.filtered_pressure(),
            _ => 0.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(pad: &mut MaschinePad, v: f32) -> MaschinePadStateTransition {
        pad.pressure_val(v)
    }

    /// Feed one value until the median settles on it, returning the last
    /// transition. The kernel is 15 long, so a value has to arrive 8 times
    /// before it can be the median.
    fn settle(pad: &mut MaschinePad, v: f32) -> MaschinePadStateTransition {
        let mut last = MaschinePadStateTransition::AtRest;
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            last = t(pad, v);
        }
        last
    }

    fn is_pressed(x: &MaschinePadStateTransition) -> bool {
        matches!(x, MaschinePadStateTransition::Pressed)
    }
    fn is_released(x: &MaschinePadStateTransition) -> bool {
        matches!(x, MaschinePadStateTransition::Released)
    }

    #[test]
    fn a_pad_starts_at_rest() {
        let mut p = MaschinePad::default();
        assert!(matches!(t(&mut p, 0.0), MaschinePadStateTransition::AtRest));
        assert!(!p.is_pressed());
    }

    #[test]
    fn a_firm_hit_presses() {
        let mut p = MaschinePad::default();
        let mut saw_press = false;
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            if is_pressed(&t(&mut p, 0.8)) {
                saw_press = true;
            }
        }
        assert!(saw_press);
        assert!(p.is_pressed());
    }

    #[test]
    fn a_held_pad_reports_aftertouch() {
        let mut p = MaschinePad::default();
        settle(&mut p, 0.8);
        assert!(matches!(t(&mut p, 0.8), MaschinePadStateTransition::Aftertouch));
    }

    #[test]
    fn releasing_to_exactly_zero_still_releases() {
        // The original behaviour, which must not regress.
        let mut p = MaschinePad::default();
        settle(&mut p, 0.8);
        let mut saw = false;
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            if is_released(&t(&mut p, 0.0)) {
                saw = true;
            }
        }
        assert!(saw);
        assert!(!p.is_pressed());
    }

    #[test]
    fn releasing_to_a_NOISE_FLOOR_releases_too() {
        // THE BUG. The original required the filtered pressure to be exactly
        // 0.0, so a pad resting on any noise at all was held forever with no
        // note-off. On the five drum channels that is invisible - a
        // LinuxSampler one-shot plays to the end regardless - so it could only
        // ever have shown up as a stuck note on one of the three voices.
        //
        // The noise floor here is a LITERAL, not a fraction of
        // RELEASE_THRESHOLD. Deriving it from the constant makes the test move
        // with the constant, so setting the threshold back to 0.0 would leave
        // this passing — which is exactly what a mutation run caught on
        // 2026-08-30, and the reason this comment exists.
        const NOISE_FLOOR: f32 = 4.0 / 4096.0;
        assert!(NOISE_FLOOR > 0.0 && NOISE_FLOOR < PRESS_THRESHOLD);

        let mut p = MaschinePad::default();
        settle(&mut p, 0.8);
        let mut saw = false;
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            if is_released(&t(&mut p, NOISE_FLOOR)) {
                saw = true;
            }
        }
        assert!(saw, "a pad resting above 0.0 must still release");
        assert!(!p.is_pressed());
    }

    #[test]
    fn a_pad_resting_ON_the_release_threshold_releases() {
        // The boundary is inclusive on purpose: a pad sitting exactly on it
        // must not be the one case that sticks.
        let mut p = MaschinePad::default();
        settle(&mut p, 0.8);
        let mut saw = false;
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            if is_released(&t(&mut p, RELEASE_THRESHOLD)) {
                saw = true;
            }
        }
        assert!(saw);
    }

    #[test]
    fn the_hysteresis_band_holds_a_pad_instead_of_chattering() {
        // Between the two thresholds a held pad stays held. Without a band,
        // pressure hovering at the arm point would emit press/release pairs.
        let mut p = MaschinePad::default();
        settle(&mut p, 0.8);
        // A literal inside the band, for the same reason as above.
        let mid = 16.0 / 4096.0;
        assert!(mid > RELEASE_THRESHOLD && mid < PRESS_THRESHOLD);
        for _ in 0..(MEDIAN_KERNEL_LENGTH * 3) {
            assert!(!is_released(&t(&mut p, mid)), "must not release inside the band");
        }
        assert!(p.is_pressed());
    }

    #[test]
    fn the_release_threshold_is_below_the_arm_threshold() {
        // If these ever cross, the band inverts and the state machine chatters.
        assert!(RELEASE_THRESHOLD < PRESS_THRESHOLD);
    }

    #[test]
    fn the_release_threshold_is_strictly_positive() {
        // The whole point. A zero release threshold is the original bug.
        assert!(RELEASE_THRESHOLD > 0.0);
    }

    #[test]
    fn a_touch_too_light_to_arm_never_presses() {
        let mut p = MaschinePad::default();
        let light = (PRESS_THRESHOLD + RELEASE_THRESHOLD) / 2.0;
        for _ in 0..(MEDIAN_KERNEL_LENGTH * 2) {
            assert!(!is_pressed(&t(&mut p, light)));
        }
        assert!(!p.is_pressed());
    }

    #[test]
    fn a_light_touch_then_lifting_returns_to_rest_silently() {
        let mut p = MaschinePad::default();
        let light = (PRESS_THRESHOLD + RELEASE_THRESHOLD) / 2.0;
        settle(&mut p, light);
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            // No note-off for a note that never sounded.
            assert!(!is_released(&t(&mut p, 0.0)));
        }
    }

    #[test]
    fn a_SLOW_press_through_the_light_zone_still_sounds() {
        // The original could only reach the pressed state from Unpressed, so a
        // press that paused in the light zone on its way down was swallowed
        // and the pad stayed silent until it was fully lifted first.
        let mut p = MaschinePad::default();
        settle(&mut p, 16.0 / 4096.0);
        assert!(!p.is_pressed());
        let mut saw = false;
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            if is_pressed(&t(&mut p, 0.9)) {
                saw = true;
            }
        }
        assert!(saw, "a slow press must still sound");
    }

    #[test]
    fn a_pad_can_be_played_again_after_release() {
        let mut p = MaschinePad::default();
        for _ in 0..4 {
            let mut pressed = false;
            for _ in 0..MEDIAN_KERNEL_LENGTH {
                if is_pressed(&t(&mut p, 0.9)) { pressed = true; }
            }
            assert!(pressed, "every hit must sound");
            let mut released = false;
            for _ in 0..MEDIAN_KERNEL_LENGTH {
                if is_released(&t(&mut p, 0.0)) { released = true; }
            }
            assert!(released, "every hit must release");
        }
    }

    #[test]
    fn one_stray_sample_cannot_trigger_a_note() {
        // What the median kernel is for: a single spike among fifteen quiet
        // samples never becomes the median.
        let mut p = MaschinePad::default();
        for _ in 0..MEDIAN_KERNEL_LENGTH {
            t(&mut p, 0.0);
        }
        assert!(!is_pressed(&t(&mut p, 1.0)));
        assert!(!p.is_pressed());
    }

    #[test]
    fn one_stray_zero_cannot_release_a_held_pad() {
        let mut p = MaschinePad::default();
        settle(&mut p, 0.8);
        assert!(!is_released(&t(&mut p, 0.0)));
        assert!(p.is_pressed());
    }

    #[test]
    fn get_pressure_is_zero_unless_pressed() {
        let mut p = MaschinePad::default();
        settle(&mut p, (PRESS_THRESHOLD + RELEASE_THRESHOLD) / 2.0);
        assert_eq!(p.get_pressure(), 0.0);
        settle(&mut p, 0.8);
        assert!(p.get_pressure() > 0.5);
    }

    #[test]
    fn the_median_is_unchanged_by_dropping_the_allocation() {
        // The filter was rewritten onto a fixed array on 2026-08-30 to stop it
        // allocating thousands of times a second on the input thread. The
        // arithmetic must be identical: the median of a full window of one
        // value is that value.
        let mut p = MaschinePad::default();
        settle(&mut p, 0.375);
        assert!((p.filtered_pressure() - 0.375).abs() < f32::EPSILON);
    }
}
