"""Age profiles and the difficulty estimate."""

import pytest

from paint_by_numbers.profiles import AGE_ALIASES, PROFILES, estimate_difficulty, get_profile


def test_profiles_get_harder_with_age() -> None:
    ordered = list(PROFILES.values())
    for younger, older in zip(ordered, ordered[1:]):
        assert younger.colors <= older.colors
        assert younger.min_size_mm >= older.min_size_mm
        assert younger.line_mm >= older.line_mm
        assert younger.detail <= older.detail


def test_youngest_painters_do_not_need_numbers() -> None:
    assert get_profile("2").marker in {"dots", "shapes"}
    assert get_profile("toddler").tint
    assert get_profile("4").marker == "number-dots"


@pytest.mark.parametrize(
    ("text", "key"),
    [("3", "toddler"), ("5", "preschool"), ("6-8", "early"), ("11", "kids"), ("15", "teen"),
     ("18+", "adult"), ("42", "adult"), ("Expert", "expert")],
)  # fmt: skip
def test_ages_map_to_profiles(text: str, key: str) -> None:
    assert get_profile(text).key == key


def test_every_alias_is_valid() -> None:
    assert set(AGE_ALIASES.values()) <= set(PROFILES)
    with pytest.raises(ValueError):
        get_profile("1")


@pytest.mark.parametrize(
    ("colors", "regions", "size", "marker", "expected"),
    [
        (3, 8, 40.0, "dots", "toddler"),
        (3, 8, 40.0, "numbers", "preschool"),  # needs number reading
        (6, 30, 16.0, "number-dots", "preschool"),
        (10, 60, 9.0, "numbers", "early"),
        (14, 200, 5.0, "numbers", "kids"),
        (30, 900, 2.0, "numbers", "adult"),
        (40, 5000, 1.0, "numbers", "expert"),
    ],
)
def test_difficulty_bands(
    colors: int, regions: int, size: float, marker: str, expected: str
) -> None:
    difficulty = estimate_difficulty(colors, regions, size, marker)
    assert difficulty.profile == expected
    assert difficulty.ages == PROFILES[expected].ages
    assert "limited by" in difficulty.summary()


def test_difficulty_names_the_hardest_aspect() -> None:
    difficulty = estimate_difficulty(4, 400, 30.0, "dots")
    assert "areas" in difficulty.reason
