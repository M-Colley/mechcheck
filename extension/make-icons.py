"""Generate the extension icons.

Kept as source rather than committed-binary-only so the mark can be changed
without a design tool. Pure standard library: a PNG is a zlib stream of
scanlines with a one-byte filter prefix, and that is the whole format we need.

    python extension/make-icons.py
"""

from __future__ import annotations

import os
import struct
import zlib

INDIGO = (0x3A, 0x4E, 0xA8)
WHITE = (0xFF, 0xFF, 0xFF)
SIZES = (16, 48, 128)


def chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: str, size: int, pixels) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)                      # filter type 0 for every scanline
        for x in range(size):
            raw.extend(pixels(x, y))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def distance_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def make(size: int):
    """A check mark on a rounded indigo tile: legible down to 16 pixels."""
    radius = size * 0.22
    stroke = max(1.6, size * 0.11)
    # the two strokes of a check, in unit coordinates
    a = (size * 0.26, size * 0.52)
    b = (size * 0.44, size * 0.70)
    c = (size * 0.76, size * 0.32)

    def pixel(x: int, y: int):
        cx, cy = x + 0.5, y + 0.5
        # rounded-rectangle mask
        qx = max(radius - cx, cx - (size - radius), 0.0)
        qy = max(radius - cy, cy - (size - radius), 0.0)
        outside = (qx * qx + qy * qy) ** 0.5 - radius
        alpha_tile = max(0.0, min(1.0, 0.5 - outside))
        if alpha_tile <= 0:
            return (0, 0, 0, 0)
        d = min(distance_to_segment(cx, cy, a[0], a[1], b[0], b[1]),
                distance_to_segment(cx, cy, b[0], b[1], c[0], c[1]))
        alpha_mark = max(0.0, min(1.0, (stroke / 2 - d) + 0.5))
        r = round(INDIGO[0] * (1 - alpha_mark) + WHITE[0] * alpha_mark)
        g = round(INDIGO[1] * (1 - alpha_mark) + WHITE[1] * alpha_mark)
        bl = round(INDIGO[2] * (1 - alpha_mark) + WHITE[2] * alpha_mark)
        return (r, g, bl, round(255 * alpha_tile))

    return pixel


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "icons")
    os.makedirs(out, exist_ok=True)
    for size in SIZES:
        path = os.path.join(out, f"{size}.png")
        write_png(path, size, make(size))
        print(f"wrote {os.path.relpath(path, here)}  ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
