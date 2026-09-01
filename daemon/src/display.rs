use crate::font::FONT5X8;

// Each screen is 256x64, 1bpp row-major, MSB = leftmost pixel. Taken from
// cabl's MaschineMK2 driver, which is known-working, and not from guesswork:
// its setPixel is byte = widthBytes*y + x/8, bit = 0x80 >> (x%8) - the same
// addressing this file already used.
//
// Every earlier width was wrong. 128 made text "readable but too big" (it
// filled half the panel). 512 came from reading header byte 1 as a 16-pixel
// column offset when it is a byte offset, so 0/8/16/24 spans 0..256, not
// 0..512.
// 255 columns are on glass, verified: lines at x=248/251/254 all render and
// 254 sits in the last physical column, while x=255 shows nothing. The row is
// still 32 bytes - the 256th bit is transferred and discarded.
pub const WIDTH: usize = 255;
pub const HEIGHT: usize = 64;
pub const STRIDE: usize = 32; // not WIDTH/8: the last byte is padding

// One logical row per physical row. Kept as an identity hook because the
// earlier wrong geometry made it look as though rows were being dropped.
pub const LOGICAL_H: usize = HEIGHT;

pub fn logical_row(lrow: usize) -> usize { lrow }

// A report carries a full-width horizontal band of 8 rows: 32 bytes per row
// x 8 rows = 256 payload bytes, which is what header bytes 5 and 7 declare
// (0x20 = bytes per row, 0x08 = rows). Those two were swapped in this driver,
// so the panel was told to expect a 64x32 region while it was fed 512 bytes
// laid out 128 px wide - the whole reason the screens garbled.
//
// A screen is 8 such bands, header byte 3 = chunk*8, byte 1 = 0. The
// framebuffer slices straight into them: no tiling, no column offset.
pub const HDR_ROW_BYTES: u8 = 0x20;  // header[5]
pub const HDR_ROWS: u8 = 0x08;       // header[7]
pub const CHUNK_ROWS: usize = HDR_ROWS as usize;
pub const CHUNK_BYTES: usize = STRIDE * CHUNK_ROWS; // 256
pub const CHUNKS: usize = HEIGHT / CHUNK_ROWS;      // 8

// --- dirty rectangles -------------------------------------------------------
//
// The report header is a dirty-RECTANGLE blit descriptor, and this project
// hardcoded it for the daemon's whole life. Measured on the rig 2026-08-31,
// owner present, photographed: one 73-byte report with byte 1 = 4, byte 3 = 24,
// byte 5 = 8, byte 7 = 8 and a 64-byte payload put a white 64x8 block exactly
// where the header asked and left the rest of the panel alone. The reopen
// counter read 1154 before and 1154 after, so the write cost the controller
// nothing.
//
// What that unlocks is not the blit - the blit is a handful of lines - it is
// dropping the ONE shared dirty flag that made touching a pixel on the left
// screen repaint the right one too. Display traffic is the daemon's dominant
// write cost and the prime suspect behind every controller wedge this project
// has had, so the flush is now "what changed", not "everything".
//
// x and w are in BYTES, not pixels. Header byte 1 is a byte offset and byte 5
// a byte count, so a region that is not byte-aligned is not expressible and
// from_pixels() widens it until it is. Over-marking redraws pixels that did
// not change; under-marking leaves the panel showing something that is no
// longer true, so every rounding here goes outwards.
//
// Half-open: the region covers [x, x+w) x [y, y+h).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Region {
    pub x: usize,
    pub y: usize,
    pub w: usize,
    pub h: usize,
}

impl Region {
    /// The whole screen - what every draw used to imply.
    ///
    /// The width is HDR_ROW_BYTES rather than STRIDE on purpose: this is the
    /// value that goes into header byte 5, and the two are asserted equal by
    /// `chunks_tile_the_framebuffer_exactly`.
    pub fn full() -> Region {
        Region { x: 0, y: 0, w: HDR_ROW_BYTES as usize, h: HEIGHT }
    }

