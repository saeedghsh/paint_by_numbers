"""The end-to-end conversion: picture in, paint-by-numbers page out."""

import io
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from paint_by_numbers.color import RGB, hex_color, rgb_to_lab
from paint_by_numbers.palettes import get_palette
from paint_by_numbers.profiles import (
    MARKERS,
    PAGE_LONG_SIDE_MM,
    Difficulty,
    estimate_difficulty,
    get_profile,
)
from paint_by_numbers.quantize import quantize
from paint_by_numbers.regions import (
    LabelPoint,
    erosion_depth,
    label_components,
    merge_regions,
    place_labels,
    region_colors,
    smooth_index_map,
)
from paint_by_numbers.styles import StyleContext, get_style, simplify

MAX_SHAPE_COLORS = 8
# Border smoothing per level, as a Gaussian radius in millimetres on the printed page.
SMOOTHING_MM = (0.0, 0.45, 0.8, 1.3, 2.0, 3.0)


@dataclass(frozen=True)
class Settings:
    """Every knob of the conversion. Start from a profile with :meth:`for_profile`."""

    colors: int = 15
    detail: int = 480
    smoothing: int = 2
    min_size_mm: float = 6.0
    max_regions: int = 0
    line_mm: float = 0.5
    label_mm: float = 4.5
    marker: str = "numbers"
    tint: bool = False
    palette: str = "auto"
    style: str = "photo"
    output_size: int = 2000
    seed: int = 0

    @classmethod
    def for_profile(cls, profile: str, **overrides: Any) -> "Settings":
        """Settings recommended for a profile (or age), with optional overrides."""
        chosen = get_profile(profile)
        base = cls(
            colors=chosen.colors,
            detail=chosen.detail,
            smoothing=chosen.smoothing,
            min_size_mm=chosen.min_size_mm,
            max_regions=chosen.max_regions,
            line_mm=chosen.line_mm,
            label_mm=chosen.label_mm,
            marker=chosen.marker,
            tint=chosen.tint,
            palette=chosen.palette,
        )
        known = {item.name for item in fields(cls)}
        unknown = set(overrides) - known
        if unknown:
            raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")
        return replace(
            base, **{key: value for key, value in overrides.items() if value is not None}
        )

    def validated(self) -> "Settings":
        """Check ranges and return a copy with values clamped to safe limits."""
        if self.marker not in MARKERS:
            raise ValueError(f"unknown marker {self.marker!r}; choose one of: {', '.join(MARKERS)}")
        get_style(self.style)
        palette = get_palette(self.palette)
        colors = int(min(max(self.colors, 2), 64))
        if not palette.is_auto:
            colors = min(colors, len(palette.colors))
        if self.marker == "shapes":
            colors = min(colors, MAX_SHAPE_COLORS)
        return replace(
            self,
            colors=colors,
            detail=int(min(max(self.detail, 64), 1600)),
            smoothing=int(min(max(self.smoothing, 0), 5)),
            min_size_mm=float(min(max(self.min_size_mm, 0.5), 80.0)),
            max_regions=int(max(self.max_regions, 0)),
            line_mm=float(min(max(self.line_mm, 0.05), 4.0)),
            label_mm=float(min(max(self.label_mm, 1.0), 30.0)),
            output_size=int(min(max(self.output_size, 400), 8000)),
            seed=int(self.seed),
        )

    def to_dict(self) -> dict[str, object]:
        """Plain-JSON representation."""
        return asdict(self)


@dataclass(frozen=True)
class PaletteEntry:
    """One paint colour in the legend."""

    number: int
    rgb: RGB
    name: str
    area_fraction: float
    regions: int

    @property
    def hex(self) -> str:
        """The colour as ``#rrggbb``."""
        return hex_color(self.rgb)

    def to_dict(self) -> dict[str, object]:
        """Plain-JSON representation."""
        return {
            "number": self.number,
            "rgb": list(self.rgb),
            "hex": self.hex,
            "name": self.name,
            "area_fraction": round(self.area_fraction, 5),
            "regions": self.regions,
        }


@dataclass
class Result:  # pylint: disable=too-many-instance-attributes
    """A finished page: regions, palette and everything needed to render it."""

    settings: Settings
    source: np.ndarray  # resized original picture (working resolution)
    styled: np.ndarray  # after the artistic style
    region_map: np.ndarray  # (H, W) region id per working pixel
    region_color: np.ndarray  # colour index per region
    palette: list[PaletteEntry]
    labels: list[LabelPoint]
    difficulty: Difficulty
    warnings: list[str] = field(default_factory=list)

    @property
    def size(self) -> tuple[int, int]:
        """Working ``(width, height)``."""
        height, width = self.region_map.shape
        return width, height

    @property
    def region_count(self) -> int:
        """Number of areas to paint."""
        return len(self.region_color)

    @property
    def output_size(self) -> tuple[int, int]:
        """Rendered page ``(width, height)`` in pixels."""
        width, height = self.size
        scale = self.settings.output_size / max(width, height)
        return max(1, round(width * scale)), max(1, round(height * scale))

    @property
    def mm_per_working_pixel(self) -> float:
        """Printed millimetres per working pixel."""
        return PAGE_LONG_SIDE_MM / max(self.size)

    def summary(self) -> dict[str, object]:
        """Plain-JSON description of the result for UIs and the CLI."""
        return {
            "settings": self.settings.to_dict(),
            "palette": [entry.to_dict() for entry in self.palette],
            "regions": self.region_count,
            "labels": len(self.labels),
            "working_size": list(self.size),
            "output_size": list(self.output_size),
            "difficulty": asdict(self.difficulty),
            "difficulty_summary": self.difficulty.summary(),
            "warnings": list(self.warnings),
        }


