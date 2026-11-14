"""Who is painting? Age-based presets and a difficulty estimate.

Painting ability changes a lot with age. A two-year-old is still learning to
hold a crayon and may not know numbers yet; a ten-year-old can follow dozens of
numbered areas; an adult may enjoy a thousand tiny ones. Each profile turns that
into concrete settings: how many colours, how big the smallest area is on the
printed page, how thick the lines are, and what kind of mark tells the painter
which colour to use.

The reverse direction is just as useful: :func:`estimate_difficulty` looks at a
finished page and suggests the age range it suits.
"""

import math
from dataclasses import dataclass, field

# Sizes are expressed in millimetres on the printed page. Pages are laid out for
# A4/Letter, whose printable long side is about 270 mm.
PAGE_LONG_SIDE_MM = 270.0

MARKERS: dict[str, str] = {
    "numbers": "Numbers - the classic: each area shows its colour number.",
    "number-dots": "Numbers on coloured dots - for children still learning numbers.",
    "shapes": "Shapes (circle, star, heart...) - for children who know shapes, not numbers.",
    "dots": "Colour dots - match the crayon to the dot; no reading needed.",
    "none": "Blank outlines - colour freely or follow the preview.",
}


@dataclass(frozen=True)
class AudienceProfile:
    """Recommended settings for one group of painters."""

    key: str
    label: str
    ages: str
    description: str
    colors: int
    detail: int  # working resolution: long side of the processed picture, in pixels
    smoothing: int  # 0..5 edge-preserving simplification
    min_size_mm: float  # smallest area on the printed page (side of a square)
    max_regions: int  # 0 = no limit
    line_mm: float  # outline thickness on the printed page
    label_mm: float  # largest number / marker height on the printed page
    marker: str
    tint: bool  # wash each area in a pale version of its colour
    palette: str
    tips: tuple[str, ...] = field(default_factory=tuple)


PROFILES: dict[str, AudienceProfile] = {
    profile.key: profile
    for profile in (
        AudienceProfile(
            key="toddler",
            label="Little hands",
            ages="2-3",
            description="A few huge areas, thick lines and colour dots instead of numbers.",
            colors=4,
            detail=180,
            smoothing=5,
            min_size_mm=30.0,
            max_regions=9,
            line_mm=1.6,
            label_mm=16.0,
            marker="dots",
            tint=True,
            palette="crayons-8",
            tips=(
                "No numbers needed: each area has a dot and a pale wash of its colour.",
                "Lay out only the crayons in the legend and say each colour's name together.",
                "Chunky crayons or dot markers are easier for small hands than brushes.",
            ),
        ),
        AudienceProfile(
            key="preschool",
            label="Preschool",
            ages="4-5",
            description="Big areas, a few colours, numbers on coloured dots.",
            colors=6,
            detail=260,
            smoothing=4,
            min_size_mm=20.0,
            max_regions=25,
            line_mm=1.1,
            label_mm=9.0,
            marker="number-dots",
            tint=False,
            palette="crayons-8",
            tips=(
                "The coloured dot behind each number helps children who are still learning digits.",
                "Try the 'shapes' marks for children who know shapes better than numbers.",
            ),
        ),
        AudienceProfile(
            key="early",
            label="Young painter",
            ages="6-8",
            description="Clear areas, up to ten colours, classic numbers.",
            colors=10,
            detail=360,
            smoothing=3,
            min_size_mm=11.0,
            max_regions=70,
            line_mm=0.7,
            label_mm=6.0,
            marker="numbers",
            tint=False,
            palette="crayons-16",
            tips=("Colours come from a 16-crayon box, so every number matches a real crayon.",),
        ),
        AudienceProfile(
            key="kids",
            label="Big kid",
            ages="9-12",
            description="More detail and colours picked from the picture.",
            colors=15,
            detail=480,
            smoothing=2,
            min_size_mm=6.0,
            max_regions=220,
            line_mm=0.5,
            label_mm=4.5,
            marker="numbers",
            tint=False,
            palette="auto",
        ),
        AudienceProfile(
            key="teen",
            label="Teen",
            ages="13-17",
            description="Detailed pictures with a rich palette.",
            colors=22,
            detail=600,
            smoothing=2,
            min_size_mm=4.0,
            max_regions=600,
            line_mm=0.35,
            label_mm=3.6,
            marker="numbers",
            tint=False,
            palette="auto",
        ),
        AudienceProfile(
            key="adult",
            label="Adult",
            ages="18+",
            description="Fine detail, thin lines, a full palette.",
            colors=30,
            detail=760,
            smoothing=1,
            min_size_mm=2.8,
            max_regions=0,
            line_mm=0.25,
            label_mm=3.0,
            marker="numbers",
            tint=False,
            palette="auto",
        ),
        AudienceProfile(
            key="expert",
            label="Expert",
            ages="18+",
            description="Maximum detail for long, patient projects.",
            colors=40,
            detail=1000,
            smoothing=1,
            min_size_mm=1.8,
            max_regions=0,
            line_mm=0.2,
            label_mm=2.6,
            marker="numbers",
            tint=False,
            palette="auto",
            tips=("Print large (A3 or bigger) or raise the output size for the finest areas.",),
        ),
    )
}