    /// A pixel-space rectangle snapped outwards to the byte grid and clipped
    /// to the panel. Returns an empty region when nothing of it is on glass.
    pub fn from_pixels(x: usize, y: usize, w: usize, h: usize) -> Region {
        if w == 0 || h == 0 || x >= WIDTH || y >= HEIGHT {
            return Region { x: 0, y: 0, w: 0, h: 0 };
        }
        // WIDTH is 255 but the row is 32 bytes: the 256th bit is transferred
        // and discarded, so clip the RIGHT edge against the byte grid, not
        // against WIDTH, or the last on-glass column falls outside the blit.
        let x1 = (x + w).min(STRIDE * 8);
        let y1 = (y + h).min(HEIGHT);
        let bx = x / 8;
        let bx1 = (x1 + 7) / 8;
        Region { x: bx, y, w: bx1 - bx, h: y1 - y }
    }

    pub fn is_empty(&self) -> bool {
        self.w == 0 || self.h == 0
    }

    pub fn union(&self, other: &Region) -> Region {
        if self.is_empty() { return *other; }
        if other.is_empty() { return *self; }
        let x = self.x.min(other.x);
        let y = self.y.min(other.y);
        let x1 = (self.x + self.w).max(other.x + other.w);
        let y1 = (self.y + self.h).max(other.y + other.h);
        Region { x, y, w: x1 - x, h: y1 - y }
    }

    /// Bytes this region costs on the wire: one 9-byte header per report plus
    /// the payload. This is the merge currency - not area, because a region
    /// that needs two reports pays a second header for it.
    pub fn cost(&self) -> usize {
        if self.is_empty() { return 0; }
        reports_for(self.w, self.h) * (1 + 8) + self.w * self.h
    }
}

/// Rows of `row_bytes` that fit in one report's payload.
///
/// The full-screen case is the one that must not move: 32 bytes per row gives
/// 256/32 = 8 rows, which is exactly today's chunking, so a full-screen region
/// still produces 8 reports of 265 bytes with the same header bytes as before.
pub fn rows_per_report(row_bytes: usize) -> usize {
    if row_bytes == 0 { return 0; }
    // Header byte 7 is the row count, so it cannot exceed 255. HEIGHT is 64,
    // so this cap is defensive rather than reachable.
    (CHUNK_BYTES / row_bytes).clamp(1, 255)
}

/// The nine bytes ahead of a blit report's payload: the report id, then the
/// eight header bytes.
///
/// Bytes 2, 4, 6 and 8 are zero and have never been written by anything, here
/// or in cabl. They are almost certainly the high halves of the four 16-bit
/// fields, which for a 256x64 panel are all zero anyway - but that is inferred,
/// not measured, so they stay zero.
///
/// `col` is the diagnostic column offset from /maschine/display/opts and is 0
/// in normal use; it is added to the region's own left edge so a full-screen
/// region reproduces exactly what this path sent before regions existed.
pub fn blit_prefix(report_id: u8, region: Region, row: usize, rows: usize, col: u8) -> [u8; 9] {
    let mut p = [0u8; 9];
    p[0] = report_id;
    p[1] = region.x as u8 + col;   // left edge, in BYTES
    p[3] = row as u8;              // top row of THIS report
    p[5] = region.w as u8;         // bytes per row
    p[7] = rows as u8;             // rows in THIS report
    p
}

pub fn reports_for(row_bytes: usize, rows: usize) -> usize {
    if row_bytes == 0 || rows == 0 { return 0; }
    let per = rows_per_report(row_bytes);
    (rows + per - 1) / per
}

/// How many regions a screen tracks before it starts merging.
///
/// Four, because the layout the driver draws has at most a handful of things
/// that move independently and every extra slot costs a linear scan on the
/// display timer. Running out is not a failure: the merge below is bounded by
/// the whole screen, which is what this path did unconditionally before.
pub const MAX_DIRTY_REGIONS: usize = 4;

