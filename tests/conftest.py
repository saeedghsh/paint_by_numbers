"""Shared fixtures: small synthetic pictures that exercise the pipeline quickly."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from paint_by_numbers.samples import sample_picture


@pytest.fixture(scope="session")
def scene() -> Image.Image:
    """The built-in sample scene, reduced for speed."""
    return sample_picture(480, 340)


@pytest.fixture()
def blocks() -> Image.Image:
    """Four flat colour quadrants with a red disc and a few noise specks."""
    picture = Image.new("RGB", (200, 160), (240, 240, 240))
    draw = ImageDraw.Draw(picture)
    draw.rectangle((100, 0, 199, 79), fill=(30, 90, 200))
    draw.rectangle((0, 80, 99, 159), fill=(40, 160, 60))
    draw.rectangle((100, 80, 199, 159), fill=(250, 210, 40))
    draw.ellipse((30, 20, 70, 60), fill=(210, 40, 40))
    pixels = np.asarray(picture).copy()
    rng = np.random.default_rng(1)
    for y, x in rng.integers(0, 150, size=(25, 2)):
        pixels[y, x] = (0, 0, 0)
    return Image.fromarray(pixels)
