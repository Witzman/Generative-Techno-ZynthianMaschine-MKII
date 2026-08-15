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

use std::fs::File;
use std::mem::transmute;
use std::os::unix::io;

extern crate nix;
use midi::{Channel::Ch2, Message, U7};
use nix::unistd;

extern crate hex;
extern crate png;

use crate::base::{Maschine, MaschineButton, MaschineHandler, MaschinePad, MaschinePadStateTransition};
use crate::display;
use crate::clock::{ClockSource, ClockState};


const BUTTON_REPORT_TO_MIKROBUTTONS_MAP: [[Option<MaschineButton>; 8]; 24] = [
    [
        Some(MaschineButton::F8),
        Some(MaschineButton::F7),
        Some(MaschineButton::F6),
        Some(MaschineButton::F5),
        Some(MaschineButton::F4),
        Some(MaschineButton::F3),
        Some(MaschineButton::F2),
        Some(MaschineButton::F1),
    ],
    [
        Some(MaschineButton::Auto),
        Some(MaschineButton::All),
        Some(MaschineButton::Pageleft),
        Some(MaschineButton::Pageright),
        Some(MaschineButton::Sampling),
        Some(MaschineButton::Browse),
        Some(MaschineButton::Step),
        Some(MaschineButton::Control),
    ],
    [
        Some(MaschineButton::Nav),
        Some(MaschineButton::Noterepeat),
        Some(MaschineButton::Enter),
        Some(MaschineButton::Navright),
        Some(MaschineButton::Navleft),
        Some(MaschineButton::Tempo),
        Some(MaschineButton::Swing),
        Some(MaschineButton::Volume),
    ],
    [
        Some(MaschineButton::GroupH),
        Some(MaschineButton::GroupG),
        Some(MaschineButton::GroupF),
        Some(MaschineButton::GroupE),
        Some(MaschineButton::GroupD),
        Some(MaschineButton::GroupC),
        Some(MaschineButton::GroupB),
        Some(MaschineButton::GroupA),
    ],
    [
        Some(MaschineButton::Shift),
        Some(MaschineButton::Erase),
        Some(MaschineButton::Rec),
        Some(MaschineButton::Play),
        Some(MaschineButton::Grid),
        Some(MaschineButton::Stepright),
        Some(MaschineButton::Stepleft),
        Some(MaschineButton::Restart),
    ],
    [
        Some(MaschineButton::Mute),
        Some(MaschineButton::Solo),
        Some(MaschineButton::Select),
        Some(MaschineButton::Duplicate),
        Some(MaschineButton::Navigate),
        Some(MaschineButton::Padmode),
        Some(MaschineButton::Pattern),
        Some(MaschineButton::Scene),
    ],
    [
        Some(MaschineButton::R1),
        Some(MaschineButton::R2),
        Some(MaschineButton::R3),
        Some(MaschineButton::R4),
        Some(MaschineButton::R5),
        Some(MaschineButton::R6),
        Some(MaschineButton::R7),
        Some(MaschineButton::R8),
    ],
    [
        Some(MaschineButton::A1),
        Some(MaschineButton::A2),
        Some(MaschineButton::A3),
        Some(MaschineButton::A4),
        Some(MaschineButton::A5),
        Some(MaschineButton::A6),
        Some(MaschineButton::A7),
        Some(MaschineButton::A8),
    ],
    [
        Some(MaschineButton::B1),
        Some(MaschineButton::B2),
        Some(MaschineButton::B3),
        Some(MaschineButton::B4),
        Some(MaschineButton::B5),
        Some(MaschineButton::B6),
        Some(MaschineButton::B7),
        Some(MaschineButton::B8),
    ],
    [
        Some(MaschineButton::C1),
        Some(MaschineButton::C2),
        Some(MaschineButton::C3),
        Some(MaschineButton::C4),
        Some(MaschineButton::C5),
        Some(MaschineButton::C6),
        Some(MaschineButton::C7),
        Some(MaschineButton::C8),
    ],
    [
        Some(MaschineButton::D1),
        Some(MaschineButton::D2),
        Some(MaschineButton::D3),
        Some(MaschineButton::D4),
        Some(MaschineButton::D5),
        Some(MaschineButton::D6),
        Some(MaschineButton::D7),
        Some(MaschineButton::D8),
    ],
    [
        Some(MaschineButton::E1),
        Some(MaschineButton::E2),
        Some(MaschineButton::E3),
        Some(MaschineButton::E4),
        Some(MaschineButton::E5),
        Some(MaschineButton::E6),
        Some(MaschineButton::E7),
        Some(MaschineButton::E8),
    ],
    [
        Some(MaschineButton::FF1),
        Some(MaschineButton::FF2),
        Some(MaschineButton::FF3),
        Some(MaschineButton::FF4),
        Some(MaschineButton::FF5),
        Some(MaschineButton::FF6),
        Some(MaschineButton::FF7),
        Some(MaschineButton::FF8),
    ],
    [
        Some(MaschineButton::G1),
        Some(MaschineButton::G2),
        Some(MaschineButton::G3),
        Some(MaschineButton::G4),
        Some(MaschineButton::G5),
        Some(MaschineButton::G6),
        Some(MaschineButton::G7),
        Some(MaschineButton::G8),
    ],
    [
        Some(MaschineButton::H1),
        Some(MaschineButton::H2),
        Some(MaschineButton::H3),
        Some(MaschineButton::H4),
        Some(MaschineButton::H5),
        Some(MaschineButton::H6),
        Some(MaschineButton::H7),
        Some(MaschineButton::H8),
    ],
    [
        Some(MaschineButton::I1),
        Some(MaschineButton::I2),
        Some(MaschineButton::I3),
        Some(MaschineButton::I4),
        Some(MaschineButton::I5),
        Some(MaschineButton::I6),
        Some(MaschineButton::I7),
        Some(MaschineButton::I8),
    ],
    [
        Some(MaschineButton::J1),
        Some(MaschineButton::J2),
        Some(MaschineButton::J3),
        Some(MaschineButton::J4),
        Some(MaschineButton::J5),
        Some(MaschineButton::J6),
        Some(MaschineButton::J7),
        Some(MaschineButton::J8),
    ],
    [
        Some(MaschineButton::K1),
        Some(MaschineButton::K2),
        Some(MaschineButton::K3),
        Some(MaschineButton::K4),
        Some(MaschineButton::K5),
        Some(MaschineButton::K6),
        Some(MaschineButton::K7),
        Some(MaschineButton::K8),
    ],
    [
        Some(MaschineButton::L1),
        Some(MaschineButton::L2),
        Some(MaschineButton::L3),
        Some(MaschineButton::L4),
        Some(MaschineButton::L5),
        Some(MaschineButton::L6),
        Some(MaschineButton::L7),
        Some(MaschineButton::L8),
    ],
    [
        Some(MaschineButton::M1),
        Some(MaschineButton::M2),
        Some(MaschineButton::M3),
        Some(MaschineButton::M4),
        Some(MaschineButton::M5),
        Some(MaschineButton::M6),
        Some(MaschineButton::M7),
        Some(MaschineButton::M8),
    ],
    [
        Some(MaschineButton::N1),
        Some(MaschineButton::N2),
        Some(MaschineButton::N3),
        Some(MaschineButton::N4),
        Some(MaschineButton::N5),
        Some(MaschineButton::N6),
        Some(MaschineButton::N7),
        Some(MaschineButton::N8),
    ],
    [
        Some(MaschineButton::O1),
        Some(MaschineButton::O2),
        Some(MaschineButton::O3),
        Some(MaschineButton::O4),
        Some(MaschineButton::O5),
        Some(MaschineButton::O6),
        Some(MaschineButton::O7),
        Some(MaschineButton::O8),
    ],
    [
        Some(MaschineButton::P1),
        Some(MaschineButton::P2),
        Some(MaschineButton::P3),
        Some(MaschineButton::P4),
        Some(MaschineButton::P5),
        Some(MaschineButton::P6),
        Some(MaschineButton::P7),
        Some(MaschineButton::P8),
    ],
    [
        Some(MaschineButton::Q1),
        Some(MaschineButton::Q2),
        Some(MaschineButton::Q3),
        Some(MaschineButton::Q4),
        Some(MaschineButton::Q5),
        Some(MaschineButton::Q6),
        Some(MaschineButton::Q7),
        Some(MaschineButton::Q8),
    ],
];

