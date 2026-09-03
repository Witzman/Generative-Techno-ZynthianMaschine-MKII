//! HID *feature* reports — a mechanism this daemon did not have.
//!
//! Every other HID write in this daemon is `write(2)` on the hidraw fd, which
//! sends an OUTPUT report. The MK2's two screen-configuration reports, `0xF8`
//! and `0xF9`, are FEATURE reports, and those are only reachable through the
//! `HIDIOCGFEATURE` / `HIDIOCSFEATURE` ioctls. So this is a new mechanism, not
//! a new call site on the old one.
//!
//! ## Why this file is so careful
//!
//! The device's own report descriptor (vendored, read 2026-08-30) declares
//! every item in these reports **Non-volatile**. In HID that means a written
//! value survives a power cycle: a bad write does NOT clear itself by
//! unplugging the controller, and this is a device whose one known failure mode
//! already needs a physical replug. Dark screens explain nothing, and this
//! instrument's one law is that a silent channel must say why.
//!
//! Three rules follow, and they are enforced below rather than remembered:
//!
//! 1. **A SET sends the WHOLE report.** Seven of the eleven bytes are declared
//!    `Feature (Const, ...)` and six of them are non-zero on this hardware
//!    (`00 01 40 00 01 01`). They must be read back with a GET and echoed
//!    byte-for-byte. `patch()` copies the report it was handed and overwrites
//!    exactly two bytes.
//! 2. **Byte 10's eight flag bits are unidentified and are never touched.**
//!    They ride along in the echo like the constants do.
//! 3. **0 is refused.** `Logical Maximum (100)` bounds the top; the floor here
//!    is ours, because a non-volatile brightness of 0 is an unreadable panel
//!    that stays unreadable through a reboot.
//!
//! ## The report, measured
//!
//! Read over SSH on 2026-08-31 alongside the running daemon, with the health
//! baseline unchanged afterwards — so GET is measured safe, not inferred safe:
//!
//! ```text
//! 0xF8   f8 00 01 40 00 01 01 00 48 32 00
//! 0xF9   f9 00 01 40 00 01 01 00 48 32 00
//!         ^id ^--- const 1..7 ---^ ^b ^c ^flags
//! ```
//!
//! Bytes 1-2 little-endian are `0x0100` = 256 and bytes 3-4 are `0x0040` = 64 —
//! **exactly this panel's geometry** (`display::STRIDE * 8` bits per row, and
//! `display::HEIGHT`). A report carrying the panel's width and height as
//! device-declared constants, followed by two writable 0..100 values, is the
//! display configuration block for that screen. That is what `looks_like_screen_report`
//! checks, and it is the gate the SET path will not write past.
//!
//! Bytes 8 and 9 read 72 and 50 on both screens, untouched from the factory.
//! Which of the two is brightness and which is contrast is still UNKNOWN —
//! the descriptor lists the usages out of order (`0xE7` before `0xE6`) and only
//! a write settles it. `BRIGHTNESS_BYTE`/`CONTRAST_BYTE` therefore record an
//! assumption, and the recovery values are identical for both so a wrong guess
//! costs nothing to undo.

use std::io;
use std::os::raw::{c_int, c_ulong, c_void};
use std::os::unix::io::RawFd;

// ---------------------------------------------------------------- the ioctls
//
// Transcribed from the kernel's include/linux/hidraw.h:
//
//   #define HIDIOCGFEATURE(len) _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, len)
//   #define HIDIOCSFEATURE(len) _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
//
// Both directions are WRITE|READ: even the GET writes the report id into the
// buffer first. The same arithmetic already runs in Python in this project's
// capture tool and has been used against this device, so these are a
// transcription of a working ioctl rather than a derivation.
const IOC_WRITE: u32 = 1;
const IOC_READ: u32 = 2;

/// `_IOC(dir, type, nr, size)` for the Linux "asm-generic" encoding, which is
/// what aarch64 and x86_64 both use.
pub fn ioc(dir: u32, letter: u8, number: u8, size: usize) -> u32 {
    (dir << 30) | ((size as u32) << 16) | ((letter as u32) << 8) | (number as u32)
}

pub fn hidiocgfeature(len: usize) -> u32 {
    ioc(IOC_WRITE | IOC_READ, b'H', 0x07, len)
}

pub fn hidiocsfeature(len: usize) -> u32 {
    ioc(IOC_WRITE | IOC_READ, b'H', 0x06, len)
}

extern "C" {
    // Declared variadic exactly as libc does. Adding libc as a direct
    // dependency would churn Cargo.lock for one symbol that std already names
    // the types for; `--offline` builds on the Pi are worth more than that.
    fn ioctl(fd: c_int, request: c_ulong, ...) -> c_int;
}

