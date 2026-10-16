"""Tiny QR code encoder (byte mode, error correction M, versions 1-10 = up to 213 bytes) - standard library only, so
the phone-link QR code works without 'pip install qrcode'. matrix(text) -> list of rows of bools (no quiet zone).
Follows ISO/IEC 18004: Reed-Solomon over GF(256) (poly 0x11d), all 8 masks scored with the 4 penalty rules."""

# version -> (EC codewords per block, [(number of blocks, data codewords per block), ...])  (level M)
_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
    6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}
_REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_ec(data, n):
    gen = [1]
    for i in range(n):  # (x - a^0)(x - a^1)...(x - a^(n-1))
        gen = [a ^ _gmul(b, _EXP[i]) for a, b in zip(gen + [0], [0] + gen)]
    rem = [0] * n
    for d in data:
        f = d ^ rem[0]
        rem = rem[1:] + [0]
        for j in range(n):
            rem[j] ^= _gmul(gen[j + 1], f)
    return rem


def _bch(value, poly, bits):
    v = value << bits
    top = poly.bit_length() - 1
    while v.bit_length() - 1 >= top:
        v ^= poly << (v.bit_length() - 1 - top)
    return (value << bits) | v


def _codewords(data, ver):
    ec, groups = _M[ver]
    cap = sum(b * d for b, d in groups)
    bits = [0, 1, 0, 0]  # byte mode
    nlen = 8 if ver < 10 else 16
    bits += [(len(data) >> i) & 1 for i in range(nlen - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(cw) < cap:
        cw.append(pad[(len(cw) - len(bits) // 8) % 2])
    blocks, i = [], 0
    for b, d in groups:
        for _ in range(b):
            blocks.append(cw[i:i + d])
            i += d
    ecb = [_rs_ec(bl, ec) for bl in blocks]
    out = []
    for k in range(max(len(bl) for bl in blocks)):
        out += [bl[k] for bl in blocks if k < len(bl)]
    for k in range(ec):
        out += [e[k] for e in ecb]
    return out


def _capacity(ver):
    _, groups = _M[ver]
    return sum(b * d for b, d in groups) - (2 if ver < 10 else 3)


def _base(ver):
    n = 17 + 4 * ver
    m = [[None] * n for _ in range(n)]

    def put(r, c, v):
        if 0 <= r < n and 0 <= c < n:
            m[r][c] = v

    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                on = 0 <= r <= 6 and 0 <= c <= 6 and (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
                put(r0 + r, c0 + c, on)
    for i in range(8, n - 8):
        m[6][i] = m[i][6] = i % 2 == 0
    pos = _ALIGN[ver]
    for r in pos:
        for c in pos:
            if (r, c) in ((pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])):
                continue  # those three would sit on the finder patterns
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1
    m[n - 8][8] = True  # dark module
    reserved = [[v is not None for v in row] for row in m]
    for i in range(9):  # format areas
        reserved[8][i] = reserved[i][8] = True
    for i in range(8):
        reserved[8][n - 1 - i] = reserved[n - 1 - i][8] = True
    if ver >= 7:
        for i in range(6):
            for j in range(3):
                reserved[i][n - 11 + j] = reserved[n - 11 + j][i] = True
    return m, reserved


_MASKS = [
    lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0, lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0, lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0, lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _place(m, reserved, cw, ver):
    n = len(m)
    bits = [(b >> i) & 1 for b in cw for i in range(7, -1, -1)] + [0] * _REMAINDER[ver]
    k, up, c = 0, True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for cc in (c, c - 1):
                if not reserved[r][cc]:
                    m[r][cc] = bool(bits[k]) if k < len(bits) else False
                    k += 1
        up = not up
        c -= 2


def _format(m, mask, ver):
    n = len(m)
    f = _bch((0b00 << 3) | mask, 0b10100110111, 10) ^ 0b101010000010010  # EC level M = 00
    b = [(f >> i) & 1 for i in range(14, -1, -1)]  # b[0] = bit 14
    seq1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8),
            (1, 8), (0, 8)]
    for (r, c), v in zip(seq1, b):
        m[r][c] = bool(v)
    seq2 = [(n - 1 - i, 8) for i in range(7)] + [(8, n - 8 + i) for i in range(8)]
    for (r, c), v in zip(seq2, b):
        m[r][c] = bool(v)
    if ver >= 7:
        v = _bch(ver, 0b1111100100101, 12)
        for i in range(18):
            bit = bool((v >> i) & 1)
            r, c = i // 3, i % 3
            m[r][n - 11 + c] = bit
            m[n - 11 + c][r] = bit


def _penalty(m):
    n = len(m)
    p = 0
    for lines in (m, [list(col) for col in zip(*m)]):
        for row in lines:
            run = 1
            for i in range(1, n):
                if row[i] == row[i - 1]:
                    run += 1
                else:
                    p += run - 2 if run >= 5 else 0
                    run = 1
            p += run - 2 if run >= 5 else 0
            s = "".join("1" if v else "0" for v in row)
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    dark = sum(v for row in m for v in row)
    p += abs(dark * 20 // (n * n) - 10) * 10
    return p


def matrix(text):
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    ver = next((v for v in range(1, 11) if _capacity(v) >= len(data)), None)
    if ver is None:
        raise ValueError("text too long for a version 1-10 QR code (%d bytes)" % len(data))
    cw = _codewords(data, ver)
    best = None
    for mask in range(8):
        m, reserved = _base(ver)
        _place(m, reserved, cw, ver)
        fn = _MASKS[mask]
        for r in range(len(m)):
            for c in range(len(m)):
                if not reserved[r][c] and fn(r, c):
                    m[r][c] = not m[r][c]
        _format(m, mask, ver)
        sc = _penalty(m)
        if best is None or sc < best[0]:
            best = (sc, m)
    return [[bool(v) for v in row] for row in best[1]]