#[allow(dead_code)]
struct ButtonReport {
    pub buttons: u32,
    pub encoder: u8,
}

pub struct Mikro {
    dev: io::RawFd,
    light_buf: [u8; 49],
    light_buf2: [u8; 32],
    light_buf3: [u8; 57],

    // Display framing, adjustable at runtime over OSC so the geometry can be
    // pinned down without a rebuild per guess. See display_opts().
    disp_col: u8,
    disp_reverse: bool,
    disp_bands: usize,
    calib: bool,
    calib_x: [i32; 2],
    calib_y: [i32; 2],
    calib_accum: [i32; 4],
    calib_prev: [i32; 4],
    calib_dirty: bool,
    // One framebuffer per screen, drawn into over OSC and pushed to the
    // hardware only on the 100 ms display timer. Writing per command would put
    // 16 HID writes on the same fd the input arrives on, which starves the
    // reader and trips the hidraw watchdog - that is a measured failure, not a
    // precaution.
    disp_fb: [[u8; display::HEIGHT * display::STRIDE]; 2],
    disp_fb_dirty: bool,
    // Diagnostic: skip the logical->transfer row mapping so a probe can write
    // transfer rows directly. Off in normal use.
    disp_raw: bool,
    lights_dirty: bool,

    pads: [MaschinePad; 16],
    buttons: [u8; 27],

    midi_note_base: u8,
    roller_state: [usize; 9],
    roller_status: [i32; 9],
    roller_value: [i32; 9],
    mod_state: usize,
    padmode: usize,

    note: [[u8; 16]; 8],
    note_state: [[usize; 16]; 8],
    noteset: bool,
    noteidx: usize,

    vel: [[U7; 16]; 8],
    speed: u64,
    playing: bool,
    current_page: usize,
    selected_step: Option<usize>,
    clock_state: ClockState,
}

impl Mikro {
    fn sixteen_maschine_pads() -> [MaschinePad; 16] {
        [
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
            MaschinePad::default(),
        ]
    }

    pub fn new(dev: io::RawFd) -> Self {
        let mut _self = Mikro {
            dev: dev,
            light_buf: [0u8; 49],
            light_buf2: [0u8; 32],
            light_buf3: [0u8; 57],

            disp_col: 0,
            disp_reverse: false,
            disp_bands: 2,
            calib: false,
            calib_x: [0, (display::WIDTH - 1) as i32],
            calib_y: [0, (display::HEIGHT - 1) as i32],
            calib_accum: [0; 4],
            calib_prev: [-1; 4],
            calib_dirty: false,
            disp_fb: [[0u8; display::HEIGHT * display::STRIDE]; 2],
            disp_fb_dirty: false,
            disp_raw: false,
            lights_dirty: true,

            pads: Mikro::sixteen_maschine_pads(),
            buttons: [
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10,
                0x10, 0x10, 0x10, 0x10, 0x10, 0x10,
            ],

            midi_note_base: 48,
            roller_state: [0usize; 9],
            roller_status: [0i32; 9],
            roller_value: [0i32; 9],
            mod_state: 0,
            padmode: 0,

            note: [[48u8; 16]; 8],
            note_state: [[0usize; 16]; 8],
            noteset: false,
            noteidx: 0,

            vel: [[80u8; 16]; 8],
            speed: 100,

            playing: false,
            current_page: 0,
            selected_step: None,
            clock_state: ClockState::new(),
        };

        _self.light_buf[0] = 0x80;
        _self.light_buf2[0] = 0x82;
        _self.light_buf3[0] = 0x81;
        return _self;
    }

    fn read_buttons(&mut self, handler: &mut dyn MaschineHandler, buf: &[u8]) {
        for (idx, &byte) in buf[0..24].iter().enumerate() {
            let mut diff = (byte ^ self.buttons[idx]) as u32;
            //println!("IDX: {}, Value{}", idx, byte);
            let mut off = 0usize;
            while diff != 0 {
                off += (diff.trailing_zeros() + 1) as usize;
                let btn = BUTTON_REPORT_TO_MIKROBUTTONS_MAP[idx][8 - off]
                    .expect("unknown button received from device");
                if idx <= 7 {
                    if (byte & (1 << (off - 1))) != 0 {
                        //println!(" {} ", byte);
                        let is_down = true;
                        handler.button_down(self, btn, byte, is_down);
                    } else {
                        let is_down = false;
                        //print!(" {} ", byte);
                        handler.button_up(self, btn, byte, is_down);
                    };
                } else {
                        if idx % 2 == 0  {
                            handler.encoder_step(self, (idx - 7) / 2 ,byte as i32 );
                        } else {
                            self.set_roller_state(byte as usize, (idx - 8) / 2 as usize);
                        };
                };
                                diff >>= off;
            }

            self.buttons[idx] = byte;
        }

        if self.buttons[23] > 0xF {
            self.buttons[23] = buf[23];
            return;
        } else if self.buttons[23] == buf[23] {
            return;
        }
        self.buttons[23] = buf[23];
    }

