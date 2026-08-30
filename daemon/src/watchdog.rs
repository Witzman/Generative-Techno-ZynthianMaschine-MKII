//! When to retry a stalled input fd, and when to stop hammering it.
//!
//! THE THING TO UNDERSTAND FIRST: a reopen is the watchdog WORKING, not the
//! fault. A healthy rig reopens 1.6 to 2.2 times a minute at idle, measured
//! 2026-08-22, and every one of those recovers. So the retry must stay
//! immediate for an isolated stall — slowing normal recovery down to fix a
//! pathology would be a straight regression.
//!
//! What was wrong is the STORM. The watchdog reset its timer whether the reopen
//! succeeded or failed, with no backoff, no cap and no give-up, so a wedged
//! endpoint was retried every 50 ms forever — 4,465 reopens in 36 minutes on
//! 2026-08-30. usbhid's own recovery ladder (13/73/413 ms, then clear-halt,
//! then hid_reset) needs quiet endpoint time that a 50 ms hammer never leaves
//! it, and this is the only hypothesis that explains a FRESHLY RESTARTED daemon
//! re-wedging within seconds.
//!
//! The backoff therefore starts only after a run of consecutive reopens, and it
//! is announced in the log: `journalctl | grep -c reopened` is this project's
//! primary diagnostic and the whole 2026-08-22 write-budget curve is
//! denominated in reopens per minute, so a silent backoff would quietly change
//! what that number means. Every attempt is still logged; the backoff says so
//! in its own line.

use std::time::Duration;

/// Reopens allowed at full speed before any backoff. An isolated stall — the
/// common, recovering case — never reaches the backoff at all.
pub const IMMEDIATE_REOPENS: u64 = 3;

/// The first backoff step, doubling from there.
pub const BACKOFF_BASE_MS: u64 = 50;

/// The longest the watchdog will ever wait between attempts. Long enough to let
/// usbhid's ladder run, short enough that a device coming back is picked up
/// within a couple of seconds.
pub const BACKOFF_CAP_MS: u64 = 2000;

/// Input must flow this long without a reopen before a storm is considered
/// over. Comfortably longer than the ~30 s that separates idle reopens on a
/// healthy rig would be too slow to reset; 5 s is longer than any recovering
/// stall and shorter than the idle spacing.
pub const STORM_RESET: Duration = Duration::from_secs(5);

/// How long to wait before the next reopen, given how many consecutive reopens
/// have already happened in this storm.
pub fn reopen_delay(prior_reopens: u64) -> Duration {
    if prior_reopens < IMMEDIATE_REOPENS {
        return Duration::from_millis(0);
    }
    let steps = prior_reopens - IMMEDIATE_REOPENS;
    // Saturating rather than shifting: a storm that ran for hours must not
    // overflow into a tiny delay.
    let ms = BACKOFF_BASE_MS
        .checked_shl(steps.min(u32::MAX as u64) as u32)
        .unwrap_or(BACKOFF_CAP_MS)
        .min(BACKOFF_CAP_MS);
    Duration::from_millis(ms)
}

/// True once input has flowed long enough to call the storm over.
pub fn storm_is_over(since_last_reopen: Duration) -> bool {
    since_last_reopen >= STORM_RESET
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(d: Duration) -> u64 {
        d.as_millis() as u64
    }

    #[test]
    fn an_isolated_stall_retries_immediately() {
        // The case that must not regress: a healthy rig does this ~2x a minute
        // and recovers every time.
        assert_eq!(ms(reopen_delay(0)), 0);
        assert_eq!(ms(reopen_delay(1)), 0);
        assert_eq!(ms(reopen_delay(2)), 0);
    }

    #[test]
    fn backoff_starts_only_after_the_immediate_run() {
        assert_eq!(ms(reopen_delay(IMMEDIATE_REOPENS - 1)), 0);
        assert_eq!(ms(reopen_delay(IMMEDIATE_REOPENS)), BACKOFF_BASE_MS);
    }

    #[test]
    fn it_doubles() {
        assert_eq!(ms(reopen_delay(3)), 50);
        assert_eq!(ms(reopen_delay(4)), 100);
        assert_eq!(ms(reopen_delay(5)), 200);
        assert_eq!(ms(reopen_delay(6)), 400);
        assert_eq!(ms(reopen_delay(7)), 800);
        assert_eq!(ms(reopen_delay(8)), 1600);
    }

    #[test]
    fn it_caps() {
        assert_eq!(ms(reopen_delay(9)), BACKOFF_CAP_MS);
        assert_eq!(ms(reopen_delay(20)), BACKOFF_CAP_MS);
    }

    #[test]
    fn a_storm_running_for_hours_does_not_wrap_to_a_tiny_delay() {
        // The shift would overflow long before this. A storm that quietly
        // resumed hammering after an hour would be the worst possible bug in
        // a piece of code whose entire job is to stop hammering.
        for n in [64u64, 65, 100, 1_000, u64::MAX / 2, u64::MAX] {
            assert_eq!(ms(reopen_delay(n)), BACKOFF_CAP_MS, "prior={}", n);
        }
    }

    #[test]
    fn the_delay_never_decreases() {
        let mut last = 0;
        for n in 0..64 {
            let d = ms(reopen_delay(n));
            assert!(d >= last, "delay went down at {}: {} < {}", n, d, last);
            last = d;
        }
    }

    #[test]
    fn the_delay_never_exceeds_the_cap() {
        for n in 0..2000 {
            assert!(ms(reopen_delay(n)) <= BACKOFF_CAP_MS);
        }
    }

    #[test]
    fn a_wedged_endpoint_is_retried_far_less_than_before() {
        // The point of the whole exercise. The old watchdog retried every
        // 50 ms without end: 60 seconds of a storm was ~1,200 attempts.
        let mut elapsed = Duration::from_millis(0);
        let minute = Duration::from_secs(60);
        let mut attempts = 0u64;
        while elapsed < minute {
            elapsed += reopen_delay(attempts) + Duration::from_millis(50);
            attempts += 1;
        }
        assert!(attempts < 100, "still hammering: {} attempts a minute", attempts);
        assert!(attempts > 20, "backed off so far the device could not come back");
    }

    #[test]
    fn a_storm_is_over_after_the_reset_window() {
        assert!(!storm_is_over(Duration::from_millis(0)));
        assert!(!storm_is_over(STORM_RESET - Duration::from_millis(1)));
        assert!(storm_is_over(STORM_RESET));
        assert!(storm_is_over(Duration::from_secs(60)));
    }

    #[test]
    fn the_reset_window_is_longer_than_any_recovering_stall() {
        // A healthy rig's reopens are ~30 s apart, so they must each be seen as
        // isolated rather than accumulating into a phantom storm.
        assert!(STORM_RESET < Duration::from_secs(30));
        assert!(STORM_RESET >= Duration::from_secs(1));
    }
}
