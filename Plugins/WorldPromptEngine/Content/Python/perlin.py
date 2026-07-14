"""
perlin.py — Standalone Ken Perlin Improved Noise (2002), pure Python.

No imports. No numpy. Deterministic: identical seed => identical output.
art_engine keeps its own internal noise classes; this module is the
canonical standalone implementation for tools, tests, and external callers.
"""

_BASE_PERM = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
    140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148,
    247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32,
    57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122,
    60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54,
    65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169,
    200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64,
    52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212,
    207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213,
    119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9,
    129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104,
    218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241,
    81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157,
    184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93,
    222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
]


def _build_perm(seed):
    """Doubled 512-entry permutation table, deterministically seeded."""
    seed = int(seed) & 0xFFFFFFFF
    table = list(_BASE_PERM)
    # xorshift32 deterministic shuffle
    s = seed if seed != 0 else 0x9E3779B9
    for i in range(255, 0, -1):
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= (s >> 17)
        s ^= (s << 5) & 0xFFFFFFFF
        j = s % (i + 1)
        table[i], table[j] = table[j], table[i]
    return table + table


P = _build_perm(0)


def set_seed(seed):
    """Rebuild the module-level permutation table for a given seed."""
    global P
    P = _build_perm(seed)


def fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def lerp(t, a, b):
    return a + t * (b - a)


def grad(h, x, y, z):
    h = h & 15
    u = x if h < 8 else y
    if h < 4:
        v = y
    elif h == 12 or h == 14:
        v = x
    else:
        v = z
    return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)


def noise(x, y, z=0.0, perm=None):
    """Improved Perlin noise, approx -1.0..1.0."""
    p = perm if perm is not None else P
    xi = int(x // 1) & 255
    yi = int(y // 1) & 255
    zi = int(z // 1) & 255
    xf = x - (x // 1)
    yf = y - (y // 1)
    zf = z - (z // 1)
    u = fade(xf)
    v = fade(yf)
    w = fade(zf)

    a = p[xi] + yi
    aa = p[a] + zi
    ab = p[a + 1] + zi
    b = p[xi + 1] + yi
    ba = p[b] + zi
    bb = p[b + 1] + zi

    return lerp(w,
        lerp(v,
            lerp(u, grad(p[aa], xf, yf, zf), grad(p[ba], xf - 1, yf, zf)),
            lerp(u, grad(p[ab], xf, yf - 1, zf), grad(p[bb], xf - 1, yf - 1, zf))),
        lerp(v,
            lerp(u, grad(p[aa + 1], xf, yf, zf - 1), grad(p[ba + 1], xf - 1, yf, zf - 1)),
            lerp(u, grad(p[ab + 1], xf, yf - 1, zf - 1), grad(p[bb + 1], xf - 1, yf - 1, zf - 1))))


def octave_noise(x, y, octaves, persistence, lacunarity, perm=None):
    """Fractal Brownian motion sum of octave layers, normalized to -1..1."""
    total = 0.0
    freq = 1.0
    amp = 1.0
    max_amp = 0.0
    for _ in range(max(1, int(octaves))):
        total += noise(x * freq, y * freq, 0.0, perm) * amp
        max_amp += amp
        amp *= persistence
        freq *= lacunarity
    return total / max_amp if max_amp > 0.0 else 0.0


def noise_2d_grid(width, height, scale, octaves, persistence, lacunarity, seed=0):
    """2D grid of normalized 0.0-1.0 floats. Deterministic per seed."""
    perm = _build_perm(seed)
    grid = []
    lo = 1e30
    hi = -1e30
    for y in range(int(height)):
        row = []
        for x in range(int(width)):
            v = octave_noise(x * scale, y * scale, octaves, persistence, lacunarity, perm)
            if v < lo:
                lo = v
            if v > hi:
                hi = v
            row.append(v)
        grid.append(row)
    span = hi - lo
    if span <= 1e-12:
        return [[0.5 for _ in range(int(width))] for _ in range(int(height))]
    inv = 1.0 / span
    for y in range(int(height)):
        row = grid[y]
        for x in range(int(width)):
            row[x] = (row[x] - lo) * inv
    return grid