/// Read a feature report. Writes nothing to the device.
///
/// `buf[0]` must already hold the report id — the ioctl uses it to choose the
/// report, which is why the "get" is declared WRITE|READ.
pub fn get_feature(fd: RawFd, buf: &mut [u8]) -> io::Result<usize> {
    let req = hidiocgfeature(buf.len()) as c_ulong;
    let rc = unsafe { ioctl(fd, req, buf.as_mut_ptr() as *mut c_void) };
    if rc < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(rc as usize)
    }
}

/// Write a feature report. **Non-volatile on this device.** Never call this
/// with a buffer that did not come from `patch()`.
pub fn set_feature(fd: RawFd, buf: &[u8]) -> io::Result<usize> {
    let req = hidiocsfeature(buf.len()) as c_ulong;
    let rc = unsafe { ioctl(fd, req, buf.as_ptr() as *const c_void) };
    if rc < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(rc as usize)
    }
}

// ------------------------------------------------- the screen setting report

/// Report ids: index 0 is the LEFT screen, matching display report `0xE0`.
pub const SCREEN_REPORT_IDS: [u8; 2] = [0xF8, 0xF9];

/// Report id plus ten payload bytes.
pub const SCREEN_REPORT_LEN: usize = 11;

/// Byte 8, usage `0xE7`. Assumed brightness — see the module docstring.
pub const BRIGHTNESS_BYTE: usize = 8;
/// Byte 9, usage `0xE6`. Assumed contrast.
pub const CONTRAST_BYTE: usize = 9;
/// Byte 10, usage `0xE8`: eight writable bits nobody has identified. Echoed,
/// never authored.
/// The eight unidentified flag bits, echoed back untouched by `patch()`.
/// Named and asserted by the tests rather than read by the writer, so that a
/// change to `patch()` which stopped echoing them fails the build.
#[allow(dead_code)]
pub const FLAGS_BYTE: usize = 10;

/// `Logical Maximum (100)` straight off the descriptor.
pub const MAX_SETTING: u8 = 100;
/// Ours, not the device's. A non-volatile 0 is a panel that is dark now and
/// still dark after a power cycle.
pub const MIN_SETTING: u8 = 1;

/// What both screens read from the factory, measured 2026-08-31. These are the
/// recovery values: put them in `maschine.json` and restart the daemon.
pub const FACTORY_BRIGHTNESS: u8 = 72;
pub const FACTORY_CONTRAST: u8 = 50;

/// The two 16-bit constants at bytes 1-4, little-endian: the panel geometry.
pub const DECLARED_WIDTH: u16 = 256;
pub const DECLARED_HEIGHT: u16 = 64;

/// Clamp a requested value into the range the device declares, with our own
/// non-zero floor. Nothing else may produce a byte for `BRIGHTNESS_BYTE` or
/// `CONTRAST_BYTE`.
pub fn clamp_setting(v: u8) -> u8 {
    v.clamp(MIN_SETTING, MAX_SETTING)
}

/// Is this really a screen-configuration report for `id`?
///
/// The identification is otherwise circumstantial — the descriptor never says
/// "brightness" anywhere. What makes it strong is that bytes 1-4 carry this
/// panel's own width and height. If they do not, we are looking at something
/// else and **must not write to it.**
pub fn looks_like_screen_report(id: u8, buf: &[u8]) -> bool {
    if buf.len() != SCREEN_REPORT_LEN || buf[0] != id {
        return false;
    }
    let w = u16::from_le_bytes([buf[1], buf[2]]);
    let h = u16::from_le_bytes([buf[3], buf[4]]);
    w == DECLARED_WIDTH && h == DECLARED_HEIGHT
}

/// Build the report to SET from the report just read back.
///
/// Everything is echoed — the id, the seven constant bytes, the eight unknown
/// flag bits — and exactly two bytes are authored. This is the whole safety
/// argument for the write, so it is one function with no other callers'
/// discretion in it.
pub fn patch(current: &[u8; SCREEN_REPORT_LEN], brightness: u8, contrast: u8) -> [u8; SCREEN_REPORT_LEN] {
    let mut out = *current;
    out[BRIGHTNESS_BYTE] = clamp_setting(brightness);
    out[CONTRAST_BYTE] = clamp_setting(contrast);
    out
}

