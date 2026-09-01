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

use std::os::unix::io::RawFd;

use midi::Message;
use crate::clock::ClockState;

#[derive(Copy, Clone, Debug)]
pub enum MaschineButton {
    F8,
    F7,
    F6,
    F5,
    F4,
    F3,
    F2,
    F1,

    Auto,
    All,
    Pageleft,
    Pageright,

    Sampling,

    Nav,
    Noterepeat,
    Enter,
    Navright,
    Navleft,
    Tempo,
    Swing,
    Volume,

    GroupH,
    GroupG,
    GroupF,
    GroupE,
    GroupD,
    GroupC,
    GroupB,
    GroupA,

    Shift,
    Erase,
    Rec,
    Play,
    Grid,
    Stepright,
    Stepleft,
    Restart,

    Mute,
    Solo,
    Select,
    Duplicate,
    Navigate,
    Padmode,
    Pattern,
    Scene,
    Browse,
    Step,
    Control,
    Encoder,
    Main,
    View,

    R1,
    R2,
    R3,
    R4,
    R5,
    R6,
    R7,
    R8,

    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    A7,
    A8,

    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    B7,
    B8,

    C1,
    C2,
    C3,
    C4,
    C5,
    C6,
    C7,
    C8,

    D1,
    D2,
    D3,
    D4,
    D5,
    D6,
    D7,
    D8,

    E1,
    E2,
    E3,
    E4,
    E5,
    E6,
    E7,
    E8,

    FF1,
    FF2,
    FF3,
    FF4,
    FF5,
    FF6,
    FF7,
    FF8,

    G1,
    G2,
    G3,
    G4,
    G5,
    G6,
    G7,
    G8,

    H1,
    H2,
    H3,
    H4,
    H5,
    H6,
    H7,
    H8,

    I1,
    I2,
    I3,
    I4,
    I5,
    I6,
    I7,
    I8,

    J1,
    J2,
    J3,
    J4,
    J5,
    J6,
    J7,
    J8,

    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    K7,
    K8,

    L1,
    L2,
    L3,
    L4,
    L5,
    L6,
    L7,
    L8,

    N1,
    N2,
    N3,
    N4,
    N5,
    N6,
    N7,
    N8,

    M1,
    M2,
    M3,
    M4,
    M5,
    M6,
    M7,
    M8,

    O1,
    O2,
    O3,
    O4,
    O5,
    O6,
    O7,
    O8,

    P1,
    P2,
    P3,
    P4,
    P5,
    P6,
    P7,
    P8,

    Q1,
    Q2,
    Q3,
    Q4,
    Q5,
    Q6,
    Q7,
    Q8,
}
pub trait Maschine {
    fn get_fd(&self) -> RawFd;

    // Used by the input watchdog: the kernel hidraw layer stops delivering
    // reports to an open fd after a few seconds at this device report rate,
    // and only a fresh open() revives it.
    fn set_fd(&mut self, _fd: RawFd) {}
    fn invalidate_lights(&mut self) {}

    fn get_pad_pressure(&self, pad_idx: usize) -> Result<f32, ()>;

    fn get_midi_note_base(&self) -> u8;
    fn set_midi_note_base(&mut self, base: u8);

    fn set_roller_state(&mut self, state: usize, idx: usize);
    fn get_roller_state(&self, idx: usize) -> usize;

    fn set_roller_status(&mut self, status: i32, idx: usize);
    fn get_roller_status(&self, idx: usize) -> i32;

    /// The CC value an encoder currently reports, 0-127. Held here rather
    /// than recomputed from the hardware counter so a host can re-centre it:
    /// the encoders are endless, and a host that maps one knob onto several
    /// parameters has to move the reported position when it switches between
    /// them, or the knob sits against an end stop it cannot leave.
    fn set_roller_value(&mut self, value: i32, idx: usize);
    fn get_roller_value(&self, idx: usize) -> i32;

    fn set_pad_light(&mut self, pad_idx: usize, color: u32, brightness: f32);
    fn set_button_light(&mut self, btn: MaschineButton, color: u32, brightness: f32);

    /// Diagnostic: write one raw byte of an LED report, bypassing every name
    /// table. This is how the button LED layout gets mapped - light a single
    /// byte and look at the device. `buffer` selects the report: 1 = pads
    /// (0x80), 2 = buttons (0x82), 3 = group/transport (0x81). Out-of-range
    /// arguments are ignored. Default is a no-op so other devices need not
    /// implement it.
    fn set_raw_light(&mut self, _buffer: usize, _index: usize, _value: u8) {}

    fn set_mod(&mut self, state: usize);
    fn get_mod(&self) -> usize;

    fn note_state(&mut self, pad_idx: usize, msg: usize);
    fn note_check(&self, pad_idx: usize) -> usize;
    fn note_save(&mut self, pad_idx: usize, note: u8, vel: u8);

    fn load_notes(&self, pad_idx: usize, context: usize) -> Message;

    fn set_seq_speed(&mut self, status: usize);
    fn get_seq_speed(&self) -> u64;

