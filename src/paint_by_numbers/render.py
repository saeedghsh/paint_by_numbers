"""Draw the page: outlines and marks, the painted preview, the colour key, print sheets."""

import io
import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from paint_by_numbers.color import RGB, contrast_text_color, mix
from paint_by_numbers.pdf import images_to_pdf
from paint_by_numbers.pipeline import PaletteEntry, Result
from paint_by_numbers.profiles import PAGE_LONG_SIDE_MM
from paint_by_numbers.regions import blurred_masks, vote
from paint_by_numbers.styles import get_style

WHITE: RGB = (255, 255, 255)
DARK_INK: RGB = (34, 34, 38)
SOFT_INK: RGB = (118, 124, 136)
SHAPES = ("circle", "square", "triangle", "star", "heart", "diamond", "plus", "house")
PRINT_DPI = 200
PRINT_PX_PER_MM = PRINT_DPI / 25.4
A4_PIXELS = (1654, 2339)  # 210 x 297 mm at 200 dpi
_DIGIT_WIDTH_EM = 0.56
_DIGIT_HEIGHT_EM = 0.72
_UPSCALE_SIGMA = 0.7  # working pixels; removes the pixel staircase when enlarging


@lru_cache(maxsize=64)
def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Pillow's bundled scalable font (no font files needed, also in Pyodide)."""
    return ImageFont.load_default(size=max(6, int(size)))


@dataclass(frozen=True)
class Ink:
    """Line and mark colours for a page."""

    line: RGB
    mark: RGB


def page_ink(result: Result) -> Ink:
    """Bold black lines for children; soft grey lines (easy to paint over) for adults."""
    settings = result.settings
    if settings.line_mm >= 0.6 or settings.tint or settings.marker != "numbers":
        return Ink(DARK_INK, DARK_INK)
    return Ink(SOFT_INK, (92, 98, 110))