/// Does the device already hold these values?
///
/// A SET that changes nothing still burns a non-volatile write cycle on every
/// boot, so a rig running the shipped defaults must issue no write at all.
/// This is also what makes the feature invisible on an unchanged rig.
pub fn already_set(current: &[u8; SCREEN_REPORT_LEN], brightness: u8, contrast: u8) -> bool {
    current[BRIGHTNESS_BYTE] == clamp_setting(brightness)
        && current[CONTRAST_BYTE] == clamp_setting(contrast)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The measured report, both screens, 2026-08-31.
    const MEASURED: [u8; SCREEN_REPORT_LEN] =
        [0xF8, 0x00, 0x01, 0x40, 0x00, 0x01, 0x01, 0x00, 0x48, 0x32, 0x00];

    #[test]
    fn hidiocgfeature_matches_the_kernel_macro() {
        // _IOC(3, 'H', 0x07, 11) = (3<<30)|(11<<16)|(0x48<<8)|0x07
        assert_eq!(hidiocgfeature(11), 0xC00B_4807);
    }

    #[test]
    fn hidiocsfeature_matches_the_kernel_macro() {
        assert_eq!(hidiocsfeature(11), 0xC00B_4806);
    }

    #[test]
    fn get_and_set_differ_only_in_the_command_number() {
        // 0x06 vs 0x07. Swapping them would turn every read into a blind
        // write of whatever happened to be in the buffer.
        assert_eq!(hidiocgfeature(11) ^ hidiocsfeature(11), 1);
    }

    #[test]
    fn the_measured_report_is_recognised() {
        assert!(looks_like_screen_report(0xF8, &MEASURED));
    }

    #[test]
    fn the_geometry_constants_are_this_panel() {
        // Bytes 1-2 = 256 bits per transferred row, which is STRIDE * 8.
        // Bytes 3-4 = 64 rows, which is display::HEIGHT.
        assert_eq!(DECLARED_WIDTH as usize, crate::display::STRIDE * 8);
        assert_eq!(DECLARED_HEIGHT as usize, crate::display::HEIGHT);
    }

    #[test]
    fn a_report_with_the_wrong_id_is_refused() {
        assert!(!looks_like_screen_report(0xF9, &MEASURED));
    }

    #[test]
    fn a_report_of_the_wrong_length_is_refused() {
        assert!(!looks_like_screen_report(0xF8, &MEASURED[..10]));
    }

    #[test]
    fn a_report_that_does_not_carry_the_panel_geometry_is_refused() {
        // An all-zero read - what a failed ioctl leaves behind - must never
        // be mistaken for a report worth echoing.
        let mut zeroed = [0u8; SCREEN_REPORT_LEN];
        zeroed[0] = 0xF8;
        assert!(!looks_like_screen_report(0xF8, &zeroed));
    }

    #[test]
    fn patch_echoes_every_constant_byte() {
        let out = patch(&MEASURED, 90, 40);
        for i in 0..=7 {
            assert_eq!(out[i], MEASURED[i], "constant byte {} was not echoed", i);
        }
    }

    #[test]
    fn patch_never_touches_the_unidentified_flag_bits() {
        let mut with_flags = MEASURED;
        with_flags[FLAGS_BYTE] = 0b1010_0101;
        let out = patch(&with_flags, 10, 20);
        assert_eq!(out[FLAGS_BYTE], 0b1010_0101);
    }

    #[test]
    fn patch_writes_the_two_settings() {
        let out = patch(&MEASURED, 90, 40);
        assert_eq!(out[BRIGHTNESS_BYTE], 90);
        assert_eq!(out[CONTRAST_BYTE], 40);
    }

    #[test]
    fn patch_refuses_zero() {
        // The whole point: a non-volatile 0 is a dark panel that a power
        // cycle does not fix.
        let out = patch(&MEASURED, 0, 0);
        assert_eq!(out[BRIGHTNESS_BYTE], MIN_SETTING);
        assert_eq!(out[CONTRAST_BYTE], MIN_SETTING);
        assert!(MIN_SETTING > 0);
    }

    #[test]
    fn patch_clamps_above_the_declared_maximum() {
        let out = patch(&MEASURED, 255, 200);
        assert_eq!(out[BRIGHTNESS_BYTE], MAX_SETTING);
        assert_eq!(out[CONTRAST_BYTE], MAX_SETTING);
    }

    #[test]
    fn writing_the_factory_values_back_is_the_identity() {
        // Step 2 of the design's method: write the values back unchanged. If
        // this ever stops being byte-identical the echo is broken.
        let out = patch(&MEASURED, FACTORY_BRIGHTNESS, FACTORY_CONTRAST);
        assert_eq!(out, MEASURED);
    }

    #[test]
    fn the_factory_values_are_what_was_measured() {
        assert_eq!(MEASURED[BRIGHTNESS_BYTE], FACTORY_BRIGHTNESS);
        assert_eq!(MEASURED[CONTRAST_BYTE], FACTORY_CONTRAST);
    }

    #[test]
    fn a_rig_already_at_the_requested_values_needs_no_write() {
        assert!(already_set(&MEASURED, FACTORY_BRIGHTNESS, FACTORY_CONTRAST));
    }

    #[test]
    fn a_changed_value_does_need_a_write() {
        assert!(!already_set(&MEASURED, 90, FACTORY_CONTRAST));
        assert!(!already_set(&MEASURED, FACTORY_BRIGHTNESS, 40));
    }

    #[test]
    fn already_set_compares_against_the_clamped_value() {
        // Asking for 0 on a rig at 1 must not loop: the clamp happens before
        // the comparison, so the write is skipped rather than re-issued.
        let mut at_floor = MEASURED;
        at_floor[BRIGHTNESS_BYTE] = MIN_SETTING;
        at_floor[CONTRAST_BYTE] = MIN_SETTING;
        assert!(already_set(&at_floor, 0, 0));
    }
}
