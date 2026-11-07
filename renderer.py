"""Render real remaining allowances on the AMG65's 63 × 5 LED matrix.

The output is logical left-to-right RGB pixels. USB memory ordering belongs to
the transport. A=Claude, X=Codex, C=Cursor; numbers are percentages remaining.
"""
from __future__ import annotations

import math

WIDTH, HEIGHT = 63, 5
COLORS = {"claude": (245, 177, 106), "codex": (123, 220, 176), "cursor": (134, 190, 248)}
PROVIDERS = (("claude", "A"), ("codex", "X"), ("cursor", "C"))
UNKNOWN = (132, 144, 157)
BLACK = (0, 0, 0)
FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "L": ("100", "100", "100", "100", "111"),
    "O": ("111", "101", "101", "101", "111"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "U": ("101", "101", "101", "101", "111"),
    "X": ("101", "101", "010", "101", "101"),
    "-": ("000", "000", "111", "000", "000"),
    "%": ("101", "001", "010", "100", "101"),
    "?": ("111", "001", "011", "000", "010"),
    " ": ("0", "0", "0", "0", "0"),
}

FONT.update({
    'B':('110','101','110','101','110'),'F':('111','100','110','100','100'),
    'G':('011','100','101','101','011'),'H':('101','101','111','101','101'),
    'I':('111','010','010','010','111'),'J':('001','001','001','101','010'),
    'K':('101','110','100','110','101'),'M':('10001','11011','10101','10001','10001'),
    'N':('1001','1101','1011','1001','1001'),'P':('110','101','110','100','100'),
    'Q':('111','101','101','111','001'),'T':('111','010','010','010','010'),
    'V':('101','101','101','101','010'),'W':('10001','10001','10101','11011','01010'),
    'Y':('101','101','010','010','010'),'Z':('111','001','010','100','111'),
    '.':('0','0','0','0','1'),':':('0','1','0','1','0'),
    '!':('1','1','1','0','1'),'/':('001','001','010','100','100'),
})


def _value(provider):
    value = provider.get("remaining_percent")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= 100 else None


def _color(provider, brightness):
    factor = brightness * (0.45 if provider.get("stale") else 1.0)
    rgb = COLORS.get(provider.get("id"), UNKNOWN) if _value(provider) is not None else UNKNOWN
    return tuple(round(min(254, channel) * factor) for channel in rgb)


def _brightness(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("brightness must be a finite number between 0 and 1")
    if not 0 <= value <= 1:
        raise ValueError("brightness must be between 0 and 1")
    return value


def _text(pixels, text, x, color, right=56):
    for char in text:
        glyph = FONT.get(char, FONT["?"])
        for y, row in enumerate(glyph):
            for dx, bit in enumerate(row):
                if bit == "1" and 0 <= x + dx < right:
                    pixels[y * WIDTH + x + dx] = color
        x += len(glyph[0]) + 1


def _bars(pixels, providers, brightness):
    for index, provider in enumerate(providers):
        x = 57 + index * 2
        value = _value(provider)
        color = _color(provider, brightness)
        if value is None:
            pixels[2 * WIDTH + x] = color
            continue
        # A nonzero allowance always retains one visible level. Zero is only
        # represented by a dim baseline, distinct from unavailable (middle dot).
        height = math.ceil(value / 20)
        for y in range(5):
            pixels[y * WIDTH + x] = color if y >= 5 - height else tuple(v // 10 for v in color)


def render_overview(snapshot: dict, brightness: float = 0.4) -> list[tuple[int, int, int]]:
    """Three concurrent percentages in 56 columns, with three right-side meters.

    Unknown values are ``--``. Stale values are dimmed and marked with a small
    amber pixel at the end of their cell. No percentages are inferred from errors.
    """
    brightness = _brightness(brightness)
    pixels = [BLACK] * (WIDTH * HEIGHT)
    entries = {p.get("id"): p for p in snapshot.get("providers", []) if isinstance(p, dict)}
    providers = []
    for index, (provider_id, letter) in enumerate(PROVIDERS):
        provider = entries.get(provider_id, {"id": provider_id})
        providers.append(provider)
        value = _value(provider)
        text = letter + (str(round(value)) if value is not None else "--")
        _text(pixels, text, index * 19, _color(provider, brightness), min(56, index * 19 + 18))
        if provider.get("stale"):
            pixels[min(55, index * 19 + 17)] = tuple(round(v * brightness) for v in (245, 177, 106))
    _bars(pixels, providers, brightness)
    return pixels


def render_detail(provider: dict, brightness: float = 0.4) -> list[tuple[int, int, int]]:
    """Show a provider's full name and its selected remaining percentage."""
    brightness = _brightness(brightness)
    pixels = [BLACK] * (WIDTH * HEIGHT)
    label = {"claude": "CLAUDE", "codex": "CODEX", "cursor": "CURSOR"}.get(provider.get("id"), "?")
    color = _color(provider, brightness)
    _text(pixels, label, 0, color)
    value = _value(provider)
    _text(pixels, "--" if value is None else f"{round(value)}%", 31, color)
    if provider.get("stale"):
        _text(pixels, "?", 58, tuple(round(v * brightness) for v in (245, 177, 106)), 63)
    elif value is None:
        _text(pixels, "?", 58, color, 63)
    else:
        height = math.ceil(value / 20)
        for x in (58, 59, 60):
            for y in range(5):
                pixels[y * WIDTH + x] = color if y >= 5 - height else tuple(v // 10 for v in color)
    return pixels


def render_text(text: str, hex_color: str, brightness: float, elapsed: float=0) -> list[tuple[int,int,int]]:
    """Bounded marquee; short text stays centered, long text scrolls at 2px/s."""
    brightness=_brightness(brightness)
    rgb=tuple(round(min(254,int(hex_color[i:i+2],16))*brightness) for i in (1,3,5))
    width=sum(len(FONT.get(c,FONT['?'])[0])+1 for c in text)-1
    x=max(0,(56-width)//2) if width<=56 else 56-int(max(0,elapsed)*2)%(width+68)
    pixels=[BLACK]*(WIDTH*HEIGHT)
    _text(pixels,text,x,rgb)
    _text(pixels,'*',58,rgb,63)
    return pixels
