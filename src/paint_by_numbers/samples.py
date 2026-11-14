"""A built-in sample picture, drawn in code so the repository ships no photo files."""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _gradient(height: int, width: int, top: tuple, bottom: tuple) -> np.ndarray:
    t = np.linspace(0.0, 1.0, height)[:, None, None]
    colours = np.array(top, dtype=np.float64) * (1 - t) + np.array(bottom, dtype=np.float64) * t
    return np.repeat(colours, width, axis=1)


def sample_picture(width: int = 960, height: int = 680, seed: int = 7) -> Image.Image:
    """A sunny countryside scene with soft gradients and texture, like a simple photo."""
    rng = np.random.default_rng(seed)
    sky = _gradient(height, width, (88, 150, 222), (250, 214, 170))
    picture = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(picture)
    w, h = width / 960, height / 680

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
        return x0 * w, y0 * h, x1 * w, y1 * h

    def poly(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(x * w, y * h) for x, y in points]

    draw.ellipse(box(690, 70, 820, 200), fill=(255, 214, 92))
    draw.ellipse(box(110, 90, 250, 150), fill=(250, 250, 252))
    draw.ellipse(box(170, 70, 300, 140), fill=(250, 250, 252))
    draw.ellipse(box(220, 100, 340, 155), fill=(244, 246, 250))
    draw.polygon(
        poly([(0, 360), (170, 190), (330, 340), (460, 220), (640, 380), (0, 420)]),
        fill=(112, 120, 150),
    )
    draw.polygon(
        poly([(130, 230), (170, 190), (210, 228), (185, 240), (160, 226)]), fill=(240, 244, 250)
    )
    draw.polygon(poly([(420, 252), (460, 220), (502, 258), (470, 262)]), fill=(240, 244, 250))
    draw.polygon(
        poly([(380, 420), (700, 250), (960, 360), (960, 460), (380, 470)]), fill=(96, 110, 140)
    )
    draw.ellipse(box(-200, 360, 620, 760), fill=(98, 170, 70))
    draw.ellipse(box(380, 380, 1200, 800), fill=(124, 186, 82))
    draw.polygon(poly([(0, 560), (960, 520), (960, 680), (0, 680)]), fill=(72, 140, 196))
    draw.rectangle(box(560, 330, 720, 450), fill=(232, 96, 72))
    draw.polygon(poly([(540, 335), (640, 260), (740, 335)]), fill=(120, 64, 52))
    draw.rectangle(box(620, 385, 660, 450), fill=(92, 60, 40))
    draw.rectangle(box(580, 355, 610, 382), fill=(250, 238, 170))
    draw.rectangle(box(675, 355, 705, 382), fill=(250, 238, 170))
    draw.rectangle(box(222, 360, 246, 470), fill=(110, 72, 44))
    draw.ellipse(box(160, 250, 310, 400), fill=(46, 120, 58))
    draw.ellipse(box(190, 230, 290, 330), fill=(60, 140, 66))
    for x, colour in (
        (90, (238, 70, 90)),
        (130, (250, 200, 60)),
        (300, (220, 90, 200)),
        (360, (250, 250, 250)),
        (820, (238, 70, 90)),
        (870, (250, 200, 60)),
    ):
        draw.ellipse(box(x, 500, x + 22, 522), fill=colour)
    picture = picture.filter(ImageFilter.GaussianBlur(1.6 * w))
    pixels = np.asarray(picture, dtype=np.float64)
    pixels += rng.normal(0.0, 3.0, pixels.shape)
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")