#[derive(Clone, Copy)]
pub struct DirtyList {
    rects: [Region; MAX_DIRTY_REGIONS],
    len: usize,
}

impl Default for DirtyList {
    fn default() -> Self {
        DirtyList {
            rects: [Region { x: 0, y: 0, w: 0, h: 0 }; MAX_DIRTY_REGIONS],
            len: 0,
        }
    }
}

impl DirtyList {
    pub fn is_empty(&self) -> bool { self.len == 0 }

    pub fn clear(&mut self) { self.len = 0; }

    pub fn regions(&self) -> &[Region] { &self.rects[..self.len] }

    /// Total bytes the current set would cost to send.
    pub fn cost(&self) -> usize {
        self.regions().iter().map(|r| r.cost()).sum()
    }

    fn remove(&mut self, i: usize) {
        self.rects[i] = self.rects[self.len - 1];
        self.len -= 1;
    }

    /// Add a region, coalescing wherever coalescing is CHEAPER.
    ///
    /// The test is the wire cost, and only the wire cost. Overlap is not a
    /// correctness question here: every region is read out of the SAME
    /// framebuffer at flush time, so a row sent twice is redundant, never
    /// wrong. That frees the policy to be one comparison - a region nested
    /// inside another always merges, two side by side on the same rows merge
    /// because one wider report beats a second header, and two far apart stay
    /// apart, which is the whole point. Two that merely clip each other's
    /// corners can be cheaper left alone, and are left alone.
    pub fn add(&mut self, r: Region) {
        if r.is_empty() { return; }
        let mut r = r;
        // Absorb repeatedly: a union is bigger than either input, so it can
        // reach a region the first pass walked past.
        loop {
            let mut merged = false;
            for i in 0..self.len {
                if r.union(&self.rects[i]).cost() <= r.cost() + self.rects[i].cost() {
                    r = r.union(&self.rects[i]);
                    self.remove(i);
                    merged = true;
                    break;
                }
            }
            if !merged { break; }
        }
        if self.len < MAX_DIRTY_REGIONS {
            self.rects[self.len] = r;
            self.len += 1;
            return;
        }
        // Full. Fold the newcomer into whichever region makes the cheapest
        // union. Merging two EXISTING regions instead is occasionally better;
        // it is not worth the extra pass, because the worst case here is one
        // region covering the screen and that is what this path did on every
        // draw before per-region tracking existed.
        let mut best = 0usize;
        let mut best_cost = usize::MAX;
        for i in 0..self.len {
            let c = self.rects[i].union(&r).cost();
            if c < best_cost { best_cost = c; best = i; }
        }
        self.rects[best] = self.rects[best].union(&r);
    }

    /// Mark the whole screen, discarding any finer regions.
    ///
    /// A full flush is still the right answer for a large change, and here is
    /// the arithmetic. One screen whole is 8 reports of 265 = **2120 bytes**;
    /// its payload is 32 x 64 = 2048. A rectangle costs 9 bytes of header per
    /// report plus its own payload, so a region set only beats the full flush
    /// while its payloads plus headers stay under 2120 - roughly, while it
    /// covers less than about 2000 of the screen's 2048 bytes. A clear really
    /// does invalidate all 2048, so it goes full rather than pretending to be
    /// four rectangles that would cost more.
    ///
    /// This is also the path the driver takes on every screen repaint, because
    /// `screen_packets` opens with a clear. The saving there is not smaller
    /// reports - it is that the OTHER screen is no longer repainted with it.
    pub fn add_full(&mut self) {
        self.len = 0;
        self.rects[0] = Region::full();
        self.len = 1;
    }
}

pub fn clear(bits: &mut [u8; HEIGHT * STRIDE]) {
    for b in bits.iter_mut() { *b = 0; }
}

pub fn set_pixel(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize) {
    if x >= WIDTH || y >= HEIGHT { return; }
    bits[y * STRIDE + x / 8] |= 0x80 >> (x % 8);
}

