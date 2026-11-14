"""Turn a colour-index map into clean, paintable regions.

All operations are vectorised NumPy so they stay fast inside Pyodide, where a
pure-Python flood fill over half a million pixels would be far too slow.

* :func:`label_components` finds 4-connected areas of equal colour (and equal
  ``partition`` cell, for styles such as the pixel grid that force boundaries).
* :func:`merge_regions` folds regions that are too small, too thin, or too many
  into their most similar neighbour.
* :func:`place_labels` finds the most comfortable spot(s) for each region's number.
"""

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from paint_by_numbers.color import delta_e

_CROSS = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))


@dataclass(frozen=True)
class LabelPoint:
    """Where to write a region's marker, in working-image pixel coordinates."""

    region: int
    color: int
    x: float
    y: float
    radius: float  # approximate radius of the largest disc that fits at (x, y)


def _shift(mask: np.ndarray, dy: int, dx: int, fill: bool | int = False) -> np.ndarray:
    """Return ``out[y, x] = mask[y + dy, x + dx]`` with ``fill`` outside the image."""
    height, width = mask.shape
    out = np.full_like(mask, fill)
    out[max(0, -dy) : height - max(0, dy), max(0, -dx) : width - max(0, dx)] = mask[
        max(0, dy) : height - max(0, -dy), max(0, dx) : width - max(0, -dx)
    ]
    return out


def combine_partition(index_map: np.ndarray, partition: np.ndarray | None) -> np.ndarray:
    """Return a single key per pixel that differs whenever colour or partition differ."""
    if partition is None:
        return index_map.astype(np.int64)
    return partition.astype(np.int64) * 256 + index_map.astype(np.int64)


def label_components(
    index_map: np.ndarray, partition: np.ndarray | None = None
) -> tuple[np.ndarray, int]:
    """Label 4-connected regions of equal colour; return ``(region_map, count)``.

    Union-find with vectorised hooking and pointer jumping: each round links
    every pair of touching roots, then flattens the trees, so the number of
    rounds grows roughly with the logarithm of region size rather than its length.
    """
    keys = combine_partition(index_map, partition)
    height, width = keys.shape
    pixel = np.arange(height * width).reshape(height, width)
    right = keys[:, :-1] == keys[:, 1:]
    down = keys[:-1, :] == keys[1:, :]
    first = np.concatenate([pixel[:, :-1][right], pixel[:-1, :][down]])
    second = np.concatenate([pixel[:, 1:][right], pixel[1:, :][down]])
    parent = np.arange(height * width)
    while len(first):
        root_first = parent[first]
        root_second = parent[second]
        differ = root_first != root_second
        if not differ.any():
            break
        first, second = first[differ], second[differ]
        low = np.minimum(root_first[differ], root_second[differ])
        high = np.maximum(root_first[differ], root_second[differ])
        np.minimum.at(parent, high, low)
        while True:
            grandparent = parent[parent]
            if np.array_equal(grandparent, parent):
                break
            parent = grandparent
    _, labels = np.unique(parent, return_inverse=True)
    region_map = labels.reshape(height, width).astype(np.int32)
    return region_map, int(region_map.max()) + 1


def erosion_depth(region_map: np.ndarray, limit: int | None = None) -> np.ndarray:
    """How many erosions each pixel survives inside its own region.

    Alternating 4- and 8-neighbour erosions approximate the Euclidean distance
    to the region boundary (an octagonal metric). The picture edge counts as a
    boundary, so labels keep away from it.
    """
    same = {
        offset: _shift(region_map, *offset, fill=-1) == region_map for offset in _CROSS + _DIAGONAL
    }
    depth = np.zeros(region_map.shape, dtype=np.int32)
    interior = np.ones(region_map.shape, dtype=bool)
    step = 0
    while interior.any() and (limit is None or step < limit):
        step += 1
        offsets = _CROSS if step % 2 else _CROSS + _DIAGONAL
        survivor = interior.copy()
        for offset in offsets:
            survivor &= same[offset] & _shift(interior, *offset)
        interior = survivor
        depth += interior
    return depth


