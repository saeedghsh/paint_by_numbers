"""Colour names and fixed real-world palettes (crayon boxes, paint sets).

A fixed palette lets a child paint with the exact crayons they own: the image is
recoloured using only colours from the box, and the legend uses plain names such
as "red" or "light blue" that a young painter can find.
"""

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from paint_by_numbers.color import RGB, rgb_to_lab


@dataclass(frozen=True)
class NamedColor:
    """A colour with a human-friendly name."""

    name: str
    rgb: RGB


@dataclass(frozen=True)
class Palette:
    """A selectable palette; ``auto`` (no colours) derives colours from the image."""

    key: str
    label: str
    description: str
    colors: tuple[NamedColor, ...] = ()

    @property
    def is_auto(self) -> bool:
        """Return whether colours are derived from the picture itself."""
        return not self.colors


def _named(*entries: tuple[str, RGB]) -> tuple[NamedColor, ...]:
    return tuple(NamedColor(name, rgb) for name, rgb in entries)


# Reference colours used only for naming. Kept deliberately plain: the names have
# to make sense to a five-year-old as well as to an adult.
COLOR_NAMES: tuple[NamedColor, ...] = _named(
    ("black", (22, 22, 22)),
    ("charcoal", (55, 58, 64)),
    ("dark gray", (92, 92, 92)),
    ("gray", (130, 130, 130)),
    ("light gray", (192, 192, 192)),
    ("white", (250, 250, 250)),
    ("cream", (248, 238, 208)),
    ("beige", (222, 203, 168)),
    ("tan", (198, 166, 122)),
    ("light brown", (168, 118, 74)),
    ("brown", (118, 74, 40)),
    ("dark brown", (72, 44, 26)),
    ("peach", (250, 200, 162)),
    ("salmon", (242, 138, 118)),
    ("light pink", (248, 200, 214)),
    ("pink", (238, 128, 168)),
    ("magenta", (214, 40, 140)),
    ("red", (212, 36, 40)),
    ("dark red", (138, 22, 30)),
    ("maroon", (98, 26, 40)),
    ("orange", (244, 128, 32)),
    ("light orange", (250, 174, 92)),
    ("burnt orange", (192, 86, 28)),
    ("gold", (222, 172, 42)),
    ("yellow", (250, 218, 42)),
    ("light yellow", (250, 240, 152)),
    ("mustard", (196, 162, 44)),
    ("olive", (118, 118, 42)),
    ("khaki", (188, 178, 120)),
    ("lime green", (160, 208, 62)),
    ("light green", (162, 218, 142)),
    ("green", (52, 158, 62)),
    ("dark green", (26, 88, 44)),
    ("mint", (172, 228, 200)),
    ("sage", (148, 168, 128)),
    ("teal", (22, 128, 128)),
    ("turquoise", (62, 198, 198)),
    ("pale blue", (196, 226, 238)),
    ("sky blue", (128, 192, 238)),
    ("light blue", (176, 206, 240)),
    ("blue", (42, 100, 198)),
    ("navy", (26, 40, 98)),
    ("slate", (100, 114, 138)),
    ("lavender", (194, 176, 228)),
    ("violet", (148, 90, 198)),
    ("purple", (118, 60, 158)),
    ("dark purple", (70, 32, 90)),
    ("plum", (138, 70, 108)),
)

_CRAYONS_8 = _named(
    ("red", (220, 36, 46)),
    ("orange", (252, 126, 32)),
    ("yellow", (252, 218, 32)),
    ("green", (32, 160, 72)),
    ("blue", (32, 100, 208)),
    ("purple", (124, 66, 168)),
    ("brown", (124, 76, 42)),
    ("black", (32, 32, 32)),
)
_CRAYONS_16 = _CRAYONS_8 + _named(
    ("white", (255, 255, 255)),
    ("gray", (140, 140, 140)),
    ("pink", (244, 140, 180)),
    ("light blue", (132, 194, 240)),
    ("light green", (150, 214, 112)),
    ("peach", (250, 196, 152)),
    ("dark green", (26, 96, 52)),
    ("magenta", (204, 42, 140)),
)
_CRAYONS_24 = _CRAYONS_16 + _named(
    ("dark red", (140, 26, 40)),
    ("gold", (220, 170, 42)),
    ("tan", (206, 170, 120)),
    ("turquoise", (52, 190, 196)),
    ("navy", (30, 46, 110)),
    ("lavender", (190, 166, 226)),
    ("dark brown", (80, 50, 30)),
    ("light yellow", (250, 240, 150)),
)
_ACRYLIC = _named(
    ("titanium white", (250, 250, 246)),
    ("lemon yellow", (250, 230, 62)),
    ("cadmium yellow", (250, 190, 22)),
    ("yellow ochre", (204, 146, 56)),
    ("cadmium orange", (240, 112, 30)),
    ("cadmium red", (204, 36, 36)),
    ("alizarin crimson", (150, 22, 46)),
    ("burnt sienna", (140, 66, 36)),
    ("burnt umber", (86, 56, 40)),
    ("sap green", (76, 110, 42)),
    ("viridian", (40, 120, 100)),
    ("cerulean blue", (42, 126, 190)),
    ("ultramarine blue", (42, 52, 150)),
    ("dioxazine purple", (76, 36, 100)),
    ("mars black", (30, 30, 32)),
)
_PASTELS = _named(
    ("baby pink", (248, 200, 212)),
    ("peach", (250, 210, 170)),
    ("butter yellow", (250, 238, 160)),
    ("mint", (186, 232, 200)),
    ("sky blue", (172, 214, 242)),
    ("lavender", (204, 188, 236)),
    ("lilac", (226, 196, 230)),
    ("sand", (232, 214, 182)),
    ("sage", (178, 196, 160)),
    ("dusty blue", (140, 164, 196)),
    ("rose", (214, 140, 160)),
    ("cocoa", (150, 116, 96)),
)
_GREYS = _named(
    ("white", (250, 250, 250)),
    ("gray 1 (lightest)", (222, 222, 222)),
    ("gray 2", (190, 190, 190)),
    ("gray 3", (158, 158, 158)),
    ("gray 4", (124, 124, 124)),
    ("gray 5", (92, 92, 92)),
    ("gray 6 (darkest)", (58, 58, 58)),
    ("black", (24, 24, 24)),
)

