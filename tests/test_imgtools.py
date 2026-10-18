import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import imgtools  # noqa: E402


def make(tmp, name="a.jpg", size=(3000, 2000), mode="RGB"):
    src = tmp / "src"
    src.mkdir(exist_ok=True)
    Image.new(mode, size, (200, 80, 40) if mode == "RGB" else (200, 80, 40, 128)).save(src / name)
    return src


def test_resize_keeps_ratio(tmp_path):
    src = make(tmp_path)
    assert imgtools.main(["resize", str(src), "--max", "1200", "--out", str(tmp_path / "o")]) == 0
    assert Image.open(tmp_path / "o" / "a.jpg").size == (1200, 800)


def test_webp_and_thumbs(tmp_path):
    src = make(tmp_path, "p.png", (800, 600), "RGBA")
    imgtools.main(["webp", str(src), "--out", str(tmp_path / "w")])
    assert (tmp_path / "w" / "p.webp").exists()
    imgtools.main(["thumbs", str(src), "--size", "200x200", "--out", str(tmp_path / "t")])
    assert Image.open(tmp_path / "t" / "p.jpg").size == (200, 200)


def test_watermark_changes_pixels(tmp_path):
    src = make(tmp_path, size=(600, 400))
    imgtools.main(["mark", str(src), "--text", "TEST", "--pos", "mc", "--out", str(tmp_path / "m")])
    img = Image.open(tmp_path / "m" / "a.jpg").convert("RGB")
    assert len(set(img.getdata())) > 1


def test_broken_file_reported(tmp_path):
    src = make(tmp_path)
    (src / "broken.jpg").write_bytes(b"not an image")
    assert imgtools.main(["resize", str(src), "--out", str(tmp_path / "o")]) == 1
    assert (tmp_path / "o" / "a.jpg").exists()


def test_strip_keeps_palette_and_transparency(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    img = Image.new("P", (40, 20))
    palette = [0, 0, 0, 255, 0, 0, 0, 0, 255] + [0] * (256 * 3 - 9)
    img.putpalette(palette)
    img.paste(1, (0, 0, 20, 20))
    img.paste(2, (20, 0, 40, 20))
    img.info["transparency"] = 2
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    img.save(src / "p.png", exif=exif.tobytes(), transparency=2)
    assert Image.open(src / "p.png").getexif()

    assert imgtools.main(["strip", str(src), "--out", str(tmp_path / "s")]) == 0
    out = Image.open(tmp_path / "s" / "p.png")
    assert out.mode == "P"
    assert out.info.get("transparency") == 2
    assert not out.getexif()
    rgba = out.convert("RGBA")
    assert rgba.getpixel((5, 5)) == (255, 0, 0, 255)
    assert rgba.getpixel((30, 5))[3] == 0
