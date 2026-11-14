"""End-to-end conversion and rendering."""

import io
import json

import numpy as np
import pytest
from PIL import Image

from paint_by_numbers import Settings, generate, render
from paint_by_numbers.pipeline import load_image, thinnest_region_depth
from paint_by_numbers.profiles import PROFILES
from paint_by_numbers.render import SHAPES, png_bytes, shape_points


@pytest.mark.parametrize("profile", list(PROFILES))
def test_every_profile_makes_a_page(profile: str, scene: Image.Image) -> None:
    settings = Settings.for_profile(profile, output_size=600)
    result = generate(scene, settings)
    assert 1 <= len(result.palette) <= settings.colors
    assert result.region_count >= 1
    assert {label.region for label in result.labels} == set(range(result.region_count))
    if PROFILES[profile].max_regions:
        assert result.region_count <= PROFILES[profile].max_regions
    json.dumps(result.summary())  # everything the UI needs is plain JSON
    rendered = render(result)
    assert rendered.canvas.size == result.output_size
    assert max(rendered.canvas.size) == 600
    assert rendered.preview.size == rendered.canvas.size


def test_younger_profiles_make_simpler_pages(scene: Image.Image) -> None:
    counts = [generate(scene, Settings.for_profile(key)).region_count for key in PROFILES]
    assert counts[0] < counts[2] < counts[-1]


def test_areas_respect_the_minimum_thickness(scene: Image.Image) -> None:
    result = generate(scene, Settings.for_profile("early"))
    assert thinnest_region_depth(result) >= 1


def test_shapes_marker_caps_colours(scene: Image.Image) -> None:
    result = generate(scene, Settings.for_profile("preschool", marker="shapes", colors=20))
    assert result.settings.colors == len(SHAPES)
    assert len(result.palette) <= len(SHAPES)
    render(result)


@pytest.mark.parametrize("marker", ["numbers", "number-dots", "dots", "shapes", "none"])
def test_markers_render(marker: str, scene: Image.Image) -> None:
    result = generate(
        scene, Settings.for_profile("early", marker=marker, tint=True, output_size=500)
    )
    rendered = render(result)
    pixels = np.asarray(rendered.canvas)
    assert pixels.min() < 60  # outlines and marks are dark
    assert len(rendered.sheets()) == 2


@pytest.mark.parametrize("style", ["pixel", "stained-glass", "pop-art"])
def test_styles_through_the_pipeline(style: str, scene: Image.Image) -> None:
    result = generate(scene, Settings.for_profile("kids", style=style, output_size=500))
    assert result.region_count > 5
    render(result)


def test_pdf_is_a_valid_two_page_document(scene: Image.Image) -> None:
    rendered = render(generate(scene, Settings.for_profile("preschool", output_size=500)))
    pdf = rendered.pdf()
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert pdf.count(b"/Type /Page ") == 2
    assert b"/FlateDecode" in pdf and b"DCTDecode" not in pdf


def test_settings_validation_and_overrides() -> None:
    settings = Settings.for_profile("adult", colors=500, palette="crayons-8").validated()
    assert settings.colors == 8
    assert Settings.for_profile("adult", colors=None).colors == PROFILES["adult"].colors
    with pytest.raises(ValueError, match="unknown setting"):
        Settings.for_profile("adult", colours=4)
    with pytest.raises(ValueError, match="unknown marker"):
        Settings(marker="stickers").validated()


def test_load_image_handles_bytes_alpha_and_exif() -> None:
    rgba = Image.new("RGBA", (20, 10), (255, 0, 0, 0))
    buffer = io.BytesIO()
    rgba.save(buffer, "PNG")
    loaded = load_image(buffer.getvalue())
    assert loaded.mode == "RGB" and loaded.getpixel((0, 0)) == (255, 255, 255)
    rotated = Image.new("RGB", (40, 20), "blue")
    exif = rotated.getexif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    buffer = io.BytesIO()
    rotated.save(buffer, "JPEG", exif=exif)
    assert load_image(buffer.getvalue()).size == (20, 40)


def test_progress_is_reported(scene: Image.Image) -> None:
    messages: list[str] = []
    generate(scene, Settings.for_profile("toddler"), messages.append)
    assert len(messages) >= 4


def test_shape_polygons_fit_their_box() -> None:
    for shape in SHAPES[1:]:
        points = np.array(shape_points(shape, 50, 50, 40))
        assert points.min() >= 28 and points.max() <= 72
    with pytest.raises(ValueError):
        shape_points("unicorn", 0, 0, 10)


def test_png_bytes() -> None:
    assert png_bytes(Image.new("RGB", (4, 4)), fast=True).startswith(b"\x89PNG")