def nearest_upscale(label_map: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Enlarge a label map with nearest-neighbour sampling (crisp pixel-art squares)."""
    out_w, out_h = size
    height, width = label_map.shape
    ys = np.minimum(np.arange(out_h) * height // out_h, height - 1)
    xs = np.minimum(np.arange(out_w) * width // out_w, width - 1)
    return np.asarray(label_map[ys[:, None], xs[None, :]])


def majority_upscale(label_map: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Enlarge any label map with a bilinear majority vote between the 4 nearest pixels.

    Works for any number of labels (regions, not just colours), which the
    stained-glass style needs to keep borders between same-coloured cells.
    """
    out_w, out_h = size
    height, width = label_map.shape
    xs = (np.arange(out_w) + 0.5) * width / out_w - 0.5
    ys = (np.arange(out_h) + 0.5) * height / out_h - 0.5
    x0, y0 = np.floor(xs).astype(np.int64), np.floor(ys).astype(np.int64)
    fx = (xs - x0).astype(np.float32)[None, :]
    fy_all = (ys - y0).astype(np.float32)
    x1, y1 = np.clip(x0 + 1, 0, width - 1), np.clip(y0 + 1, 0, height - 1)
    x0, y0 = np.clip(x0, 0, width - 1), np.clip(y0, 0, height - 1)
    out = np.empty((out_h, out_w), dtype=label_map.dtype)
    for start in range(0, out_h, 192):
        rows = slice(start, min(out_h, start + 192))
        top, bottom = label_map[y0[rows]], label_map[y1[rows]]
        fy = fy_all[rows][:, None]
        corners = (top[:, x0], top[:, x1], bottom[:, x0], bottom[:, x1])
        weights = ((1 - fy) * (1 - fx), (1 - fy) * fx, fy * (1 - fx), fy * fx)
        best = corners[0]
        best_score = np.full(best.shape, -1.0, dtype=np.float32)
        for candidate in corners:
            score = np.zeros(best.shape, dtype=np.float32)
            for other, weight in zip(corners, weights):
                score += weight * (other == candidate)
            better = score > best_score
            best = np.where(better, candidate, best)
            best_score = np.where(better, score, best_score)
        out[rows] = best
    return out


def _dilate(mask: np.ndarray, width: int) -> np.ndarray:
    """Thicken a boolean mask to ``width`` pixels with a square brush."""
    if width <= 1:
        return mask
    before, after = (width - 1) // 2, width // 2
    grown = mask.copy()
    for offset in range(1, before + 1):
        grown[:, offset:] |= mask[:, :-offset]
    for offset in range(1, after + 1):
        grown[:, :-offset] |= mask[:, offset:]
    rows = grown.copy()
    for offset in range(1, before + 1):
        grown[offset:, :] |= rows[:-offset, :]
    for offset in range(1, after + 1):
        grown[:-offset, :] |= rows[offset:, :]
    return grown


def outline_mask(label_map: np.ndarray, width: int, frame: bool = True) -> np.ndarray:
    """Pixels on a border between different labels, thickened to ``width``."""
    mask = np.zeros(label_map.shape, dtype=bool)
    mask[:, :-1] |= label_map[:, :-1] != label_map[:, 1:]
    mask[:-1, :] |= label_map[:-1, :] != label_map[1:, :]
    mask = _dilate(mask, width)
    if frame:
        mask[:width, :] = True
        mask[-width:, :] = True
        mask[:, :width] = True
        mask[:, -width:] = True
    return mask


class PageRenderer:
    """Render a :class:`Result` at its output size."""

    def __init__(self, result: Result):
        self.result = result
        self.size = result.output_size
        self.scale = self.size[0] / result.size[0]
        self.px_per_mm = max(self.size) / PAGE_LONG_SIDE_MM
        self.colors = np.array([entry.rgb for entry in result.palette], dtype=np.uint8)
        self.ink = page_ink(result)
        self.line_px = max(1, round(result.settings.line_mm * self.px_per_mm))
        style = result.settings.style
        if style == "pixel":
            self.edges = nearest_upscale(result.region_map, self.size)
            self.color_map = result.region_color[self.edges]
        elif get_style(style).geometric:
            self.edges = majority_upscale(result.region_map, self.size)
            self.color_map = result.region_color[self.edges]
        else:
            # Adjacent regions always differ in colour, so colour borders are region
            # borders; smoothing colour masks gives round, staircase-free outlines.
            index_map = result.region_color[result.region_map]
            masks = blurred_masks(index_map, len(result.palette), _UPSCALE_SIGMA)
            self.color_map = vote(masks, self.size)
            self.edges = self.color_map

    def canvas(self) -> Image.Image:
        """The page to paint: outlines plus a mark in every area."""
        if self.result.settings.tint:
            tints = np.array([mix(rgb, WHITE, 0.72) for rgb in self.colors], dtype=np.uint8)
            pixels = tints[self.color_map]
        else:
            pixels = np.full((self.size[1], self.size[0], 3), 255, dtype=np.uint8)
        pixels[outline_mask(self.edges, self.line_px)] = self.ink.line
        picture = Image.fromarray(pixels, "RGB")
        draw = ImageDraw.Draw(picture)
        for label in self.result.labels:
            x = (label.x + 0.5) * self.scale - 0.5
            y = (label.y + 0.5) * self.scale - 0.5
            radius = (label.radius + 0.5) * self.scale
            self.draw_marker(draw, label.color, x, y, radius)
        return picture

    def preview(self) -> Image.Image:
        """What the finished painting will look like (with faint borders)."""
        pixels = self.colors[self.color_map]
        edge = outline_mask(self.edges, 1, frame=False)
        pixels[edge] = (pixels[edge].astype(np.int32) * 4 // 5).astype(np.uint8)
        return Image.fromarray(pixels, "RGB")

    def draw_marker(
        self, draw: ImageDraw.ImageDraw, color: int, x: float, y: float, radius: float
    ) -> None:
        """Draw the mark for palette colour ``color`` centred at ``(x, y)``."""
        marker = self.result.settings.marker
        largest = self.result.settings.label_mm * self.px_per_mm
        smallest = max(9.0, largest * 0.42)
        number = str(color + 1)
        rgb = tuple_rgb(self.colors[color])
        if marker == "numbers":
            fit = radius / math.hypot(_DIGIT_WIDTH_EM * len(number) / 2, _DIGIT_HEIGHT_EM / 2)
            height = min(max(fit * _DIGIT_HEIGHT_EM, smallest), largest)
            draw_number(draw, number, x, y, height, self.ink.mark)
        elif marker == "number-dots":
            dot = min(max(radius * 0.8, smallest * 0.75), largest * 0.75)
            draw_dot(draw, x, y, dot, rgb, self.ink.line)
            text_height = dot * (0.95 if len(number) == 1 else 0.75)
            draw_number(draw, number, x, y, text_height, contrast_text_color(rgb))
        elif marker == "dots":
            dot = min(max(radius * 0.7, smallest * 0.5), largest * 0.5)
            draw_dot(draw, x, y, dot, rgb, self.ink.line)
        elif marker == "shapes":
            size = min(max(radius * 1.3, smallest), largest)
            draw_shape(draw, SHAPES[color % len(SHAPES)], x, y, size, self.ink.mark)


def tuple_rgb(values: np.ndarray | tuple[int, ...]) -> RGB:
    """Plain ``(r, g, b)`` ints, as Pillow's drawing functions expect."""
    red, green, blue = (int(value) for value in values)
    return red, green, blue


def draw_number(
    draw: ImageDraw.ImageDraw, text: str, x: float, y: float, digit_height: float, fill: RGB
) -> None:
    """Draw ``text`` with its digits (not its em box) centred on ``(x, y)``."""
    em = max(6, round(digit_height / _DIGIT_HEIGHT_EM))
    stroke = 1 if em >= 34 else 0
    draw.text(
        (x, y + digit_height / 2),
        text,
        fill=fill,
        font=font(em),
        anchor="ms",
        stroke_width=stroke,
        stroke_fill=fill,
    )


def draw_dot(
    draw: ImageDraw.ImageDraw, x: float, y: float, radius: float, fill: RGB, ring: RGB
) -> None:
    """A filled colour dot with a thin dark ring."""
    border = max(1, round(radius / 9))
    box = (x - radius, y - radius, x + radius, y + radius)
    draw.ellipse(box, fill=fill, outline=ring, width=border)


def _star(cx: float, cy: float, size: float) -> list[tuple[float, float]]:
    points = []
    for i in range(10):
        radius = size / 2 if i % 2 == 0 else size / 4.6
        angle = math.pi / 2 + i * math.pi / 5
        points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle) + size * 0.04))
    return points


