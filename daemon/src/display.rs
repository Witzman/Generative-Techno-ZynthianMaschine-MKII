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
