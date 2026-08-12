use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ClockSource {
    Internal,
    External,
}

pub struct ClockState {
    pub source: ClockSource,
    pub playing: bool,
    pub tick_counter: u8,
    pub step: usize,
    pub last_external_tick: Option<Instant>,
    prev_tick: Option<Instant>,
}

impl ClockState {
    pub fn new() -> Self {
        ClockState {
            source: ClockSource::Internal,
            playing: false,
            tick_counter: 0,
            step: 0,
            last_external_tick: None,
            prev_tick: None,
        }
    }

    pub fn on_clock_tick(&mut self, now: Instant) -> Option<usize> {
        self.prev_tick = self.last_external_tick;
        self.last_external_tick = Some(now);
        self.source = ClockSource::External;

        if !self.playing {
            return None;
        }

        self.tick_counter += 1;
        if self.tick_counter >= 6 {
            self.tick_counter = 0;
            let advanced_step = self.step;
            self.step = (self.step + 1) % 16;
            return Some(advanced_step);
        }
        None
    }

    pub fn on_start(&mut self) {
        self.tick_counter = 0;
        self.step = 0;
        self.playing = true;
        self.source = ClockSource::External;
    }

    pub fn on_stop(&mut self) {
        self.playing = false;
    }

    pub fn bpm_from_tick_interval(interval: Duration) -> f32 {
        let micros = interval.as_micros() as f32;
        if micros == 0.0 {
            return 0.0;
        }
        60_000_000.0 / (micros * 24.0)
    }

    pub fn estimated_bpm(&self) -> Option<f32> {
        match (self.prev_tick, self.last_external_tick) {
            (Some(prev), Some(last)) => {
                let interval = last.duration_since(prev);
                Some(Self::bpm_from_tick_interval(interval))
            }
            _ => None,
        }
    }

    pub fn should_fallback_to_internal(&self, timeout: Duration) -> bool {
        if self.source != ClockSource::External || !self.playing {
            return false;
        }
        match self.last_external_tick {
            None => true,
            Some(t) => t.elapsed() > timeout,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    #[test]
    fn new_state_is_internal_and_stopped() {
        let s = ClockState::new();
        assert!(matches!(s.source, ClockSource::Internal));
        assert!(!s.playing);
        assert_eq!(s.tick_counter, 0);
        assert_eq!(s.step, 0);
    }

    #[test]
    fn six_ticks_advance_one_step() {
        let mut s = ClockState::new();
        s.playing = true;
        s.source = ClockSource::External;
        let base = Instant::now();
        for _ in 0..6 {
            s.on_clock_tick(base);
        }
        assert_eq!(s.step, 1);
        assert_eq!(s.tick_counter, 0);
    }

    #[test]
    fn five_ticks_do_not_advance() {
        let mut s = ClockState::new();
        s.playing = true;
        s.source = ClockSource::External;
        let base = Instant::now();
        for _ in 0..5 {
            s.on_clock_tick(base);
        }
        assert_eq!(s.step, 0);
        assert_eq!(s.tick_counter, 5);
    }

    #[test]
    fn step_wraps_at_16() {
        let mut s = ClockState::new();
        s.playing = true;
        s.source = ClockSource::External;
        let base = Instant::now();
        for _ in 0..(16 * 6) {
            s.on_clock_tick(base);
        }
        assert_eq!(s.step, 0);
    }

    #[test]
    fn on_start_resets_counter_and_step() {
        let mut s = ClockState::new();
        s.tick_counter = 4;
        s.step = 7;
        s.on_start();
        assert_eq!(s.tick_counter, 0);
        assert_eq!(s.step, 0);
        assert!(s.playing);
        assert!(matches!(s.source, ClockSource::External));
    }

    #[test]
    fn on_stop_stops_playing_keeps_position() {
        let mut s = ClockState::new();
        s.playing = true;
        s.step = 5;
        s.on_stop();
        assert!(!s.playing);
        assert_eq!(s.step, 5);
    }

    #[test]
    fn bpm_from_tick_interval_120bpm() {
        let interval = Duration::from_micros(20_833);
        let bpm = ClockState::bpm_from_tick_interval(interval);
        assert!((bpm - 120.0).abs() < 0.5, "got {}", bpm);
    }

    #[test]
    fn fallback_timeout_triggers_when_no_ticks() {
        let mut s = ClockState::new();
        s.playing = true;
        s.source = ClockSource::External;
        s.last_external_tick = Some(Instant::now() - Duration::from_millis(600));
        assert!(s.should_fallback_to_internal(Duration::from_millis(500)));
    }

    #[test]
    fn no_fallback_when_ticks_are_recent() {
        let mut s = ClockState::new();
        s.playing = true;
        s.source = ClockSource::External;
        s.last_external_tick = Some(Instant::now() - Duration::from_millis(100));
        assert!(!s.should_fallback_to_internal(Duration::from_millis(500)));
    }
}
