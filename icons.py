"""Small anti-aliased icons for the PL100 display, as LVGL v7 image data.

The firmware's own icons are LV_IMG_CF_TRUE_COLOR_ALPHA with 16-bit colour:
3 bytes per pixel, RGB565 little-endian followed by an 8-bit alpha. White
line art like the repeat icons (~#E8E8E8); drawn by supersampling simple shapes.
"""
import math
import struct

SS = 4  # supersampling per axis


def _seg_dist2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx - px, ay + t * dy - py
    return qx * qx + qy * qy


def _in_poly(px, py, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def render(w, h, lines=(), polys=(), width=2.0):
    """Alpha map (0..255) for strokes (line segments) and filled polygons."""
    r2 = (width / 2) ** 2
    alpha = []
    for y in range(h):
        for x in range(w):
            hits = 0
            for sy in range(SS):
                for sx in range(SS):
                    px, py = x + (sx + 0.5) / SS, y + (sy + 0.5) / SS
                    if any(_seg_dist2(px, py, *seg) <= r2 for seg in lines) or \
                            any(_in_poly(px, py, p) for p in polys):
                        hits += 1
            alpha.append(round(255 * hits / (SS * SS)))
    return alpha


def hourglass(size=30):
    """Hourglass: top and bottom bar, two glass sides, sand in the bottom bulb."""
    s = size / 30
    p = lambda x, y: (x * s, y * s)  # noqa: E731
    bars = [(*p(7, 4), *p(23, 4)), (*p(7, 26), *p(23, 26))]
    glass = [(*p(9, 5), *p(14, 15)), (*p(14, 15), *p(9, 25)),
             (*p(21, 5), *p(16, 15)), (*p(16, 15), *p(21, 25)),
             (*p(14, 15), *p(16, 15))]
    sand = [[p(11, 25), p(15, 19), p(19, 25)],      # bottom heap
            [p(12, 8), p(18, 8), p(15, 12)]]        # what is left on top
    return render(size, size, lines=bars + glass, polys=sand, width=1.6 * s)


def render_polar(size, inside):
    """Alpha map for a shape given as inside(r, angle) around the centre."""
    c = size / 2
    alpha = []
    for y in range(size):
        for x in range(size):
            hits = 0
            for sy in range(SS):
                for sx in range(SS):
                    px, py = x + (sx + 0.5) / SS - c, y + (sy + 0.5) / SS - c
                    if inside(math.hypot(px, py), math.atan2(py, px)):
                        hits += 1
            alpha.append(round(255 * hits / (SS * SS)))
    return alpha


def cd(size=64):
    """Solid compact disc with a centre hole and two reflection arcs cut out."""
    s = size / 40

    def ring(r, radius, width):
        return abs(r - radius * s) <= width * s / 2

    def shine(r, a):
        return (ring(r, 13, 1.6) and -2.6 < a < -1.7) or (ring(r, 10.2, 1.6) and -2.5 < a < -1.9)

    return render_polar(size, lambda r, a: (7.5 * s < r <= 19.3 * s and not shine(r, a)) or ring(r, 4, 1.4))


def lv_img_true_color_alpha(alpha, w, h, rgb=(232, 232, 232)):
    """(header, pixel data) for an LVGL v7 TRUE_COLOR_ALPHA image, 16-bit colour."""
    r, g, b = rgb
    c565 = (r >> 3) << 11 | (g >> 2) << 5 | b >> 3
    data = b''.join(struct.pack('<HB', c565, a) for a in alpha)
    header = 5 | w << 10 | h << 21          # cf = TRUE_COLOR_ALPHA
    return header, data


def lv_img_alpha4(alpha, w, h):
    """(header, pixel data) for an LVGL v7 ALPHA_4BIT image: opacity only, 2
    pixels per byte (left one in the high nibble), each row starting on a byte;
    drawn in the object's image recolor colour."""
    nib = [round(a * 15 / 255) for a in alpha]
    rows = [nib[y * w:(y + 1) * w] + [0] * (w % 2) for y in range(h)]
    data = bytes(r[x] << 4 | r[x + 1] for r in rows for x in range(0, len(r), 2))
    header = 13 | w << 10 | h << 21         # cf = ALPHA_4BIT
    return header, data
