#!/usr/bin/env python3
"""imgtools: пакетная обработка картинок для сайтов и маркетплейсов.

    python imgtools.py resize  photos/ --max 1600 --out out/
    python imgtools.py webp    photos/ --quality 82
    python imgtools.py thumbs  photos/ --size 400x400
    python imgtools.py mark    photos/ --text "© Мастерская" --pos br
    python imgtools.py strip   photos/                  # убрать EXIF (геопозиция, модель телефона)
"""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def collect(src: Path) -> list[Path]:
    if src.is_file():
        return [src]
    return sorted(p for p in src.rglob("*") if p.suffix.lower() in EXTS)


def target(path: Path, src: Path, out: Path, suffix: str | None = None) -> Path:
    rel = path.relative_to(src) if src.is_dir() else Path(path.name)
    dest = out / rel
    if suffix:
        dest = dest.with_suffix(suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    return ImageOps.exif_transpose(img)  # телефоны пишут поворот в EXIF, применяем его к пикселям


def save(img: Image.Image, dest: Path, quality: int) -> None:
    fmt = dest.suffix.lower()
    if fmt in (".jpg", ".jpeg") and img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = bg
    kwargs = {"quality": quality, "optimize": True} if fmt in (".jpg", ".jpeg", ".webp") else {"optimize": True}
    if fmt in (".jpg", ".jpeg"):
        kwargs["progressive"] = True
    img.save(dest, **kwargs)


def do_resize(img, a):
    img.thumbnail((a.max, a.max), Image.LANCZOS)
    return img


def do_thumb(img, a):
    w, h = (int(x) for x in a.size.lower().split("x"))
    return ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.4))


def do_mark(img, a):
    img = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    size = max(14, img.width // 28)
    try:
        font = ImageFont.truetype(a.font or "DejaVuSans.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), a.text, font=font)
    tw, th, pad = box[2] - box[0], box[3] - box[1], size // 2
    x = {"l": pad, "c": (img.width - tw) // 2, "r": img.width - tw - pad}[a.pos[1]]
    y = {"t": pad, "m": (img.height - th) // 2, "b": img.height - th - pad * 2}[a.pos[0]]
    draw.text((x + 1, y + 1), a.text, font=font, fill=(0, 0, 0, int(a.opacity * 140)))
    draw.text((x, y), a.text, font=font, fill=(255, 255, 255, int(a.opacity * 255)))
    return Image.alpha_composite(img, layer)


def do_strip(img, a):
    clean = Image.new(img.mode, img.size)
    clean.frombytes(img.tobytes())
    # Палитра и прозрачность это часть картинки, а не метаданные: переносим их,
    # иначе P-режим (GIF-подобные PNG) теряет цвета и прозрачный фон
    if img.mode in ("P", "PA") and img.palette is not None:
        clean.putpalette(img.getpalette(img.palette.mode), img.palette.mode)
    if "transparency" in img.info:
        clean.info["transparency"] = img.info["transparency"]
    return clean


ACTIONS = {"resize": (do_resize, None), "webp": (lambda img, a: img, ".webp"), "thumbs": (do_thumb, None),
           "mark": (do_mark, None), "strip": (do_strip, None)}


def process(job):
    path, src, out, a = job
    func, suffix = ACTIONS[a.cmd]
    dest = target(path, src, out, suffix or (".jpg" if a.cmd == "thumbs" else None))
    try:
        before = path.stat().st_size
        save(func(open_image(path), a), dest, a.quality)
        return path.name, before, dest.stat().st_size, None
    except Exception as exc:  # битый файл не должен останавливать пачку
        return path.name, 0, 0, str(exc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Пакетная обработка изображений")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in [("resize", "уменьшить по длинной стороне"), ("webp", "конвертировать в WebP"), ("thumbs", "квадратные превью"),
                        ("mark", "водяной знак"), ("strip", "удалить EXIF")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("src", type=Path)
        p.add_argument("--out", type=Path, default=Path("out"))
        p.add_argument("--quality", type=int, default=85)
        if name == "resize":
            p.add_argument("--max", type=int, default=1600)
        if name == "thumbs":
            p.add_argument("--size", default="400x400")
        if name == "mark":
            p.add_argument("--text", required=True)
            p.add_argument("--pos", default="br", choices=["tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"])
            p.add_argument("--opacity", type=float, default=0.7)
            p.add_argument("--font", help="путь к .ttf, если нужен свой шрифт")
    a = ap.parse_args(argv)
    files = collect(a.src)
    if not files:
        print("Картинок не найдено", file=sys.stderr)
        return 1
    total_before = total_after = errors = 0
    with ProcessPoolExecutor() as pool:
        for name, before, after, err in pool.map(process, [(f, a.src, a.out, a) for f in files]):
            if err:
                errors += 1
                print(f"  ✗ {name}: {err}")
                continue
            total_before += before
            total_after += after
            print(f"  ✓ {name}: {before // 1024} → {after // 1024} КБ")
    saved = (1 - total_after / total_before) * 100 if total_before else 0
    print(f"\nГотово: {len(files) - errors} из {len(files)}, {total_before // 1024} → {total_after // 1024} КБ ({saved:+.0f}% экономии) → {a.out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