    fn read_pads(&mut self, handler: &mut dyn MaschineHandler, buf: &[u8]) {
        let pads: &[u16] = unsafe { transmute(buf) };
        // HID report is top-row-first (index 0 = top-left pad).
        // Remap to bottom-row-first so pad 0 = physical bottom-left (lowest note).
        const PAD_HID_TO_PHYS: [usize; 16] = [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3];

        for i in 0..16 {
            let pad = PAD_HID_TO_PHYS[i];
            let pressure = ((pads[i] & 0xFFF) as f32) / 4095.0;

            match self.pads[pad].pressure_val(pressure) {
                MaschinePadStateTransition::Pressed => handler.pad_pressed(self, pad, pressure),

                MaschinePadStateTransition::Aftertouch => handler.pad_aftertouch(self, pad, pressure),

                MaschinePadStateTransition::Released => handler.pad_released(self, pad),

                _ => {}
            }
        }
    }

    fn draw_calib(&mut self) {
        const SZ: usize = display::HEIGHT * display::STRIDE;
        let mut bits = [0u8; SZ];
        for &x in self.calib_x.iter() {
            for y in 0..display::HEIGHT {
                display::set_pixel(&mut bits, x as usize, y);
            }
        }
        for &y in self.calib_y.iter() {
            for x in 0..display::WIDTH {
                display::set_pixel(&mut bits, x, y as usize);
            }
        }
        self.send_display_bits(0xE0, &bits);
        self.send_display_bits(0xE1, &bits);
    }

    fn send_display_bits(&mut self, report_id: u8, bits: &[u8]) {
        debug_assert_eq!(bits.len(), display::HEIGHT * display::STRIDE);
        // A 256x64 screen is 8 reports, each a full-width band of 8 rows:
        // header byte 5 = 0x20 bytes per row, byte 7 = 0x08 rows, byte 3 =
        // chunk*8, byte 1 = 0. Payload is 256 bytes and the report is exactly
        // 9 + 256 long - this is cabl's working transfer, byte for byte.
        let mut buf = [0u8; 1 + 8 + display::CHUNK_BYTES];
        buf[0] = report_id;
        buf[1] = self.disp_col;
        buf[5] = display::HDR_ROW_BYTES;
        buf[7] = display::HDR_ROWS;

        for chunk in 0..display::CHUNKS {
            buf[3] = (chunk * display::CHUNK_ROWS) as u8;
            let src = chunk * display::CHUNK_BYTES;
            for i in 0..display::CHUNK_BYTES {
                let byte = bits[src + i];
                buf[9 + i] = if self.disp_reverse { byte.reverse_bits() } else { byte };
            }
            let _ = unistd::write(self.dev, &buf);
        }
    }
}

fn group_slot(btn: MaschineButton) -> Option<usize> {
    match btn {
        MaschineButton::GroupA => Some(0),
        MaschineButton::GroupB => Some(1),
        MaschineButton::GroupC => Some(2),
        MaschineButton::GroupD => Some(3),
        MaschineButton::GroupE => Some(4),
        MaschineButton::GroupF => Some(5),
        MaschineButton::GroupG => Some(6),
        MaschineButton::GroupH => Some(7),
        _ => None,
    }
}

fn set_rgb_light(rgb: &mut [u8], color: u32, brightness: f32) {
    let brightness = brightness * 0.5;

    rgb[0] = (brightness * (((color >> 16) & 0xFF) as f32)) as u8;
    rgb[1] = (brightness * (((color >> 8) & 0xFF) as f32)) as u8;
    rgb[2] = (brightness * (((color) & 0xFF) as f32)) as u8;
}

impl Maschine for Mikro {
    fn get_fd(&self) -> io::RawFd {
        return self.dev;
    }

    fn set_fd(&mut self, fd: io::RawFd) {
        self.dev = fd;
    }

    fn invalidate_lights(&mut self) {
        // Force the next write_lights() to push the full LED state, e.g. after
        // the watchdog reopened the device on a new fd.
        self.lights_dirty = true;
    }

    fn write_lights(&mut self) {
        // Avoid pointless HID traffic: the previous code rewrote all three LED
        // reports every 16ms even when nothing had changed.
        if !self.lights_dirty {
            return;
        }
        let _ = unistd::write(self.dev, &self.light_buf);
        let _ = unistd::write(self.dev, &self.light_buf2);
        let _ = unistd::write(self.dev, &self.light_buf3);
        self.lights_dirty = false;
    }

    fn set_raw_light(&mut self, buffer: usize, index: usize, value: u8) {
        // Byte 0 of every report is its report id, so index 0 is refused.
        let target = match buffer {
            1 => &mut self.light_buf[..],
            2 => &mut self.light_buf2[..],
            3 => &mut self.light_buf3[..],
            _ => return,
        };
        if index == 0 || index >= target.len() {
            return;
        }
        target[index] = value;
        self.lights_dirty = true;
    }

    fn set_pad_light(&mut self, pad: usize, color: u32, brightness: f32) {
        self.lights_dirty = true;
        // LED report is display-order (top-left first); input is bottom-up row-major.
        // PAD_DISPLAY_ORDER is its own inverse, so applying it remaps correctly in both directions.
        const PAD_LED_MAP: [usize; 16] = [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3];
        let offset = 1 + (PAD_LED_MAP[pad] * 3);
        let rgb = &mut self.light_buf[offset..(offset + 3)];

        set_rgb_light(rgb, color, brightness);
    }

    fn set_midi_note_base(&mut self, base: u8) {
        self.midi_note_base = base;
    }

    fn get_midi_note_base(&self) -> u8 {
        return self.midi_note_base;
    }

    fn set_roller_state(&mut self, state: usize, idx: usize) {
        self.roller_state[idx] = state;
    }

    fn get_roller_state(&self, idx: usize) -> usize {
        return self.roller_state[idx];
    }

