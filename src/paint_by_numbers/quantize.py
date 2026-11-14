"""Reduce a picture to a handful of paint colours.

Colours are clustered with k-means in L*a*b* space. For a fixed palette (say, a
box of 8 crayons) the clusters are snapped to the nearest colours in the box, so
the picture is redrawn with crayons the painter actually owns.
"""

import math
from dataclasses import dataclass

import numpy as np

from paint_by_numbers.color import RGB, delta_e, hue_sort_key, lab_to_rgb, rgb_to_lab
from paint_by_numbers.palettes import Palette, unique_names

_SAMPLE_SIZE = 24_000
# Colours closer than this (CIE76 Delta E) are hard to tell apart as paints, and
# splitting a flat area between them only produces speckles. They are merged.
MIN_PAINT_DELTA_E = 6.0
_CHUNK = 65_536


@dataclass(frozen=True)
class Quantized:
    """A colour-index map plus the colours (and their names) it refers to."""

    index_map: np.ndarray  # (H, W) uint8 indices into ``colors``
    colors: list[RGB]
    names: list[str]


def assign_nearest(lab_pixels: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """Return the index of the nearest centre for every L*a*b* pixel (chunked)."""
    labels = np.empty(len(lab_pixels), dtype=np.int64)
    center_norms = np.sum(centers**2, axis=1)
    for start in range(0, len(lab_pixels), _CHUNK):
        chunk = lab_pixels[start : start + _CHUNK]
        # |p - c|^2 = |p|^2 - 2 p.c + |c|^2 ; |p|^2 is constant per row.
        distances = center_norms[None, :] - 2.0 * chunk @ centers.T
        labels[start : start + _CHUNK] = np.argmin(distances, axis=1)
    return labels


def _kmeans_plus_plus(points: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    centers = [points[rng.integers(len(points))]]
    closest = np.sum((points - centers[0]) ** 2, axis=1)
    for _ in range(1, k):
        total = closest.sum()
        if total <= 0:
            break
        choice = rng.choice(len(points), p=closest / total)
        centers.append(points[choice])
        closest = np.minimum(closest, np.sum((points - points[choice]) ** 2, axis=1))
    return np.array(centers)


def kmeans(
    points: np.ndarray, k: int, rng: np.random.Generator, iterations: int = 30
) -> np.ndarray:
    """Cluster ``points`` into at most ``k`` centres (fewer if the data has fewer colours)."""
    unique = np.unique(np.round(points, 1), axis=0)
    if len(unique) <= k:
        return unique.astype(np.float64)
    centers = _kmeans_plus_plus(points, k, rng)
    for _ in range(iterations):
        labels = assign_nearest(points, centers)
        counts = np.bincount(labels, minlength=len(centers)).astype(np.float64)
        sums = np.zeros_like(centers)
        np.add.at(sums, labels, points)
        updated = centers.copy()
        filled = counts > 0
        updated[filled] = sums[filled] / counts[filled, None]
        if not filled.all():
            # Re-seed empty clusters with the points worst served by the current centres.
            distances = np.min(np.sum((points[:, None, :] - updated[None]) ** 2, axis=2), axis=1)
            worst = np.argsort(distances)[::-1][: int((~filled).sum())]
            updated[~filled] = points[worst]
        shift = float(np.max(np.abs(updated - centers)))
        centers = updated
        if shift < 0.05:
            break
    return centers


def merge_close_colors(centers: np.ndarray, sample: np.ndarray, min_delta: float) -> np.ndarray:
    """Merge cluster centres closer than ``min_delta``, weighting by cluster size."""
    counts = np.bincount(assign_nearest(sample, centers), minlength=len(centers)).astype(float)
    centers = centers[counts > 0]
    counts = counts[counts > 0]
    while len(centers) > 2:
        distances = np.sqrt(np.sum((centers[:, None, :] - centers[None, :, :]) ** 2, axis=2))
        np.fill_diagonal(distances, np.inf)
        first, second = divmod(int(np.argmin(distances)), len(centers))
        if distances[first, second] >= min_delta:
            break
        total = counts[first] + counts[second]
        centers[first] = (centers[first] * counts[first] + centers[second] * counts[second]) / total
        counts[first] = total
        centers = np.delete(centers, second, axis=0)
        counts = np.delete(counts, second)
    return centers


def stretch_to_palette(centers: np.ndarray, box_lab: np.ndarray) -> np.ndarray:
    """Spread cluster colours over the palette's lightness range and boost their chroma.

    A dim, low-contrast photo would otherwise map every cluster to the same few
    dull crayons; stretching keeps light areas light and dark areas dark.
    """
    stretched = centers.copy()
    low, high = float(centers[:, 0].min()), float(centers[:, 0].max())
    target_low = float(box_lab[:, 0].min()) + 5
    target_high = float(box_lab[:, 0].max()) - 5
    if 1e-6 < high - low < target_high - target_low:
        stretched[:, 0] = target_low + (centers[:, 0] - low) * (target_high - target_low) / (
            high - low
        )
    stretched[:, 1:] *= 1.3
    return stretched


def assign_distinct(cost: np.ndarray, tolerance: float = 22.0) -> list[int]:
    """Map each row (cluster) to a column (palette colour), preferring different colours.

    Cheapest pairs are matched first, one colour per cluster, so contrasts in the
    picture survive. A cluster whose distinct colour would be more than
    ``tolerance`` (Delta E) worse than its nearest one shares the nearest colour
    instead - a brown cat should not turn green just to use more crayons - but
    never so often that a small palette collapses: at least four colours (or
    60% of the clusters) stay distinct.
    """
    rows, columns = cost.shape
    distinct = [-1] * rows
    remaining = cost.astype(np.float64).copy()
    for _ in range(min(rows, columns)):
        best_row, best_column = (
            int(index) for index in np.unravel_index(int(np.argmin(remaining)), remaining.shape)
        )
        distinct[best_row] = best_column
        remaining[best_row, :] = np.inf
        remaining[:, best_column] = np.inf
    nearest = [int(column) for column in np.argmin(cost, axis=1)]
    penalty = [
        np.inf if distinct[row] < 0 else cost[row, distinct[row]] - cost[row, nearest[row]]
        for row in range(rows)
    ]
    assignment = [
        nearest[row] if penalty[row] > tolerance else distinct[row] for row in range(rows)
    ]
    wanted = min(rows, columns, max(4, math.ceil(0.6 * rows)))
    for row in sorted(range(rows), key=lambda index: penalty[index]):
        if len(set(assignment)) >= wanted:
            break
        if distinct[row] >= 0:
            assignment[row] = distinct[row]
    return assignment


def _sample(lab_pixels: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    if len(lab_pixels) <= _SAMPLE_SIZE:
        return lab_pixels
    return lab_pixels[rng.choice(len(lab_pixels), size=_SAMPLE_SIZE, replace=False)]


def quantize(image: np.ndarray, n_colors: int, palette: Palette, seed: int = 0) -> Quantized:
    """Reduce an ``(H, W, 3)`` uint8 image to at most ``n_colors`` colours."""
    if n_colors < 2:
        raise ValueError("at least two colours are needed")
    height, width, _ = image.shape
    rng = np.random.default_rng(seed)
    lab_pixels = rgb_to_lab(image.reshape(-1, 3))
    sample = _sample(lab_pixels, rng)
    centers = kmeans(sample, n_colors, rng)

    if palette.is_auto:
        centers = merge_close_colors(centers, sample, MIN_PAINT_DELTA_E)
        center_rgb = lab_to_rgb(centers)
        candidate_rgb = [(int(r), int(g), int(b)) for r, g, b in center_rgb]
        candidate_names = unique_names(candidate_rgb)
        # Pixels are assigned to the displayed (rounded) colours themselves.
        nearest_lab = rgb_to_lab(np.array(candidate_rgb, dtype=np.float64))
        cluster_to_color = np.arange(len(candidate_rgb))
    else:
        # Each cluster gets its own crayon, so the picture's light/dark and colour
        # contrasts survive even when its true colours are not in the box.
        box_lab = rgb_to_lab(np.array([color.rgb for color in palette.colors], dtype=np.float64))
        cost = delta_e(stretch_to_palette(centers, box_lab)[:, None, :], box_lab[None, :, :])
        chosen = assign_distinct(cost)
        # Clusters sharing a colour are merged; pixels go to the nearest cluster.
        shared = sorted(set(chosen))
        candidate_rgb = [palette.colors[index].rgb for index in shared]
        candidate_names = [palette.colors[index].name for index in shared]
        nearest_lab = centers
        cluster_to_color = np.array([shared.index(index) for index in chosen])

    labels = cluster_to_color[assign_nearest(lab_pixels, nearest_lab)]
    counts = np.bincount(labels, minlength=len(candidate_rgb))
    used = [index for index in range(len(candidate_rgb)) if counts[index] > 0]
    used.sort(key=lambda index: hue_sort_key(candidate_rgb[index]))
    remap = np.zeros(len(candidate_rgb), dtype=np.uint8)
    for new_index, old_index in enumerate(used):
        remap[old_index] = new_index
    return Quantized(
        index_map=remap[labels].reshape(height, width),
        colors=[candidate_rgb[index] for index in used],
        names=[candidate_names[index] for index in used],
    )


def palette_distances(colors: list[RGB]) -> np.ndarray:
    """Pairwise perceptual distances between palette colours."""
    lab = rgb_to_lab(np.array(colors, dtype=np.float64))
    return np.asarray(delta_e(lab[:, None, :], lab[None, :, :]))