# Ages accepted by the CLI's --age option, mapped to profiles.
AGE_ALIASES: dict[str, str] = {
    "2": "toddler",
    "3": "toddler",
    "2-3": "toddler",
    "4": "preschool",
    "5": "preschool",
    "4-5": "preschool",
    "6": "early",
    "7": "early",
    "8": "early",
    "6-8": "early",
    "9": "kids",
    "10": "kids",
    "11": "kids",
    "12": "kids",
    "9-12": "kids",
    "13": "teen",
    "14": "teen",
    "15": "teen",
    "16": "teen",
    "17": "teen",
    "13-17": "teen",
    "18+": "adult",
    "adult": "adult",
    "expert": "expert",
}


def get_profile(key: str) -> AudienceProfile:
    """Return a profile by key or by age (``"5"``, ``"6-8"``, ``"18+"``...)."""
    text = key.strip().lower()
    if text in PROFILES:
        return PROFILES[text]
    if text in AGE_ALIASES:
        return PROFILES[AGE_ALIASES[text]]
    if text.isdigit() and int(text) >= 18:
        return PROFILES["adult"]
    choices = ", ".join(list(PROFILES) + ["or an age such as 4 or 9-12"])
    raise ValueError(f"unknown profile or age {key!r}; choose {choices}")


@dataclass(frozen=True)
class _Band:
    profile: str
    max_colors: float
    max_regions: float
    min_size_mm: float  # typical small area (10th percentile) on the printed page


_BANDS = (
    _Band("toddler", 4, 12, 28.0),
    _Band("preschool", 6, 35, 14.0),
    _Band("early", 10, 100, 7.5),
    _Band("kids", 16, 300, 4.5),
    _Band("teen", 24, 800, 3.0),
    _Band("adult", 36, 2500, 1.8),
    _Band("expert", math.inf, math.inf, 0.0),
)


@dataclass(frozen=True)
class Difficulty:
    """A suggested age range for a finished page, with the reason behind it."""

    profile: str
    ages: str
    label: str
    reason: str
    colors: int
    regions: int
    small_area_mm: float

    def summary(self) -> str:
        """One line, e.g. ``Suggested ages 6-8 (Young painter): 64 areas ...``."""
        return f"Suggested ages {self.ages} ({self.label}): {self.reason}"


def estimate_difficulty(colors: int, regions: int, small_area_mm: float, marker: str) -> Difficulty:
    """Suggest the youngest age group that can comfortably paint a page.

    ``small_area_mm`` is the side of a typical small area (10th percentile) on
    the printed page. The page is as hard as its hardest aspect: too many
    colours, too many areas, areas too small for the painter's fine motor
    skills, or marks the painter cannot read yet.
    """
    requirements: list[tuple[int, str]] = []

    def first_band(test: str, value: float) -> int:
        for index, band in enumerate(_BANDS):
            if test == "colors" and value <= band.max_colors:
                return index
            if test == "regions" and value <= band.max_regions:
                return index
            if test == "size" and value >= band.min_size_mm:
                return index
        return len(_BANDS) - 1

    requirements.append((first_band("colors", colors), f"{colors} colours"))
    requirements.append((first_band("regions", regions), f"{regions} areas to paint"))
    requirements.append(
        (first_band("size", small_area_mm), f"small areas about {small_area_mm:.0f} mm across")
    )
    if marker in {"numbers", "number-dots"}:
        reading = 1 if colors <= 9 else 2
        requirements.append((reading, f"reading numbers up to {colors}"))
    elif marker == "shapes":
        requirements.append((0 if colors <= 4 else 1, f"telling {colors} shapes apart"))

    level, reason = max(requirements, key=lambda item: item[0])
    profile = PROFILES[_BANDS[level].profile]
    return Difficulty(
        profile=profile.key,
        ages=profile.ages,
        label=profile.label,
        reason=f"limited by {reason}",
        colors=colors,
        regions=regions,
        small_area_mm=small_area_mm,
    )
