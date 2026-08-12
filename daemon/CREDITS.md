# Lineage

    wrl/maschine.rs  (William Light, GPL-3.0)
        └── Witzman/MaschineMK2_linux  (fork: MK2 support, display, OSC, web editor)
                └── this repository  (development home as of 2026-08-13)

The upstream `LICENSE` and source notices are preserved unchanged. Changes made
in this lineage: MK2 HID report maps, the 255x64 display protocol, the OSC
drawing API, the hidraw close-then-reopen watchdog, the WebSocket LED editor,
and the `external_pad_leds` config flag.

## What is not vendored here

- `maschine.json` lives in `../system/`, because it is deployed configuration
  rather than source, and it must carry `"external_pad_leds": true`.
- The old fork's `docs/superpowers/` specs are not copied; in this repository
  `docs/` is the generated documentation site.
- `target/` is build output and is gitignored. Build with
  `cd daemon && cargo build --release` on the Pi.
