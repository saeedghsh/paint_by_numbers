"""Colour-space conversions, perceptual distances and small colour helpers.

Colour clustering happens in CIE L*a*b* (D65), where Euclidean distance roughly
follows how different two colours look. Everything here is plain NumPy so the
same code runs in CPython and in Pyodide.
"""

import numpy as np

_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)
_WHITE_D65 = np.array([0.95047, 1.0, 1.08883])
_EPSILON = 216 / 24389
_KAPPA = 24389 / 27

RGB = tuple[int, int, int]


def _srgb_to_linear(channel: np.ndarray) -> np.ndarray:
    scaled = channel / 255.0
    return np.where(scaled <= 0.04045, scaled / 12.92, ((scaled + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(channel: np.ndarray) -> np.ndarray:
    channel = np.clip(channel, 0.0, 1.0)
    encoded = np.where(
        channel <= 0.0031308, channel * 12.92, 1.055 * np.power(channel, 1 / 2.4) - 0.055
    )
    return encoded * 255.0


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB values in 0..255 (any leading shape, last axis 3) to L*a*b*."""
    linear = _srgb_to_linear(np.asarray(rgb, dtype=np.float64))
    xyz = linear @ _RGB_TO_XYZ.T / _WHITE_D65
    f = np.where(xyz > _EPSILON, np.cbrt(xyz), (_KAPPA * xyz + 16) / 116)
    lightness = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([lightness, a, b], axis=-1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Convert L*a*b* values back to clipped sRGB ``uint8`` values."""
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], axis=-1)
    cubed = f**3
    xyz = np.where(cubed > _EPSILON, cubed, (116 * f - 16) / _KAPPA)
    xyz[..., 1] = np.where(lab[..., 0] > _KAPPA * _EPSILON, fy**3, lab[..., 0] / _KAPPA)
    linear = (xyz * _WHITE_D65) @ _XYZ_TO_RGB.T
    return np.rint(_linear_to_srgb(linear)).astype(np.uint8)


def delta_e(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Return the CIE76 colour difference between broadcastable L*a*b* arrays."""
    difference = np.asarray(first, dtype=np.float64) - np.asarray(second, dtype=np.float64)
    return np.asarray(np.sqrt(np.sum(difference**2, axis=-1)))


def hex_color(rgb: RGB | np.ndarray) -> str:
    """Format an RGB triple as ``#rrggbb``."""
    red, green, blue = (int(value) for value in rgb)
    return f"#{red:02x}{green:02x}{blue:02x}"


def parse_hex(value: str) -> RGB:
    """Parse ``#rrggbb`` (or ``rrggbb``) into an RGB triple."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected a #rrggbb colour, got {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def relative_luminance(rgb: RGB | np.ndarray) -> float:
    """WCAG relative luminance of an sRGB colour (0 = black, 1 = white)."""
    linear = _srgb_to_linear(np.asarray(rgb, dtype=np.float64)) / 1.0
    return float(linear @ np.array([0.2126, 0.7152, 0.0722]))


def contrast_text_color(rgb: RGB | np.ndarray) -> RGB:
    """Pick black or white text, whichever reads better on ``rgb``."""
    return (20, 20, 20) if relative_luminance(rgb) > 0.36 else (255, 255, 255)


def mix(rgb: RGB | np.ndarray, other: RGB | np.ndarray, amount: float) -> RGB:
    """Blend ``amount`` (0..1) of ``other`` into ``rgb``."""
    start = np.asarray(rgb, dtype=np.float64)
    end = np.asarray(other, dtype=np.float64)
    blended = np.rint(start + (end - start) * amount).astype(int)
    return int(blended[0]), int(blended[1]), int(blended[2])


def hue_sort_key(rgb: RGB | np.ndarray) -> tuple[int, float, float]:
    """Order colours as a painter would lay them out: hues around the wheel, greys last."""
    lab = rgb_to_lab(np.asarray(rgb, dtype=np.float64))
    lightness, a, b = (float(value) for value in lab)
    chroma = float(np.hypot(a, b))
    if chroma < 12:
        return 1, -lightness, 0.0
    hue = (float(np.degrees(np.arctan2(b, a))) + 360 - 20) % 360
    return 0, round(hue / 30), -lightness
