"""Regenerate the README illustrations from the built-in sample picture."""

from pathlib import Path

from PIL import Image, ImageDraw

from paint_by_numbers import Settings, generate, render
from paint_by_numbers.render import font
from paint_by_numbers.samples import sample_picture

DOCS = Path(__file__).resolve().parents[1] / "docs"
TILE = 560


def _tile(picture: Image.Image, caption: str) -> Image.Image:
    fitted = picture.resize(
        (TILE, round(picture.height * TILE / picture.width)), Image.Resampling.LANCZOS
    )
    tile = Image.new("RGB", (TILE, fitted.height + 44), "white")
    tile.paste(fitted, (0, 44))
    ImageDraw.Draw(tile).text((2, 6), caption, fill=(34, 34, 38), font=font(26))
    return tile


def _grid(tiles: list[Image.Image], columns: int) -> Image.Image:
    rows = -(-len(tiles) // columns)
    gap = 24
    height = max(tile.height for tile in tiles)
    grid = Image.new("RGB", (columns * (TILE + gap) - gap, rows * (height + gap) - gap), "white")
    for index, tile in enumerate(tiles):
        grid.paste(tile, ((index % columns) * (TILE + gap), (index // columns) * (height + gap)))
    return grid


def main() -> None:
    """Write ``docs/ages.png`` and ``docs/styles.png``."""
    picture = sample_picture()
    ages = []
    for profile, caption in [
        ("toddler", "Ages 2-3: dots + colour hints"),
        ("preschool", "Ages 4-5: numbers on dots"),
        ("early", "Ages 6-8: crayon-box numbers"),
        ("adult", "Adults: fine detail"),
    ]:
        result = generate(picture, Settings.for_profile(profile, output_size=1400))
        ages.append(_tile(render(result).canvas, caption))
    _grid(ages, 2).save(DOCS / "ages.png", optimize=True)

    styles = [_tile(picture, "Original")]
    for style, caption in [
        ("painterly", "Oil painting"),
        ("cartoon", "Cartoon"),
        ("pop-art", "Pop art"),
        ("pixel", "Pixel art"),
        ("stained-glass", "Stained glass"),
    ]:
        result = generate(picture, Settings.for_profile("kids", style=style, output_size=1000))
        styles.append(_tile(render(result).preview, caption))
    _grid(styles, 3).save(DOCS / "styles.png", optimize=True)


if __name__ == "__main__":
    main()
