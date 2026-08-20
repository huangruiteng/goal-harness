#!/usr/bin/env python3
"""Ensure desktop icons keep a rounded white background and visible product mark."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = REPO_ROOT / "apps" / "desktop" / "loopx-control-plane" / "src-tauri" / "icons"
ICON_PATHS = [
    ICON_DIR / "32x32.png",
    ICON_DIR / "128x128.png",
    ICON_DIR / "128x128@2x.png",
]
ICO_PATH = ICON_DIR / "icon.ico"


def read_png_rgba(path: Path) -> tuple[int, int, bytes]:
    return read_png_rgba_from_bytes(path, path.read_bytes())


def alpha_at(pixels: bytes, width: int, x: int, y: int) -> int:
    return pixels[(y * width + x) * 4 + 3]


def rgba_at(pixels: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    offset = (y * width + x) * 4
    return tuple(pixels[offset : offset + 4])


def read_ico_pngs(path: Path) -> list[tuple[int, int, bytes]]:
    data = path.read_bytes()
    if len(data) < 6:
        raise AssertionError(f"{path} is too small to be an ICO file")
    reserved, icon_type, count = struct.unpack("<HHH", data[:6])
    if reserved != 0 or icon_type != 1 or count == 0:
        raise AssertionError(f"{path} is not an ICO file")

    pngs: list[tuple[int, int, bytes]] = []
    for index in range(count):
        entry_offset = 6 + index * 16
        _, _, _, _, _, _, size, offset = struct.unpack("<BBBBHHII", data[entry_offset : entry_offset + 16])
        payload = data[offset : offset + size]
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AssertionError(f"{path} icon #{index + 1} is not PNG-backed")
        png_path = path.with_name(f"{path.stem}-{index + 1}.png")
        pngs.append(read_png_rgba_from_bytes(png_path, payload))
    return pngs


def read_png_rgba_from_bytes(path: Path, data: bytes) -> tuple[int, int, bytes]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{path} is not a PNG file")

    position = 8
    width = height = color_type = None
    compressed = bytearray()
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        chunk = data[position + 8 : position + 8 + length]
        position += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk)
            if bit_depth != 8 or color_type != 6:
                raise AssertionError(f"{path} must be 8-bit RGBA, got bit_depth={bit_depth} color_type={color_type}")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk)
        elif chunk_type == b"IEND":
            break

    if width is None or height is None or color_type != 6:
        raise AssertionError(f"{path} is missing an RGBA header")

    stride = width * 4
    raw = zlib.decompress(bytes(compressed))
    rows: list[bytearray] = []
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride
        previous = rows[-1] if rows else bytearray(stride)
        for index in range(stride):
            left = row[index - 4] if index >= 4 else 0
            up = previous[index]
            up_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                prediction = left + up - up_left
                distances = (
                    abs(prediction - left),
                    abs(prediction - up),
                    abs(prediction - up_left),
                )
                predictor = (left, up, up_left)[distances.index(min(distances))]
                row[index] = (row[index] + predictor) & 0xFF
            elif filter_type != 0:
                raise AssertionError(f"{path} uses unsupported PNG filter {filter_type}")
        rows.append(row)

    return width, height, b"".join(rows)


def assert_rounded_white_background(path: Path, width: int, height: int, pixels: bytes) -> None:
    corners = [
        rgba_at(pixels, width, 0, 0),
        rgba_at(pixels, width, width - 1, 0),
        rgba_at(pixels, width, 0, height - 1),
        rgba_at(pixels, width, width - 1, height - 1),
    ]
    if any(corner[3] != 0 for corner in corners):
        raise AssertionError(f"{path.relative_to(REPO_ROOT)} must have transparent outer corners: {corners}")

    interior = [
        rgba_at(pixels, width, width // 2, height // 8),
        rgba_at(pixels, width, width // 8, height // 2),
        rgba_at(pixels, width, width * 7 // 8, height // 2),
        rgba_at(pixels, width, width // 2, height * 7 // 8),
    ]
    if any(pixel != (255, 255, 255, 255) for pixel in interior):
        raise AssertionError(f"{path.relative_to(REPO_ROOT)} must have a white opaque rounded-square body: {interior}")

    dark_pixels = 0
    for y in range(height // 4, height * 3 // 4):
        for x in range(width // 4, width * 3 // 4):
            red, green, blue, alpha = rgba_at(pixels, width, x, y)
            if alpha == 255 and red < 80 and green < 80 and blue < 80:
                dark_pixels += 1
    if dark_pixels == 0:
        raise AssertionError(f"{path.relative_to(REPO_ROOT)} is missing the dark product mark")


def main() -> None:
    for path in ICON_PATHS:
        width, height, pixels = read_png_rgba(path)
        assert_rounded_white_background(path, width, height, pixels)
    for index, (width, height, pixels) in enumerate(read_ico_pngs(ICO_PATH), start=1):
        assert_rounded_white_background(ICO_PATH.with_name(f"{ICO_PATH.stem}-{index}.png"), width, height, pixels)
    print("desktop icon background smoke passed")


if __name__ == "__main__":
    main()
