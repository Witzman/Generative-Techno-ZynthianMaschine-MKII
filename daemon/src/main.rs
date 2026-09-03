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

use std::env;
use std::os::unix::io::{AsRawFd, RawFd};
use std::path::Path;

use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, UdpSocket};

use std::time::{Duration, Instant};

extern crate nix;
use nix::fcntl::{O_NONBLOCK, O_RDWR};
use nix::poll::*;
use nix::{fcntl, sys};

extern crate alsa_seq;
extern crate midi;
use alsa_seq::*;
use alsa_seq::SeqInputEvent;
use midi::*;

extern crate hsl;
use hsl::HSL;

#[macro_use(osc_args)]
extern crate tinyosc;
use tinyosc as osc;

mod base;
mod cc_math;
mod devices;
mod display;
mod hid_feature;
mod font;
mod ws_types;
mod ws_server;
mod midi_parse;
mod config;
mod hid_stats;
mod watchdog;
mod sequencer;
mod clock;
use clock::ClockSource;
use config::MaschineConfig;

use crate::base::{Maschine, MaschineButton, MaschineHandler};
use std::sync::mpsc;
use crate::ws_types::{DeviceEvent, WsCommand};

fn ev_loop(dev: &mut dyn Maschine, mhandler: &mut MHandler, dev_path: &str) {
    let mut fds = [
        PollFd::new(dev.get_fd(), POLLIN, EventFlags::empty()),
        PollFd::new(mhandler.osc_socket.as_raw_fd(), POLLIN, EventFlags::empty()),
        PollFd::new(mhandler.seq_in_fd, POLLIN, EventFlags::empty()),
    ];

    // INSTANT, NOT SystemTime, since 2026-09-03. `SystemTime::elapsed()`
    // returns a Result and these four were all `.unwrap()`, so a BACKWARD
    // clock step panicked the daemon - and this Pi has no RTC: fake-hwclock
    // restores a stale time at boot and NTP corrects it later, measured eight
    // days out on 2026-08-30. Every one of these is an interval, which is what
    // a monotonic clock is for; none of them wants a wall-clock date.
    let mut now = Instant::now();
    let mut now2 = Instant::now();
    let mut now_display = Instant::now();
    let timer_interval = Duration::from_millis(16);
    let display_interval = Duration::from_millis(100);
    let clock_fallback_timeout = Duration::from_millis(500);
    let mut timer_interval2;
    let mut step = 0;
    let mut check = 0;
    let mut last_report = Instant::now();
    let mut reopens: u64 = 0;
    // Storm state for the input watchdog. `consecutive` counts reopens since
    // input last flowed healthily; it is what the backoff is computed from, and
    // it is NOT the same as `reopens`, which stays a lifetime total because
    // `journalctl | grep -c reopened` is this project's primary diagnostic.
    let mut consecutive: u64 = 0;
    let mut last_reopen = Instant::now();
    let mut last_bpm_sent = Instant::now();
    let mut backoff_until = Instant::now();
    let mut announced_backoff = Duration::from_millis(0);
    let input_timeout = Duration::from_millis(50);
    let mut active = false;
    loop {
        // poll() returns EINTR on any signal the process is handed, and
        // `.unwrap()` on that ended the daemon. There is nothing to do about
        // an interrupted wait except take the next lap.
        if let Err(err) = poll(&mut fds, 16) {
            if err.errno() != nix::errno::Errno::EINTR {
                println!("poll failed: {} - retrying", err);
            }
            continue;
        }

        if fds[0].revents().unwrap_or_else(EventFlags::empty).contains(POLLIN) {
            dev.readable(mhandler);
            last_report = Instant::now();
            // Input is flowing. If it has been flowing long enough, the storm
            // is over and the next isolated stall gets an immediate retry
            // again - which is the common, recovering case and must stay fast.
            if consecutive > 0 && watchdog::storm_is_over(last_reopen.elapsed()) {
                println!(
                    "watchdog: input recovered after {} consecutive reopens",
                    consecutive
                );
                consecutive = 0;
                announced_backoff = Duration::from_millis(0);
            }
        }

        // Input watchdog. The device streams ~750 reports/s unconditionally, so
        // any silence longer than this means the kernel hidraw layer has stopped
        // delivering to our fd (verified with usbmon: the URBs keep completing
        // with data while read() returns EAGAIN forever). A fresh open() is the
        // only known recovery.
        if last_report.elapsed() >= input_timeout
            && Instant::now() >= backoff_until
        {
            // Close BEFORE reopening: usbhid only tears down and resubmits the
            // interrupt URB when the device user count drops to zero, and that
            // teardown is what actually revives the stream. Opening first left
            // one user held throughout, and the reopen had no effect at all.
            let _ = nix::unistd::close(dev.get_fd());
            match fcntl::open(
                Path::new(dev_path),
                O_RDWR | O_NONBLOCK,
                sys::stat::Mode::empty(),
            ) {
                Ok(new_fd) => {
                    dev.set_fd(new_fd);
                    dev.invalidate_lights();
                    fds[0] = PollFd::new(new_fd, POLLIN, EventFlags::empty());
                    reopens += 1;
                    println!("watchdog: input stalled, reopened {} (reopen #{})", dev_path, reopens);
                }
                Err(err) => {
                    println!("watchdog: reopen of {} failed: {}", dev_path, err);
                }
            }
            // Counted on failure too: a reopen that cannot even open the node
            // is the strongest possible reason to stop hammering it.
            consecutive += 1;
            last_reopen = Instant::now();
            let delay = watchdog::reopen_delay(consecutive);
            backoff_until = last_reopen + delay;
            // Announced only when the step CHANGES. Every reopen still prints
            // its own line above, so `grep -c reopened` keeps counting exactly
            // what it always counted; this line explains the spacing between
            // them rather than replacing them.
            if delay != announced_backoff {
                announced_backoff = delay;
                if delay > Duration::from_millis(0) {
                    println!(
                        "watchdog: backing off {}ms after {} consecutive reopens",
                        delay.as_millis(),
                        consecutive
                    );
                }
            }
            last_report = Instant::now();
        }

        if fds[1].revents().unwrap_or_else(EventFlags::empty).contains(POLLIN) {
            mhandler.recv_osc_msg(dev);
        }

        if mhandler.seq_in_fd >= 0
            && fds[2].revents().unwrap_or_else(EventFlags::empty).contains(POLLIN)
        {
            while let Some(ev) = mhandler.seq_handle.try_receive_event() {
                match ev {
                    SeqInputEvent::NoteOn { note, velocity, .. } if note < 16 => {
                        let brightness = if velocity == 0 {
                            PAD_RELEASED_BRIGHTNESS
                        } else {
                            velocity as f32 / 127.0
                        };
                        let color = mhandler.pad_color();
                        dev.set_pad_light(note as usize, color, brightness);
                    }
                    SeqInputEvent::NoteOff { note, .. } if note < 16 => {
                        let color = mhandler.pad_color();
                        dev.set_pad_light(note as usize, color, PAD_RELEASED_BRIGHTNESS);
                    }
                    SeqInputEvent::Clock => {
                        let _ = mhandler.seq_port.send_message(&Message::TimingClock);
                        mhandler.seq_handle.drain_output();
                        if let Some(_fired_step) = dev.clock_tick() {
                        }
                        // RATE LIMITED. This fired on every MIDI clock -
                        // twenty-four a beat, fifty a second at 125 BPM - to
                        // move a tempo readout in a web page. Twice a second
                        // is faster than anyone can read it.
                        if last_bpm_sent.elapsed() >= BPM_REPORT_INTERVAL {
                            if let Some(bpm) = dev.get_clock_state().estimated_bpm() {
                                let _ = mhandler.event_tx.try_send(
                                    DeviceEvent::ClockBpm { bpm });
                                last_bpm_sent = Instant::now();
                            }
                        }
                    }
                    SeqInputEvent::Start => {
                        let _ = mhandler.seq_port.send_message(&Message::Start);
                        mhandler.seq_handle.drain_output();
                        dev.clock_start();
                        step = 0;
                        check = 0;
                        now2 = Instant::now();
                    }
                    SeqInputEvent::Stop => {
                        let _ = mhandler.seq_port.send_message(&Message::Stop);
                        mhandler.seq_handle.drain_output();
                        dev.clock_stop();
                    }
                    _ => {}
                }
            }
        }

        while let Ok(cmd) = mhandler.cmd_rx.try_recv() {
            match cmd {
                WsCommand::SetPadColor { pad, color, brightness } => {
                    // BOUNDED, and the bound is the point. `pad` arrives as a
                    // usize straight out of JSON on a socket, and
                    // set_pad_light indexes a sixteen-entry table with it - so
                    // one message with pad 16 ended the daemon. Every other
                    // arm here already checked its index; this one did not.
                    if pad < 16 {
                        dev.set_pad_light(pad, color, brightness);
                    }
                }
                WsCommand::SetButtonColor { button, brightness } => {
                    if let Some(btn) = osc_button_to_btn_map(&button) {
                        dev.set_button_light(btn, 0xFFFFFF, brightness);
                    }
                }
                WsCommand::SetNoteBase { base } => {
                    dev.set_midi_note_base(base);
                }
                WsCommand::SetPadNote { pad, note } => {
                    if pad < 16 {
                        mhandler.pad_notes[pad] = note;
                        mhandler.save_config();
                    }
                }
                WsCommand::SetEncoderCC { encoder, cc } => {
                    if encoder < 8 {
                        mhandler.encoder_ccs[encoder] = cc;
                        mhandler.save_config();
                    }
                }
                WsCommand::RequestConfig => {
                    let _ = mhandler.event_tx.try_send(DeviceEvent::ConfigSnapshot {
                        pad_notes: mhandler.pad_notes.to_vec(),
                        encoder_ccs: mhandler.encoder_ccs.to_vec(),
                    });
                }
            }
        }

        if now.elapsed() >= timer_interval {
            dev.write_lights();
            now = Instant::now();
        }
        if now_display.elapsed() >= display_interval {
            // Normal rendering stays off - it issued ~180 writes/s. Each
            // report is 9 header bytes plus a 256-byte payload = 265, and a
            // both-screen rebuild is 16 of them (this comment said 521 bytes
            // until 2026-08-30; the write COUNT was always the half that
            // mattered). Calibration redraws are rate-limited to this timer.
            dev.calib_flush();
            // Screen framebuffers written over OSC land here too, for the same
            // reason: pushing them from the OSC handler would interleave HID
            // writes with the input reads.
            dev.display_fb_flush();
            now_display = Instant::now();
        }

        if dev.get_clock_state().should_fallback_to_internal(clock_fallback_timeout) {
            dev.set_clock_source(ClockSource::Internal);
            now2 = Instant::now();
        }

        if dev.get_playing() == true {
            timer_interval2 = Duration::from_millis(dev.get_seq_speed());
            active = true;
            let use_internal_clock = matches!(dev.get_clock_state().source, ClockSource::Internal);
            if use_internal_clock && dev.note_check(step) == 1 && now2.elapsed() >= timer_interval2 && check == 0
            {
                let msg = dev.load_notes(step, 1);
                mhandler.send_midi(&msg);
                check = 1;
            };
            if use_internal_clock && now2.elapsed() >= timer_interval2 * 2 && dev.note_check(step) == 1 {
                let msg = dev.load_notes(step, 0);
                mhandler.send_midi(&msg);
                now2 = Instant::now();
                step += 1;
                check = 0;
            } else if use_internal_clock && now2.elapsed() >= timer_interval2 * 2 && dev.note_check(step) == 0 {
                step += 1;
                check = 0;
                now2 = Instant::now();
            };
            if !use_internal_clock {
                let ext_step = dev.get_clock_state().step;
                if ext_step != step {
                    if dev.note_check(step) == 1 && check == 1 {
                        let msg = dev.load_notes(step, 0);
                        mhandler.send_midi(&msg);
                    }
                    step = ext_step;
                    check = 0;
                    if dev.note_check(step) == 1 {
                        let msg = dev.load_notes(step, 1);
                        mhandler.send_midi(&msg);
                        check = 1;
                    }
                }
            }
            if step >= 16 {
                step = 0;
            };
        } else if active == true {
            let msg = dev.load_notes(step, 0);
            mhandler.send_midi(&msg);
            active = false;
        }
    }
}