def load_image(data: bytes | str | Image.Image) -> Image.Image:
    """Open image bytes or a path, honour EXIF rotation, flatten transparency onto white."""
    if isinstance(data, Image.Image):
        picture = data
    elif isinstance(data, (bytes, bytearray, memoryview)):
        picture = Image.open(io.BytesIO(bytes(data)))
    else:
        picture = Image.open(data)
    picture.load()
    picture = ImageOps.exif_transpose(picture) or picture
    if picture.mode in {"RGBA", "LA"} or (picture.mode == "P" and "transparency" in picture.info):
        rgba = picture.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        picture = Image.alpha_composite(background, rgba)
    return picture.convert("RGB")


def _resize(picture: Image.Image, long_side: int) -> np.ndarray:
    width, height = picture.size
    scale = long_side / max(width, height)
    size = (max(8, round(width * scale)), max(8, round(height * scale)))
    resized = picture.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
    return np.asarray(resized, dtype=np.uint8).copy()


def _compact_colors(
    index_map: np.ndarray, colors: list[RGB], names: list[str]
) -> tuple[np.ndarray, list[RGB], list[str]]:
    used = np.unique(index_map)
    remap = np.zeros(max(len(colors), 1), dtype=np.uint8)
    remap[used] = np.arange(len(used), dtype=np.uint8)
    return (
        remap[index_map],
        [colors[i] for i in used.tolist()],
        [names[i] for i in used.tolist()],
    )


def generate(
    picture: bytes | str | Image.Image,
    settings: Settings | None = None,
    progress: Callable[[str], None] | None = None,
) -> Result:
    """Convert a picture (bytes, path, or PIL image) into a paint-by-numbers page.

    ``progress`` (optional) is called with a short message before each stage.
    """
    report = progress or (lambda _message: None)
    settings = (settings or Settings()).validated()
    warnings: list[str] = []
    if settings.marker == "shapes" and settings.colors == MAX_SHAPE_COLORS:
        warnings.append(f"Shape marks support at most {MAX_SHAPE_COLORS} colours.")

    source = _resize(load_image(picture), settings.detail)
    height, width, _ = source.shape
    px_per_mm = max(width, height) / PAGE_LONG_SIDE_MM
    min_side_px = settings.min_size_mm * px_per_mm
    min_area = max(1, round(min_side_px**2))
    min_depth = max(1, round(min_side_px * 0.28))

    style = get_style(settings.style)
    report(
        "Preparing the picture"
        if style.key == "photo"
        else f"Painting it in {style.label.lower()} style"
    )
    cell = max(2, math.ceil(min_side_px * 1.05), 2 * min_depth + 2)
    if settings.max_regions:
        cell = max(cell, math.ceil(math.sqrt(width * height / settings.max_regions)))
    styled = style.apply(source, StyleContext(max(width, height), cell, settings.seed))
    blur = 0.5 * SMOOTHING_MM[settings.smoothing] * px_per_mm
    simplified = (
        styled.image if style.geometric else simplify(styled.image, settings.smoothing, blur)
    )

    report("Choosing paint colours")
    quantized = quantize(simplified, settings.colors, get_palette(settings.palette), settings.seed)
    index_map = quantized.index_map
    if not style.geometric:
        sigma = SMOOTHING_MM[settings.smoothing] * px_per_mm
        index_map = smooth_index_map(index_map, len(quantized.colors), sigma)
    colors_lab = rgb_to_lab(np.array(quantized.colors, dtype=np.float64))
    report("Merging areas that are too small to paint")
    index_map, partition = merge_regions(
        index_map,
        colors_lab,
        min_area=min_area,
        min_depth=min_depth,
        max_regions=settings.max_regions,
        partition=styled.partition,
    )
    index_map, colors, names = _compact_colors(index_map, quantized.colors, quantized.names)
    if len(colors) < settings.colors:
        warnings.append(
            f"Using {len(colors)} of the {settings.colors} requested colours: "
            "the others only covered areas too small to paint."
        )

    report("Finding the best spots for the numbers")
    region_map, count = label_components(index_map, partition)
    color_of = region_colors(region_map, index_map, count)
    labels = place_labels(region_map, count, color_of, spacing=max(width, height) * 0.3)

    area = np.bincount(region_map.ravel(), minlength=count)
    color_area = np.bincount(color_of, weights=area, minlength=len(colors))
    color_regions = np.bincount(color_of, minlength=len(colors))
    palette = [
        PaletteEntry(
            number=index + 1,
            rgb=colors[index],
            name=names[index],
            area_fraction=float(color_area[index] / area.sum()),
            regions=int(color_regions[index]),
        )
        for index in range(len(colors))
    ]
    small_side = float(np.sqrt(np.percentile(area, 10))) / px_per_mm
    difficulty = estimate_difficulty(len(colors), count, small_side, settings.marker)
    return Result(
        settings=settings,
        source=source,
        styled=styled.image,
        region_map=region_map,
        region_color=color_of,
        palette=palette,
        labels=labels,
        difficulty=difficulty,
        warnings=warnings,
    )


def thinnest_region_depth(result: Result) -> int:
    """Smallest maximum erosion depth among all regions (useful for tests and tuning)."""
    depth = erosion_depth(result.region_map)
    deepest = np.zeros(result.region_count, dtype=np.int32)
    np.maximum.at(deepest, result.region_map.ravel(), depth.ravel())
    return int(deepest.min())
