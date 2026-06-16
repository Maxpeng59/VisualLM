#!/usr/bin/env python3
"""Generate the VisualLM app icon (1024x1024 PNG) with only the standard library.

Design echoes the app's "breathing circle" motif: a dark gradient rounded square
with two concentric accent rings and a bright center dot. Output:  VisualLM.png
(make_app.sh downsamples it into an .iconset and runs iconutil -> .icns).

Usage:  python3 make_icon.py [out.png]
"""
from __future__ import annotations

import math
import struct
import sys
import zlib

SIZE = 1024


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


BG_TOP, BG_BOT = _hex("#16203a"), _hex("#0b1120")
ACCENT, ACCENT2, INK = _hex("#7cc4ff"), _hex("#f4a259"), _hex("#eef2ff")


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def build() -> bytes:
    half = SIZE / 2.0
    cr = SIZE * 0.235           # corner radius
    flat = half - cr            # half-extent of the straight edges
    r1, w1 = SIZE * 0.300, SIZE * 0.024   # outer ring radius / half-width
    r2, w2 = SIZE * 0.200, SIZE * 0.020   # inner ring
    rdot = SIZE * 0.072         # center dot radius
    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)  # PNG filter byte (None) per scanline
        ty = y / (SIZE - 1)
        bg = (
            _lerp(BG_TOP[0], BG_BOT[0], ty),
            _lerp(BG_TOP[1], BG_BOT[1], ty),
            _lerp(BG_TOP[2], BG_BOT[2], ty),
        )
        dyc = y - half
        for x in range(SIZE):
            # Rounded-square mask (hard edge; sips downscaling anti-aliases it).
            ex = abs(x - half) - flat
            ey = abs(dyc) - flat
            ex = ex if ex > 0 else 0.0
            ey = ey if ey > 0 else 0.0
            if ex * ex + ey * ey > cr * cr:
                rows += b"\x00\x00\x00\x00"
                continue
            r, g, b = bg
            d = math.hypot(x - half, dyc)
            a1 = 1.0 - abs(d - r1) / w1
            if a1 > 0:
                r = _lerp(r, ACCENT[0], a1); g = _lerp(g, ACCENT[1], a1); b = _lerp(b, ACCENT[2], a1)
            a2 = 1.0 - abs(d - r2) / w2
            if a2 > 0:
                r = _lerp(r, ACCENT2[0], a2); g = _lerp(g, ACCENT2[1], a2); b = _lerp(b, ACCENT2[2], a2)
            if d < rdot:
                r, g, b = INK
            rows += bytes((int(r), int(g), int(b), 255))
    return _png(SIZE, SIZE, bytes(rows))


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "VisualLM.png"
    with open(out, "wb") as f:
        f.write(build())
    print(f"wrote {out} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