fn usage(prog_name: &String) {
    println!("usage: {} <hidraw device>", prog_name);
}

/// Where the big encoder's counter and reported value live.
///
/// roller_status and roller_value are both [i32; 9] for eight encoders. The
/// ninth slot was always spare; the big encoder now uses it, so it shares the
/// jump-rejection and accumulation the other eight have had all along.
const BIG_ENC_SLOT: usize = 8;

const PAD_RELEASED_BRIGHTNESS: f32 = 0.015;

/// Events held for a web editor that may never connect.
///
/// Deep enough that a burst of pad and encoder traffic reaches an attached
/// client whole; shallow enough that an absent one costs a few kilobytes
/// rather than growing forever. ws_server drains what is left before it serves
/// a new client, so a full queue is never shown to anyone as history.
const WS_EVENT_QUEUE: usize = 256;

/// Gap between two `ClockBpm` events. See the send site.
const BPM_REPORT_INTERVAL: Duration = Duration::from_millis(500);

/// Minimum gap between two aftertouch sends for the SAME pad.
///
/// The device streams pressure at ~750 reports/s (endpoint ceiling is 8,000/s:
/// high speed, bInterval 1, measured on the rig 2026-08-30). Every send is a
/// MIDI message into ZynMidiRouter, and the driver's `midi_event` holds its
/// lock for the whole event — so the raw rate is a hazard, not a resolution.
/// 25 ms caps one held pad at ~40 msg/s, a 19x reduction, which is still four
/// times the driver's own ~10 Hz consumption of it.
const AFTERTOUCH_MIN_INTERVAL: Duration = Duration::from_millis(25);

#[allow(dead_code)]
enum PressureShape {
    Linear,
    Exponential(f32),
    Constant(f32),
}

struct MHandler<'a> {
    color: HSL,

    seq_handle: &'a SequencerHandle,
    seq_port: &'a SequencerPort<'a>,

    pressure_shape: PressureShape,
    send_aftertouch: bool,

    osc_socket: &'a UdpSocket,
    osc_outgoing_addr: SocketAddr,

    event_tx: mpsc::SyncSender<DeviceEvent>,
    cmd_rx: mpsc::Receiver<WsCommand>,

    seq_in_fd: RawFd,

    pad_notes: [u8; 16],
    encoder_ccs: [u16; 8],
    external_pad_leds: bool,
    /// Whether SHIFT + PAD MODE may hand the pads to the daemon's own step
    /// sequencer. Off unless maschine.json asks; see `config::internal_sequencer`.
    internal_sequencer: bool,
    /// The config as loaded, kept whole so `save_config` can round-trip every
    /// key it does not own - including keys added after this line was written.
    cfg: MaschineConfig,

    /// Last aftertouch value sent per pad, and when. Both are needed: the
    /// change gate alone still lets a slowly-moving finger send at the report
    /// rate, and the time gate alone re-sends a value nobody changed.
    at_last_val: [u8; 16],
    at_last_sent: [Option<Instant>; 16],
}