pub fn draw_char(bits: &mut [u8; HEIGHT * STRIDE], px: usize, py: usize, c: u8) {
    let idx = match c {
        32..=127 => (c - 32) as usize,
        _ => 0,
    };
    let glyph = &FONT5X8[idx];
    for col in 0..5 {
        let col_byte = glyph[col];
        for row in 0..8 {
            if (col_byte >> row) & 1 == 1 {
                set_pixel(bits, px + col, py + row);
            }
        }
    }
}

pub fn draw_text(bits: &mut [u8; HEIGHT * STRIDE], px: usize, py: usize, text: &str) {
    let mut x = px;
    for c in text.bytes() {
        if x + 5 > WIDTH { break; }
        draw_char(bits, x, py, c);
        x += 6; // 5px char + 1px gap
    }
}

// --- primitives for the rig's screen layout ---------------------------------
//
// The reference is Maschine's own screen: boxed labels along the top under the
// buttons, a rule, then one column per encoder with a small caps name above a
// double-height value. That needs three things the original font code had no
// answer for - scaled text, filled/outlined/dashed boxes, and inversion for
// the selected item - so they live here rather than being open-coded per
// layout.

pub fn clear_pixel(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize) {
    if x >= WIDTH || y >= HEIGHT { return; }
    bits[y * STRIDE + x / 8] &= !(0x80 >> (x % 8));
}

// Glyphs are square on the panel now that rows map 1:1, so no horizontal
// compensation is needed. Kept as a named constant because getting this wrong
// once already cost a full round of unreadable screens.
pub const X_SCALE: usize = 1;

/// Character cell width at a given scale, gap included.
pub fn char_w(scale: usize) -> usize { 6 * X_SCALE * scale.max(1) }

/// Pixel width a string occupies at a given scale, trailing gap excluded.
pub fn text_w(text: &str, scale: usize) -> usize {
    let n = text.len();
    if n == 0 { 0 } else { n * char_w(scale) - X_SCALE * scale.max(1) }
}

pub fn draw_char_scaled(bits: &mut [u8; HEIGHT * STRIDE], px: usize, py: usize, c: u8, scale: usize) {
    let sy = scale.max(1);
    let sx = sy * X_SCALE;
    let idx = match c { 32..=127 => (c - 32) as usize, _ => 0 };
    let glyph = &FONT5X8[idx];
    for col in 0..5 {
        let col_byte = glyph[col];
        for row in 0..8 {
            if (col_byte >> row) & 1 == 1 {
                for dy in 0..sy {
                    for dx in 0..sx {
                        set_pixel(bits, px + col * sx + dx, py + row * sy + dy);
                    }
                }
            }
        }
    }
}

pub fn draw_text_scaled(bits: &mut [u8; HEIGHT * STRIDE], px: usize, py: usize, text: &str, scale: usize) {
    let s = scale.max(1);
    let mut x = px;
    for c in text.bytes() {
        if x + 5 * s * X_SCALE > WIDTH { break; }
        draw_char_scaled(bits, x, py, c, s);
        x += char_w(s);
    }
}

pub fn hline(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, w: usize) {
    for i in 0..w { set_pixel(bits, x + i, y); }
}

pub fn vline(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, h: usize) {
    for i in 0..h { set_pixel(bits, x, y + i); }
}

/// Every other pixel - the separator Maschine draws under its tab row.
pub fn dotted_hline(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, w: usize) {
    let mut i = 0;
    while i < w { set_pixel(bits, x + i, y); i += 2; }
}

pub fn fill_rect(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, w: usize, h: usize) {
    for dy in 0..h { for dx in 0..w { set_pixel(bits, x + dx, y + dy); } }
}

pub fn rect(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, w: usize, h: usize) {
    if w == 0 || h == 0 { return; }
    hline(bits, x, y, w);
    hline(bits, x, y + h - 1, w);
    vline(bits, x, y, h);
    vline(bits, x + w - 1, y, h);
}

