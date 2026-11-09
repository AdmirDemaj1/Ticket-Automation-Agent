"""Screenshot validation: real image check by magic bytes, size limits, EXIF removal.

Images are re-encoded from pixel data only, so EXIF, GPS, ICC profiles and comments are
dropped. They are also downscaled so the long side is at most `MAX_SIDE_PX`, which keeps
them under the Claude API image limits and cuts token use.
"""

import io
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

ImageKind = Literal["png", "jpeg", "webp"]

MAX_SIDE_PX = 1568
MAX_PIXELS = 50_000_000  # refuse decompression bombs before decoding

MEDIA_TYPES: dict[ImageKind, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
EXTENSIONS: dict[ImageKind, str] = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
_PIL_FORMATS: dict[ImageKind, str] = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}


class UploadError(ValueError):
    """An upload was rejected. The message is safe to show."""


@dataclass(frozen=True)
class CleanImage:
    data: bytes
    kind: ImageKind

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.kind]

    @property
    def extension(self) -> str:
        return EXTENSIONS[self.kind]


def sniff_image(data: bytes) -> ImageKind | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def clean_screenshot(data: bytes, name: str, max_bytes: int) -> CleanImage:
    if len(data) > max_bytes:
        raise UploadError(f"{name}: larger than {max_bytes // 1_000_000} MB")
    kind = sniff_image(data)
    if kind is None:
        raise UploadError(f"{name}: not a PNG, JPEG or WebP image")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise UploadError(f"{name}: image dimensions are too large")
            if (img.format or "").upper() != _PIL_FORMATS[kind]:
                raise UploadError(f"{name}: file content does not match its image type")
            img.load()
            upright = ImageOps.exif_transpose(img)
    except UploadError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise UploadError(f"{name}: the image could not be read") from e

    has_alpha = upright.mode in ("RGBA", "LA", "PA") or "transparency" in upright.info
    mode = "RGBA" if has_alpha and kind != "jpeg" else "RGB"
    converted = upright.convert(mode)
    # Rebuild from raw pixels: no metadata survives.
    pixels = Image.frombytes(mode, converted.size, converted.tobytes())
    pixels.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))

    out = io.BytesIO()
    if kind == "jpeg":
        pixels.save(out, format="JPEG", quality=90)
    else:
        pixels.save(out, format=_PIL_FORMATS[kind])
    return CleanImage(data=out.getvalue(), kind=kind)