    fn set_roller_value(&mut self, value: i32, idx: usize) {
        if idx < self.roller_value.len() {
            self.roller_value[idx] = value.clamp(0, 127);
        }
    }

    fn get_roller_value(&self, idx: usize) -> i32 {
        if idx < self.roller_value.len() { self.roller_value[idx] } else { 0 }
    }

    fn set_roller_status(&mut self, status: i32, idx: usize) {
        self.roller_status[idx] = status;
    }

    fn get_roller_status(&self, idx:usize) -> i32 {
        return self.roller_status[idx]
    }
    fn set_mod(&mut self, state: usize) {
        self.mod_state = state;
    }

    fn get_mod(&self) -> usize {
        return self.mod_state;
    }

    fn set_padmode(&mut self, state: usize) {
        if self.padmode < 3 && state == 1 {
            self.padmode += 1
        } else {
            self.padmode = 0;
        };
        println!("Padmode {}", self.padmode);
        if self.padmode == 2 {
            println!("This is Sequencer mode");
            println!("");
            println!("Tapping on pads activates them for the sequence.");
            println!("Tapping on a pad while holding shift, then pressing another pad");
            println!("will change the note of the pad you pressed first");
        }
    }

    fn get_padmode(&self) -> usize {
        return self.padmode;
    }

    fn get_seq_page(&self) -> usize { self.current_page }

    fn set_seq_page(&mut self, page: usize) {
        if page < 8 {
            self.current_page = page;
            self.selected_step = None;
        }
    }

    fn get_selected_step(&self) -> Option<usize> { self.selected_step }

    fn set_selected_step(&mut self, step: Option<usize>) { self.selected_step = step; }

    fn get_step_note(&self, step: usize) -> u8 {
        self.note[self.current_page][step]
    }

    fn set_step_note(&mut self, step: usize, note: u8) {
        self.note[self.current_page][step] = note;
    }

    fn get_step_vel(&self, step: usize) -> u8 {
        self.vel[self.current_page][step]
    }

    fn set_step_vel(&mut self, step: usize, vel: u8) {
        self.vel[self.current_page][step] = vel;
    }

    fn apply_euclidean(&mut self, hits: usize) {
        let pattern = crate::sequencer::euclidean_pattern(16, hits);
        for i in 0..16 {
            self.note_state[self.current_page][i] = if pattern[i] { 1 } else { 0 };
        }
    }

    fn set_playing(&mut self, state: usize) {
        if state == 1 {
            self.playing = true;
        } else {
            self.playing = false;
        }
    }

    fn get_playing(&self) -> bool {
        return self.playing;
    }

    fn clock_tick(&mut self) -> Option<usize> {
        self.clock_state.on_clock_tick(std::time::Instant::now())
    }

    fn clock_start(&mut self) {
        self.clock_state.on_start();
        self.playing = true;
    }

    fn clock_stop(&mut self) {
        self.clock_state.on_stop();
        self.playing = false;
    }

    fn get_clock_state(&self) -> &ClockState {
        &self.clock_state
    }

    fn set_clock_source(&mut self, source: ClockSource) {
        self.clock_state.source = source;
    }

    fn note_save(&mut self, pad_idx: usize, note: u8, vel: u8) {
        if self.noteset {
            self.vel[self.current_page][self.noteidx] = vel;
            self.note[self.current_page][self.noteidx] = note;
            println!("step: {}, note:{}, velocity:{}", self.noteidx,
                self.note[self.current_page][self.noteidx],
                self.vel[self.current_page][self.noteidx]);
            self.noteset = false;
        } else {
            self.noteidx = pad_idx;
            self.noteset = true;
        }
    }

    fn note_state(&mut self, pad_idx: usize, msg: usize) {
        self.note_state[self.current_page][pad_idx] = msg;
    }

    fn note_check(&self, pad_idx: usize) -> usize {
        self.note_state[self.current_page][pad_idx]
    }

    fn load_notes(&self, pad_idx: usize, context: usize) -> midi::Message {
        if context == 1 {
            Message::NoteOn(Ch2, self.note[self.current_page][pad_idx],
                                  self.vel[self.current_page][pad_idx])
        } else {
            Message::NoteOff(Ch2, self.note[self.current_page][pad_idx],
                                   self.vel[self.current_page][pad_idx])
        }
    }

    fn set_seq_speed(&mut self, status: usize) {
        self.speed = status as u64;
        println!("sequencer rate: {}", self.speed);
    }

    fn get_seq_speed(&self) -> u64 {
        return self.speed
    }