    fn set_padmode(&mut self, state: usize);
    fn get_padmode(&self) -> usize;

    // Sequencer page (0–7)
    fn get_seq_page(&self) -> usize { 0 }
    fn set_seq_page(&mut self, _page: usize) {}

    // Selected step for velocity/note editing (None = nothing selected)
    fn get_selected_step(&self) -> Option<usize> { None }
    fn set_selected_step(&mut self, _step: Option<usize>) {}

    // Per-step note (offset, 0–127) and velocity on the current page
    fn get_step_note(&self, _step: usize) -> u8 { 48 }
    fn set_step_note(&mut self, _step: usize, _note: u8) {}
    fn get_step_vel(&self, _step: usize) -> u8 { 80 }
    fn set_step_vel(&mut self, _step: usize, _vel: u8) {}

    // Apply Euclidean rhythm to current page, `hits` = number of active steps
    fn apply_euclidean(&mut self, _hits: usize) {}

    fn set_playing(&mut self, state: usize);
    fn get_playing(&self) -> bool;

    fn clock_tick(&mut self) -> Option<usize> { None }
    fn clock_start(&mut self) {}
    fn clock_stop(&mut self) {}
    fn get_clock_state(&self) -> &ClockState;
    fn set_clock_source(&mut self, _source: crate::clock::ClockSource) {}

    fn readable(&mut self, _: &mut dyn MaschineHandler);

    fn clear_screen(&mut self);

    /// Diagnostic: draw a built-in calibration pattern on both screens.
    /// Patterns are chosen to separate the unknowns one at a time - see
    /// display_test() in the MK2 implementation for what each index draws.
    fn display_test(&mut self, _pattern: usize) {}

    /// Screen framebuffer drawing, driven over OSC so the layout lives in the
    /// Zynthian driver rather than being hardcoded here. Screen 0 is the left
    /// panel, 1 the right. Nothing reaches the hardware until display_fb_flush
    /// runs on the display timer.
    fn display_fb_clear(&mut self, _screen: usize) {}
    fn display_fb_text(
        &mut self, _screen: usize, _x: usize, _y: usize, _scale: usize, _invert: bool, _text: &str,
    ) {}
    /// style: 0 outline, 1 filled, 2 dashed outline, 3 dotted rule, 4 invert.
    fn display_fb_rect(
        &mut self, _screen: usize, _x: usize, _y: usize, _w: usize, _h: usize, _style: usize,
    ) {}
    fn display_fb_flush(&mut self) {}
    /// Diagnostic: address transfer rows directly, bypassing the logical
    /// canvas mapping.
    fn display_fb_raw(&mut self, _on: bool) {}

    /// Interactive display calibration. With it on, encoders 1-4 drag two
    /// vertical and two horizontal lines; dialling each to the edge of the
    /// visible area reads the true framebuffer bounds straight off the panel.
    fn calib_active(&self) -> bool { false }
    fn calib_set(&mut self, _on: bool) {}
    fn calib_move(&mut self, _idx: usize, _delta: i32) {}

    /// Redraw the calibration lines if a move is pending. Called from the
    /// 100ms display timer, not from calib_move: redrawing per input report
    /// meant 16 HID writes per report on the same fd the input arrives on,
    /// which starved the reader and set the watchdog off.
    fn calib_flush(&mut self) {}

    /// Apply the panel's brightness and contrast from maschine.json, once, at
    /// start-up. Reaches the device through HID FEATURE reports, which no other
    /// path in this daemon uses - see hid_feature.rs for why that is careful
    /// rather than routine. Called nowhere else: the values are Non-volatile on
    /// this hardware, so this must never run on a timer or per frame.
    fn apply_screen_settings(&mut self, _brightness: Option<u8>, _contrast: Option<u8>) {}

    /// Diagnostic: change how display data is framed, without a rebuild.
    /// col = header byte 1 (column offset), reverse = mirror each byte's bits,
    /// bands = how many 32-row reports to send per screen (1 or 2).
    fn display_opts(&mut self, _col: u8, _reverse: bool, _bands: usize) {}
    fn write_lights(&mut self);
    fn write_screen(&mut self);
    fn write_display(&mut self) {}
}

#[allow(unused_variables)]
pub trait MaschineHandler {
    fn pad_pressed(&mut self, _: &mut dyn Maschine, pad_idx: usize, pressure: f32) {}
    fn pad_aftertouch(&mut self, _: &mut dyn Maschine, pad_idx: usize, pressure: f32) {}
    fn pad_released(&mut self, _: &mut dyn Maschine, pad_idx: usize) {}

    fn encoder_step(&mut self, _: &mut dyn Maschine, encoder_idx: usize, delta: i32) {}

    fn button_down(&mut self, _: &mut dyn Maschine, button: MaschineButton, byte: u8, is_down: bool) {}
    fn button_up(&mut self, _: &mut dyn Maschine, button: MaschineButton, byte: u8, is_down: bool) {}

    fn midi_in_received(&mut self, _: &mut dyn Maschine, _bytes: &[u8]) {}
}
