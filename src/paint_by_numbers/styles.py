"""Artistic restyling applied before the picture is turned into regions.

A paint-by-numbers page does not have to look like a photo. Each style here is
a small NumPy/Pillow filter that pushes the picture towards a look (oil paint,
cartoon, pop art, pixel art, stained glass...) before colours are reduced.

Styles that impose their own geometry (the pixel grid and stained glass) also
return a *partition*: a cell id per pixel. Cell borders are kept as region
borders even where neighbouring cells end up with the same colour.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass(frozen=True)
class StyleContext:
    """What a style needs to know about the job."""

    long_side: int  # working resolution of the picture
    cell_size: int  # smallest comfortable region width, in working pixels
    seed: int = 0


@dataclass(frozen=True)
class Styled:
    """A restyled picture and, optionally, the cells it is built from."""

    image: np.ndarray  # (H, W, 3) uint8
    partition: np.ndarray | None = None


@dataclass(frozen=True)
class Style:
    """A selectable look."""

    key: str
    label: str
    description: str
    apply: Callable[[np.ndarray, StyleContext], Styled]
    geometric: bool = False  # True if the style draws its own region shapes


def kuwahara(image: np.ndarray, radius: int) -> np.ndarray:
    """Kuwahara filter: flatten texture while keeping edges sharp (an oil-paint look).

    Every pixel takes the mean colour of whichever of its four overlapping
    ``(radius + 1)``-square quadrants has the lowest brightness variance.
    """
    if radius < 1:
        return image.copy()
    height, width, _ = image.shape
    padded = np.pad(image.astype(np.float64), ((radius, radius), (radius, radius), (0, 0)), "edge")
    luminance = padded @ np.array([0.299, 0.587, 0.114])
    features = np.concatenate([padded, luminance[..., None], (luminance**2)[..., None]], axis=2)
    integral = np.zeros((features.shape[0] + 1, features.shape[1] + 1, features.shape[2]))
    integral[1:, 1:] = features.cumsum(axis=0).cumsum(axis=1)
    size = radius + 1

    def quadrant_mean(offset_y: int, offset_x: int) -> np.ndarray:
        y0, x0 = offset_y, offset_x
        total = (
            integral[y0 + size : y0 + size + height, x0 + size : x0 + size + width]
            - integral[y0 : y0 + height, x0 + size : x0 + size + width]
            - integral[y0 + size : y0 + size + height, x0 : x0 + width]
            + integral[y0 : y0 + height, x0 : x0 + width]
        )
        return np.asarray(total / (size * size))

    best_mean = np.zeros((height, width, 3))
    best_variance = np.full((height, width), np.inf)
    for offset_y, offset_x in ((0, 0), (0, radius), (radius, 0), (radius, radius)):
        mean = quadrant_mean(offset_y, offset_x)
        variance = mean[..., 4] - mean[..., 3] ** 2
        better = variance < best_variance
        best_variance = np.where(better, variance, best_variance)
        best_mean[better] = mean[..., :3][better]
    return np.clip(np.rint(best_mean), 0, 255).astype(np.uint8)


def _pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(image, "RGB")


def _array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def _brush_radius(context: StyleContext, divisor: int) -> int:
    return max(2, round(context.long_side / divisor))


def _photo(image: np.ndarray, _context: StyleContext) -> Styled:
    return Styled(_array(_pil(image).filter(ImageFilter.MedianFilter(3))))


def _painterly(image: np.ndarray, context: StyleContext) -> Styled:
    radius = _brush_radius(context, 160)
    painted = kuwahara(kuwahara(image, radius), max(1, radius // 2))
    return Styled(_array(ImageEnhance.Color(_pil(painted)).enhance(1.12)))


def _cartoon(image: np.ndarray, context: StyleContext) -> Styled:
    radius = _brush_radius(context, 120)
    flat = kuwahara(kuwahara(image, radius), radius)
    picture = _pil(flat).filter(ImageFilter.MedianFilter(5))
    picture = ImageEnhance.Color(picture).enhance(1.45)
    picture = ImageEnhance.Contrast(picture).enhance(1.15)
    return Styled(_array(picture))


def _pop_art(image: np.ndarray, context: StyleContext) -> Styled:
    smooth = kuwahara(image, _brush_radius(context, 200))
    picture = ImageOps.autocontrast(_pil(smooth), cutoff=2)
    picture = ImageEnhance.Color(picture).enhance(2.3)
    picture = ImageEnhance.Contrast(picture).enhance(1.35)
    picture = ImageOps.posterize(picture, 2)
    return Styled(_array(picture.filter(ImageFilter.ModeFilter(5))))


def _pastel(image: np.ndarray, context: StyleContext) -> Styled:
    smooth = kuwahara(image, _brush_radius(context, 200))
    picture = ImageEnhance.Color(_pil(smooth)).enhance(0.75)
    soft = np.asarray(picture, dtype=np.float64) * 0.6 + 255 * 0.4
    return Styled(np.clip(np.rint(soft), 0, 255).astype(np.uint8))


def _watercolor(image: np.ndarray, context: StyleContext) -> Styled:
    radius = _brush_radius(context, 140)
    washed = _pil(kuwahara(image, radius)).filter(ImageFilter.GaussianBlur(radius * 0.8))
    lifted = (np.asarray(washed, dtype=np.float64) / 255.0) ** 0.75 * 255
    picture = ImageEnhance.Color(_pil(np.clip(lifted, 0, 255).astype(np.uint8))).enhance(1.2)
    return Styled(_array(picture))


def _vintage(image: np.ndarray, context: StyleContext) -> Styled:
    smooth = kuwahara(image, _brush_radius(context, 220)).astype(np.float64)
    gray = smooth @ np.array([0.299, 0.587, 0.114])
    sepia = np.stack([gray * 1.07 + 18, gray * 0.95 + 8, gray * 0.78], axis=-1)
    blend = 0.55 * sepia + 0.45 * smooth
    faded = blend * 0.86 + 22
    return Styled(np.clip(np.rint(faded), 0, 255).astype(np.uint8))


def _cell_means(image: np.ndarray, partition: np.ndarray) -> np.ndarray:
    """Fill every cell of ``partition`` with its mean colour."""
    flat = partition.ravel()
    counts = np.bincount(flat).astype(np.float64)
    pixels = image.reshape(-1, 3).astype(np.float64)
    means = np.stack([np.bincount(flat, pixels[:, c]) / counts for c in range(3)], axis=-1)
    return np.asarray(np.rint(means[partition]), dtype=np.uint8)


def _pixel(image: np.ndarray, context: StyleContext) -> Styled:
    height, width, _ = image.shape
    cell = max(2, context.cell_size)
    rows, cols = max(1, round(height / cell)), max(1, round(width / cell))
    cell_y = np.minimum(np.arange(height) * rows // height, rows - 1)
    cell_x = np.minimum(np.arange(width) * cols // width, cols - 1)
    partition = (cell_y[:, None] * cols + cell_x[None, :]).astype(np.int32)
    return Styled(_cell_means(image, partition), partition)


def _stained_glass(image: np.ndarray, context: StyleContext) -> Styled:
    """Voronoi cells around jittered grid points, each filled with its mean colour."""
    height, width, _ = image.shape
    cell = max(3, round(context.cell_size * 1.6))
    rows, cols = max(1, -(-height // cell)), max(1, -(-width // cell))
    rng = np.random.default_rng(context.seed)
    seed_y = (np.arange(rows)[:, None] + rng.uniform(0.15, 0.85, (rows, cols))) * cell
    seed_x = (np.arange(cols)[None, :] + rng.uniform(0.15, 0.85, (rows, cols))) * cell
    ys, xs = np.indices((height, width))
    grid_y, grid_x = ys // cell, xs // cell
    best_distance = np.full((height, width), np.inf)
    nearest_seed = np.zeros((height, width), dtype=np.int64)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            neighbour_y = np.clip(grid_y + dy, 0, rows - 1)
            neighbour_x = np.clip(grid_x + dx, 0, cols - 1)
            distance = (ys - seed_y[neighbour_y, neighbour_x]) ** 2 + (
                xs - seed_x[neighbour_y, neighbour_x]
            ) ** 2
            closer = distance < best_distance
            best_distance = np.where(closer, distance, best_distance)
            nearest_seed = np.where(closer, neighbour_y * cols + neighbour_x, nearest_seed)
    _, cells = np.unique(nearest_seed, return_inverse=True)
    partition = cells.reshape(height, width).astype(np.int32)
    glass = _cell_means(kuwahara(image, max(1, cell // 4)), partition)
    glass = _array(ImageEnhance.Color(_pil(glass)).enhance(1.3))
    return Styled(glass, partition)


STYLES: dict[str, Style] = {
    style.key: style
    for style in (
        Style("photo", "Photo", "Keep the picture as it is.", _photo),
        Style(
            "painterly", "Oil painting", "Soft brush-stroke patches with crisp edges.", _painterly
        ),
        Style("cartoon", "Cartoon", "Bold, flat, cheerful colours.", _cartoon),
        Style("pop-art", "Pop art", "Punchy comic-book colours.", _pop_art),
        Style("watercolor", "Watercolour", "Light, luminous washes.", _watercolor),
        Style("pastel", "Pastel", "Soft, gentle, light colours.", _pastel),
        Style("vintage", "Vintage", "Warm, faded retro tones.", _vintage),
        Style("pixel", "Pixel art", "A grid of squares, like a mosaic.", _pixel, geometric=True),
        Style(
            "stained-glass",
            "Stained glass",
            "Glass-like pieces with lead lines.",
            _stained_glass,
            geometric=True,
        ),
    )
}


def get_style(key: str) -> Style:
    """Return a style by key, with a helpful error for unknown keys."""
    try:
        return STYLES[key]
    except KeyError as error:
        raise ValueError(f"unknown style {key!r}; choose one of: {', '.join(STYLES)}") from error


def simplify(image: np.ndarray, level: int, blur: float = 0.0) -> np.ndarray:
    """Edge-preserving smoothing: the higher the level, the fewer tiny details survive.

    ``blur`` (pixels) adds a light Gaussian blur that averages away sensor noise and
    fine texture, so flat areas do not break into speckles between two similar
    colours. Colour reduction afterwards restores crisp edges.
    """
    if level <= 0:
        return image
    picture = image
    if level >= 2:
        for _ in range(1 if level < 4 else 2):
            picture = kuwahara(picture, level)
    median = (3, 3, 5, 5, 7)[min(level, 5) - 1]
    filtered = _pil(picture).filter(ImageFilter.MedianFilter(median))
    if blur > 0:
        filtered = filtered.filter(ImageFilter.GaussianBlur(blur))
    return _array(filtered)