fn osc_button_to_btn_map(osc_button: &str) -> Option<MaschineButton> {
    match osc_button {
        "restart" => Some(MaschineButton::Restart),
        "step_left" => Some(MaschineButton::Stepleft),
        "step_right" => Some(MaschineButton::Stepright),
        "grid" => Some(MaschineButton::Grid),
        "play" => Some(MaschineButton::Play),
        "rec" => Some(MaschineButton::Rec),
        "stop" => Some(MaschineButton::Erase),
        "shift" => Some(MaschineButton::Shift),

        "browse" => Some(MaschineButton::Browse),
        "sampling" => Some(MaschineButton::Sampling),
        "note_repeat" => Some(MaschineButton::Noterepeat),

        "encoder" => Some(MaschineButton::Encoder),

        "f1" => Some(MaschineButton::F1),
        "f2" => Some(MaschineButton::F2),
        "f3" => Some(MaschineButton::F3),
        "f4" => Some(MaschineButton::F4),
        "f5" => Some(MaschineButton::F5),
        "f6" => Some(MaschineButton::F6),
        "f7" => Some(MaschineButton::F7),
        "f8" => Some(MaschineButton::F8),

        "swing" => Some(MaschineButton::Swing),
        "step" => Some(MaschineButton::Step),
        "volume" => Some(MaschineButton::Volume),

        "enter" => Some(MaschineButton::Enter),
        "auto" => Some(MaschineButton::Auto),
        "all" => Some(MaschineButton::All),
        "navigate" => Some(MaschineButton::Navigate),
        "tempo" => Some(MaschineButton::Tempo),
        //"stop" => Some(MaschineButton::Erase),
        "control" => Some(MaschineButton::Control),
        "nav" => Some(MaschineButton::Nav),
        "nav_left" => Some(MaschineButton::Navleft),
        "nav_right" => Some(MaschineButton::Navright),
        "main" => Some(MaschineButton::Main),

        "scene" => Some(MaschineButton::Scene),
        "pattern" => Some(MaschineButton::Pattern),
        "pad_mode" => Some(MaschineButton::Padmode),
        "view" => Some(MaschineButton::View),
        "duplicate" => Some(MaschineButton::Duplicate),
        "select" => Some(MaschineButton::Select),
        "solo" => Some(MaschineButton::Solo),
        "mute" => Some(MaschineButton::Mute),

        "group_a" => Some(MaschineButton::GroupA),
        "group_b" => Some(MaschineButton::GroupB),
        "group_c" => Some(MaschineButton::GroupC),
        "group_d" => Some(MaschineButton::GroupD),
        "group_e" => Some(MaschineButton::GroupE),
        "group_f" => Some(MaschineButton::GroupF),
        "group_g" => Some(MaschineButton::GroupG),
        "group_h" => Some(MaschineButton::GroupH),

        "page_right" => Some(MaschineButton::Pageright),
        "page_left" => Some(MaschineButton::Pageleft),

        _ => None,
    }
}

fn btn_to_osc_button_map(btn: MaschineButton) -> &'static str {
    match btn {
        MaschineButton::Restart => "restart",
        MaschineButton::Stepleft => "step_left",
        MaschineButton::Stepright => "step_right",
        MaschineButton::Grid => "grid",
        MaschineButton::Play => "play",
        MaschineButton::Rec => "rec",
        MaschineButton::Erase => "stop",
        MaschineButton::Shift => "shift",

        MaschineButton::Browse => "browse",
        MaschineButton::Sampling => "sampling",
        MaschineButton::Noterepeat => "note_repeat",

        MaschineButton::Encoder => "encoder",

        MaschineButton::F1 => "f1",
        MaschineButton::F2 => "f2",
        MaschineButton::F3 => "f3",
        MaschineButton::F4 => "f4",
        MaschineButton::F5 => "f5",
        MaschineButton::F6 => "f6",
        MaschineButton::F7 => "f7",
        MaschineButton::F8 => "f8",

        MaschineButton::Swing => "swing",
        MaschineButton::Step => "step",
        MaschineButton::Volume => "volume",

        MaschineButton::Enter => "enter",
        MaschineButton::Auto => "auto",
        MaschineButton::All => "all",
        MaschineButton::Navigate => "navigate",
        MaschineButton::Tempo => "tempo",

        MaschineButton::Control => "control",
        MaschineButton::Nav => "nav",
        MaschineButton::Navleft => "nav_left",
        MaschineButton::Navright => "nav_right",
        MaschineButton::Main => "main",

        MaschineButton::Scene => "scene",
        MaschineButton::Pattern => "pattern",
        MaschineButton::Padmode => "pad_mode",
        MaschineButton::View => "view",
        MaschineButton::Duplicate => "duplicate",
        MaschineButton::Select => "select",
        MaschineButton::Solo => "solo",
        MaschineButton::Mute => "mute",

        MaschineButton::GroupA => "group_a",
        MaschineButton::GroupB => "group_b",
        MaschineButton::GroupC => "group_c",
        MaschineButton::GroupD => "group_d",
        MaschineButton::GroupE => "group_e",
        MaschineButton::GroupF => "group_f",
        MaschineButton::GroupG => "group_g",
        MaschineButton::GroupH => "group_h",

        MaschineButton::Pageright => "page_right",
        MaschineButton::Pageleft => "page_left",
        MaschineButton::R1 => "R1",
        MaschineButton::R2 => "R2",
        MaschineButton::R3 => "R3",
        MaschineButton::R4 => "R4",
        MaschineButton::R5 => "R5",
        MaschineButton::R6 => "R6",
        MaschineButton::R7 => "R7",
        MaschineButton::R8 => "R8",

        MaschineButton::A1 => "A1",
        MaschineButton::A2 => "A2",
        MaschineButton::A3 => "A3",
        MaschineButton::A4 => "A4",
        MaschineButton::A5 => "A5",
        MaschineButton::A6 => "A6",
        MaschineButton::A7 => "A7",
        MaschineButton::A8 => "A8",

        MaschineButton::B1 => "B1",
        MaschineButton::B2 => "B2",
        MaschineButton::B3 => "B3",
        MaschineButton::B4 => "B4",
        MaschineButton::B5 => "B5",
        MaschineButton::B6 => "B6",
        MaschineButton::B7 => "B7",
        MaschineButton::B8 => "B8",

        MaschineButton::C1 => "C1",
        MaschineButton::C2 => "C2",
        MaschineButton::C3 => "C3",
        MaschineButton::C4 => "C4",
        MaschineButton::C5 => "C5",
        MaschineButton::C6 => "C6",
        MaschineButton::C7 => "C7",
        MaschineButton::C8 => "C8",

        MaschineButton::D1 => "D1",
        MaschineButton::D2 => "D2",
        MaschineButton::D3 => "D3",
        MaschineButton::D4 => "D4",
        MaschineButton::D5 => "D5",
        MaschineButton::D6 => "D6",
        MaschineButton::D7 => "D7",
        MaschineButton::D8 => "D8",

        MaschineButton::E1 => "E1",
        MaschineButton::E2 => "E2",
        MaschineButton::E3 => "E3",
        MaschineButton::E4 => "E4",
        MaschineButton::E5 => "E5",
        MaschineButton::E6 => "E6",
        MaschineButton::E7 => "E7",
        MaschineButton::E8 => "E8",

        MaschineButton::FF1 => "FF1",
        MaschineButton::FF2 => "FF2",
        MaschineButton::FF3 => "FF3",
        MaschineButton::FF4 => "FF4",
        MaschineButton::FF5 => "FF5",
        MaschineButton::FF6 => "FF6",
        MaschineButton::FF7 => "FF7",
        MaschineButton::FF8 => "FF8",

        MaschineButton::G1 => "G1",
        MaschineButton::G2 => "G2",
        MaschineButton::G3 => "G3",
        MaschineButton::G4 => "G4",
        MaschineButton::G5 => "G5",
        MaschineButton::G6 => "G6",
        MaschineButton::G7 => "G7",
        MaschineButton::G8 => "G8",

        MaschineButton::H1 => "H1",
        MaschineButton::H2 => "H2",
        MaschineButton::H3 => "H3",
        MaschineButton::H4 => "H4",
        MaschineButton::H5 => "H5",
        MaschineButton::H6 => "H6",
        MaschineButton::H7 => "H7",
        MaschineButton::H8 => "H8",

        MaschineButton::I1 => "I1",
        MaschineButton::I2 => "I2",
        MaschineButton::I3 => "I3",
        MaschineButton::I4 => "I4",
        MaschineButton::I5 => "I5",
        MaschineButton::I6 => "I6",
        MaschineButton::I7 => "I7",
        MaschineButton::I8 => "I8",

        MaschineButton::J1 => "J1",
        MaschineButton::J2 => "J2",
        MaschineButton::J3 => "J3",
        MaschineButton::J4 => "J4",
        MaschineButton::J5 => "J5",
        MaschineButton::J6 => "J6",
        MaschineButton::J7 => "J7",
        MaschineButton::J8 => "J8",

        MaschineButton::K1 => "K1",
        MaschineButton::K2 => "K2",
        MaschineButton::K3 => "K3",
        MaschineButton::K4 => "K4",
        MaschineButton::K5 => "K5",
        MaschineButton::K6 => "K6",
        MaschineButton::K7 => "K7",
        MaschineButton::K8 => "K8",

        MaschineButton::L1 => "L1",
        MaschineButton::L2 => "L2",
        MaschineButton::L3 => "L3",
        MaschineButton::L4 => "L4",
        MaschineButton::L5 => "L5",
        MaschineButton::L6 => "L6",
        MaschineButton::L7 => "L7",
        MaschineButton::L8 => "L8",

        MaschineButton::M1 => "M1",
        MaschineButton::M2 => "M2",
        MaschineButton::M3 => "M3",
        MaschineButton::M4 => "M4",
        MaschineButton::M5 => "M5",
        MaschineButton::M6 => "M6",
        MaschineButton::M7 => "M7",
        MaschineButton::M8 => "M8",

        MaschineButton::N1 => "N1",
        MaschineButton::N2 => "N2",
        MaschineButton::N3 => "N3",
        MaschineButton::N4 => "N4",
        MaschineButton::N5 => "N5",
        MaschineButton::N6 => "N6",
        MaschineButton::N7 => "N7",
        MaschineButton::N8 => "N8",

        MaschineButton::O1 => "O1",
        MaschineButton::O2 => "O2",
        MaschineButton::O3 => "O3",
        MaschineButton::O4 => "O4",
        MaschineButton::O5 => "O5",
        MaschineButton::O6 => "O6",
        MaschineButton::O7 => "O7",
        MaschineButton::O8 => "O8",

        MaschineButton::P1 => "P1",
        MaschineButton::P2 => "P2",
        MaschineButton::P3 => "P3",
        MaschineButton::P4 => "P4",
        MaschineButton::P5 => "P5",
        MaschineButton::P6 => "P6",
        MaschineButton::P7 => "P7",
        MaschineButton::P8 => "P8",

        _=> "NO",
    }
}

