"""Small monochrome icons drawn with Pillow so the Deck and the desktop match."""

from PIL import Image, ImageDraw
import customtkinter as ctk

_pil_cache: dict = {}
_INK = (248, 250, 252, 255)


def icon(name: str, size: int = 20):
    """Return a CTkImage for the current Tk interpreter. PIL bitmaps are cached."""
    key = (name, size)
    image = _pil_cache.get(key)
    if image is None:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        _draw(ImageDraw.Draw(image), name, size)
        _pil_cache[key] = image
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def _draw(draw: ImageDraw.ImageDraw, name: str, size: int) -> None:
    ink = _INK
    stroke = max(2, size // 10)
    pad = size * 0.18
    if name == "search":
        radius = size * 0.28
        draw.ellipse((pad, pad, pad + radius * 2, pad + radius * 2), outline=ink, width=stroke)
        draw.line((pad + radius * 1.7, pad + radius * 1.7, size - pad, size - pad), fill=ink, width=stroke)
    elif name == "scan":
        draw.arc((pad, pad, size - pad, size - pad), start=40, end=320, fill=ink, width=stroke)
        draw.polygon(
            [(size - pad, pad), (size - pad - size * 0.22, pad + size * 0.02), (size - pad, pad + size * 0.24)],
            fill=ink,
        )
    elif name == "plus":
        mid = size / 2
        draw.line((pad, mid, size - pad, mid), fill=ink, width=stroke)
        draw.line((mid, pad, mid, size - pad), fill=ink, width=stroke)
    elif name == "gear":
        mid = size / 2
        outer = size * 0.34
        draw.ellipse((mid - outer, mid - outer, mid + outer, mid + outer), outline=ink, width=stroke)
        inner = size * 0.12
        draw.ellipse((mid - inner, mid - inner, mid + inner, mid + inner), outline=ink, width=stroke)
        for angle_pad in (pad, size - pad):
            draw.line((mid, angle_pad, mid, angle_pad + size * 0.08), fill=ink, width=stroke)
            draw.line((angle_pad, mid, angle_pad + size * 0.08, mid), fill=ink, width=stroke)
    elif name == "back":
        mid = size / 2
        draw.line((size * 0.62, pad, size * 0.32, mid), fill=ink, width=stroke)
        draw.line((size * 0.32, mid, size * 0.62, size - pad), fill=ink, width=stroke)
    elif name == "close":
        draw.line((pad, pad, size - pad, size - pad), fill=ink, width=stroke)
        draw.line((size - pad, pad, pad, size - pad), fill=ink, width=stroke)
    elif name == "grid":
        gap = size * 0.14
        cell = (size - pad * 2 - gap) / 2
        for row in (0, 1):
            for col in (0, 1):
                x0 = pad + col * (cell + gap)
                y0 = pad + row * (cell + gap)
                draw.rectangle((x0, y0, x0 + cell, y0 + cell), outline=ink, width=stroke)
    elif name == "list":
        for step in (0.28, 0.5, 0.72):
            y = size * step
            draw.line((pad, y, size - pad, y), fill=ink, width=stroke)
    elif name == "chevron":
        mid = size / 2
        draw.line((pad, size * 0.38, mid, size * 0.62), fill=ink, width=stroke)
        draw.line((mid, size * 0.62, size - pad, size * 0.38), fill=ink, width=stroke)
    else:
        draw.ellipse((pad, pad, size - pad, size - pad), outline=ink, width=stroke)
