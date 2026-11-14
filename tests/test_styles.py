"""Artistic styles."""

import numpy as np
import pytest
from PIL import Image

from paint_by_numbers.styles import STYLES, StyleContext, get_style, kuwahara, simplify


@pytest.mark.parametrize("key", list(STYLES))
def test_every_style_returns_a_picture_of_the_same_size(key: str, scene: Image.Image) -> None:
    image = np.asarray(scene)
    styled = get_style(key).apply(image, StyleContext(max(image.shape), 12))
    assert styled.image.shape == image.shape
    assert styled.image.dtype == np.uint8
    if get_style(key).geometric:
        assert styled.partition is not None
        assert styled.partition.shape == image.shape[:2]
        assert 10 < len(np.unique(styled.partition)) < image.shape[0] * image.shape[1] / 50


def test_styles_change_the_picture(scene: Image.Image) -> None:
    image = np.asarray(scene)
    outputs = {
        key: style.apply(image, StyleContext(480, 12)).image for key, style in STYLES.items()
    }
    for key, output in outputs.items():
        if key != "photo":
            assert np.mean(np.abs(output.astype(int) - image.astype(int))) > 1.0, key


def test_kuwahara_keeps_edges_and_flattens_noise() -> None:
    rng = np.random.default_rng(0)
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    image[:, 20:] = 200
    noisy = np.clip(image + rng.normal(0, 12, image.shape), 0, 255).astype(np.uint8)
    filtered = kuwahara(noisy, 3)
    assert filtered[:, :18].std() < noisy[:, :18].std()
    assert abs(int(filtered[20, 15, 0]) - int(filtered[20, 25, 0])) > 150


def test_simplify_levels(scene: Image.Image) -> None:
    image = np.asarray(scene)
    assert simplify(image, 0) is image
    assert simplify(image, 3, blur=1.0).shape == image.shape


def test_unknown_style() -> None:
    with pytest.raises(ValueError, match="unknown style"):
        get_style("cubism")
