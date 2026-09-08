//! When to retry a stalled input fd, and when to stop hammering it.
//!
//! THE THING TO UNDERSTAND FIRST: a reopen is the watchdog WORKING, not the
//! fault. A healthy rig reopens 1.6 to 2.2 times a minute at idle, measured
//! 2026-08-22, and 2.38/min over a whole 11 h 35 m boot on 2026-09-08. Every
//! one of those recovers. So the retry must stay immediate for an isolated
//! stall — slowing normal recovery down to fix a pathology would be a straight
//! regression.
//!
//! AND THE REOPEN IS WHAT ENDS THE DROPOUT, measured 2026-09-08 and not
//! assumed. With the window widened to 2,000 ms the stream stayed dead for the
//! full two seconds, six times out of six, while the daemon took 124-141 laps
//! of the event loop asking for it. At the shipped 50 ms the same dropout
//! measures 113-125 ms end to end. So every millisecond added to
//! `input_timeout` is a millisecond of dead panel: this is not a knob to
//! relax. `notes/findings/2026-09-08-item-79-stall-shape.md`
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
/// over. Idle reopens are 17 s apart at the median, p25 7 s and p75 35 s
/// (measured over 1,653 of them, 2026-09-08; this comment said "~30 s" and
/// that was the p75, not the middle). 5 s is longer than any recovering stall
/// and shorter than the median spacing, which is what it has to be.
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

/// What the event loop saw between the last serviced input report and now.
///
/// ITEM 79, 2026-09-08. The 50 ms `input_timeout` cannot on its own tell a
/// SILENT DEVICE from a DESCHEDULED DAEMON — `last_report` only moves when the
/// loop services `POLLIN`, so both look like "no report for 50 ms". A lap is
/// one trip round `ev_loop` and `poll()` waits at most 16 ms, so the two cases
/// have different shapes: a device that went quiet leaves three or four SHORT
/// laps inside the window, a lost CPU slice leaves ONE lap about as long as the
/// window itself. Recorded per stall and logged, so the distribution can be
/// read off the journal rather than argued about.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct StallWindow {
    /// Laps taken since input last flowed.
    pub laps: u64,
    /// The longest single lap in that run.
    pub longest_lap: Duration,
}

impl StallWindow {
    pub fn lap(&mut self, lap: Duration) {
        self.laps += 1;
        if lap > self.longest_lap {
            self.longest_lap = lap;
        }
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }
}

/// The distribution of gaps BETWEEN serviced input reports.
///
/// ITEM 79, 2026-09-08. `input_timeout` is 50 ms because a comment says the
/// device "streams ~750 reports/s unconditionally" — i.e. a report every
/// ~1.3 ms. That claim has never been measured, and the whole watchdog is
/// denominated in it: if the stream's normal jitter reaches tens of
/// milliseconds, then 50 ms is a hair-trigger and the reopen counter is mostly
/// counting normal behaviour.
///
/// Off unless `MASCHINE_INPUT_STATS` is set — a line a minute forever would be
/// noise in a 50 M tmpfs journal, and this is an instrument, not a feature.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct InputGaps {
    /// Gaps under 2, 8, 16, 32, 50, 100, 250, 1000 ms, then a second and over.
    /// The edges above 50 ms exist for the widened-window experiment: they are
    /// where a dropout's TRUE length shows up once the watchdog is not cutting
    /// every one of them short at ~60 ms.
    pub buckets: [u64; 9],
    pub max: Duration,
    pub reports: u64,
}

/// Upper edges of every bucket but the last, in ms.
pub const GAP_EDGES_MS: [u64; 8] = [2, 8, 16, 32, 50, 100, 250, 1000];

impl InputGaps {
    pub fn record(&mut self, gap: Duration) {
        self.reports += 1;
        if gap > self.max {
            self.max = gap;
        }
        let ms = gap.as_millis() as u64;
        let slot = GAP_EDGES_MS
            .iter()
            .position(|&edge| ms < edge)
            .unwrap_or(GAP_EDGES_MS.len());
        self.buckets[slot] += 1;
    }

