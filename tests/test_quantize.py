"""Colour reduction with free and fixed palettes."""

import numpy as np
from PIL import Image

from paint_by_numbers.color import rgb_to_lab
from paint_by_numbers.palettes import get_palette
from paint_by_numbers.quantize import assign_distinct, kmeans, merge_close_colors, quantize


def test_kmeans_recovers_flat_colours(blocks: Image.Image) -> None:
    image = np.asarray(blocks)
    result = quantize(image, 6, get_palette("auto"))
    assert result.index_map.shape == image.shape[:2]
    assert len(result.colors) == len(result.names) <= 6
    # Every block colour is represented almost exactly.
    lab = rgb_to_lab(np.array(result.colors, dtype=float))
    for colour in [(30, 90, 200), (40, 160, 60), (250, 210, 40), (210, 40, 40)]:
        assert np.min(np.linalg.norm(lab - rgb_to_lab(colour), axis=1)) < 3


def test_quantize_is_deterministic(blocks: Image.Image) -> None:
    image = np.asarray(blocks)
    first = quantize(image, 5, get_palette("auto"), seed=3)
    second = quantize(image, 5, get_palette("auto"), seed=3)
    assert np.array_equal(first.index_map, second.index_map)
    assert first.colors == second.colors


def test_kmeans_returns_unique_colours_when_fewer_than_k() -> None:
    points = np.array([[10.0, 0, 0]] * 50 + [[80.0, 5, 5]] * 50)
    centers = kmeans(points, 8, np.random.default_rng(0))
    assert len(centers) == 2


def test_close_colours_are_merged() -> None:
    centers = np.array([[50.0, 0, 0], [52.0, 1, 0], [80.0, 0, 0]])
    sample = np.repeat(centers, 10, axis=0)
    merged = merge_close_colors(centers.copy(), sample, 6.0)
    assert len(merged) == 2


def test_crayon_palette_uses_only_crayons(blocks: Image.Image) -> None:
    box = get_palette("crayons-8")
    result = quantize(np.asarray(blocks), 5, box)
    crayons = {colour.rgb for colour in box.colors}
    assert set(result.colors) <= crayons
    assert {"red", "blue", "green", "yellow"} <= set(result.names)


def test_monochrome_picture_still_gets_distinct_crayons() -> None:
    # A brown-only gradient: naive nearest-crayon matching would give one colour.
    ramp = np.linspace(60, 200, 120)
    image = np.stack([ramp, ramp * 0.75, ramp * 0.5], axis=-1)[None].repeat(40, axis=0)
    result = quantize(image.astype(np.uint8), 4, get_palette("crayons-8"))
    assert len(result.colors) == 4


def test_assign_distinct_prefers_unique_columns_within_tolerance() -> None:
    cost = np.array([[1.0, 5.0, 90.0], [2.0, 6.0, 95.0], [3.0, 80.0, 4.0]])
    assert assign_distinct(cost, tolerance=10) == [0, 1, 2]
    # Row 1's only free column is far worse than its nearest, so it may share...
    far = np.array([[1.0, 90.0], [2.0, 95.0], [3.0, 99.0]])
    assert assign_distinct(far, tolerance=10)[2] == 0