    fn set_button_light(&mut self, btn: MaschineButton, color: u32, brightness: f32) {
        self.lights_dirty = true;

        // The group buttons are full RGB, three contiguous bytes each. Mapped
        // on the hardware 2026-08-07 with /maschine/rawled: lighting a single
        // byte shows which channel it drives, so the colour it produces gives
        // its position in the triplet (red = first, green = middle, blue =
        // last). Everything else on the device is one byte.
        if let Some(slot) = group_slot(btn) {
            const GROUP_RGB_START: [usize; 8] = [1, 7, 13, 22, 25, 34, 37, 46];
            let start = GROUP_RGB_START[slot];
            let level = brightness.clamp(0.0, 1.0);
            let rgb = &mut self.light_buf3[start..(start + 3)];
            // Deliberately not set_rgb_light(): that halves brightness, which
            // callers of this method do not expect.
            rgb[0] = (level * (((color >> 16) & 0xFF) as f32)) as u8;
            rgb[1] = (level * (((color >> 8) & 0xFF) as f32)) as u8;
            rgb[2] = (level * ((color & 0xFF) as f32)) as u8;
            return;
        }

        let mut idx = 0;
        let mut idx2 = 0;
        match btn {
            // Indices 1-16 verified on the hardware 2026-08-07 by lighting
            // each byte on its own and reading back the physical button. The
            // old table had F1-F8 on 1-8, which is actually the left cluster
            // and the arrows; the F row is 9-16, in natural left-to-right
            // order. Indices 17-31 are NOT verified - block probing showed
            // 17-24 lands on the Scene/Pattern/Pad Mode row and 25-31 on the
            // master section, so the names below are still guesses.
            MaschineButton::Control => idx = 1,
            MaschineButton::Step => idx = 2,
            MaschineButton::Browse => idx = 3,
            MaschineButton::Sampling => idx = 4,
            MaschineButton::Pageleft => idx = 5,
            MaschineButton::Pageright => idx = 6,
            MaschineButton::All => idx = 7,
            MaschineButton::Auto => idx = 8,

            MaschineButton::F1 => idx = 9,
            MaschineButton::F2 => idx = 10,
            MaschineButton::F3 => idx = 11,
            MaschineButton::F4 => idx = 12,
            MaschineButton::F5 => idx = 13,
            MaschineButton::F6 => idx = 14,
            MaschineButton::F7 => idx = 15,
            MaschineButton::F8 => idx = 16,

            // Unverified. These keep their previous relative order, shifted
            // into the 17-31 range left free by the corrections above so no
            // two buttons share a byte. Correct them the same way if any of
            // them ever needs to light: send one index at a time and read
            // back which button lights.
            // MEASURED ON THE HARDWARE 2026-08-15, replacing guesses. Same
            // method as indices 1-16: light one byte of light_buf2 at a time
            // with every other index in 17-31 forced to 0, and read back the
            // physical button that lights.
            //
            // Five of the six previous names in this range were wrong, and two
            // of them were live bugs in the shipped instrument: solo mode lit
            // VOLUME, and MIXER mode lit SOLO. Nothing caught it because no
            // code lit this block until a modifier needed an indicator.
            //
            // The layout is the right-hand column first, top to bottom, and
            // then the master section:
            //
            //   17 SCENE      25 VOLUME     (measured)
            //   18 PATTERN    26 SWING      (measured)
            //   19 PAD MODE   27 TEMPO      (inferred)
            //   20 NAVIGATE   28-31 unknown
            //   21 DUPLICATE  (measured)
            //   22 SELECT     (measured)
            //   23 SOLO       (measured)
            //   24 MUTE       (measured)
            //
            // 21-26 are measured. 17-20 continue the same column upward and
            // 27 continues the master section, so they are inferred with high
            // confidence but NOT verified - light them and read them back
            // before trusting them. Inferring is exactly what produced the
            // wrong table this replaces.
            MaschineButton::Scene => idx = 17,
            MaschineButton::Pattern => idx = 18,
            MaschineButton::Padmode => idx = 19,
            MaschineButton::Navigate => idx = 20,
            MaschineButton::Duplicate => idx = 21,
            MaschineButton::Select => idx = 22,
            MaschineButton::Solo => idx = 23,
            MaschineButton::Mute => idx = 24,
            MaschineButton::Volume => idx = 25,
            MaschineButton::Swing => idx = 26,
            MaschineButton::Tempo => idx = 27,

            // MEASURED 2026-08-15: the master-section pair below the big
            // encoder, which emit CC 13 and 14 and step a voice's presets.
            // They previously pointed at 19/20, which the measurement shows
            // belong to the Pad Mode / Navigate column.
            MaschineButton::Navleft => idx = 28,
            MaschineButton::Navright => idx = 29,

            // MEASURED 2026-08-15, completing the master section. Both used to
            // point at 17-18, which the measurement shows belong to the
            // Scene/Pattern column.
            MaschineButton::Enter => idx = 30,
            MaschineButton::Noterepeat => idx = 31,

            // Group A-H are handled above as RGB triplets, not here.
            // MEASURED 2026-08-15: these two were SWAPPED. 55 lights ERASE and
            // 56 lights SHIFT, confirmed one index at a time on the hardware.
            // Restart 49, transport left 50 and transport right 51 were all
            // checked at the same time and were already correct - so this is a
            // swapped pair, not an offset across the block.
            MaschineButton::Erase => idx2 = 55,
            MaschineButton::Shift => idx2 = 56,
            MaschineButton::Rec => idx2 = 54,
            MaschineButton::Play => idx2 = 53,
            MaschineButton::Grid => idx2 = 52,
            MaschineButton::Stepright => idx2 = 51,
            MaschineButton::Stepleft => idx2 = 50,
            MaschineButton::Restart => idx2 = 49,

            _ => return,
        };
        // Every caller passes brightness on 0.0..=1.0 (see main.rs:731, which
        // sends 1.0 and 0.05), but this used to store the float straight into
        // the byte: 1.0 became LED byte 1 of 255 and anything below 1.0 became
        // 0. That is why a "full brightness" button looked nearly dead and a
        // "half brightness" one did not light at all. Scale to the byte range.
        let level = (brightness.clamp(0.0, 1.0) * 255.0) as u8;
        if idx != 0 {
            self.light_buf2[idx] = level;
        } else {
            self.light_buf3[idx2] = level;
        }
    }

    fn readable(&mut self, handler: &mut dyn MaschineHandler) {
        // The MK2 stops sending input reports altogether if the host does not
        // keep up with its ~750 reports/s. Reading a single report per poll
        // iteration left us draining at ~220/s, and the device went silent
        // within seconds (pads, buttons and encoders all dead, LEDs still
        // working). Drain the fd until EAGAIN on every wakeup.
        loop {
            let mut buf = [0u8; 512];

            let nbytes = match unistd::read(self.dev, &mut buf) {
                Err(nix::Error::Sys(nix::errno::Errno::EAGAIN)) => return,
                Err(err) => panic!("read failed: {}", err.to_string()),
                Ok(nbytes) => nbytes,
            };

            if nbytes == 0 {
                return;
            }

            let report_nr = buf[0];
            let buf = &buf[1..nbytes];

            match report_nr {
                0x01 => self.read_buttons(handler, &buf),
                0x20 => self.read_pads(handler, &buf),
                0x03 => handler.midi_in_received(self, buf),
                _ => println!(" :: {:2X}: got {} bytes", report_nr, nbytes),
            }
        }
    }

    fn get_pad_pressure(&self, pad_idx: usize) -> Result<f32, ()> {
        match pad_idx {
            0..=15 => Ok(self.pads[pad_idx].get_pressure()),
            _ => Err(()),
        }
    }

    fn clear_screen(&mut self) {
        // Was a hand-rolled sweep of overlapping regions with a stale header;
        // a blank framebuffer through the one transfer path covers every
        // pixel exactly once and cannot drift from it.
        let blank = [0u8; display::HEIGHT * display::STRIDE];
        self.send_display_bits(0xE0, &blank);
        self.send_display_bits(0xE1, &blank);
    }