def blurred_masks(index_map: np.ndarray, count: int, sigma: float) -> list[Image.Image]:
    """One Gaussian-blurred 8-bit mask per colour index (Pillow keeps this fast)."""
    masks = []
    for color in range(count):
        mask = Image.fromarray(np.where(index_map == color, 255, 0).astype(np.uint8), "L")
        masks.append(mask.filter(ImageFilter.GaussianBlur(sigma)) if sigma > 0 else mask)
    return masks


def vote(masks: list[Image.Image], size: tuple[int, int] | None = None) -> np.ndarray:
    """Per pixel, the index of the strongest mask (optionally after bilinear resizing)."""
    best: np.ndarray | None = None
    strongest: np.ndarray | None = None
    for color, mask in enumerate(masks):
        if size is not None and mask.size != size:
            mask = mask.resize(size, Image.Resampling.BILINEAR)
        values = np.asarray(mask, dtype=np.int16)
        if best is None or strongest is None:
            best = np.zeros(values.shape, dtype=np.uint8)
            strongest = values
            continue
        better = values > strongest
        best[better] = color
        strongest = np.where(better, values, strongest)
    if best is None:
        raise ValueError("no masks to vote on")
    return best


def smooth_index_map(index_map: np.ndarray, count: int, sigma: float) -> np.ndarray:
    """Round off jagged, speckled colour borders with a Gaussian-weighted majority vote.

    Unlike a box-shaped mode filter, the Gaussian vote is isotropic: corners round
    off evenly and noisy borders (for example between bands of a sky gradient)
    become smooth curves.
    """
    if sigma <= 0 or count < 2:
        return index_map
    return vote(blurred_masks(index_map, count, sigma))


def region_colors(region_map: np.ndarray, index_map: np.ndarray, count: int) -> np.ndarray:
    """Return the colour index of every region."""
    colors = np.zeros(count, dtype=np.int64)
    colors[region_map.ravel()] = index_map.ravel()
    return colors


def _adjacent_pairs(region_map: np.ndarray, count: int) -> tuple[np.ndarray, ...]:
    """Return ``(source, neighbour, shared_border_length)`` for every touching pair."""
    first = np.concatenate([region_map[:, :-1].ravel(), region_map[:-1, :].ravel()])
    second = np.concatenate([region_map[:, 1:].ravel(), region_map[1:, :].ravel()])
    differ = first != second
    first, second = first[differ].astype(np.int64), second[differ].astype(np.int64)
    source = np.concatenate([first, second])
    neighbour = np.concatenate([second, first])
    keys, border = np.unique(source * count + neighbour, return_counts=True)
    return keys // count, keys % count, border


def _follow_chains(target: np.ndarray) -> np.ndarray:
    while True:
        jumped = target[target]
        if np.array_equal(jumped, target):
            return target
        target = jumped


