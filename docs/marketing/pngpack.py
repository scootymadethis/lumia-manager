"""Shrink a Chrome screenshot of og-card.html into lumia/static/og-card.png (standard library only).

usage: python docs/marketing/pngpack.py screenshot.png lumia/static/og-card.png

Chrome dithers CSS gradients, and that noise is most of the screenshot's weight.
Where a whole 7×7 window is flat (every channel within 6 levels), the pixel takes
the window's mean; text, the mark and every edge keep their exact pixels (no pixel
moves by more than a few levels). The result is written as 8-bit RGB at zlib level 9
with a per-row filter choice.
"""
import struct
import sys
import zlib

WINDOW, LIMIT = 7, 6


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def read_png(path):
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    pos, idat, ihdr = 8, b'', None
    while pos < len(data):
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat += body
        pos += 12 + length
    width, height, depth, ctype, _, _, interlace = ihdr
    assert depth == 8 and ctype in (2, 6) and not interlace, 'expected 8-bit RGB or RGBA'
    bpp = 4 if ctype == 6 else 3
    raw, stride = zlib.decompress(idat), width * bpp
    pixels, prev = [], bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            line[i] = (line[i] + (0, a, b, (a + b) >> 1, paeth(a, b, c))[f]) & 255
        for x in range(width):
            o = x * bpp
            assert bpp == 3 or line[o + 3] == 255, 'the card must be opaque'
            pixels.append((line[o], line[o + 1], line[o + 2]))
        prev = line
    return width, height, pixels


def sliding(seq, fn):
    r = WINDOW // 2
    pad = [seq[0]] * r + list(seq) + [seq[-1]] * r
    return [fn(t) for t in zip(*(pad[i:i + len(seq)] for i in range(WINDOW)))]


def smooth_flat(width, height, pixels):
    flat = [True] * len(pixels)
    means = []
    for ch in range(3):
        plane = [p[ch] for p in pixels]
        rows = [plane[y * width:(y + 1) * width] for y in range(height)]
        hi, lo, total = ([sliding(r, fn) for r in rows] for fn in (max, min, sum))
        mean = [0.0] * len(pixels)
        for x in range(width):
            col_hi = sliding([hi[y][x] for y in range(height)], max)
            col_lo = sliding([lo[y][x] for y in range(height)], min)
            col_sum = sliding([total[y][x] for y in range(height)], sum)
            for y in range(height):
                i = y * width + x
                if col_hi[y] - col_lo[y] > LIMIT:
                    flat[i] = False
                mean[i] = col_sum[y] / (WINDOW * WINDOW)
        means.append(mean)
    return [tuple(round(means[ch][i]) for ch in range(3)) if flat[i] else p for i, p in enumerate(pixels)]


def write_png(path, width, height, pixels):
    out, prev = bytearray(), bytearray(width * 3)
    for y in range(height):
        line = bytearray(b for p in pixels[y * width:(y + 1) * width] for b in p)
        best = None
        for f in range(5):
            res = bytearray(len(line))
            for i in range(len(line)):
                a = line[i - 3] if i >= 3 else 0
                b, c = prev[i], (prev[i - 3] if i >= 3 else 0)
                res[i] = (line[i] - (0, a, b, (a + b) >> 1, paeth(a, b, c))[f]) & 255
            score = sum(v if v < 128 else 256 - v for v in res)
            if best is None or score < best[0]:
                best = (score, f, res)
        out.append(best[1])
        out += best[2]
        prev = line

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(out), 9)) + chunk(b'IEND', b''))
    open(path, 'wb').write(png)
    return len(png)


if __name__ == '__main__':
    src, dst = sys.argv[1:3]
    width, height, pixels = read_png(src)
    print(f'{width}x{height}: {write_png(dst, width, height, smooth_flat(width, height, pixels))} bytes')
