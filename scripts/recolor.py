"""Recolor git-bonsai output with a comet-night palette.

git-bonsai renders every image from one fixed 32-slot palette, and the GIFs
store it as a single global color table. Swapping slots there recolors the
GIFs; the PNG/SVG are truecolor, so their pixels are remapped by exact RGB.
Idempotent: a second run maps each color onto itself.

usage: python3 scripts/recolor.py [output-dir]
"""
import base64
import re
import struct
import sys
import zlib
from pathlib import Path

# palette slot -> new color, dark -> light within each ramp
PALETTE = {
    # leaf epoch 0 (oldest third of the account): twilight rose
    17: '#4a1f4f', 18: '#73306f', 19: '#a04c8e', 20: '#d27fb6',
    # leaf epoch 1: comet blue fading to its cyan head
    21: '#0b2f7a', 22: '#1257ab', 23: '#2a8bd8', 24: '#7ccdf2',
    # leaf epoch 2 (newest): violet
    28: '#2b1d6b', 29: '#4a32a6', 30: '#7253dc', 31: '#a98ff7',
}

GCT_OFFSET = 13  # GIF header (6) + logical screen descriptor (7)


def rgb(color):
    return bytes.fromhex(color[1:])


def gif_palette(data):
    assert data[:6] in (b'GIF87a', b'GIF89a') and data[10] & 0x80, 'GIF without a global color table'
    size = 3 << ((data[10] & 0x07) + 1)
    return data[GCT_OFFSET:GCT_OFFSET + size]


def recolor_gif(data):
    out = bytearray(data)
    for slot, color in PALETTE.items():
        out[GCT_OFFSET + slot * 3:GCT_OFFSET + slot * 3 + 3] = rgb(color)
    return bytes(out)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def png_chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def recolor_png(data, mapping):
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    chunks, pos = [], 8
    while pos < len(data):
        (length,) = struct.unpack('>I', data[pos:pos + 4])
        chunks.append((data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]))
        pos += 12 + length
    ihdr = chunks[0][1]
    w, h, depth, ctype = struct.unpack('>IIBB', ihdr[:10])
    assert depth == 8 and ctype == 6, 'expected 8-bit RGBA'
    raw = zlib.decompress(b''.join(body for kind, body in chunks if kind == b'IDAT'))

    stride, bpp = w * 4, 4
    prev, rows = bytearray(stride), []
    for y in range(h):
        ftype = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            c = prev[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + (0, a, prev[i], (a + prev[i]) // 2, paeth(a, prev[i], c))[ftype]) & 0xff
        rows.append(line)
        prev = line

    for line in rows:
        for i in range(0, stride, 4):
            new = mapping.get(bytes(line[i:i + 3]))
            if new:
                line[i:i + 3] = new

    idat = zlib.compress(b''.join(b'\x00' + bytes(line) for line in rows), 9)
    tail = [png_chunk(kind, body) for kind, body in chunks[1:] if kind not in (b'IDAT', b'IEND')]
    return data[:8] + png_chunk(b'IHDR', ihdr) + b''.join(tail) + png_chunk(b'IDAT', idat) + png_chunk(b'IEND', b'')


def recolor_svg(text, mapping):
    def swap(m):
        png = recolor_png(base64.b64decode(m.group(2)), mapping)
        return m.group(1) + base64.b64encode(png).decode()
    return re.sub(r'(data:image/png;base64,)([A-Za-z0-9+/=]+)', swap, text)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'output')
    gifs = [out / 'bonsai.gif', out / 'bonsai-growth.gif']

    # the original slot colors tell us which RGB values to remap in PNG/SVG
    old = gif_palette(gifs[0].read_bytes())
    others = {old[s * 3:s * 3 + 3] for s in range(len(old) // 3) if s not in PALETTE}
    mapping = {}
    for slot, color in PALETTE.items():
        before = old[slot * 3:slot * 3 + 3]
        assert before not in others, f'slot {slot} shares its color with a non-leaf slot'
        mapping[before] = rgb(color)

    for gif in gifs:
        gif.write_bytes(recolor_gif(gif.read_bytes()))
    (out / 'bonsai.png').write_bytes(recolor_png((out / 'bonsai.png').read_bytes(), mapping))
    svg = out / 'bonsai.svg'
    svg.write_text(recolor_svg(svg.read_text(), mapping))
    print(f'recolored {len(PALETTE)} palette slots in {out}/')


if __name__ == '__main__':
    main()
