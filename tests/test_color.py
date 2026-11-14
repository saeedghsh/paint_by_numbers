"""Colour conversions and naming."""

import numpy as np
import pytest

from paint_by_numbers.color import (
    contrast_text_color,
    delta_e,
    hex_color,
    hue_sort_key,
    lab_to_rgb,
    mix,
    parse_hex,
    rgb_to_lab,
)
from paint_by_numbers.palettes import (
    PALETTES,
    get_palette,
    nearest_color_name,
    unique_names,
)


def test_lab_round_trip_is_exact_for_many_colours() -> None:
    rng = np.random.default_rng(0)
    colours = rng.integers(0, 256, size=(500, 3))
    assert np.array_equal(lab_to_rgb(rgb_to_lab(colours)), colours)


def test_lab_reference_values() -> None:
    assert np.allclose(rgb_to_lab([255, 255, 255]), [100, 0, 0], atol=0.01)
    assert np.allclose(rgb_to_lab([0, 0, 0]), [0, 0, 0], atol=0.01)
    assert np.allclose(rgb_to_lab([255, 0, 0]), [53.24, 80.09, 67.20], atol=0.05)


def test_delta_e_and_hex_helpers() -> None:
    assert float(delta_e([50, 0, 0], [53, 4, 0])) == pytest.approx(5.0)
    assert hex_color((255, 128, 0)) == "#ff8000"
    assert parse_hex("#ff8000") == (255, 128, 0)
    with pytest.raises(ValueError):
        parse_hex("#fff")
    assert mix((0, 0, 0), (255, 255, 255), 0.5) == (128, 128, 128)
    assert contrast_text_color((250, 250, 250)) == (20, 20, 20)
    assert contrast_text_color((20, 20, 120)) == (255, 255, 255)


def test_hue_sort_puts_greys_last() -> None:
    colours = [(128, 128, 128), (30, 60, 200), (220, 30, 30), (30, 160, 60)]
    ordered = sorted(colours, key=hue_sort_key)
    assert ordered[-1] == (128, 128, 128)
    assert ordered[0] == (220, 30, 30)


def test_colour_names_are_plain() -> None:
    assert nearest_color_name((215, 30, 40)) == "red"
    assert nearest_color_name((40, 100, 200)) == "blue"
    assert nearest_color_name((250, 250, 250)) == "white"


def test_unique_names_disambiguate_shades() -> None:
    names = unique_names([(40, 160, 60), (30, 120, 50), (90, 190, 90)])
    assert len(set(names)) == 3
    blacks = unique_names([(10, 10, 10), (25, 25, 25)])
    assert blacks == ["black 1", "black 2"]


def test_palettes() -> None:
    assert get_palette("auto").is_auto
    assert len(get_palette("crayons-8").colors) == 8
    assert len(get_palette("crayons-24").colors) == 24
    for palette in PALETTES.values():
        names = [colour.name for colour in palette.colors]
        assert len(names) == len(set(names)), palette.key
    with pytest.raises(ValueError, match="unknown palette"):
        get_palette("felt-tips")
