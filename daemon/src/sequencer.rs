pub fn euclidean_pattern(steps: usize, hits: usize) -> [bool; 16] {
    let mut pattern = [false; 16];
    let steps = steps.min(16);
    let hits = hits.min(steps);
    if hits == 0 { return pattern; }
    // Bresenham-style: place hit i at floor(i * steps / hits)
    for i in 0..hits {
        let pos = (i * steps) / hits;
        pattern[pos] = true;
    }
    pattern
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_hits_returns_all_false() {
        let p = euclidean_pattern(16, 0);
        assert!(p.iter().all(|&x| !x));
    }

    #[test]
    fn all_hits_returns_all_true() {
        let p = euclidean_pattern(16, 16);
        assert!(p.iter().all(|&x| x));
    }

    #[test]
    fn four_hits_evenly_spaced() {
        let p = euclidean_pattern(16, 4);
        assert_eq!(p[0], true);
        assert_eq!(p[4], true);
        assert_eq!(p[8], true);
        assert_eq!(p[12], true);
        assert_eq!(p.iter().filter(|&&x| x).count(), 4);
    }

    #[test]
    fn one_hit_lands_at_zero() {
        let p = euclidean_pattern(16, 1);
        assert_eq!(p[0], true);
        assert_eq!(p.iter().filter(|&&x| x).count(), 1);
    }

    #[test]
    fn hits_clamped_to_steps() {
        let p = euclidean_pattern(16, 20);
        assert_eq!(p.iter().filter(|&&x| x).count(), 16);
    }
}