def _heart(cx: float, cy: float, size: float) -> list[tuple[float, float]]:
    points = []
    for i in range(48):
        t = 2 * math.pi * i / 48
        hx = 16 * math.sin(t) ** 3
        hy = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((cx + hx * size / 34, cy - hy * size / 34 - size * 0.04))
    return points


def shape_points(  # pylint: disable=too-many-return-statements
    shape: str, cx: float, cy: float, size: float
) -> list[tuple[float, float]]:
    """Polygon for a named shape inside a ``size`` box centred on ``(cx, cy)``."""
    h = size / 2
    if shape == "square":
        s = h * 0.82
        return [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s)]
    if shape == "triangle":
        return [(cx, cy - h), (cx + h, cy + h * 0.75), (cx - h, cy + h * 0.75)]
    if shape == "star":
        return _star(cx, cy, size)
    if shape == "heart":
        return _heart(cx, cy, size)
    if shape == "diamond":
        return [(cx, cy - h), (cx + h * 0.72, cy), (cx, cy + h), (cx - h * 0.72, cy)]
    if shape == "plus":
        a = h * 0.34
        steps = [(-a, -h), (a, -h), (a, -a), (h, -a), (h, a), (a, a), (a, h), (-a, h), (-a, a),
                 (-h, a), (-h, -a), (-a, -a)]  # fmt: skip
        return [(cx + dx, cy + dy) for dx, dy in steps]
    if shape == "house":
        wall, eave = h * 0.78, -h * 0.1
        steps = [(0, -h), (h, eave), (wall, eave), (wall, h), (-wall, h), (-wall, eave), (-h, eave)]
        return [(cx + dx, cy + dy) for dx, dy in steps]
    raise ValueError(f"unknown shape {shape!r}")


