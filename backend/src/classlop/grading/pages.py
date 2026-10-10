import base64
import io

import pillow_heif
import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

LONG_SIDE = 2000
MAX_PAGES = 6
TOO_MANY_PAGES, NO_USABLE_FILE = "za dużo stron", "brak czytelnych plików"


def _split(file: bytes, limit: int) -> list[Image.Image]:
    """At most `limit` pages of one hand-in file; none when it is neither an image nor a PDF.

    Files are told apart by content: phones name and type them unreliably."""
    try:
        # PDF allows bytes before its header, within the first kilobyte.
        if b"%PDF" in file[:1024]:
            pdf = pdfium.PdfDocument(file)
            return [
                pdf[i].render(scale=LONG_SIDE / max(pdf[i].get_size())).to_pil()
                for i in range(min(len(pdf), limit))
            ]
        image = Image.open(io.BytesIO(file))
        image.load()
        return [image]
    except (pdfium.PdfiumError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return []


def pages_of(files: list[bytes]) -> tuple[list[Image.Image], str | None]:
    """The pages of a hand-in in order, or the Held reason when they cannot be transcribed."""
    pages: list[Image.Image] = []
    for file in files:
        pages += _split(file, MAX_PAGES + 1 - len(pages))
        if len(pages) > MAX_PAGES:
            return [], TOO_MANY_PAGES
    return pages, None if pages else NO_USABLE_FILE


def prepare(page: Image.Image) -> bytes:
    """Upright from EXIF, at most LONG_SIDE px on the long side, as JPEG."""
    page = ImageOps.exif_transpose(page)
    page.thumbnail((LONG_SIDE, LONG_SIDE))
    out = io.BytesIO()
    page.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def image_parts(pages: list[bytes]) -> list[dict]:
    """Prepared pages as image parts of a chat message."""
    return [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p).decode()},
        }
        for p in pages
    ]