def merge_regions(
    index_map: np.ndarray,
    colors_lab: np.ndarray,
    *,
    min_area: int = 1,
    min_depth: int = 0,
    max_regions: int = 0,
    partition: np.ndarray | None = None,
    max_passes: int = 60,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Repaint regions that are too small, too thin, or surplus with a neighbour's colour.

    Each region marked for merging joins a *larger* neighbour (so merges never
    cycle), preferring similar colours and long shared borders. ``min_depth`` is
    the erosion depth a region needs somewhere inside it: slivers thinner than
    about ``2 * min_depth`` pixels are folded away even if their area is large.
    Returns the new ``(index_map, partition)``.
    """
    index_map = index_map.copy()
    partition = None if partition is None else partition.copy()
    for _ in range(max_passes):
        region_map, count = label_components(index_map, partition)
        if count <= 1:
            break
        flat = region_map.ravel()
        area = np.bincount(flat, minlength=count)
        doomed = area < min_area
        if min_depth > 0:
            depth = erosion_depth(region_map, limit=min_depth)
            deepest = np.zeros(count, dtype=np.int32)
            np.maximum.at(deepest, flat, depth.ravel())
            doomed |= deepest < min_depth
        if max_regions and count > max_regions:
            doomed[np.argsort(area, kind="stable")[: count - max_regions]] = True
        if not doomed.any():
            break

        color_of = region_colors(region_map, index_map, count)
        source, neighbour, border = _adjacent_pairs(region_map, count)
        larger = (area[neighbour] > area[source]) | (
            (area[neighbour] == area[source]) & (neighbour < source)
        )
        keep = doomed[source] & larger
        source, neighbour, border = source[keep], neighbour[keep], border[keep]
        if len(source) == 0:
            break
        cost = delta_e(colors_lab[color_of[source]], colors_lab[color_of[neighbour]])
        cost = cost - 4.0 * np.log1p(border)
        order = np.lexsort((cost, source))
        source, neighbour = source[order], neighbour[order]
        best = np.ones(len(source), dtype=bool)
        best[1:] = source[1:] != source[:-1]
        target = np.arange(count)
        target[source[best]] = neighbour[best]
        target = _follow_chains(target)
        index_map = color_of[target][region_map].astype(index_map.dtype)
        if partition is not None:
            cell_of = np.zeros(count, dtype=np.int64)
            cell_of[flat] = partition.ravel()
            partition = cell_of[target][region_map].astype(partition.dtype)
    return index_map, partition


def place_labels(
    region_map: np.ndarray,
    count: int,
    color_of: np.ndarray,
    *,
    spacing: float = 0.0,
    max_per_region: int = 4,
) -> list[LabelPoint]:
    """Pick one label spot per region (more for big regions when ``spacing`` > 0).

    The main spot is the deepest point of the region - the centre of the largest
    disc that fits - with ties broken towards the region's centroid. Regions that
    stretch further than ``spacing`` pixels from their first label get extra
    labels at the farthest comfortable points, so nobody hunts for a number.
    """
    height, width = region_map.shape
    depth = erosion_depth(region_map).astype(np.float64)
    flat = region_map.ravel()
    area = np.bincount(flat, minlength=count).astype(np.float64)
    ys, xs = np.indices((height, width))
    centre_y = np.bincount(flat, ys.ravel(), minlength=count) / area
    centre_x = np.bincount(flat, xs.ravel(), minlength=count) / area
    off_centre = np.hypot(ys.ravel() - centre_y[flat], xs.ravel() - centre_x[flat])
    score = depth.ravel() * 1e6 - off_centre
    order = np.lexsort((score, flat))
    last = np.ones(len(order), dtype=bool)
    last[:-1] = flat[order][1:] != flat[order][:-1]
    best_pixels = order[last]

    labels: list[LabelPoint] = []
    for pixel in best_pixels:
        region = int(flat[pixel])
        y, x = divmod(int(pixel), width)
        labels.append(LabelPoint(region, int(color_of[region]), float(x), float(y), depth[y, x]))

    if spacing > 0 and max_per_region > 1:
        labels.extend(_extra_labels(region_map, depth, labels, color_of, spacing, max_per_region))
    return labels


def _extra_labels(
    region_map: np.ndarray,
    depth: np.ndarray,
    primary: list[LabelPoint],
    color_of: np.ndarray,
    spacing: float,
    max_per_region: int,
) -> list[LabelPoint]:
    """Farthest-point sampling of extra label spots inside very large regions."""
    extra: list[LabelPoint] = []
    area = np.bincount(region_map.ravel(), minlength=len(primary))
    for label in primary:
        if area[label.region] < spacing * spacing * 0.6 or label.radius < 2:
            continue
        ys, xs = np.nonzero(region_map == label.region)
        comfortable = depth[ys, xs] >= max(2.0, label.radius * 0.45)
        ys, xs = ys[comfortable], xs[comfortable]
        if len(ys) == 0:
            continue
        nearest = np.hypot(ys - label.y, xs - label.x)
        for _ in range(max_per_region - 1):
            candidate = int(np.argmax(nearest))
            if nearest[candidate] < spacing:
                break
            y, x = int(ys[candidate]), int(xs[candidate])
            extra.append(
                LabelPoint(label.region, int(color_of[label.region]), x, y, float(depth[y, x]))
            )
            nearest = np.minimum(nearest, np.hypot(ys - y, xs - x))
    return extra