def draw_shape(
    draw: ImageDraw.ImageDraw, shape: str, x: float, y: float, size: float, ink: RGB
) -> None:
    """Draw an outlined shape (it stays easy to colour over)."""
    width = max(2, round(size / 11))
    if shape == "circle":
        radius = size * 0.45
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=ink, width=width)
        return
    points = shape_points(shape, x, y, size)
    draw.line(points + points[:2], fill=ink, width=width, joint="curve")


# -- colour key --------------------------------------------------------------------------
def render_legend(
    result: Result, width: int, px_per_mm: float, renderer: PageRenderer | None = None
) -> Image.Image:
    """A colour key - mark, swatch and name per colour - sized for print at ``px_per_mm``."""
    renderer = renderer or PageRenderer(result)
    entries = result.palette
    kids = result.settings.label_mm >= 5 or result.settings.marker != "numbers"
    row = round((13.0 if kids else 7.5) * px_per_mm)
    column_min = (60.0 if kids else 46.0) * px_per_mm
    columns = max(1, min(len(entries), int(width // column_min)))
    rows = math.ceil(len(entries) / columns)
    title = round(9 * px_per_mm)
    picture = Image.new("RGB", (width, title + rows * row + round(2 * px_per_mm)), WHITE)
    draw = ImageDraw.Draw(picture)
    title_font = font(round(4.6 * px_per_mm))
    draw.text((0, round(1.5 * px_per_mm)), "Colour key", fill=DARK_INK, font=title_font)
    column_width = width / columns
    for position, entry in enumerate(entries):
        column, line = position % columns, position // columns
        _legend_entry(draw, renderer, entry, column * column_width, title + line * row, row, kids)
    return picture


def _legend_entry(
    draw: ImageDraw.ImageDraw,
    renderer: PageRenderer,
    entry: PaletteEntry,
    left: float,
    top: float,
    row: float,
    kids: bool,
) -> None:
    marker = renderer.result.settings.marker
    middle = top + row / 2
    box = row * 0.86
    centre = left + box / 2
    index = entry.number - 1
    if marker == "numbers":
        draw_number(draw, str(entry.number), centre, middle, box * 0.5, DARK_INK)
    elif marker == "number-dots":
        draw_dot(draw, centre, middle, box * 0.42, entry.rgb, DARK_INK)
        size = box * (0.4 if entry.number < 10 else 0.32)
        draw_number(draw, str(entry.number), centre, middle, size, contrast_text_color(entry.rgb))
    elif marker == "dots":
        draw_dot(draw, centre, middle, box * 0.42, entry.rgb, DARK_INK)
    elif marker == "shapes":
        draw_shape(draw, SHAPES[index % len(SHAPES)], centre, middle, box * 0.85, DARK_INK)
    swatch_left = left + (box + row * 0.14 if marker != "none" else 0)
    swatch = (swatch_left, top + row * 0.14, swatch_left + row * 1.15, top + row * 0.86)
    outline = max(1, round(row / 40))
    draw.rounded_rectangle(
        swatch, radius=row * 0.12, fill=entry.rgb, outline=DARK_INK, width=outline
    )
    text_left = swatch[2] + row * 0.22
    name = entry.name[:1].upper() + entry.name[1:]
    if kids:
        draw.text(
            (text_left, middle), name, fill=DARK_INK, font=font(round(row * 0.36)), anchor="lm"
        )
        return
    draw.text(
        (text_left, middle - row * 0.02),
        name,
        fill=DARK_INK,
        font=font(round(row * 0.36)),
        anchor="ls",
    )
    detail = f"{entry.hex}  ·  {entry.area_fraction * 100:.1f}%"
    draw.text(
        (text_left, middle + row * 0.1),
        detail,
        fill=SOFT_INK,
        font=font(round(row * 0.28)),
        anchor="lt",
    )


# -- print sheets ------------------------------------------------------------------------
def _fit(picture: Image.Image, box: tuple[int, int]) -> Image.Image:
    scale = min(box[0] / picture.width, box[1] / picture.height)
    size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    return picture.resize(size, Image.Resampling.LANCZOS)


def print_sheet(
    result: Result, picture: Image.Image, title: str, renderer: PageRenderer
) -> Image.Image:
    """Lay ``picture`` and the colour key out on an A4 page (200 dpi)."""
    landscape = picture.width > picture.height * 1.08
    page_w, page_h = A4_PIXELS[::-1] if landscape else A4_PIXELS
    margin, header, gap = round(10 * PRINT_PX_PER_MM), round(10 * PRINT_PX_PER_MM), 30
    inner_w, inner_h = page_w - 2 * margin, page_h - 2 * margin - header

    # Try the key below the picture and beside it; keep whichever leaves the picture largest.
    layouts = []
    below = render_legend(result, inner_w, PRINT_PX_PER_MM, renderer)
    room = (inner_w, inner_h - below.height - gap)
    if room[1] > 0:
        layouts.append((min(room[0] / picture.width, room[1] / picture.height), "below", below))
    for share in (0.3, 0.42):
        beside = render_legend(result, round(inner_w * share), PRINT_PX_PER_MM, renderer)
        room = (inner_w - beside.width - gap, inner_h)
        if beside.height <= inner_h:
            layouts.append(
                (min(room[0] / picture.width, room[1] / picture.height), "beside", beside)
            )
    if not layouts:  # an enormous palette: shrink the key onto the page
        layouts.append((0.0, "below", _fit(below, (inner_w, inner_h // 2))))
    _, placement, legend = max(layouts, key=lambda layout: layout[0])

    page = Image.new("RGB", (page_w, page_h), WHITE)
    draw = ImageDraw.Draw(page)
    draw.text((margin, margin), title, fill=DARK_INK, font=font(round(6 * PRINT_PX_PER_MM)))
    meta = (
        f"Ages {result.difficulty.ages}  ·  {len(result.palette)} colours  ·  "
        f"{result.region_count} areas"
    )
    draw.text(
        (page_w - margin, margin + round(1.5 * PRINT_PX_PER_MM)),
        meta,
        fill=SOFT_INK,
        font=font(round(3.6 * PRINT_PX_PER_MM)),
        anchor="ra",
    )
    top = margin + header
    if placement == "below":
        fitted = _fit(picture, (inner_w, max(1, inner_h - legend.height - gap)))
        page.paste(fitted, (margin + (inner_w - fitted.width) // 2, top))
        page.paste(legend, (margin, top + fitted.height + gap))
    else:
        fitted = _fit(picture, (inner_w - legend.width - gap, inner_h))
        page.paste(fitted, (margin, top))
        page.paste(legend, (margin + fitted.width + gap, top))
    return page


@dataclass
class Rendered:
    """All renderings of one result."""

    canvas: Image.Image
    preview: Image.Image
    legend: Image.Image
    renderer: PageRenderer

    def sheets(self) -> list[Image.Image]:
        """Printable A4 pages: the page to paint, then the finished picture as a key."""
        result = self.renderer.result
        reading = result.settings.marker in {"numbers", "number-dots"}
        title = "Paint by numbers" if reading else "Colour by colour"
        return [
            print_sheet(result, self.canvas, title, self.renderer),
            print_sheet(result, self.preview, "How it will look", self.renderer),
        ]

    def pdf(self) -> bytes:
        """The printable sheets as a lossless PDF."""
        return images_to_pdf(self.sheets(), dpi=PRINT_DPI, title="Paint by numbers")


def render(result: Result) -> Rendered:
    """Render the page, the preview and the colour key."""
    renderer = PageRenderer(result)
    legend = render_legend(result, result.output_size[0], renderer.px_per_mm, renderer)
    return Rendered(renderer.canvas(), renderer.preview(), legend, renderer)


def png_bytes(picture: Image.Image, fast: bool = False) -> bytes:
    """Encode an image as PNG (``fast`` trades file size for speed)."""
    buffer = io.BytesIO()
    picture.save(buffer, "PNG", compress_level=1 if fast else 6)
    return buffer.getvalue()