    fn write_screen(&mut self) {
        let png_path = "picturetest.png";
        if !std::path::Path::new(png_path).exists() {
            return;
        }
        let mut limits = png::Limits::default();
        limits.bytes = 10 * 1024;
        let decoder = png::Decoder::new_with_limits(File::open(png_path).unwrap(), limits);
        let mut reader = decoder.read_info().unwrap();
        let mut picture = vec![0; reader.output_buffer_size()];
        let info = reader.next_frame(&mut picture).unwrap();
        let bytes = &picture[..info.buffer_size()];
        let mut screen_buf = [0u8; 1 + 8 + 512];
        //println!("{}", bytes.len());

        //let mut screen_buf2 = [0u8; 1 + 8+ 512];
        screen_buf[0] = 0xE0;
        screen_buf[5] = 0x08;
        screen_buf[7] = 0x20;

        screen_buf[1] = 0;
        screen_buf[3] = 0;

        let mut screen_writer = 9;
        let mut steps = 0;
        let mut bits = [0u8; 4097];
        let mut inc = 0;
        let mut ok = 0;
        let mut count2 = 0;

        let mut a1 = 0;
        let mut a2 = 0;
        let mut a3 = 0;
        let mut a4 = 0;
        let mut a5 = 0;
        let mut a6 = 0;
        let mut a7 = 0;
        let mut a8 = 0;

        for count in 0..bytes.len() {
            let c = 1 + 4 * count;
            let mut swap = 0;
            //if bytes[c] / 8 + bytes[c + 1] / 8  + bytes[c + 2] / 8 + bytes[c + 3] / 8  + bytes[c + 4] / 8  + bytes[c + 5] / 8  + bytes[c + 6] / 8  + bytes[c + 7] / 8 >= 32{
            if c < bytes.len() - 3 {
                if bytes[c] / 2 + bytes[c + 2] / 2 >= 128 {
                    swap = 1;
                } else {
                    swap = 0;
                }
                //println!("{}", swap);
            }
            let mut binary = [0u8; 4097];
            if c < 65534 {
                //print!("{}, ", bytes[count]);
                let intval;
                match inc {
                    0 => a1 = swap,
                    1 => a2 = swap,
                    2 => a3 = swap,
                    3 => a4 = swap,
                    4 => a5 = swap,
                    5 => a6 = swap,
                    6 => a7 = swap,
                    7 => a8 = swap,
                    _ => return,
                }
                inc += 1;
                if inc == 8 {
                    inc = 0;
                }
                ok += 1;
                if ok == 8 {
                    let combination = format!("{}{}{}{}{}{}{}{}", a1, a2, a3, a4, a5, a6, a7, a8);
                    intval = usize::from_str_radix(&combination, 2).unwrap();
                    ok = 0;
                    binary[count2] = intval as u8;
                    bits[count2] = binary[count2];
                    count2 += 1;
                    a1 = 0;
                    a2 = 0;
                    a3 = 0;
                    a4 = 0;
                    a5 = 0;
                    a6 = 0;
                    a7 = 0;
                    a8 = 0;
                }
            }
            //let intval = usize::from_str_radix(&combination, 4).unwrap();
            //println!("{}", combination)
        }

        for a in 0..bits.len() {
            if screen_writer == 10 {
                if steps <= 30 {
                    screen_buf[1] += 1;
                    steps += 1;
                    screen_writer = 9;
                    screen_buf[screen_writer] = bits[a];
                } else {
                    screen_buf[3] += 1;
                    screen_buf[1] = 0;
                    steps = 0;
                    screen_writer = 9;
                    screen_buf[screen_writer] = bits[a];
                }
            }
            //println!("{}", bits[a]);
            let _ = unistd::write(self.dev, &screen_buf);
            screen_writer += 1;
        }
        println!("RUNNING!");
    }

    fn calib_active(&self) -> bool {
        self.calib
    }

    fn calib_set(&mut self, on: bool) {
        self.calib = on;
        if on {
            // Start the lines inside the panel so none of them is stranded
            // off-screen and unreachable.
            self.calib_x = [8, (display::WIDTH / 2) as i32];
            self.calib_y = [8, (display::HEIGHT / 2) as i32];
            self.calib_accum = [0; 4];
            self.calib_prev = [-1; 4];
            self.draw_calib();
        }
        println!("calibration {}", if on { "ON" } else { "OFF" });
    }

    fn calib_move(&mut self, idx: usize, raw: i32) {
        if idx >= 4 {
            return;
        }
        // encoder_step is handed the encoder's ABSOLUTE counter byte from the
        // report (mikro.rs:415 passes `byte as i32`), not a delta - which is
        // why treating it as one sent every line straight to its limit and
        // made them wiggle. Recover a real delta as the wrapped difference
        // against the previous byte, then 4 counts per pixel, matching the
        // /4 that send_encoder_cc applies.
        let raw = raw & 0xFF;
        let prev = self.calib_prev[idx];
        self.calib_prev[idx] = raw;
        if prev < 0 {
            return;                      // first report just seeds the value
        }
        let delta = ((raw - prev + 128).rem_euclid(256)) - 128;
        self.calib_accum[idx] += delta;
        let step = (self.calib_accum[idx] / 4).clamp(-8, 8);
        if step == 0 {
            return;
        }
        self.calib_accum[idx] -= step * 4;

        let max_x = (display::WIDTH - 1) as i32;
        let max_y = (display::HEIGHT - 1) as i32;
        match idx {
            0 => self.calib_x[0] = (self.calib_x[0] + step).clamp(0, max_x),
            1 => self.calib_x[1] = (self.calib_x[1] + step).clamp(0, max_x),
            2 => self.calib_y[0] = (self.calib_y[0] + step).clamp(0, max_y),
            _ => self.calib_y[1] = (self.calib_y[1] + step).clamp(0, max_y),
        }
        self.calib_dirty = true;
    }

    fn calib_flush(&mut self) {
        if !self.calib || !self.calib_dirty {
            return;
        }
        self.calib_dirty = false;
        self.draw_calib();
        println!(
            "calib x1={} x2={} y1={} y2={}",
            self.calib_x[0], self.calib_x[1], self.calib_y[0], self.calib_y[1]
        );
    }

    // --- OSC-driven screen drawing ------------------------------------------
    //
    // The driver owns what the screens say, so the daemon exposes primitives
    // rather than layouts: clear, text (with scale and inversion) and boxes,
    // all into a per-screen framebuffer, pushed by flush on the display timer.
    // Screen 0 is the left panel (report 0xE0), screen 1 the right (0xE1).