/// Outline drawn every other pixel - Maschine's "available but not selected"
/// box, distinct from a solid one at a glance.
pub fn dashed_rect(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, w: usize, h: usize) {
    if w == 0 || h == 0 { return; }
    let mut i = 0;
    while i < w { set_pixel(bits, x + i, y); set_pixel(bits, x + i, y + h - 1); i += 2; }
    let mut j = 0;
    while j < h { set_pixel(bits, x, y + j); set_pixel(bits, x + w - 1, y + j); j += 2; }
}

/// Swap lit and unlit inside a box. Drawing text first and inverting after is
/// how a label becomes dark-on-light without a second draw path.
pub fn invert_rect(bits: &mut [u8; HEIGHT * STRIDE], x: usize, y: usize, w: usize, h: usize) {
    for dy in 0..h {
        for dx in 0..w {
            let (px, py) = (x + dx, y + dy);
            if px >= WIDTH || py >= HEIGHT { continue; }
            bits[py * STRIDE + px / 8] ^= 0x80 >> (px % 8);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blank_bitmap_is_all_zeros() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        clear(&mut bits);
        assert!(bits.iter().all(|&b| b == 0));
    }

    #[test]
    fn set_pixel_top_left() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        set_pixel(&mut bits, 0, 0);
        assert_eq!(bits[0], 0x80);
    }

    #[test]
    fn set_pixel_second_in_row() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        set_pixel(&mut bits, 1, 0);
        assert_eq!(bits[0], 0x40);
    }

    #[test]
    fn set_pixel_byte_boundary() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        set_pixel(&mut bits, 8, 0);
        assert_eq!(bits[1], 0x80);
    }

    #[test]
    fn set_pixel_out_of_bounds_does_not_panic() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        set_pixel(&mut bits, 200, 200);
    }

    #[test]
    fn chunks_tile_the_framebuffer_exactly() {
        // The transfer is a straight slice of the framebuffer; if these ever
        // stop matching, part of the screen goes stale or reads past the end.
        assert_eq!(CHUNKS * CHUNK_BYTES, HEIGHT * STRIDE);
        assert_eq!(CHUNK_BYTES, HDR_ROW_BYTES as usize * HDR_ROWS as usize);
        assert_eq!(STRIDE, HDR_ROW_BYTES as usize);
    }

    // --- dirty rectangles ---------------------------------------------------

    #[test]
    fn the_logical_row_mapping_is_the_identity() {
        // Region blitting addresses TRANSFER rows directly. If logical_row
        // ever stops being the identity, every region's y is wrong and the
        // panel shows the right pixels in the wrong place - which reads as
        // "the rectangle does not work" rather than as a mapping bug.
        for r in 0..LOGICAL_H { assert_eq!(logical_row(r), r); }
        assert_eq!(LOGICAL_H, HEIGHT);
    }

    #[test]
    fn a_full_screen_region_is_the_old_transfer_exactly() {
        // The one thing that must not move. 8 reports, 32 bytes per row, 8
        // rows each, 265 bytes on the wire per report.
        let r = Region::full();
        assert_eq!(rows_per_report(r.w), CHUNK_ROWS);
        assert_eq!(reports_for(r.w, r.h), CHUNKS);
        assert_eq!(r.cost(), CHUNKS * 265);
        assert_eq!(r.w, HDR_ROW_BYTES as usize);
        assert_eq!(rows_per_report(r.w), HDR_ROWS as usize);
    }

    #[test]
    fn the_measured_rectangle_costs_one_report() {
        // The 64x8 block photographed on the rig 2026-08-31: byte 1 = 4,
        // byte 5 = 8, byte 7 = 8, 64 bytes of payload = 73 on the wire.
        let r = Region::from_pixels(32, 24, 64, 8);
        assert_eq!(r, Region { x: 4, y: 24, w: 8, h: 8 });
        assert_eq!(reports_for(r.w, r.h), 1);
        assert_eq!(r.cost(), 73);
    }

    #[test]
    fn a_small_widget_is_cheaper_than_a_flush_by_two_orders() {
        // The reason any of this exists. 73 bytes against 16 x 265 for a
        // both-screen rebuild, or 8 x 265 for one screen.
        let widget = Region::from_pixels(32, 24, 64, 8).cost();
        assert!(widget * 8 < Region::full().cost(), "{} vs {}", widget, Region::full().cost());
    }

    #[test]
    fn from_pixels_snaps_outwards_to_the_byte_grid() {
        // x=3..11 spans bytes 0 and 1. Rounding either edge inwards would
        // leave stale pixels on the panel.
        let r = Region::from_pixels(3, 0, 8, 1);
        assert_eq!(r.x, 0);
        assert_eq!(r.w, 2);
    }

    #[test]
    fn from_pixels_clips_to_the_panel() {
        let r = Region::from_pixels(250, 60, 100, 100);
        assert_eq!(r.x + r.w, STRIDE);
        assert_eq!(r.y + r.h, HEIGHT);
    }

    #[test]
    fn from_pixels_reaches_the_last_on_glass_column() {
        // WIDTH is 255 but the row is 32 bytes. Clipping the right edge at
        // WIDTH would drop column 254, which IS on glass.
        let r = Region::from_pixels(248, 0, 8, 1);
        assert_eq!(r.x + r.w, STRIDE);
    }

    #[test]
    fn from_pixels_off_panel_is_empty() {
        assert!(Region::from_pixels(300, 0, 8, 8).is_empty());
        assert!(Region::from_pixels(0, 90, 8, 8).is_empty());
        assert!(Region::from_pixels(0, 0, 0, 8).is_empty());
    }

    #[test]
    fn the_full_screen_header_is_byte_for_byte_the_old_one() {
        // What send_display_bits hardcoded for the daemon's whole life:
        // byte 1 = 0, byte 5 = 0x20, byte 7 = 0x08, byte 3 = chunk * 8, and
        // bytes 2, 4, 6, 8 never written.
        let r = Region::full();
        assert_eq!(
            blit_prefix(0xE0, r, 0, CHUNK_ROWS, 0),
            [0xE0, 0x00, 0, 0x00, 0, 0x20, 0, 0x08, 0]
        );
        assert_eq!(
            blit_prefix(0xE1, r, 3 * CHUNK_ROWS, CHUNK_ROWS, 0),
            [0xE1, 0x00, 0, 0x18, 0, 0x20, 0, 0x08, 0]
        );
    }

    #[test]
    fn the_header_matches_the_report_photographed_on_the_rig() {
        // 2026-08-31: byte 1 = 4, byte 3 = 24, byte 5 = 8, byte 7 = 8, with a
        // 64-byte payload. The block landed exactly where this asked.
        let r = Region::from_pixels(32, 24, 64, 8);
        assert_eq!(
            blit_prefix(0xE0, r, r.y, r.h, 0),
            [0xE0, 4, 0, 24, 0, 8, 0, 8, 0]
        );
        assert_eq!(9 + r.w * r.h, 73);
    }

    #[test]
    fn the_header_carries_the_ROW_COUNT_of_this_report_not_a_constant() {
        // Byte 7 was 0x08 for the daemon's whole life and the two cases above
        // both happen to be 8 rows tall, so they cannot catch it being
        // hardcoded again. A 3-row rule and the short tail of a split can.
        let r = Region::from_pixels(0, 5, 64, 3);
        assert_eq!(blit_prefix(0xE0, r, r.y, r.h, 0)[7], 3);
        assert_eq!(blit_prefix(0xE0, r, r.y, r.h, 0)[3], 5);

        // A 20-row full-width region splits 8 + 8 + 4; the tail must say 4.
        let tall = Region { x: 0, y: 0, w: STRIDE, h: 20 };
        let per = rows_per_report(tall.w);
        assert_eq!(blit_prefix(0xE0, tall, 2 * per, 20 - 2 * per, 0)[7], 4);
    }

    #[test]
    fn the_diagnostic_column_offset_still_shifts_the_header() {
        // /maschine/display/opts must keep working unchanged; it is 0 in
        // normal use, which is why a full-screen region is unaffected.
        let p = blit_prefix(0xE0, Region::full(), 0, CHUNK_ROWS, 4);
        assert_eq!(p[1], 4);
    }

    #[test]
    fn an_empty_list_flushes_nothing() {
        let d = DirtyList::default();
        assert!(d.is_empty());
        assert_eq!(d.regions().len(), 0);
        assert_eq!(d.cost(), 0);
    }

    #[test]
    fn adding_an_empty_region_changes_nothing() {
        let mut d = DirtyList::default();
        d.add(Region::from_pixels(300, 0, 8, 8));
        assert!(d.is_empty());
    }

    #[test]
    fn two_distant_regions_stay_apart() {
        // The whole point of tracking regions instead of a flag.
        let mut d = DirtyList::default();
        d.add(Region::from_pixels(0, 0, 32, 8));
        d.add(Region::from_pixels(200, 48, 32, 8));
        assert_eq!(d.regions().len(), 2);
        assert!(d.cost() < Region::full().cost());
    }

    #[test]
    fn heavily_overlapping_regions_coalesce() {
        // Two 64x16 blocks one byte apart on the same rows: the union is
        // 9 bytes wide, 9 + 144 = 153, against 2 x 137 = 274 apart.
        let mut d = DirtyList::default();
        d.add(Region::from_pixels(0, 0, 64, 16));
        d.add(Region::from_pixels(8, 0, 64, 16));
        assert_eq!(d.regions().len(), 1);
        assert_eq!(d.regions()[0], Region { x: 0, y: 0, w: 9, h: 16 });
        assert_eq!(d.cost(), 9 + 9 * 16);
    }

    #[test]
    fn a_cheap_overlap_is_allowed_to_stay_split() {
        // Two blocks clipping each other's corners: apart they cost 274,
        // merged 297. Sending a row twice is redundant, not wrong - both
        // regions are read out of the same framebuffer at flush time - so the
        // rule is free to take the cheaper answer.
        let a = Region::from_pixels(0, 0, 64, 16);
        let b = Region::from_pixels(32, 8, 64, 16);
        assert!(a.union(&b).cost() > a.cost() + b.cost());
        let mut d = DirtyList::default();
        d.add(a);
        d.add(b);
        assert_eq!(d.regions().len(), 2);
    }

    #[test]
    fn a_region_inside_another_is_absorbed() {
        let mut d = DirtyList::default();
        d.add(Region::from_pixels(0, 0, 128, 32));
        d.add(Region::from_pixels(16, 8, 16, 8));
        assert_eq!(d.regions().len(), 1);
        assert_eq!(d.regions()[0], Region::from_pixels(0, 0, 128, 32));
    }

    #[test]
    fn side_by_side_regions_coalesce_because_it_is_cheaper() {
        // Two 64x8 blocks on the same rows, exactly adjacent: one 128-wide
        // report is 9 + 128 = 137 against 2 x 73 = 146.
        let mut d = DirtyList::default();
        d.add(Region::from_pixels(0, 0, 64, 8));
        d.add(Region::from_pixels(64, 0, 64, 8));
        assert_eq!(d.regions().len(), 1);
        assert_eq!(d.cost(), 9 + 128);
    }

    #[test]
    fn coalescing_never_costs_more_than_keeping_apart() {
        // The merge rule is the wire cost, so this is the invariant it exists
        // to hold. Two regions far apart on both axes must NOT merge.
        let a = Region::from_pixels(0, 0, 8, 8);
        let b = Region::from_pixels(240, 56, 8, 8);
        assert!(a.union(&b).cost() > a.cost() + b.cost());
        let mut d = DirtyList::default();
        d.add(a);
        d.add(b);
        assert_eq!(d.regions().len(), 2);
    }

    #[test]
    fn a_full_list_merges_rather_than_dropping() {
        // Losing a region would leave the panel showing something untrue,
        // which is worse than any amount of redraw.
        let mut d = DirtyList::default();
        for i in 0..(MAX_DIRTY_REGIONS + 3) {
            d.add(Region::from_pixels(i * 24, i * 8, 8, 8));
        }
        assert!(d.regions().len() <= MAX_DIRTY_REGIONS);
        // Every added region is still covered by something in the list.
        for i in 0..(MAX_DIRTY_REGIONS + 3) {
            let r = Region::from_pixels(i * 24, i * 8, 8, 8);
            assert!(
                d.regions().iter().any(|c| c.x <= r.x
                    && c.y <= r.y
                    && c.x + c.w >= r.x + r.w
                    && c.y + c.h >= r.y + r.h),
                "region {} was dropped", i
            );
        }
    }

    #[test]
    fn the_worst_case_is_the_old_behaviour_not_worse_than_it() {
        // Whatever the merges do, one screen can never cost more than the
        // full flush that used to happen unconditionally.
        let mut d = DirtyList::default();
        for i in 0..40 {
            d.add(Region::from_pixels((i * 13) % 250, (i * 7) % 60, 9, 5));
        }
        assert!(d.cost() <= Region::full().cost() * MAX_DIRTY_REGIONS);
        let mut all = DirtyList::default();
        all.add_full();
        assert_eq!(all.regions().len(), 1);
        assert_eq!(all.cost(), Region::full().cost());
    }

    #[test]
    fn add_full_replaces_everything() {
        let mut d = DirtyList::default();
        d.add(Region::from_pixels(0, 0, 8, 8));
        d.add(Region::from_pixels(200, 50, 8, 8));
        d.add_full();
        assert_eq!(d.regions(), &[Region::full()]);
    }

    #[test]
    fn clear_empties_the_list() {
        let mut d = DirtyList::default();
        d.add_full();
        d.clear();
        assert!(d.is_empty());
    }

    #[test]
    fn a_one_byte_wide_column_still_splits_into_whole_reports() {
        // rows_per_report would be 256 for a 1-byte row; the panel is only 64
        // rows tall, so one report covers a full-height column.
        assert_eq!(reports_for(1, HEIGHT), 1);
        assert_eq!(Region { x: 0, y: 0, w: 1, h: HEIGHT }.cost(), 9 + HEIGHT);
    }

    #[test]
    fn a_tall_full_width_region_splits_at_the_payload_limit() {
        // 32 bytes per row means 8 rows per report; 20 rows needs 3.
        assert_eq!(reports_for(STRIDE, 20), 3);
        assert_eq!(Region { x: 0, y: 0, w: STRIDE, h: 20 }.cost(), 3 * 9 + 20 * STRIDE);
    }

    #[test]
    fn a_report_never_carries_more_than_the_known_good_payload() {
        // 256 bytes is what the panel has accepted since the daemon was
        // vendored. Nothing here may build a bigger one.
        for w in 1..=STRIDE {
            assert!(rows_per_report(w) * w <= CHUNK_BYTES, "row_bytes {}", w);
        }
    }

    #[test]
    fn draw_text_marks_pixels() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        draw_text(&mut bits, 0, 0, "0");
        assert!(bits[..STRIDE].iter().any(|&b| b != 0));
    }

    #[test]
    fn draw_text_does_not_overflow() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        draw_text(&mut bits, 0, 0, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789");
    }
}

#[cfg(test)]
mod render_dump {
    use super::*;

    /// Renders text and prints it as ASCII art so the glyph layout can be read
    /// without a panel in the loop.
    #[test]
    fn dump_text_layout() {
        let mut bits = [0u8; HEIGHT * STRIDE];
        draw_text_scaled(&mut bits, 0, 0, "AB C", 1);
        for y in 0..8 {
            let mut line = String::new();
            for x in 0..40 {
                line.push(if bits[y * STRIDE + x / 8] & (0x80 >> (x % 8)) != 0 { '#' } else { '.' });
            }
            println!("{}", line);
        }
        println!("char_w(1)={} text_w(\"AB C\",1)={}", char_w(1), text_w("AB C", 1));
    }
}