impl<'a> MHandler<'a> {
    /// One MIDI send, and it CANNOT end the process.
    ///
    /// Sixty call sites were `self.seq_port.send_message(&msg).unwrap()`
    /// followed by a drain. Every one of them turned an ALSA error into a
    /// panic, and a panic here is the worst failure this daemon has: the
    /// surface goes dark and the music stops, from a button press. A dropped
    /// message costs one button; a panic costs the instrument.
    ///
    /// The drain belongs here too - it followed every one of those sends, and
    /// a send whose drain was forgotten is a message that sits in the queue.
    /// Persist what the editor can change, WITHOUT rebuilding the config.
    ///
    /// Both callers used to construct a fresh `MaschineConfig` out of six
    /// handler fields, so every key added to the config had to be remembered
    /// in two more places or a live rig silently lost it on the next pad-note
    /// change. config.rs carries two tests about exactly that hazard; holding
    /// the loaded config and overwriting only the two mutable arrays removes
    /// the hazard instead of testing for it.
    fn save_config(&self) {
        let mut cfg = self.cfg.clone();
        cfg.pad_notes = self.pad_notes;
        cfg.encoder_ccs = self.encoder_ccs;
        cfg.save();
    }

    fn send_midi(&self, msg: &Message) {
        if let Err(err) = self.seq_port.send_message(msg) {
            println!("midi send failed: {:?}", err);
        }
        self.seq_handle.drain_output();
    }

    fn pad_color(&self) -> u32 {
        let (r, g, b) = self.color.to_rgb();

        ((r as u32) << 16) | ((g as u32) << 8) | (b as u32)
    }

    fn pressure_to_vel(&self, pressure: f32) -> U7 {
        (match self.pressure_shape {
            PressureShape::Linear => pressure,
            PressureShape::Exponential(power) => pressure.powf(power),
            PressureShape::Constant(c_pressure) => c_pressure,
        } * 127.0) as U7
    }

    fn recv_osc_msg(&self, maschine: &mut dyn Maschine) {
        let mut buf = [0u8; 128];

        let nbytes = match self.osc_socket.recv_from(&mut buf) {
            Ok((nbytes, _)) => nbytes,
            Err(e) => {
                println!(" :: error in recv_from(): {}", e);
                return;
            }
        };

        let msg = match osc::Message::deserialize(&buf[..nbytes]) {
            Ok(msg) => msg,
            Err(_) => {
                println!(" :: couldn't decode OSC message :c");
                return;
            }
        };

        self.handle_osc_messge(maschine, &msg);
    }

