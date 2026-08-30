//! Counting HID writes, because until 2026-08-30 nothing did.
//!
//! Every one of the daemon's five HID write sites was `let _ =
//! unistd::write(...)`. No error was checked, no short write was noticed, and
//! there was no counter anywhere — so every investigation of the wedge that has
//! cost this project several sessions was blind to whether writes were even
//! succeeding.
//!
//! The syscall itself cannot be unit tested here. What CAN be tested is the
//! classification and the log rate-limit, and those are the parts with the
//! decisions in them — so they live here as pure functions and the caller stays
//! a thin wrapper.

/// What one write actually did.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WriteOutcome {
    Ok,
    /// The kernel accepted fewer bytes than the report contains. On an
    /// interrupt endpoint this means a TRUNCATED report reached the device,
    /// which is worse than an outright failure: the device acts on a partial
    /// report and nothing upstream knows.
    Short(usize),
    Failed,
}

/// `written` is None when the syscall returned an error.
pub fn classify(written: Option<usize>, len: usize) -> WriteOutcome {
    match written {
        None => WriteOutcome::Failed,
        Some(n) if n == len => WriteOutcome::Ok,
        Some(n) => WriteOutcome::Short(n),
    }
}

#[derive(Debug, Default, Clone, Copy)]
pub struct WriteStats {
    pub ok: u64,
    pub short: u64,
    pub failed: u64,
}

impl WriteStats {
    /// Record an outcome and say whether the caller should log it.
    ///
    /// A wedged endpoint can fail every write many times a second, and a log
    /// line per failure is itself a load on the machine we are trying to
    /// diagnose. The first three of each kind are logged so the onset is never
    /// missed, then every hundredth so a sustained fault stays visible without
    /// flooding.
    pub fn record(&mut self, outcome: WriteOutcome) -> bool {
        let count = match outcome {
            WriteOutcome::Ok => {
                self.ok += 1;
                return false;
            }
            WriteOutcome::Short(_) => {
                self.short += 1;
                self.short
            }
            WriteOutcome::Failed => {
                self.failed += 1;
                self.failed
            }
        };
        should_log(count)
    }

    pub fn bad(&self) -> u64 {
        self.short + self.failed
    }
}

pub fn should_log(count: u64) -> bool {
    count <= 3 || count % 100 == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_full_write_is_ok() {
        assert_eq!(classify(Some(265), 265), WriteOutcome::Ok);
    }

    #[test]
    fn a_partial_write_is_short_and_says_how_short() {
        assert_eq!(classify(Some(64), 265), WriteOutcome::Short(64));
    }

    #[test]
    fn a_zero_length_write_is_short_not_ok() {
        // The kernel accepting nothing is not success, and it is exactly what a
        // starved endpoint would look like.
        assert_eq!(classify(Some(0), 265), WriteOutcome::Short(0));
    }

    #[test]
    fn an_error_is_failed() {
        assert_eq!(classify(None, 265), WriteOutcome::Failed);
    }

    #[test]
    fn stats_start_at_zero_and_ok_writes_are_never_logged() {
        let mut s = WriteStats::default();
        for _ in 0..1000 {
            assert!(!s.record(WriteOutcome::Ok));
        }
        assert_eq!(s.ok, 1000);
        assert_eq!(s.bad(), 0);
    }

    #[test]
    fn the_first_three_failures_are_logged() {
        let mut s = WriteStats::default();
        assert!(s.record(WriteOutcome::Failed));
        assert!(s.record(WriteOutcome::Failed));
        assert!(s.record(WriteOutcome::Failed));
        assert!(!s.record(WriteOutcome::Failed));
    }

    #[test]
    fn a_sustained_failure_still_reports_every_hundredth() {
        let mut s = WriteStats::default();
        let logged = (1..=300).filter(|_| s.record(WriteOutcome::Failed)).count();
        // 3 at the onset, then 100, 200 and 300.
        assert_eq!(logged, 6);
        assert_eq!(s.failed, 300);
    }

    #[test]
    fn short_and_failed_are_counted_separately() {
        let mut s = WriteStats::default();
        s.record(WriteOutcome::Short(64));
        s.record(WriteOutcome::Failed);
        assert_eq!(s.short, 1);
        assert_eq!(s.failed, 1);
        assert_eq!(s.bad(), 2);
    }

    #[test]
    fn the_two_kinds_rate_limit_independently() {
        // A flood of one must not hide the onset of the other.
        let mut s = WriteStats::default();
        for _ in 0..50 {
            s.record(WriteOutcome::Failed);
        }
        assert!(s.record(WriteOutcome::Short(0)));
    }

    #[test]
    fn should_log_boundaries() {
        assert!(should_log(1));
        assert!(should_log(3));
        assert!(!should_log(4));
        assert!(!should_log(99));
        assert!(should_log(100));
        assert!(!should_log(101));
    }
}