PALETTES: dict[str, Palette] = {
    palette.key: palette
    for palette in (
        Palette("auto", "From the picture", "Colours are picked to match the picture."),
        Palette(
            "crayons-8", "Crayon box (8)", "The classic 8-crayon box: bold, easy names.", _CRAYONS_8
        ),
        Palette(
            "crayons-16", "Crayon box (16)", "A 16-crayon box with lighter tones.", _CRAYONS_16
        ),
        Palette(
            "crayons-24", "Crayon box (24)", "A 24-crayon box with in-between tones.", _CRAYONS_24
        ),
        Palette(
            "acrylic",
            "Student acrylic set (15)",
            "Common artist pigments, for painting with real paint.",
            _ACRYLIC,
        ),
        Palette("pastels", "Soft pastels (12)", "Gentle nursery-style colours.", _PASTELS),
        Palette("greys", "Greys only (8)", "A value study in shades of grey.", _GREYS),
    )
}

_NAME_LAB = rgb_to_lab(np.array([color.rgb for color in COLOR_NAMES], dtype=np.float64))


def get_palette(key: str) -> Palette:
    """Return a palette by key, with a helpful error for unknown keys."""
    try:
        return PALETTES[key]
    except KeyError as error:
        choices = ", ".join(PALETTES)
        raise ValueError(f"unknown palette {key!r}; choose one of: {choices}") from error


def nearest_color_name(rgb: RGB | np.ndarray) -> str:
    """Return the closest plain colour name for an sRGB colour."""
    lab = rgb_to_lab(np.asarray(rgb, dtype=np.float64))
    distances = np.sum((_NAME_LAB - lab) ** 2, axis=1)
    return COLOR_NAMES[int(np.argmin(distances))].name


_SHADE_PREFIXES = {
    2: ["dark", "light"],
    3: ["dark", "", "light"],
    4: ["darkest", "dark", "light", "lightest"],
    5: ["darkest", "dark", "", "light", "lightest"],
}


def unique_names(colors: list[RGB]) -> list[str]:
    """Name each colour, disambiguating repeats with "dark"/"light" or numbers."""
    names = [nearest_color_name(rgb) for rgb in colors]
    groups: dict[str, list[int]] = defaultdict(list)
    for index, name in enumerate(names):
        groups[name].append(index)
    lightness = rgb_to_lab(np.array(colors, dtype=np.float64).reshape(-1, 3))[:, 0]
    for name, indices in groups.items():
        if len(indices) == 1:
            continue
        ordered = sorted(indices, key=lambda index: lightness[index])
        modified = name.split(" ")[0] in {"light", "dark", "pale"} or name in {"black", "white"}
        prefixes = [] if modified else _SHADE_PREFIXES.get(len(ordered), [])
        for position, index in enumerate(ordered):
            if prefixes:
                names[index] = f"{prefixes[position]} {name}".strip()
            else:
                names[index] = f"{name} {position + 1}"
    # Prefixing can collide with an existing name ("dark" + "green" = "dark green").
    clashes: dict[str, list[int]] = defaultdict(list)
    for index, name in enumerate(names):
        clashes[name].append(index)
    for name, indices in clashes.items():
        if len(indices) > 1:
            for position, index in enumerate(sorted(indices, key=lambda i: lightness[i])):
                names[index] = f"{name} {position + 1}"
    return names
