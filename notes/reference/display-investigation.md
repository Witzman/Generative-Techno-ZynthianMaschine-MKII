# Maschine MK2 Display — Solved

The two screens work. This file describes only how, because every earlier model in
it was wrong and a subagent acted on the wrong one even though it was marked
superseded. The dead-end history (128x128, 512x64, 128x32 tiles, two row bands per
tile, "rows are 2 px tall", "transfer rows discarded") is in git if ever wanted:
`git log --follow MD/display-investigation.md`.

## The geometry, hardware-verified 2026-08-09

The panel is **255x64, 1bpp row-major, MSB = leftmost pixel**, 32 bytes per row (the 256th column is transferred and discarded). One screen is **8 HID reports**, each a full-width band of 8 rows:

```
header = [0xE0|screen, 0x00, 0x00, chunk*8, 0x00, 0x20, 0x00, 0x08, 0x00]
payload = 256 bytes = framebuffer[chunk*256 .. +256]     chunk = 0..7
report length = 9 + 256
```

- **Header byte 5 = bytes per row (0x20 = 32 → 255 px), byte 7 = rows per report (0x08).** This driver had those two **swapped**, so the panel was told to expect a 64x32 region while being fed 512 bytes laid out 128 px wide. That single swap is the whole reason the screens garbled, through every earlier theory.
- **Byte 1 is an x offset in bytes, byte 3 a y offset in rows.** Reading byte 1 as a 16-pixel unit is where "the panel is 512 wide" came from: the offsets 0/8/16/24 span 0..256, not 0..512.
- No tiling, no column strips, no row bands, no page/column conversion, no bit reversal, no x scaling. The framebuffer slices straight into the 8 reports.

Source of truth: **cabl** (`shaduzlabs/cabl`, `src/devices/ni/MaschineMK2.cpp`) — known-working, MIT. Its `sendFrame` is the transfer above verbatim, and its `GDisplayMaschineMK2::setPixel` is `data[widthBytes*y + (x>>3)] |= 0x80 >> (x&7)`, identical to `display.rs`. Three months of guessing lost to not reading it.

**Verified on hardware 2026-08-09:**

- Border rect on all four edges; lines at x=248, 251, 254 all render with **254 in the last physical column**, x=255 shows nothing → width is 255.
- Text at y=2 (5x8), y=24 (double height) and y=48 (5x8) all render complete and correctly placed, full width, no wrap.
- The full rig layout renders clean: four group tabs, dotted rule, four encoder columns with name + double-height value + indicator bar. Nothing cut off or cramped.

Code: `MaschineMK2_linux` `bbf2a62`. `clear_screen` now goes through `send_display_bits` with a blank buffer instead of its own hand-rolled sweep. `display::CHUNKS/CHUNK_ROWS/CHUNK_BYTES/HDR_ROW_BYTES/HDR_ROWS` carry the numbers; a unit test asserts the chunks tile the framebuffer exactly.

Layout mock on the Pi: `/root/mock2.py` (255-wide, four 64-px columns, bars at y 52-61). Probe tool: `/root/disp2.py`.