    fn display_fb_raw(&mut self, on: bool) {
        self.disp_raw = on;
        self.disp_fb_dirty = true;
    }

    fn display_fb_clear(&mut self, screen: usize) {
        if screen > 1 { return; }
        for b in self.disp_fb[screen].iter_mut() { *b = 0; }
        self.disp_fb_dirty = true;
    }

    /// Text at `scale` (1 = 5x8, 2 = 10x16). `invert` swaps the box behind it,
    /// giving the dark-on-light label Maschine uses for the selected item.
    fn display_fb_text(
        &mut self, screen: usize, x: usize, y: usize, scale: usize, invert: bool, text: &str,
    ) {
        if screen > 1 { return; }
        let fb = &mut self.disp_fb[screen];
        display::draw_text_scaled(fb, x, y, text, scale);
        if invert {
            let s = scale.max(1);
            let pad = 1;
            let w = display::text_w(text, s) + pad * 2;
            let h = 8 * s + pad * 2;
            display::invert_rect(fb, x.saturating_sub(pad), y.saturating_sub(pad), w, h);
        }
        self.disp_fb_dirty = true;
    }

    /// style: 0 outline, 1 filled, 2 dashed outline, 3 dotted horizontal rule,
    /// 4 invert the region.
    fn display_fb_rect(
        &mut self, screen: usize, x: usize, y: usize, w: usize, h: usize, style: usize,
    ) {
        if screen > 1 { return; }
        let fb = &mut self.disp_fb[screen];
        match style {
            1 => display::fill_rect(fb, x, y, w, h),
            2 => display::dashed_rect(fb, x, y, w, h),
            3 => display::dotted_hline(fb, x, y, w),
            4 => display::invert_rect(fb, x, y, w, h),
            _ => display::rect(fb, x, y, w, h),
        }
        self.disp_fb_dirty = true;
    }

    /// Push both framebuffers if anything changed. Called from the 100 ms
    /// display timer, never from the input path.
    ///
    /// The framebuffer is addressed as the LOGICAL canvas - 512x32, each row
    /// two physical pixels tall - and expanded here. Measured on the hardware
    /// 2026-08-08 by drawing single rows and blocks and reading the panel:
    ///
    ///   logical 0-15  -> transfer rows 0-15  -> physical rows 0-31
    ///   logical 16-31 -> transfer rows 32-47 -> physical rows 32-63
    ///
    /// Transfer rows 16-31 and 48-63 are discarded by the panel; a 1-row line
    /// always comes back 2 px thick. That hole is why the earlier layout mock
    /// fell apart below the top line: an 8-px glyph at y=12 needed rows 12-19
    /// and lost everything from 16 up. Anything drawn at logical y >= 32 is
    /// off-panel and dropped here rather than silently vanishing later.
    fn display_fb_flush(&mut self) {
        if !self.disp_fb_dirty { return; }
        self.disp_fb_dirty = false;
        if self.disp_raw {
            // Probing mode: the buffer IS the transfer buffer, no row mapping,
            // so a test can address transfer rows directly.
            let left = self.disp_fb[0];
            let right = self.disp_fb[1];
            self.send_display_bits(0xE0, &left);
            self.send_display_bits(0xE1, &right);
            return;
        }
        for screen in 0..2 {
            let mut out = [0u8; display::HEIGHT * display::STRIDE];
            for lrow in 0..display::LOGICAL_H {
                let prow = display::logical_row(lrow);
                let (src, dst) = (lrow * display::STRIDE, prow * display::STRIDE);
                out[dst..dst + display::STRIDE]
                    .copy_from_slice(&self.disp_fb[screen][src..src + display::STRIDE]);
            }
            let id = if screen == 0 { 0xE0 } else { 0xE1 };
            self.send_display_bits(id, &out);
        }
    }

    fn display_opts(&mut self, col: u8, reverse: bool, bands: usize) {
        self.disp_col = col;
        self.disp_reverse = reverse;
        // Bands no longer select anything - a screen is always its 8 chunks -
        // but the OSC path keeps its arity, so record it and ignore it.
        self.disp_bands = bands;
        println!(
            "display opts: col={} reverse={} bands={}",
            self.disp_col, self.disp_reverse, self.disp_bands
        );
    }

    fn display_test(&mut self, pattern: usize) {
        const SZ: usize = display::HEIGHT * display::STRIDE;
        let mut bits = [0u8; SZ];

        match pattern {
            // A single lit row against a single lit column is the decisive
            // test for addressing: if row 0 shows as a horizontal line the
            // data is row-major, if it shows as a vertical line the
            // controller is page-addressed and every byte is 8 stacked pixels.
            1 => for x in 0..display::WIDTH { display::set_pixel(&mut bits, x, 0); },
            2 => for y in 0..display::HEIGHT { display::set_pixel(&mut bits, 0, y); },
            // An 8x8 block in one corner locates the origin unambiguously.
            3 => for y in 0..8 { for x in 0..8 { display::set_pixel(&mut bits, x, y); } },
            // Border: shows the true width and height, and whether the
            // bottom half (the second band) arrives at all.
            4 => {
                for x in 0..display::WIDTH {
                    display::set_pixel(&mut bits, x, 0);
                    display::set_pixel(&mut bits, x, display::HEIGHT - 1);
                }
                for y in 0..display::HEIGHT {
                    display::set_pixel(&mut bits, 0, y);
                    display::set_pixel(&mut bits, display::WIDTH - 1, y);
                }
            }
            // Ruler: a tick every 8px along the top, double height every 32,
            // so a column offset or a wrap is countable.
            5 => {
                for x in (0..display::WIDTH).step_by(8) {
                    let h = if x % 32 == 0 { 8 } else { 4 };
                    for y in 0..h { display::set_pixel(&mut bits, x, y); }
                }
            }
            // Text at the top-left, smallest thing that proves legibility.
            6 => {
                display::draw_text(&mut bits, 0, 0, "ABC 123");
                display::draw_text(&mut bits, 0, 8, "abc xyz");
            }
            // Everything lit - proves the full addressable area.
            7 => for b in bits.iter_mut() { *b = 0xFF; },
            // Vertical ruler: a full-width line every 8 rows plus one on the
            // very last row. Counting the lines gives the true row count, the
            // spacing shows whether rows are doubled, and whether the last
            // line sits on the bottom edge shows if row HEIGHT-1 arrives.
            8 => {
                for y in (0..display::HEIGHT).step_by(8) {
                    for x in 0..display::WIDTH { display::set_pixel(&mut bits, x, y); }
                }
                for x in 0..display::WIDTH {
                    display::set_pixel(&mut bits, x, display::HEIGHT - 1);
                }
            }
            // Layout mock inside the measured usable box (x 0..446, y 0..47):
            // four columns under the F buttons, each with a label, a value and
            // a position bar. Judges legibility at the real scale before the
            // driver starts feeding it.
            10 => {
                const USABLE_W: usize = 447;
                const COL_W: usize = USABLE_W / 4;
                let labels = ["A KICK", "B SNARE", "C HAT", "D CLAP"];
                let values = [12, 4, 96, 64];
                for (col, label) in labels.iter().enumerate() {
                    let x0 = col * COL_W + 2;
                    display::draw_text(&mut bits, x0, 0, label);
                    let val = format!("{}", values[col]);
                    display::draw_text(&mut bits, x0, 12, &val);
                    // Position bar: outline plus fill proportional to value.
                    let bar_w = COL_W - 8;
                    let (by, bh) = (26usize, 8usize);
                    for x in 0..bar_w {
                        display::set_pixel(&mut bits, x0 + x, by);
                        display::set_pixel(&mut bits, x0 + x, by + bh);
                    }
                    for y in 0..=bh {
                        display::set_pixel(&mut bits, x0, by + y);
                        display::set_pixel(&mut bits, x0 + bar_w, by + y);
                    }
                    let fill = values[col] as usize * bar_w / 127;
                    for x in 0..fill {
                        for y in 2..(bh - 1) {
                            display::set_pixel(&mut bits, x0 + x, by + y);
                        }
                    }
                }
            }
            // Two lines 2 rows apart: if they merge, rows are being doubled.
            9 => {
                for x in 0..display::WIDTH {
                    display::set_pixel(&mut bits, x, 10);
                    display::set_pixel(&mut bits, x, 12);
                }
            }
            // Diagonal corner to corner: catches stride and offset errors.
            _ => {
                for y in 0..display::HEIGHT {
                    let x = y * display::WIDTH / display::HEIGHT;
                    display::set_pixel(&mut bits, x, y);
                }
            }
        }

        println!("display test pattern {}", pattern);
        self.send_display_bits(0xE0, &bits);
        self.send_display_bits(0xE1, &bits);
    }

