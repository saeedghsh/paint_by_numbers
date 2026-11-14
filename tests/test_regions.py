"""Connected regions, merging and label placement."""

import numpy as np

from paint_by_numbers.regions import (
    erosion_depth,
    label_components,
    merge_regions,
    place_labels,
    region_colors,
    smooth_index_map,
)


def test_label_components_counts_separate_areas() -> None:
    index_map = np.zeros((6, 8), dtype=np.uint8)
    index_map[1:3, 1:3] = 1
    index_map[4:6, 5:8] = 1
    index_map[0, 7] = 2
    regions, count = label_components(index_map)
    assert count == 4  # background, two separate 1-blocks, one 2-pixel
    assert regions[1, 1] == regions[2, 2] != regions[4, 6]


def test_label_components_handles_a_long_spiral() -> None:
    # A one-pixel-wide snake is the worst case for naive label propagation.
    index_map = np.ones((41, 41), dtype=np.uint8)
    index_map[::2, :] = 0
    index_map[1::4, -1] = 0
    index_map[3::4, 0] = 0
    _, count = label_components(index_map)
    ones = np.sum(index_map == 1)
    assert count >= 2 and ones > 0
    regions, _ = label_components(index_map)
    assert len(np.unique(regions[index_map == 0])) == 1


def test_partition_keeps_borders_between_same_colours() -> None:
    index_map = np.zeros((4, 4), dtype=np.uint8)
    partition = np.zeros((4, 4), dtype=np.int32)
    partition[:, 2:] = 1
    _, count = label_components(index_map, partition)
    assert count == 2


def test_erosion_depth_is_highest_in_the_middle() -> None:
    regions = np.zeros((21, 21), dtype=np.int32)
    depth = erosion_depth(regions)
    assert depth[10, 10] == depth.max()
    assert depth[0, 0] == 0
    assert erosion_depth(regions, limit=3).max() == 3


def test_merge_removes_specks_and_slivers() -> None:
    index_map = np.zeros((40, 40), dtype=np.uint8)
    index_map[20:, :] = 1
    index_map[5, 5] = 2  # a speck
    index_map[30, :] = 2  # a one-pixel line through the lower half
    lab = np.array([[90.0, 0, 0], [40.0, 0, 0], [60.0, 0, 0]])
    merged, _ = merge_regions(index_map, lab, min_area=20, min_depth=2)
    assert 2 not in np.unique(merged)
    _, count = label_components(merged)
    assert count == 2


def test_merge_respects_max_regions() -> None:
    rng = np.random.default_rng(0)
    index_map = np.kron(rng.integers(0, 3, size=(8, 8)), np.ones((5, 5), dtype=int))
    lab = np.array([[90.0, 0, 0], [50.0, 30, 0], [20.0, 0, 30]])
    merged, _ = merge_regions(index_map.astype(np.uint8), lab, max_regions=5)
    _, count = label_components(merged)
    assert count <= 5


def test_labels_sit_inside_their_regions() -> None:
    index_map = np.zeros((30, 130), dtype=np.uint8)
    index_map[:, 25:] = 1
    index_map[10:20, 5:15] = 2
    regions, count = label_components(index_map)
    colours = region_colors(regions, index_map, count)
    labels = place_labels(regions, count, colours, spacing=25)
    assert {label.region for label in labels} == set(range(count))
    for label in labels:
        assert regions[int(label.y), int(label.x)] == label.region
        assert index_map[int(label.y), int(label.x)] == label.color
    # The long right-hand strip gets extra labels so nobody hunts for its number.
    assert sum(label.region == regions[0, 100] for label in labels) > 1


def test_smoothing_rounds_off_noise() -> None:
    rng = np.random.default_rng(0)
    index_map = np.zeros((60, 60), dtype=np.uint8)
    index_map[:, 30:] = 1
    flips = rng.random(index_map.shape) < 0.08
    noisy = np.where(flips, 1 - index_map, index_map).astype(np.uint8)
    smoothed = smooth_index_map(noisy, 2, 1.5)
    assert np.mean(smoothed != index_map) < np.mean(noisy != index_map) / 4
