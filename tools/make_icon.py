"""Midnight app icon generator for FPS Patcher Studio."""

from __future__ import annotations

import io
import math
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "src" / "fps_patcher" / "ui" / "assets"
BUILD_DIR = ROOT / "build"
FALLBACK_DIR = Path.home() / "Documents" / "Universal"

SIZES = [16, 24, 32, 48, 64, 128, 256]


def squircle(cx: float, cy: float, r: float, n: float = 5, steps: int = 240) -> str:
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = cx + r * math.copysign(abs(c) ** (2 / n), c)
        y = cy + r * math.copysign(abs(s) ** (2 / n), s)
        pts.append(f"{x:.1f},{y:.1f}")
    return "M" + " L".join(pts) + " Z"


SQ = squircle(512, 512, 484)
BOLT = "M585,170 L318,566 L488,566 L436,858 L714,432 L540,432 Z"


def svg(small: bool = False) -> str:
    gauge = (
        ""
        if small
        else (
            '  <g transform="rotate(135 512 548)" fill="none" stroke-linecap="round">\n'
            '    <circle cx="512" cy="548" r="348" stroke="#FFFFFF" stroke-opacity=".10" '
            'stroke-width="40" stroke-dasharray="1642 2187"/>\n'
            '    <circle cx="512" cy="548" r="348" stroke="#0A84FF" stroke-width="40" '
            'stroke-dasharray="1230 2187"/>\n'
            "  </g>"
        )
    )
    scale = (
        'transform="translate(512 540) scale(1.12) translate(-512 -540)"'
        if small
        else ""
    )
    defs = (
        "<defs>\n"
        '  <linearGradient id="bg" x1="0.2" y1="0" x2="0.8" y2="1">'
        '<stop offset="0" stop-color="#2C2C2E"/>'
        '<stop offset=".5" stop-color="#1C1C1E"/>'
        '<stop offset="1" stop-color="#000000"/></linearGradient>\n'
        '  <linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#fff" stop-opacity=".22"/>'
        '<stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>\n'
        '  <linearGradient id="bolt" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#FFFFFF"/>'
        '<stop offset="1" stop-color="#BFDDFF"/></linearGradient>\n'
        '  <filter id="sh" x="-30%" y="-30%" width="160%" height="170%">'
        '<feDropShadow dx="0" dy="26" stdDeviation="26" '
        'flood-color="#0A84FF" flood-opacity=".55"/></filter>\n'
        f'  <clipPath id="clip"><path d="{SQ}"/></clipPath>\n'
        "</defs>"
    )
    body = (
        f'<path d="{SQ}" fill="url(#bg)"/>\n'
        '<g clip-path="url(#clip)"><rect width="1024" height="520" fill="url(#gloss)"/>'
        f'<path d="{SQ}" fill="none" stroke="#fff" stroke-opacity=".18" stroke-width="4"/></g>\n'
        f"{gauge}\n"
        f'<g {scale}><path d="{BOLT}" fill="url(#bolt)" stroke="url(#bolt)" '
        'stroke-width="36" stroke-linejoin="round" filter="url(#sh)"/></g>'
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" '
        'width="1024" height="1024">\n'
        f"{defs}\n"
        f"{body}\n"
        "</svg>"
    )


def render(small: bool, size: int) -> Image.Image:
    import cairosvg  # type: ignore[import-untyped]

    png: bytes = cairosvg.svg2png(
        bytestring=svg(small).encode("utf-8"),
        output_width=size,
        output_height=size,
    )
    return Image.open(io.BytesIO(png)).convert("RGBA")


def build_icons() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Save SVG files
    svg_full = svg(small=False)
    svg_small = svg(small=True)
    (ASSETS_DIR / "app_icon.svg").write_text(svg_full, encoding="utf-8")
    (ASSETS_DIR / "app_icon_small.svg").write_text(svg_small, encoding="utf-8")
    print(f"Wrote {ASSETS_DIR / 'app_icon.svg'}")
    print(f"Wrote {ASSETS_DIR / 'app_icon_small.svg'}")

    # 2. Try rendering with cairosvg
    rendered = False
    imgs: dict[int, Image.Image] = {}
    try:
        print("Rendering multi-size images via cairosvg...")
        for s in SIZES:
            imgs[s] = render(s <= 32, s)
        img_1024 = render(False, 1024)
        img_1024.save(ASSETS_DIR / "app_icon.png")
        rendered = True
    except Exception as exc:
        print(f"cairosvg rendering unavailable ({exc}). Using pre-rendered assets...")
        fallback_png = FALLBACK_DIR / "icon-midnight.png"
        fallback_ico = FALLBACK_DIR / "app-midnight.ico"
        if fallback_png.is_file():
            shutil.copyfile(fallback_png, ASSETS_DIR / "app_icon.png")
            print(f"Copied {fallback_png} -> {ASSETS_DIR / 'app_icon.png'}")
        if fallback_ico.is_file():
            shutil.copyfile(fallback_ico, BUILD_DIR / "app.ico")
            shutil.copyfile(fallback_ico, ASSETS_DIR / "app.ico")
            print(f"Copied {fallback_ico} -> {BUILD_DIR / 'app.ico'} & {ASSETS_DIR / 'app.ico'}")
            return

    if rendered:
        ico_256 = imgs[256]
        append_imgs = [imgs[s] for s in SIZES if s != 256]
        ico_sizes: Any = [(s, s) for s in SIZES]

        for dest in (BUILD_DIR / "app.ico", ASSETS_DIR / "app.ico"):
            ico_256.save(dest, format="ICO", sizes=ico_sizes, append_images=append_imgs)
            print(f"Saved {dest}")


if __name__ == "__main__":
    build_icons()