    fn write_display(&mut self) {
        const SZ: usize = display::HEIGHT * display::STRIDE;

        let note_names = ["C-1","C0","C1","C2","C3","C4","C5","C6","C7","C8","C9"];
        let base = self.midi_note_base;
        let note_name = note_names.get((base / 12) as usize).unwrap_or(&"?");

        // Left display (0xE0): encoders 0-3
        let mut left = [0u8; SZ];
        display::draw_text(&mut left, 0, 0, " K1    K2    K3    K4");
        let v0 = self.roller_status[0].clamp(0, 127);
        let v1 = self.roller_status[1].clamp(0, 127);
        let v2 = self.roller_status[2].clamp(0, 127);
        let v3 = self.roller_status[3].clamp(0, 127);
        let line1 = format!("{:>3}   {:>3}   {:>3}   {:>3}", v0, v1, v2, v3);
        display::draw_text(&mut left, 0, 10, &line1);
        let base_line = format!("BASE:{}{}", note_name, base);
        display::draw_text(&mut left, 0, 20, &base_line);

        // Right display (0xE1): encoders 4-7
        let mut right = [0u8; SZ];
        display::draw_text(&mut right, 0, 0, " K5    K6    K7    K8");
        let v4 = self.roller_status[4].clamp(0, 127);
        let v5 = self.roller_status[5].clamp(0, 127);
        let v6 = self.roller_status[6].clamp(0, 127);
        let v7 = self.roller_status[7].clamp(0, 127);
        let line2 = format!("{:>3}   {:>3}   {:>3}   {:>3}", v4, v5, v6, v7);
        display::draw_text(&mut right, 0, 10, &line2);

        self.send_display_bits(0xE0, &left);
        self.send_display_bits(0xE1, &right);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::base::Maschine;

    fn make_mikro() -> Mikro { Mikro::new(0) }

    #[test]
    fn pages_are_independent() {
        let mut m = make_mikro();
        m.note_state(0, 1);          // page 0 step 0 = on
        m.set_seq_page(1);
        assert_eq!(m.note_check(0), 0); // page 1 step 0 = still off
    }

    #[test]
    fn set_seq_page_clears_selected_step() {
        let mut m = make_mikro();
        m.set_selected_step(Some(3));
        m.set_seq_page(1);
        assert_eq!(m.get_selected_step(), None);
    }

    #[test]
    fn step_vel_independent_per_page() {
        let mut m = make_mikro();
        m.set_step_vel(0, 100);
        assert_eq!(m.get_step_vel(0), 100);
        m.set_seq_page(1);
        assert_eq!(m.get_step_vel(0), 80); // default unchanged
    }

    #[test]
    fn step_note_independent_per_page() {
        let mut m = make_mikro();
        m.set_step_note(0, 60);
        assert_eq!(m.get_step_note(0), 60);
        m.set_seq_page(1);
        assert_eq!(m.get_step_note(0), 48); // default unchanged
    }

    #[test]
    fn apply_euclidean_4_hits() {
        let mut m = make_mikro();
        m.apply_euclidean(4);
        assert_eq!(m.note_check(0),  1);
        assert_eq!(m.note_check(4),  1);
        assert_eq!(m.note_check(8),  1);
        assert_eq!(m.note_check(12), 1);
        assert_eq!(m.note_check(1),  0);
    }

    #[test]
    fn clock_start_resets_state() {
        let mut m = make_mikro();
        m.clock_tick();
        m.clock_tick();
        m.clock_start();
        assert!(m.get_playing());
        let state = m.get_clock_state();
        assert_eq!(state.step, 0);
        assert_eq!(state.tick_counter, 0);
    }

    #[test]
    fn clock_stop_halts_playing() {
        let mut m = make_mikro();
        m.clock_start();
        m.clock_stop();
        assert!(!m.get_playing());
    }

    #[test]
    fn six_clock_ticks_return_step_on_sixth() {
        let mut m = make_mikro();
        m.clock_start();
        for i in 0..5 {
            let result = m.clock_tick();
            assert!(result.is_none(), "tick {} should not advance step", i);
        }
        let result = m.clock_tick();
        assert_eq!(result, Some(0));
    }
}