    fn handle_osc_messge(&self, maschine: &mut dyn Maschine, msg: &osc::Message) {
        if msg.path.starts_with("/maschine/button") {
            // strip_prefix, NOT a fixed slice. `&msg.path[17..]` panicked on
            // the exact path "/maschine/button", which is sixteen bytes: the
            // starts_with passed and the slice ran off the end. One OSC
            // message from any local process ended the daemon.
            let name = match msg.path.strip_prefix("/maschine/button/") {
                Some(name) => name,
                None => return,
            };
            let btn = match osc_button_to_btn_map(name) {
                Some(btn) => btn,
                None => return,
            };

            match msg.arguments.len() {
                1 => maschine.set_button_light(
                    btn,
                    0xFFFFFF,
                    match msg.arguments[0] {
                        osc::Argument::i(val) => val as f32,
                        osc::Argument::f(val) => val,
                        _ => return,
                    },
                ),

                2 => {
                    if let (&osc::Argument::i(color), &osc::Argument::f(brightness)) =
                        (&msg.arguments[0], &msg.arguments[1])
                    {
                        maschine.set_button_light(btn, (color as u32) & 0xFFFFFF, brightness);
                    }
                }

                _ => return,
            };
        } else if msg.path.starts_with("/maschine/pad") {
            match msg.arguments.len() {
                3 => {
                    if let (
                        &osc::Argument::i(pad),
                        &osc::Argument::i(color),
                        &osc::Argument::f(brightness),
                    ) = (&msg.arguments[0], &msg.arguments[1], &msg.arguments[2])
                    {
                        // Range-checked BEFORE the cast: a negative i32 becomes
                        // an enormous usize, and set_pad_light indexes a
                        // sixteen-entry table with it.
                        if (0..16).contains(&pad) {
                            maschine.set_pad_light(
                                pad as usize,
                                (color as u32) & 0xFFFFFF,
                                brightness as f32,
                            );
                        }
                    }
                }

                _ => return,
            }
        } else if msg.path.starts_with("/maschine/display/test") {
            if let [osc::Argument::i(pattern)] = msg.arguments[..] {
                if pattern >= 0 {
                    maschine.display_test(pattern as usize);
                }
            }
        } else if msg.path.starts_with("/maschine/display/opts") {
            if let [osc::Argument::i(col), osc::Argument::i(reverse), osc::Argument::i(bands)] =
                msg.arguments[..]
            {
                if (0..=255).contains(&col) && bands >= 1 {
                    maschine.display_opts(col as u8, reverse != 0, bands as usize);
                }
            }
        } else if msg.path.starts_with("/maschine/display/calib") {
            if let [osc::Argument::i(on)] = msg.arguments[..] {
                maschine.calib_set(on != 0);
            }
        } else if msg.path.starts_with("/maschine/display/fbclear") {
            // Screen framebuffer commands. Screen 0 = left (0xE0), 1 = right
            // (0xE1). Nothing reaches the hardware until the display timer
            // flushes, so a whole screen is composed with several messages and
            // shown in one write.
            if let [osc::Argument::i(screen)] = msg.arguments[..] {
                if screen >= 0 {
                    maschine.display_fb_clear(screen as usize);
                }
            }
        } else if msg.path.starts_with("/maschine/display/raw") {
            if let [osc::Argument::i(on)] = msg.arguments[..] {
                maschine.display_fb_raw(on != 0);
            }
        } else if msg.path.starts_with("/maschine/display/text") {
            if let [
                osc::Argument::i(screen), osc::Argument::i(x), osc::Argument::i(y),
                osc::Argument::i(scale), osc::Argument::i(invert), osc::Argument::s(text),
            ] = msg.arguments[..]
            {
                if screen >= 0 && x >= 0 && y >= 0 && scale >= 1 {
                    maschine.display_fb_text(
                        screen as usize, x as usize, y as usize, scale as usize,
                        invert != 0, text,
                    );
                }
            }
        } else if msg.path.starts_with("/maschine/display/rect") {
            if let [
                osc::Argument::i(screen), osc::Argument::i(x), osc::Argument::i(y),
                osc::Argument::i(w), osc::Argument::i(h), osc::Argument::i(style),
            ] = msg.arguments[..]
            {
                if screen >= 0 && x >= 0 && y >= 0 && w >= 0 && h >= 0 && style >= 0 {
                    maschine.display_fb_rect(
                        screen as usize, x as usize, y as usize,
                        w as usize, h as usize, style as usize,
                    );
                }
            }
        } else if msg.path.starts_with("/maschine/display/clear") {
            maschine.clear_screen();
        } else if msg.path.starts_with("/maschine/rawled") {
            // Diagnostic path for mapping LED report layouts: buffer, index,
            // value. See Maschine::set_raw_light.
            if let [osc::Argument::i(buffer), osc::Argument::i(index), osc::Argument::i(value)] =
                msg.arguments[..]
            {
                if buffer >= 0 && index >= 0 && (0..=255).contains(&value) {
                    maschine.set_raw_light(buffer as usize, index as usize, value as u8);
                }
            }
        } else if msg.path.starts_with("/maschine/encoder") {
            // Re-centre an encoder: idx 0-7, value 0-127. A host that points
            // one endless knob at several parameters uses this when it
            // switches between them, so the knob is never parked against an
            // end stop belonging to a parameter it no longer controls.
            if let [osc::Argument::i(idx), osc::Argument::i(value)] = msg.arguments[..] {
                if (0..8).contains(&idx) && (0..=127).contains(&value) {
                    maschine.set_roller_value(value, idx as usize);
                }
            }
        } else if msg.path.starts_with("/maschine/midi_note_base") {
            match msg.arguments.len() {
                1 => {
                    if let osc::Argument::i(base) = msg.arguments[0] {
                        maschine.set_midi_note_base(base as u8);
                    }
                }
                _ => return,
            }
        }
    }

    fn send_osc_msg(&self, path: &str, arguments: Vec<osc::Argument>) {
        let msg = osc::Message {
            path: path,
            arguments: arguments,
        };

        let bytes = match msg.serialize() {
            Ok(bytes) => bytes,
            Err(e) => {
                println!(" :: could not serialise OSC {}: {:?}", path, e);
                return;
            }
        };
        match self.osc_socket.send_to(&bytes, &self.osc_outgoing_addr) {
            Ok(_) => {}
            Err(e) => println!(" :: error in send_to: {}", e),
        }
    }

    fn refresh_seq_page(&self, maschine: &mut dyn Maschine) {
        let page = maschine.get_seq_page();
        let color = self.pad_color();
        for i in 0..16 {
            let b = if maschine.note_check(i) == 1 { 0.4 } else { PAD_RELEASED_BRIGHTNESS };
            maschine.set_pad_light(i, color, b);
        }
        const GROUPS: [MaschineButton; 8] = [
            MaschineButton::GroupA, MaschineButton::GroupB, MaschineButton::GroupC,
            MaschineButton::GroupD, MaschineButton::GroupE, MaschineButton::GroupF,
            MaschineButton::GroupG, MaschineButton::GroupH,
        ];
        for (i, &btn) in GROUPS.iter().enumerate() {
            maschine.set_button_light(btn, 0xFFFFFF, if i == page { 1.0 } else { 0.05 });
        }
    }

