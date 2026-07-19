#!/usr/bin/env python3
"""Erzeugt ein Zeitraffer-GIF aus den lokal heruntergeladenen Kamera-Fotos.

Die Fotos holt man vorher mit scripts/fetch-photos.ps1 (Default-Ziel: camera-photos/).
Dateien heissen photo_YYYYMMDD_HHMMSS.jpg — daraus wird pro Frame ein Zeitstempel
eingeblendet und chronologisch animiert.

Beispiele (aus dem Repo-Wurzelverzeichnis):
    python scripts/make-timelapse.py
    python scripts/make-timelapse.py --src camera-photos/Garten01 --width 800 --colors 256
    python scripts/make-timelapse.py --duration 120 --out garten.gif
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_TS_RE = re.compile(r"photo_(\d{8})_(\d{6})\.jpg$", re.IGNORECASE)

# Schriftkandidaten: Windows (Arial Bold), Linux/Pi (DejaVu), sonst Pillow-Default.
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arialbd.ttf",
]


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _timestamp(path: Path):
    m = _TS_RE.search(path.name)
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S") if m else None


def _caption(dt: datetime) -> str:
    return dt.strftime("%a %d.%m.%Y  %H:%M")


def build(src: Path, out: Path, width: int, duration: int, colors: int) -> int:
    # Rekursiv alle Aufnahmen sammeln (latest.jpg faellt durch das photo_*-Muster raus),
    # chronologisch nach eingebettetem Zeitstempel sortieren.
    photos = [p for p in src.rglob("photo_*.jpg") if _timestamp(p)]
    photos.sort(key=_timestamp)
    if not photos:
        print(f"Keine photo_*.jpg in {src}", file=sys.stderr)
        return 1

    font = _load_font(max(14, width // 28))
    pad = max(6, width // 60)
    frames = []
    for path in photos:
        img = Image.open(path).convert("RGB")
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        text = _caption(_timestamp(path))
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        y = img.height - th - 2 * pad
        draw.rectangle([0, y - pad, tw + 3 * pad, img.height], fill=(0, 0, 0))
        draw.text((pad + 1, y + 1), text, font=font, fill=(0, 0, 0))   # Schatten
        draw.text((pad, y), text, font=font, fill=(255, 255, 255))
        frames.append(img.quantize(colors=colors, method=Image.MEDIANCUT))

    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out, save_all=True, append_images=frames[1:],
        duration=duration, loop=0, disposal=2, optimize=True,
    )
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"OK: {len(frames)} Frames -> {out}")
    print(f"    {frames[0].size[0]}x{frames[0].size[1]}, {duration} ms/Frame, {colors} Farben, {size_mb:.1f} MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Zeitraffer-GIF aus Kamera-Fotos erzeugen.")
    ap.add_argument("--src", type=Path, default=Path("camera-photos"),
                    help="Foto-Verzeichnis (rekursiv). Default: camera-photos")
    ap.add_argument("--out", type=Path, default=Path("camera-photos/garten-zeitraffer.gif"),
                    help="Ausgabe-GIF. Default: camera-photos/garten-zeitraffer.gif")
    ap.add_argument("--width", type=int, default=500, help="max. Breite in px (Default 500)")
    ap.add_argument("--duration", type=int, default=180, help="ms pro Frame (Default 180)")
    ap.add_argument("--colors", type=int, default=128, help="GIF-Palettenfarben (Default 128)")
    args = ap.parse_args()

    if not args.src.exists():
        print(f"Quelle nicht gefunden: {args.src}", file=sys.stderr)
        return 1
    return build(args.src, args.out, args.width, args.duration, args.colors)


if __name__ == "__main__":
    raise SystemExit(main())
