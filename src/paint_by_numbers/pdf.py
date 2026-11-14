"""A tiny, dependency-free PDF writer for full-page images.

Pillow's PDF writer stores RGB pages as JPEG, which smudges thin outlines and
small numbers. Here each page is PNG-encoded and its compressed pixel data is
embedded unchanged: PDF's Flate filter with PNG predictors reads PNG data
natively, so pages stay lossless and small.
"""

import io
import struct

from PIL import Image


def _png_parts(page: Image.Image) -> tuple[int, int, bytes]:
    buffer = io.BytesIO()
    page.convert("RGB").save(buffer, "PNG", compress_level=9)
    data = buffer.getvalue()
    position = 8
    width = height = 0
    idat = bytearray()
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        body = data[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat.extend(body)
        position += 12 + length
    return width, height, bytes(idat)


def images_to_pdf(pages: list[Image.Image], dpi: float = 200.0, title: str = "") -> bytes:
    """Return a PDF with one image per page, each page sized to the image at ``dpi``."""
    if not pages:
        raise ValueError("a PDF needs at least one page")
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # placeholders, filled in once the page ids are known
    page_tree = add(b"")
    info = add(
        b"<< /Producer (paint-by-numbers) /Title ("
        + title.replace("\\", "").replace("(", "").replace(")", "").encode("latin-1", "replace")
        + b") >>"
    )
    page_ids: list[int] = []
    for page in pages:
        width, height, data = _png_parts(page)
        image = add(
            (
                f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                f"/DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 "
                f"/Columns {width} >> /Length {len(data)} >>\nstream\n"
            ).encode("ascii")
            + data
            + b"\nendstream"
        )
        points_w, points_h = width * 72.0 / dpi, height * 72.0 / dpi
        content = f"q {points_w:.2f} 0 0 {points_h:.2f} 0 0 cm /Im0 Do Q".encode("ascii")
        stream = add(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream"
        )
        page_ids.append(
            add(
                (
                    f"<< /Type /Page /Parent {page_tree} 0 R "
                    f"/MediaBox [0 0 {points_w:.2f} {points_h:.2f}] "
                    f"/Resources << /XObject << /Im0 {image} 0 R >> >> "
                    f"/Contents {stream} 0 R >>"
                ).encode("ascii")
            )
        )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {page_tree} 0 R >>".encode("ascii")
    objects[page_tree - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode(
        "ascii"
    )

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return output.getvalue()