    /// One journal line. Takes the window so reports/s is read, not computed
    /// from an assumed interval.
    pub fn line(&self, window: Duration) -> String {
        let secs = window.as_secs_f64().max(0.001);
        format!(
            "input: {} reports in {:.1}s ({:.0}/s), max gap {}ms, \
             <2ms {} <8ms {} <16ms {} <32ms {} <50ms {} <100ms {} <250ms {} <1s {} >=1s {}",
            self.reports,
            secs,
            self.reports as f64 / secs,
            self.max.as_millis(),
            self.buckets[0],
            self.buckets[1],
            self.buckets[2],
            self.buckets[3],
            self.buckets[4],
            self.buckets[5],
            self.buckets[6],
            self.buckets[7],
            self.buckets[8],
        )
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }
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
    fn a_silent_device_leaves_several_short_laps() {
        // poll() waits 16 ms, so a 50 ms window with the daemon scheduled
        // normally is three or four laps, none of them long.
        let mut w = StallWindow::default();
        for _ in 0..4 {
            w.lap(Duration::from_millis(16));
        }
        assert_eq!(w.laps, 4);
        assert_eq!(ms(w.longest_lap), 16);
    }

    #[test]
    fn a_descheduled_daemon_leaves_one_long_lap() {
        let mut w = StallWindow::default();
        w.lap(Duration::from_millis(63));
        assert_eq!(w.laps, 1);
        assert_eq!(ms(w.longest_lap), 63);
    }

    #[test]
    fn the_window_keeps_the_longest_lap_not_the_last() {
        let mut w = StallWindow::default();
        w.lap(Duration::from_millis(16));
        w.lap(Duration::from_millis(120));
        w.lap(Duration::from_millis(16));
        assert_eq!(ms(w.longest_lap), 120);
    }

    #[test]
    fn a_serviced_report_clears_the_window() {
        let mut w = StallWindow::default();
        w.lap(Duration::from_millis(120));
        w.reset();
        assert_eq!(w, StallWindow::default());
        assert_eq!(w.laps, 0);
        assert_eq!(ms(w.longest_lap), 0);
    }

    #[test]
    fn a_gap_lands_in_the_bucket_below_its_edge() {
        let mut g = InputGaps::default();
        for ms in [0u64, 1, 2, 7, 8, 15, 16, 31, 32, 49, 50, 99, 100, 249, 250, 999, 1000, 4000] {
            g.record(Duration::from_millis(ms));
        }
        // two per bucket, by construction
        assert_eq!(g.buckets, [2, 2, 2, 2, 2, 2, 2, 2, 2]);
        assert_eq!(g.reports, 18);
        assert_eq!(ms(g.max), 4000);
    }

    #[test]
    fn a_gap_of_exactly_an_edge_goes_up_not_down() {
        // The 50 ms bucket must mean "the watchdog would have fired", so the
        // boundary belongs to the upper bucket or the counter flatters itself.
        let mut g = InputGaps::default();
        g.record(Duration::from_millis(50));
        assert_eq!(g.buckets[5], 1);
        assert_eq!(g.buckets[4], 0);
        assert_eq!(g.buckets.len(), GAP_EDGES_MS.len() + 1);
    }

    #[test]
    fn sub_millisecond_gaps_are_the_healthy_case() {
        // ~750 reports/s is a report every 1.3 ms.
        let mut g = InputGaps::default();
        for _ in 0..750 {
            g.record(Duration::from_micros(1333));
        }
        assert_eq!(g.buckets[0], 750);
        let line = g.line(Duration::from_secs(1));
        assert!(line.contains("750 reports"), "{}", line);
        assert!(line.contains("750/s"), "{}", line);
    }

    #[test]
    fn the_line_survives_a_zero_length_window() {
        // Division by the window, so the degenerate case must not produce inf.
        let line = InputGaps::default().line(Duration::from_millis(0));
        assert!(!line.contains("inf"), "{}", line);
    }

    #[test]
    fn a_reset_clears_the_max_as_well_as_the_counts() {
        let mut g = InputGaps::default();
        g.record(Duration::from_millis(900));
        g.reset();
        assert_eq!(g, InputGaps::default());
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
