#!/usr/bin/env python3
"""Rasterise assets/icon.svg into PNGs and a macOS .icns iconset.

Uses PyQt6's QtSvg renderer (already a project dependency) so no extra tools are
required. Produces assets/icon.png (1024px) and assets/icon.icns.
"""
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "icon.svg"
PNG = ROOT / "assets" / "icon.png"
ICNS = ROOT / "assets" / "icon.icns"


def render(size: int) -> QImage:
    renderer = QSvgRenderer(str(SVG))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    renderer.render(p)
    p.end()
    return img


def main():
    app = QApplication(sys.argv)  # noqa: F841 - needed for QImage/QPainter

    render(1024).save(str(PNG), "PNG")
    print(f"wrote {PNG}")

    iconset = ROOT / "assets" / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
    for base, scale in specs:
        px = base * scale
        name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
        render(px).save(str(iconset / name), "PNG")

    # iconutil ships with macOS; build the .icns from the iconset.
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset),
                        "-o", str(ICNS)], check=True)
        print(f"wrote {ICNS}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"iconutil unavailable ({e}); PNG icon still written.")


if __name__ == "__main__":
    main()