    fn refresh_normal_mode(&self, maschine: &mut dyn Maschine) {
        let color = self.pad_color();
        for i in 0..16 {
            maschine.set_pad_light(i, color, PAD_RELEASED_BRIGHTNESS);
        }
        const GROUPS: [MaschineButton; 8] = [
            MaschineButton::GroupA, MaschineButton::GroupB, MaschineButton::GroupC,
            MaschineButton::GroupD, MaschineButton::GroupE, MaschineButton::GroupF,
            MaschineButton::GroupG, MaschineButton::GroupH,
        ];
        for &btn in GROUPS.iter() {
            maschine.set_button_light(btn, 0xFFFFFF, 0.05);
        }
    }

//Status is Byte from previous stupid naming!
    fn send_osc_button_msg(
        &mut self,
        maschine: &mut dyn Maschine,
        btn: MaschineButton,
        status: usize,
        is_down: bool,
    ) {
        let button = btn_to_osc_button_map(btn);
        let controlbase = 15;
        let modpress = maschine.get_mod();
        //println!("{} is:  {}", button, status);
        // EXACT MATCHES, not substrings, since 2026-09-03. This block used to
        // read `button.contains("shift")` and `button.contains("C")` and then
        // test the exact name inside, so the outer guards did nothing except
        // make it look as though a whole family of tokens was handled. They
        // were also a live trap: every uppercase group letter is a single
        // character, so any future token carrying a capital C, E, G, I, K, M or
        // O would have entered a branch that reparks an encoder. The names
        // matched here are exactly the names the old code could reach.
        if button == "shift" {
            maschine.set_mod(if status > 0 { 1 } else { 0 });
        }
        // The high-order counter bytes are NOT handled here either, for the
        // same reason: "C7", "E8" and the rest are row-8-and-up names, and
        // `read_buttons` sets those directly with `set_roller_state`. Removed
        // 2026-09-03; row 7 - A1..A8, the big encoder's nibble byte - IS a
        // button row and is handled below.
        if button == "A8" {
            // THE BIG ENCODER, and it is the only one that does not go through
            // send_encoder_cc. It used to send `status * 8` as an ABSOLUTE
            // value on every detent, so the counter rolling over snapped the
            // target from 120 to 0 once per revolution - MOD depth rides this
            // knob, so that was audible.
            //
            // Slot 8 of roller_status/roller_value has been sitting free since
            // both arrays were declared [_; 9] for eight encoders. This is
            // what it was for.
            // THE LOW NIBBLE, AND ONLY THE LOW NIBBLE, since 2026-09-02.
            // The HID descriptor declares this byte as `2 x 4 bit, Logical
            // Maximum (15)` - two counters sharing one byte - and the capture
            // of 2026-08-31 settled which one moves: the LOW nibble ran all
            // sixteen values across 117 transitions, every one +1, wrapping
            // 15 to 0, while the HIGH nibble stayed at zero throughout.
            //
            // Reading the whole byte therefore WORKED BY ACCIDENT. It worked
            // because the other nibble happens to be zero, and it would have
            // stopped the moment whatever that nibble counts started moving -
            // the value would jump by 16 per foreign tick and big_encoder_value
            // would read it as a wild turn.
            //
            // notes/findings/2026-08-31-three-hardware-answers-one-capture.md
            let counter = (status & 0x0F) as i32;
            let prev = maschine.get_roller_status(BIG_ENC_SLOT);
            // Resync the baseline whether or not the report is used, exactly
            // as send_encoder_cc does: leaving a stale baseline makes every
            // later delta carry the wrap too, and the knob goes dead until the
            // counter comes back round.
            maschine.set_roller_status(counter, BIG_ENC_SLOT);
            let value = cc_math::big_encoder_value(
                prev, counter, maschine.get_roller_value(BIG_ENC_SLOT));
            maschine.set_roller_value(value as i32, BIG_ENC_SLOT);
            let msg = Message::RPN7(Ch1, controlbase, value);
            self.send_midi(&msg);
        }

        if status <= 250 {
            match button {
                "play" => {
                    if maschine.get_padmode() != 2 {
                        let msg = Message::RPN7(Ch1, 1, cc_math::button_cc_value(is_down));
                        self.send_midi(&msg);
                    } else if is_down {
                        maschine.clock_start();
                        maschine.set_playing(1);
                    };
                }

                "stop" => {
                    if maschine.get_padmode() != 2 {
                        let msg = Message::RPN7(Ch1, 2, cc_math::button_cc_value(is_down));
                        self.send_midi(&msg);
                    } else if !is_down {
                        maschine.set_playing(0);
                    }
                }
                "rec" => {
                    let msg = Message::RPN7(Ch1, 3, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "grid" => {
                    let msg = Message::RPN7(Ch1, 4, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "step_left" => {
                    let msg = Message::RPN7(Ch1, 5, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "step_right" => {
                    let msg = Message::RPN7(Ch1, 6, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "restart" => {
                    let msg = Message::RPN7(Ch1, 7, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "browse" => {
                    let msg = Message::RPN7(Ch1, 8, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "sampling" => {
                    let msg = Message::RPN7(Ch1, 9, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "note_repeat" => {
                    let msg = Message::RPN7(Ch1, 10, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "control" => {
                    let msg = Message::RPN7(Ch1, 11, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "nav" => {
                    let msg = Message::RPN7(Ch1, 12, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "nav_left" => {
                    let msg = Message::RPN7(Ch1, 13, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "nav_right" => {
                    let msg = Message::RPN7(Ch1, 14, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "main" => {
                    let msg = Message::RPN7(Ch1, 24, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "scene" => {
                    let msg = Message::RPN7(Ch1, 25, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "pattern" => {
                    let msg = Message::RPN7(Ch1, 26, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "pad_mode" => {
                    if modpress == 1 {
                        // SHIFT + PAD MODE, and it stays EATEN either way -
                        // the driver's own `_act_freeze` docstring says this
                        // chord never arrives, and that is still true, so the
                        // panel's grammar does not move.
                        //
                        // What has gone, since 2026-09-03, is what it used to
                        // do unasked: step the daemon into its own sequencer,
                        // where the pads stop sending notes to the host, PLAY
                        // and STOP drive the daemon's transport instead of the
                        // driver's, the Group buttons switch its pages instead
                        // of the pad octave, and every pad LED is repainted in
                        // its colour. Nothing on the panel said so and three
                        // more presses of the same chord were the way out.
                        // config::internal_sequencer turns it back on.
                        if is_down && self.internal_sequencer {
                            maschine.set_padmode(1);
                            if maschine.get_padmode() == 2 {
                                self.refresh_seq_page(maschine);
                            } else {
                                self.refresh_normal_mode(maschine);
                            }
                        } else if is_down {
                            println!(
                                "SHIFT + PAD MODE: the daemon's own sequencer is \
                                 off (\"internal_sequencer\" in maschine.json); \
                                 ignored");
                        }
                    } else {
                        let msg = Message::RPN7(Ch1, 27, cc_math::button_cc_value(is_down));
                        self.send_midi(&msg);
                    }
                }
                "view" => {
                    let msg = Message::RPN7(Ch1, 28, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "duplicate" => {
                    let msg = Message::RPN7(Ch1, 29, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "select" => {
                    let msg = Message::RPN7(Ch1, 30, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "solo" => {
                    let msg = Message::RPN7(Ch1, 31, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "step" => {
                    let msg = Message::RPN7(Ch1, 32, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "mute" => {
                    let msg = Message::RPN7(Ch1, 33, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "navigate" => {
                    let msg = Message::RPN7(Ch1, 34, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "tempo" => {
                    let msg = Message::RPN7(Ch1, 35, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "enter" => {
                    let msg = Message::RPN7(Ch1, 36, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "auto" => {
                    let msg = Message::RPN7(Ch1, 37, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "all" => {
                    let msg = Message::RPN7(Ch1, 38, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f1" => {
                    let msg = Message::RPN7(Ch1, 39, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f2" => {
                    let msg = Message::RPN7(Ch1, 40, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f3" => {
                    let msg = Message::RPN7(Ch1, 41, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f4" => {
                    let msg = Message::RPN7(Ch1, 42, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f5" => {
                    let msg = Message::RPN7(Ch1, 43, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f6" => {
                    let msg = Message::RPN7(Ch1, 44, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f7" => {
                    let msg = Message::RPN7(Ch1, 45, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "f8" => {
                    let msg = Message::RPN7(Ch1, 46, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "page_right" => {
                    let msg = Message::RPN7(Ch1, 47, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "page_left" => {
                    let msg = Message::RPN7(Ch1, 48, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                // SHIFT also stays an internal modifier - the set_mod block
                // above runs first and does not return, so it keeps gating PAD
                // MODE and the B6 encoder while the host sees it too.
                "shift" => {
                    let msg = Message::RPN7(Ch1, 49, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "swing" => {
                    let msg = Message::RPN7(Ch1, 50, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }
                "volume" => {
                    let msg = Message::RPN7(Ch1, 51, cc_math::button_cc_value(is_down));
                    self.send_midi(&msg);
                }

                // NO ENCODER ARMS HERE. There used to be eight - "B6" through
                // "P6", each rebuilding an encoder's absolute position and
                // sending it on CC 16-23 - and they were UNREACHABLE, which
                // the button-name tests at the bottom of this file found on
                // 2026-09-03. `read_buttons` hands rows 0-7 of the report to
                // `button_down` and rows 8-23 to `encoder_step` and
                // `set_roller_state`; every one of those arms was keyed on a
                // row-8-and-up name. The live path is `send_encoder_cc`, and
                // it is the only one that has run for years.
                "group_a" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(0), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(1); }
                        else { maschine.set_seq_page(0); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(24); }
                }
                "group_b" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(1), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(2); }
                        else { maschine.set_seq_page(1); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(36); }
                }
                "group_c" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(2), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(3); }
                        else { maschine.set_seq_page(2); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(48); }
                }
                "group_d" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(3), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(4); }
                        else { maschine.set_seq_page(3); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(60); }
                }
                "group_e" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(4), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(5); }
                        else { maschine.set_seq_page(4); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(72); }
                }
                "group_f" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(5), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(6); }
                        else { maschine.set_seq_page(5); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(84); }
                }
                "group_g" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(6), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(7); }
                        else { maschine.set_seq_page(6); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(96); }
                }
                "group_h" => {
                    let msg = Message::RPN7(Ch1, cc_math::group_cc(7), cc_math::button_cc_value(is_down));
                    if let Err(err) = self.seq_port.send_message(&msg) {
                        println!("group button: MIDI send failed: {:?}", err);
                    }
                    self.seq_handle.drain_output();
                    if maschine.get_padmode() == 2 && is_down {
                        if maschine.get_mod() == 1 { maschine.apply_euclidean(8); }
                        else { maschine.set_seq_page(7); }
                        self.refresh_seq_page(maschine);
                    } else { maschine.set_midi_note_base(108); }
                }
                _ => {}
            }
        }
        if is_down {
            let _ = self.event_tx.try_send(DeviceEvent::ButtonDown { button: button.to_string() });
        } else {
            let _ = self.event_tx.try_send(DeviceEvent::ButtonUp { button: button.to_string() });
        }
        self.send_osc_msg(&*format!("/{}", button), osc_args![status as f32]);
    }

    fn send_encoder_cc(&self, maschine: &mut dyn Maschine, idx: usize, raw: i32) {
        let state = maschine.get_roller_state(idx);
        let accumulated = cc_math::accumulate_raw(raw, state);
        let prev = maschine.get_roller_status(idx);
        let delta = accumulated - prev;
        // A wrap of the hardware counter shows up as a jump far larger than
        // any real movement, so it is not reported. The baseline still has to
        // be resynced to it: leaving the old one in place makes every later
        // delta measure the wrap's size as well, so every one of them is
        // rejected too and the encoder goes dead until the counter comes back
        // round. One wrap should cost one message, not the knob.
        maschine.set_roller_status(accumulated, idx);
        if !cc_math::is_encoder_jump(delta) {
            let value = cc_math::accumulate_encoder(maschine.get_roller_value(idx), delta);
            let cc_num = self.encoder_ccs[idx];
            let msg = Message::RPN7(Ch1, cc_num, value);
            maschine.set_roller_value(value as i32, idx);
            self.send_midi(&msg);
            let _ = self.event_tx.try_send(DeviceEvent::Encoder { idx, value });
        }
    }
}

impl<'a> MaschineHandler for MHandler<'a> {
    fn pad_pressed(&mut self, maschine: &mut dyn Maschine, pad_idx: usize, pressure: f32) {
        let midi_note = maschine.get_midi_note_base() + self.pad_notes[pad_idx];
        let msg = Message::NoteOn(Ch1, midi_note, self.pressure_to_vel(pressure));
        if maschine.get_padmode() == 2 {
            if maschine.get_mod() != 1 {
                if maschine.note_check(pad_idx) == 0 {
                    maschine.note_state(pad_idx, 1);
                    maschine.set_selected_step(Some(pad_idx));
                    maschine.set_pad_light(pad_idx, 0xFF8800, 0.7);
                } else {
                    maschine.note_state(pad_idx, 0);
                    maschine.set_selected_step(None);
                    maschine.set_pad_light(pad_idx, self.pad_color(), PAD_RELEASED_BRIGHTNESS);
                }
            } else {
                maschine.note_save(pad_idx, midi_note, self.pressure_to_vel(pressure));
            }
        } else {
            self.send_midi(&msg);
            if !self.external_pad_leds {
                maschine.set_pad_light(pad_idx, self.pad_color(), pressure.sqrt());
            }
            let _ = self.event_tx.try_send(DeviceEvent::PadPressed {
                pad: pad_idx,
                velocity: self.pressure_to_vel(pressure),
            });
        };
    }

    fn pad_aftertouch(&mut self, maschine: &mut dyn Maschine, pad_idx: usize, pressure: f32) {
        match self.pressure_shape {
            PressureShape::Constant(_) => return,
            _ => {}
        }

        if !self.send_aftertouch {
            return;
        }

        // Two gates, and the LED glow sits behind them too. Without that the
        // pressure glow would mark the LED buffer dirty on every report, so a
        // single held pad would pin the 16 ms flush at its 187 writes/s
        // ceiling for as long as it was held.
        // AFTERTOUCH ONLY. The raw pressure is normalised against 4095 in
        // mikro.rs, and all sixteen pads were measured on 2026-08-31 topping
        // out between 3101 and 3479 - so a fifth of the control was
        // unreachable however hard anyone pressed. Rescaled here rather than
        // at the divisor, because that divisor also feeds NOTE VELOCITY, which
        // is shipped and gated. Owner's call: scale aftertouch, leave velocity
        // alone.
        let value = self.pressure_to_vel(cc_math::aftertouch_scale(pressure));
        if value == self.at_last_val[pad_idx] {
            return;
        }
        if let Some(sent) = self.at_last_sent[pad_idx] {
            if sent.elapsed() < AFTERTOUCH_MIN_INTERVAL {
                return;
            }
        }
        self.at_last_val[pad_idx] = value;
        self.at_last_sent[pad_idx] = Some(Instant::now());

        let midi_note = maschine.get_midi_note_base() + self.pad_notes[pad_idx];
        let msg = Message::PolyphonicPressure(Ch1, midi_note, value);

        self.send_midi(&msg);

        if !self.external_pad_leds {
            maschine.set_pad_light(pad_idx, self.pad_color(), pressure.sqrt());
        }
    }

    fn pad_released(&mut self, maschine: &mut dyn Maschine, pad_idx: usize) {
        // Re-arm the aftertouch gates, or the next press of this pad is held
        // off by up to 25 ms and its first value can be swallowed as
        // unchanged.
        self.at_last_val[pad_idx] = 0;
        self.at_last_sent[pad_idx] = None;

        if maschine.get_padmode() != 2 {
            let midi_note = maschine.get_midi_note_base() + self.pad_notes[pad_idx];
            let msg = Message::NoteOff(Ch1, midi_note, 0);
            self.send_midi(&msg);
            if !self.external_pad_leds {
                maschine.set_pad_light(pad_idx, self.pad_color(), PAD_RELEASED_BRIGHTNESS);
            }
            let _ = self.event_tx.try_send(DeviceEvent::PadReleased { pad: pad_idx });
        };
    }

    fn encoder_step(&mut self, maschine: &mut dyn Maschine, idx: usize, state: i32) {
        if maschine.calib_active() {
            maschine.calib_move(idx, state);
            return;
        }
        if maschine.get_padmode() == 2 {
            if let Some(sel) = maschine.get_selected_step() {
                match idx {
                    0 => {
                        let new_vel = ((maschine.get_step_vel(sel) as i32) + state)
                            .clamp(0, 127) as u8;
                        maschine.set_step_vel(sel, new_vel);
                        return;
                    }
                    1 => {
                        let new_note = ((maschine.get_step_note(sel) as i32) + state)
                            .clamp(0, 127) as u8;
                        maschine.set_step_note(sel, new_note);
                        return;
                    }
                    _ => {}
                }
            }
        }
        self.send_encoder_cc(maschine, idx, state);
    }

    fn button_down(
        &mut self,
        maschine: &mut dyn Maschine,
        btn: MaschineButton,
        byte: u8,
        is_down: bool,
    ) {
        //println!("{}", byte);
        self.send_osc_button_msg(maschine, btn, byte as usize, is_down);
    }

    fn button_up(
        &mut self,
        maschine: &mut dyn Maschine,
        btn: MaschineButton,
        byte: u8,
        is_down: bool,
    ) {
        self.send_osc_button_msg(maschine, btn, byte as usize, is_down);
    }

    fn midi_in_received(&mut self, _maschine: &mut dyn Maschine, bytes: &[u8]) {
        for msg in midi_parse::parse(bytes) {
            let _ = self.seq_port.send_message(&msg);
        }
        self.seq_handle.drain_output();
    }
}

fn main() {
    let args: Vec<_> = env::args().collect();

    if args.len() < 2 {
        usage(&args[0]);
        panic!("missing hidraw device path");
    }

    let dev_fd = match fcntl::open(
        Path::new(&args[1]),
        O_RDWR | O_NONBLOCK,
        sys::stat::Mode::empty(),
    ) {
        Err(err) => panic!("couldn't open {}: {}", args[1], err.errno().desc()),
        Ok(file) => file,
    };

    let osc_socket = match UdpSocket::bind("127.0.0.1:42434") {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error: failed to bind OSC socket on port 42434: {}", e);
            eprintln!("hint: is another maschine daemon already running?");
            std::process::exit(1);
        }
    };

    // Loaded before the WebSocket server, which needs its bind address.
    let cfg = MaschineConfig::load();

    // BOUNDED, since 2026-09-03. `event_rx` is drained ONLY inside
    // ws_server's per-client loop, so on a rig with no web editor attached -
    // which is every rig - nothing ever read this channel while pad presses,
    // encoder moves, button edges and one ClockBpm PER MIDI CLOCK TICK were
    // pushed into it. At 125 BPM that is fifty messages a second into an
    // unbounded queue, for the life of the process.
    //
    // A bounded channel with try_send makes the overflow a dropped event
    // instead of a leak. Every send site already ignored its result, because
    // none of them can do anything about a missing web editor.
    let (event_tx, event_rx) = mpsc::sync_channel::<DeviceEvent>(WS_EVENT_QUEUE);
    let (cmd_tx, cmd_rx) = mpsc::channel::<WsCommand>();
    ws_server::start(cfg.ws_bind.clone(), cmd_tx, event_rx);

    let seq_handle = SequencerHandle::open("maschine.rs", HandleOpenStreams::Duplex)
        .unwrap_or_else(|_| {
            eprintln!("warning: ALSA not available — MIDI disabled");
            SequencerHandle::null()
        });
    let seq_port = seq_handle
        .create_port(
            "Pads MIDI",
            PortCapabilities::PORT_CAPABILITY_READ | PortCapabilities::PORT_CAPABILITY_SUBS_READ,
            PortType::MidiGeneric,
        )
        .unwrap();
    let _seq_in_port = seq_handle
        .create_port(
            "MIDI Control",
            PortCapabilities::PORT_CAPABILITY_WRITE | PortCapabilities::PORT_CAPABILITY_SUBS_WRITE,
            PortType::MidiGeneric,
        )
        .unwrap();
    seq_handle.set_nonblock();
    let seq_in_fd = seq_handle.get_poll_fd();

    let mut dev = devices::mk2::Mikro::new(dev_fd);

    let mut handler = MHandler {
        color: HSL {
            h: 0.0,
            s: 1.0,
            l: 0.3,
        },

        seq_port: &seq_port,
        seq_handle: &seq_handle,

        pressure_shape: PressureShape::Exponential(0.4),
        send_aftertouch: cfg.send_aftertouch,

        osc_socket: &osc_socket,
        osc_outgoing_addr: SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::new(127, 0, 0, 1), 42435)),

        event_tx,
        cmd_rx,

        seq_in_fd,

        pad_notes: cfg.pad_notes,
        encoder_ccs: cfg.encoder_ccs,
        external_pad_leds: cfg.external_pad_leds,
        internal_sequencer: cfg.internal_sequencer,
        cfg: cfg.clone(),

        at_last_val: [0; 16],
        at_last_sent: [None; 16],
    };

    // Panel brightness and contrast, once, before anything else touches the
    // device. A no-op unless maschine.json carries both keys; see
    // hid_feature.rs for why the read comes first and why the write is
    // skipped when the device already agrees.
    dev.apply_screen_settings(cfg.screen_brightness, cfg.screen_contrast);

    // Display disabled, see write_display() above.
    // dev.clear_screen();

    if !handler.external_pad_leds {
        for i in 0..16 {
            dev.set_pad_light(i, handler.pad_color(), PAD_RELEASED_BRIGHTNESS);
        }
    }

    ev_loop(&mut dev, &mut handler, &args[1]);
}


#[cfg(test)]
mod tests {
    use super::*;
    use crate::devices::mk2::BUTTON_REPORT_TO_MIKROBUTTONS_MAP;

    /// Report rows that `read_buttons` hands to `button_down` / `button_up`.
    ///
    /// Rows 8-23 of the same table are the ENCODER bytes: read_buttons sends
    /// those to `encoder_step` and `set_roller_state` and never to a button
    /// handler, so their names (B1..Q8) never reach the host at all. Walking
    /// them here is what found the eight dead match arms this file used to
    /// carry - and it is why the range stops at 8 rather than at the end.
    ///
    /// Row 7 IS a button row: A1..A8 is byte 7, the big encoder's nibble pair,
    /// which arrives as eight fake buttons and is decoded in "A8".
    const BUTTON_ROWS: usize = 8;

    /// Every button the DEVICE can actually send, taken from the report decode
    /// table rather than from a list written by hand - a fourth list would
    /// drift from the three that already exist.
    fn every_reachable_button() -> Vec<MaschineButton> {
        BUTTON_REPORT_TO_MIKROBUTTONS_MAP[..BUTTON_ROWS]
            .iter()
            .flatten()
            .filter_map(|b| *b)
            .collect()
    }

    #[test]
    fn every_reachable_button_has_a_name() {
        // `btn_to_osc_button_map` ends in `_ => "NO"`, so an unnamed button is
        // not a compile error: it silently becomes a button called NO, and
        // every one of them collides with all the others.
        for btn in every_reachable_button() {
            let name = btn_to_osc_button_map(btn);
            assert_ne!(name, "NO", "{:?} reaches the host as \"NO\"", btn);
        }
    }

    #[test]
    fn no_two_buttons_share_a_name() {
        // THIS IS THE FF7 DEFECT, kept executable. `MaschineButton::FF7`
        // answered to "FF8": two buttons on one token, the seventh
        // unreachable, and nothing could see it because both tables are
        // maintained by hand.
        let mut seen: Vec<(&str, MaschineButton)> = Vec::new();
        for btn in every_reachable_button() {
            let name = btn_to_osc_button_map(btn);
            if let Some((_, other)) = seen.iter().find(|(n, _)| *n == name) {
                panic!("{:?} and {:?} both answer to {:?}", btn, other, name);
            }
            seen.push((name, btn));
        }
    }

    #[test]
    fn the_named_buttons_round_trip() {
        // The reverse table is what the driver's LED writes go through, so a
        // name that does not come back to the same button is an LED that
        // lights the wrong thing - which has happened here twice.
        for btn in every_reachable_button() {
            let name = btn_to_osc_button_map(btn);
            if let Some(back) = osc_button_to_btn_map(name) {
                assert_eq!(
                    btn_to_osc_button_map(back), name,
                    "{:?} -> {:?} -> {:?}", btn, name, back);
            }
        }
    }

    #[test]
    fn the_encoder_arms_agree_with_the_shared_formula() {
        // Eight unreachable arms used to open-code `status / 4 + state * 64`
        // beside a tested function nothing called. One copy now, on the live
        // path, and this pins the two together.
        for raw in [0i32, 4, 100, 252] {
            for state in [0usize, 1, 3] {
                assert_eq!(cc_math::accumulate_raw(raw, state),
                           raw / 4 + state as i32 * 64);
            }
        }
    }
}
