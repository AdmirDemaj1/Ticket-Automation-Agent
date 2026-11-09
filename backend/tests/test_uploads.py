import io

import pytest
from PIL import Image

from app.uploads import MAX_SIDE_PX, UploadError, clean_screenshot, sniff_image
from tests.conftest import FIXTURES


def _jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    exif[0x0132] = "2026:11:08 10:00:00"  # DateTime
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_sniff() -> None:
    png = (FIXTURES / "screenshots/01-login.png").read_bytes()
    assert sniff_image(png) == "png"
    assert sniff_image(_jpeg_with_exif()) == "jpeg"
    assert sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert sniff_image(b"<svg xmlns=...>") is None


def test_exif_is_stripped() -> None:
    data = _jpeg_with_exif()
    assert b"SecretCam" in data
    clean = clean_screenshot(data, "photo.jpg", 1_000_000)
    assert clean.kind == "jpeg" and clean.media_type == "image/jpeg"
    assert b"SecretCam" not in clean.data
    with Image.open(io.BytesIO(clean.data)) as img:
        assert dict(img.getexif()) == {}
        assert img.size == (40, 20)


def test_large_images_are_downscaled() -> None:
    buf = io.BytesIO()
    Image.new("RGBA", (4000, 1000), (0, 0, 255, 128)).save(buf, format="PNG")
    clean = clean_screenshot(buf.getvalue(), "wide.png", 10_000_000)
    with Image.open(io.BytesIO(clean.data)) as img:
        assert max(img.size) == MAX_SIDE_PX
        assert img.mode == "RGBA"


def test_rejects_non_images_and_mismatched_content() -> None:
    with pytest.raises(UploadError, match="not a PNG"):
        clean_screenshot(b"GIF89a....", "anim.png", 1_000_000)
    with pytest.raises(UploadError, match="could not be read"):
        clean_screenshot(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "broken.png", 1_000_000)


def test_rejects_oversized_files() -> None:
    png = (FIXTURES / "screenshots/01-login.png").read_bytes()
    with pytest.raises(UploadError, match="larger than"):
        clean_screenshot(png, "01-login.png", len(png) - 1)
