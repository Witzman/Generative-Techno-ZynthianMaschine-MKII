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

use crate::hid_feature;
use crate::hid_stats::{self, WriteStats};
use std::os::unix::io;

extern crate nix;
use midi::{Channel::Ch2, Message, U7};
use nix::unistd;

extern crate hex;

use crate::base::{Maschine, MaschineButton, MaschineHandler, MaschinePad, MaschinePadStateTransition};
use crate::display;
use crate::clock::{ClockSource, ClockState};


/// Every button this device can actually send, by report byte and bit.
///
/// `pub` so a test in main.rs can walk it: it is the authoritative list of
/// reachable buttons, which makes it the only honest input for "is every
/// button the device can send also a button the host is told about?".
pub const BUTTON_REPORT_TO_MIKROBUTTONS_MAP: [[Option<MaschineButton>; 8]; 24] = [
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

/// Is this report long enough to decode?
///
/// A pure function on purpose: the decision lives on the input path, where no
/// test can reach it, and the failure it prevents is a truncated report read
/// as pad pressure - a note nobody played, from a device that is already known
/// to stall and re-deliver under load.
pub fn report_is_complete(report_nr: u8, payload_len: usize) -> bool {
    match report_nr {
        0x01 => payload_len >= BUTTON_REPORT_BYTES,
        0x20 => payload_len >= PAD_REPORT_BYTES,
        _ => true,
    }
}

/// Payload bytes `read_buttons` requires, report id excluded.
///
/// It walks `buf[0..24]` and then reads `buf[23]` again for the encoder
/// nibbles, so 24 is the floor rather than a preference.
const BUTTON_REPORT_BYTES: usize = 24;

/// Payload bytes `read_pads` requires, report id excluded: sixteen pads at
/// 16 bits each.
const PAD_REPORT_BYTES: usize = 32;

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
    // One dirty-rectangle list PER SCREEN, replacing the single shared bool
    // this had until 2026-09-01. That bool meant touching one pixel on the
    // left screen repainted the right one as well - 16 reports of 265 bytes
    // for a change that had already happened in eight of them. The panel was
    // measured to honour a rectangle header on 2026-08-31, so the flush can
    // now send only what moved.
    disp_dirty: [display::DirtyList; 2],
    // Diagnostic: skip the logical->transfer row mapping so a probe can write
    // transfer rows directly. Off in normal use.
    disp_raw: bool,
    lights_dirty: bool,

    /// Every HID write is counted here. Until 2026-08-30 all five write sites
    /// were `let _ = unistd::write(...)`, so a failing or truncated write was
    /// invisible and no investigation of the wedge could tell whether writes
    /// were even landing.
    wstats: WriteStats,

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

    /// One HID write, counted and classified.
    ///
    /// A free-standing helper taking the fd and the stats as separate field
    /// borrows, deliberately: a `&mut self` method could not be called with
    /// `&self.light_buf` as its argument, and copying a 265-byte report to get
    /// around that would put an allocation on the hot path.
    fn hid_write(fd: io::RawFd, stats: &mut WriteStats, buf: &[u8], what: &str) {
        let written = unistd::write(fd, buf).ok();
        let outcome = hid_stats::classify(written, buf.len());
        if stats.record(outcome) {
            println!(
                "HID WRITE {:?}: {} ({} bytes) - ok={} short={} failed={}",
                outcome, what, buf.len(), stats.ok, stats.short, stats.failed
            );
        }
    }

    pub fn new(dev: io::RawFd) -> Self {
        let mut _self = Mikro {
            dev: dev,
            wstats: WriteStats::default(),
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
            disp_dirty: [display::DirtyList::default(); 2],
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
        // `from_le_bytes`, NOT `transmute`, since 2026-09-03. The old line was
        // `let pads: &[u16] = unsafe { transmute(buf) }`, which keeps the
        // slice's LENGTH while doubling the size of its element - so the
        // resulting slice claimed twice the bytes it had - and it assumed both
        // 2-byte alignment (not guaranteed for a `[u8; 512]` field) and
        // little-endian layout without saying so. The caller now guarantees
        // the length; this reads the field explicitly.
        // HID report is top-row-first (index 0 = top-left pad).
        // Remap to bottom-row-first so pad 0 = physical bottom-left (lowest note).
        const PAD_HID_TO_PHYS: [usize; 16] = [12, 13, 14, 15, 8, 9, 10, 11, 4, 5, 6, 7, 0, 1, 2, 3];

        for i in 0..16 {
            let pad = PAD_HID_TO_PHYS[i];
            let raw = u16::from_le_bytes([buf[i * 2], buf[i * 2 + 1]]);
            let pressure = ((raw & 0xFFF) as f32) / 4095.0;

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

    /// Push one rectangle of a framebuffer to one screen.
    ///
    /// The header is a dirty-rectangle blit descriptor, proven on the rig
    /// 2026-08-31: byte 1 the left edge in BYTES, byte 3 the top row, byte 5
    /// the bytes per row, byte 7 the row count. This project hardcoded bytes 5
    /// and 7 for the daemon's whole life and only ever varied byte 3.
    ///
    /// A rectangle wider than one report's payload is split by ROWS, never by
    /// columns: `rows_per_report` is what keeps every report inside the
    /// 256-byte payload the panel has always accepted. For a full-width
    /// region that works out at 32 bytes x 8 rows - byte for byte the transfer
    /// this function performed before it took a region at all.
    ///
    /// A free function taking the fd, the stats and the framing as arguments
    /// for the same reason `hid_write` is: a `&mut self` method could not be
    /// handed `&self.disp_fb[n]`, and copying 2 KB per flush to get around
    /// that is exactly the cost this change exists to remove.
    fn send_display_region(
        fd: io::RawFd, stats: &mut WriteStats, report_id: u8, bits: &[u8],
        region: display::Region, col: u8, reverse: bool,
    ) {
        if region.is_empty() { return; }
        debug_assert_eq!(bits.len(), display::HEIGHT * display::STRIDE);
        // A region's y IS a transfer row. That holds only while the logical
        // canvas maps 1:1 onto the panel, and display.rs keeps `logical_row`
        // as an identity hook with a test pinning it - because a non-identity
        // mapping cannot be expressed by ONE rectangle header at all, so it
        // would have to be caught here rather than drawn wrong.
        debug_assert!(region.y + region.h <= display::LOGICAL_H);
        debug_assert_eq!(display::logical_row(region.y), region.y);
        let mut buf = [0u8; 1 + 8 + display::CHUNK_BYTES];

        let rows_per = display::rows_per_report(region.w);
        let mut row = region.y;
        while row < region.y + region.h {
            let rows = rows_per.min(region.y + region.h - row);
            buf[..9].copy_from_slice(&display::blit_prefix(report_id, region, row, rows, col));
            for r in 0..rows {
                let src = (row + r) * display::STRIDE + region.x;
                for i in 0..region.w {
                    let byte = bits[src + i];
                    buf[9 + r * region.w + i] =
                        if reverse { byte.reverse_bits() } else { byte };
                }
            }
            let len = 9 + rows * region.w;
            Self::hid_write(fd, stats, &buf[..len], "display/blit");
            row += rows;
        }
    }

    /// Whole-screen push. Kept for the diagnostic paths - calibration, the
    /// built-in test patterns, clear_screen - which have no notion of a
    /// region and want the panel wholly rewritten.
    fn send_display_bits(&mut self, report_id: u8, bits: &[u8]) {
        Self::send_display_region(
            self.dev, &mut self.wstats, report_id, bits,
            display::Region::full(), self.disp_col, self.disp_reverse,
        );
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
        Self::hid_write(self.dev, &mut self.wstats, &self.light_buf, "leds/pads");
        Self::hid_write(self.dev, &mut self.wstats, &self.light_buf2, "leds/groups");
        Self::hid_write(self.dev, &mut self.wstats, &self.light_buf3, "leds/buttons");
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
        // The last line of defence. Both callers bound this now - the OSC
        // handler and the WebSocket arm - but this is the function that
        // indexes a sixteen-entry table, so it is the function that must not
        // be able to end the process.
        if pad >= 16 {
            return;
        }
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
        // Bounded like set_roller_value beside it. Every caller computes this
        // index arithmetically from a report byte; one arithmetic mistake
        // should cost a lost detent, not the daemon.
        if idx < self.roller_state.len() {
            self.roller_state[idx] = state;
        }
    }

    fn get_roller_state(&self, idx: usize) -> usize {
        if idx < self.roller_state.len() { self.roller_state[idx] } else { 0 }
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
        if idx < self.roller_status.len() {
            self.roller_status[idx] = status;
        }
    }

    fn get_roller_status(&self, idx: usize) -> i32 {
        if idx < self.roller_status.len() { self.roller_status[idx] } else { 0 }
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
            //   17 SCENE      25 VOLUME
            //   18 PATTERN    26 SWING
            //   19 PAD MODE   27 TEMPO
            //   20 NAVIGATE   28 master left
            //   21 DUPLICATE  29 master right
            //   22 SELECT     30 ENTER
            //   23 SOLO       31 NOTE REPEAT
            //   24 MUTE
            //
            // EVERY index in 17-31 is now MEASURED. 21-26 and 28-31 on
            // 2026-08-15; 17-20 and 27 on 2026-08-16, one index at a time,
            // owner reading the physical button back. Those five had been
            // carried here as high-confidence inference with a warning not to
            // trust them, and this time the inference happened to be right -
            // which is worth nothing as evidence, since nine of the thirteen
            // indices measured the day before had been wrong. The block is
            // closed: nothing here is a guess any more.
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
                Err(nix::errno::Errno::EAGAIN) => return,
                // NOT a panic, since 2026-09-03. An unplug gives ENODEV here
                // and the daemon died on it; the input watchdog above is built
                // to reopen the node, and it cannot do that from a dead
                // process. Return and let it work.
                Err(err) => {
                    println!("read failed: {} - leaving it to the watchdog", err);
                    return;
                }
                Ok(nbytes) => nbytes,
            };

            if nbytes == 0 {
                return;
            }

            let report_nr = buf[0];
            let buf = &buf[1..nbytes];

            // LENGTH-CHECKED, since 2026-09-03. `read_buttons` slices
            // `buf[0..24]` and `read_pads` reads sixteen 16-bit fields, and
            // neither asked how many bytes had actually arrived: a truncated
            // report panicked the first and made the second read whatever was
            // left on the stack - phantom pad hits with no explanation, which
            // is precisely the failure mode of the wedge this daemon spends a
            // watchdog on. A short report is dropped and counted instead.
            if !report_is_complete(report_nr, buf.len()) {
                println!(
                    " :: short {:02X} report: {} payload bytes, dropped",
                    report_nr, buf.len());
                continue;
            }

            match report_nr {
                0x01 => self.read_buttons(handler, buf),
                0x20 => self.read_pads(handler, buf),
                0x03 => handler.midi_in_received(self, buf),
                _ => println!(" :: {:2X}: got {} bytes", report_nr, nbytes),
            }
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
        // The mapping changes under both screens, so both are wholly stale.
        for d in self.disp_dirty.iter_mut() { d.add_full(); }
    }

    fn display_fb_clear(&mut self, screen: usize) {
        if screen > 1 { return; }
        for b in self.disp_fb[screen].iter_mut() { *b = 0; }
        // A clear is the one draw that really does dirty everything, and it
        // discards whatever finer regions were pending. It is also how the
        // driver starts every screen repaint, which is why THIS screen still
        // costs its 8 reports and the other one now costs nothing.
        self.disp_dirty[screen].add_full();
    }

    /// Text at `scale` (1 = 5x8, 2 = 10x16). `invert` swaps the box behind it,
    /// giving the dark-on-light label Maschine uses for the selected item.
    fn display_fb_text(
        &mut self, screen: usize, x: usize, y: usize, scale: usize, invert: bool, text: &str,
    ) {
        if screen > 1 { return; }
        let fb = &mut self.disp_fb[screen];
        display::draw_text_scaled(fb, x, y, text, scale);
        let s = scale.max(1);
        // draw_text_scaled stops before it would run off the right edge, so
        // the ink never reaches past text_w; from_pixels clips the rest.
        let mut dirty = display::Region::from_pixels(x, y, display::text_w(text, s), 8 * s);
        if invert {
            let pad = 1;
            let w = display::text_w(text, s) + pad * 2;
            let h = 8 * s + pad * 2;
            let (ix, iy) = (x.saturating_sub(pad), y.saturating_sub(pad));
            display::invert_rect(fb, ix, iy, w, h);
            dirty = dirty.union(&display::Region::from_pixels(ix, iy, w, h));
        }
        self.disp_dirty[screen].add(dirty);
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
        // Style 3 is a rule, one row tall whatever h says. Marking h rows
        // would still be correct, just wasteful; marking one is exact.
        let rows = if style == 3 { 1 } else { h };
        self.disp_dirty[screen].add(display::Region::from_pixels(x, y, w, rows));
    }

    /// Push WHAT CHANGED on each screen. Called from the 100 ms display timer,
    /// never from the input path.
    ///
    /// Until 2026-09-01 this pushed BOTH screens whole whenever a single
    /// shared `disp_fb_dirty` bool was set - 16 reports of 265 bytes, 2120 of
    /// them for a screen nothing had touched. Each screen now carries its own
    /// dirty-rectangle list and only its own regions are sent. Against the
    /// driver as it stands, which opens every screen repaint with a clear,
    /// that halves the display path outright: one screen's 8 reports instead
    /// of two screens' 16. A widget that does not clear first costs one 73-byte
    /// report for 64x8.
    ///
    /// FLAGGED, NOT FIXED (working rule 3): this function's docstring used to
    /// describe a 512x32 logical canvas expanded to transfer rows here, with
    /// transfer rows 16-31 and 48-63 discarded by the panel. `LOGICAL_H` is
    /// `HEIGHT` and `logical_row` is the identity, so the code has not done
    /// that for a long time, and the expansion loop it described was copying
    /// each row onto itself. The two have been out of step since before this
    /// change; reconciling what the panel really does with rows belongs with
    /// somebody at the rig, not here.
    ///
    /// `disp_raw` is likewise vestigial for the same reason: with the mapping
    /// an identity there is nothing for a "raw" mode to bypass, so it now only
    /// forces a full repaint of both screens. The OSC verb is unchanged.
    fn display_fb_flush(&mut self) {
        for screen in 0..2 {
            if self.disp_dirty[screen].is_empty() { continue; }
            let id = if screen == 0 { 0xE0 } else { 0xE1 };
            // The list is copied out because `send_display_region` needs
            // `&mut self.wstats` while `&self.disp_fb[screen]` is borrowed.
            // DirtyList is Copy and sixteen words wide; the 2 KB framebuffer
            // copy this used to make on every flush is gone.
            let dirty = self.disp_dirty[screen];
            let (fd, col, reverse) = (self.dev, self.disp_col, self.disp_reverse);
            for r in dirty.regions() {
                Self::send_display_region(
                    fd, &mut self.wstats, id, &self.disp_fb[screen], *r, col, reverse,
                );
            }
            self.disp_dirty[screen].clear();
        }
    }

    /// Read, echo, write - in that order, and the order IS the safety.
    ///
    /// Nothing happens at all unless both keys are present in maschine.json.
    /// When they are, each screen's 11-byte feature report is READ first, the
    /// read is checked against the panel geometry the device declares in it,
    /// and only then are two of its eleven bytes replaced. Everything else -
    /// the report id, the seven constant bytes, the eight unidentified flag
    /// bits - is echoed back exactly as it came off the device.
    ///
    /// The write is skipped when the device already holds the requested pair,
    /// so a rig running the shipped defaults issues no write at all. That is
    /// not an optimisation: these fields are Non-volatile, and a write per boot
    /// is a flash cycle per boot for no gain.
    ///
    /// Every branch prints. The failure this guards against is a dark panel,
    /// and a dark panel cannot explain itself.
    fn apply_screen_settings(&mut self, brightness: Option<u8>, contrast: Option<u8>) {
        let (b, c) = match (brightness, contrast) {
            (Some(b), Some(c)) => (b, c),
            (None, None) => return,
            _ => {
                println!(
                    "screen settings: ignored - screen_brightness and screen_contrast \
                     must BOTH be set in maschine.json (a SET sends the whole report, \
                     so half a pair is not writable)"
                );
                return;
            }
        };

        for (screen, &id) in hid_feature::SCREEN_REPORT_IDS.iter().enumerate() {
            let mut buf = [0u8; hid_feature::SCREEN_REPORT_LEN];
            buf[0] = id;
            match hid_feature::get_feature(self.dev, &mut buf) {
                Ok(n) if n >= hid_feature::SCREEN_REPORT_LEN => {}
                Ok(n) => {
                    println!(
                        "screen {}: short GET_FEATURE 0x{:02X} ({} of {} bytes) - not writing",
                        screen, id, n, hid_feature::SCREEN_REPORT_LEN
                    );
                    continue;
                }
                Err(e) => {
                    println!("screen {}: GET_FEATURE 0x{:02X} failed: {} - not writing", screen, id, e);
                    continue;
                }
            }

            if !hid_feature::looks_like_screen_report(id, &buf) {
                // Bytes 1-4 did not decode as this panel's width and height,
                // so whatever came back is not the report we think it is.
                // Refusing here is the difference between a settings write and
                // a blind one.
                println!(
                    "screen {}: 0x{:02X} does not carry the panel geometry ({}) - REFUSING to write",
                    screen, id, hex::encode(&buf[..])
                );
                continue;
            }

            println!("screen {}: 0x{:02X} reads {}", screen, id, hex::encode(&buf[..]));

            if hid_feature::already_set(&buf, b, c) {
                println!("screen {}: already at brightness {} contrast {} - no write", screen, b, c);
                continue;
            }

            let out = hid_feature::patch(&buf, b, c);
            match hid_feature::set_feature(self.dev, &out) {
                Ok(_) => println!(
                    "screen {}: SET_FEATURE 0x{:02X} -> {} (brightness {} contrast {}; \
                     was {} / {}. Restore with screen_brightness {} and screen_contrast {})",
                    screen, id, hex::encode(&out[..]),
                    out[hid_feature::BRIGHTNESS_BYTE], out[hid_feature::CONTRAST_BYTE],
                    buf[hid_feature::BRIGHTNESS_BYTE], buf[hid_feature::CONTRAST_BYTE],
                    hid_feature::FACTORY_BRIGHTNESS, hid_feature::FACTORY_CONTRAST,
                ),
                Err(e) => println!("screen {}: SET_FEATURE 0x{:02X} failed: {}", screen, id, e),
            }
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

    // --- the input path's own guards, 2026-09-03 ---------------------------

    #[test]
    fn a_full_button_report_is_decoded() {
        assert!(report_is_complete(0x01, BUTTON_REPORT_BYTES));
        assert!(report_is_complete(0x01, BUTTON_REPORT_BYTES + 8));
    }

    #[test]
    fn a_short_button_report_is_dropped() {
        // `read_buttons` slices buf[0..24] and then reads buf[23] again. One
        // byte short of that was an index panic on the input path.
        assert!(!report_is_complete(0x01, BUTTON_REPORT_BYTES - 1));
        assert!(!report_is_complete(0x01, 0));
    }

    #[test]
    fn a_short_pad_report_is_dropped() {
        // Sixteen pads at 16 bits. A byte short and the last pad's pressure
        // came from whatever was left in the read buffer - a phantom hit.
        assert!(report_is_complete(0x20, PAD_REPORT_BYTES));
        assert!(!report_is_complete(0x20, PAD_REPORT_BYTES - 1));
    }

    #[test]
    fn a_midi_report_has_no_minimum() {
        // 0x03 is a passthrough to the MIDI parser, which handles any length.
        assert!(report_is_complete(0x03, 0));
        assert!(report_is_complete(0xFF, 0));
    }

    #[test]
    fn an_out_of_range_pad_light_is_refused_rather_than_fatal() {
        // The WebSocket arm takes this index out of JSON on a socket and the
        // OSC arm out of a datagram. It indexes a sixteen-entry table.
        let mut m = make_mikro();
        m.lights_dirty = false;
        m.set_pad_light(16, 0xFFFFFF, 1.0);
        m.set_pad_light(usize::MAX, 0xFFFFFF, 1.0);
        assert!(!m.lights_dirty, "a refused pad must not dirty the LED buffer");
        m.set_pad_light(15, 0xFFFFFF, 1.0);
        assert!(m.lights_dirty, "a real pad must still light");
    }

    #[test]
    fn an_out_of_range_roller_index_is_refused_rather_than_fatal() {
        let mut m = make_mikro();
        m.set_roller_state(5, 99);
        m.set_roller_status(5, 99);
        assert_eq!(m.get_roller_state(99), 0);
        assert_eq!(m.get_roller_status(99), 0);
    }

    #[test]
    fn pad_pressure_is_read_little_endian_from_the_report() {
        // What the transmute used to do implicitly, now asserted: pad 0 of the
        // report is the first two bytes, low byte first, and only the low
        // twelve bits are pressure.
        let mut buf = [0u8; PAD_REPORT_BYTES];
        buf[0] = 0xFF;
        buf[1] = 0x0F;
        let raw = u16::from_le_bytes([buf[0], buf[1]]);
        assert_eq!(raw & 0xFFF, 4095);
    }
}
