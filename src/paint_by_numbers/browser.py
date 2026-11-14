"""JSON adapter between the static web page and the Python engine (runs in Pyodide).

The page never sends Python code: it sends ``{"action": ..., "args": {...}}`` and
gets ``{"ok": true, "result": {...}}`` back. Pictures travel through the Pyodide
virtual filesystem: the page writes an uploaded file to a path, and results list
the paths of the PNG/PDF files to read back. Nothing here imports browser APIs,
so the adapter is tested with plain pytest.
"""

import json
import traceback
from collections.abc import Callable
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from PIL import Image

from paint_by_numbers.palettes import PALETTES
from paint_by_numbers.pipeline import Result, Settings, generate, load_image
from paint_by_numbers.profiles import MARKERS, PROFILES, get_profile
from paint_by_numbers.render import Rendered, png_bytes, render
from paint_by_numbers.samples import sample_picture
from paint_by_numbers.styles import STYLES

MAX_INPUT_SIDE = 2400  # big phone photos are shrunk on arrival to keep memory low
BROWSER_OUTPUT_SIZE = 2000
DEFAULT_PROFILE = "kids"

CONTROLS: list[dict[str, Any]] = [
    {"name": "colors", "label": "Colours", "kind": "range", "min": 2, "max": 48, "step": 1,
     "help": "How many different paints or crayons the page uses."},
    {"name": "min_size_mm", "label": "Smallest area", "kind": "range", "min": 1.5, "max": 50,
     "step": 0.5, "unit": "mm", "help": "Areas smaller than this on the printed page are merged."},
    {"name": "max_regions", "label": "Most areas", "kind": "range", "min": 0, "max": 1500,
     "step": 5, "zero": "no limit", "help": "Caps how many areas there are to paint."},
    {"name": "smoothing", "label": "Simplify", "kind": "range", "min": 0, "max": 5, "step": 1,
     "help": "Smooths texture and wiggly borders before areas are drawn."},
    {"name": "detail", "label": "Detail", "kind": "range", "min": 120, "max": 1200, "step": 20,
     "unit": "px", "help": "Working resolution: higher keeps finer features (and is slower)."},
    {"name": "line_mm", "label": "Line thickness", "kind": "range", "min": 0.1, "max": 2.5,
     "step": 0.05, "unit": "mm", "help": "Outline width on the printed page."},
    {"name": "label_mm", "label": "Mark size", "kind": "range", "min": 1.5, "max": 20,
     "step": 0.5, "unit": "mm", "help": "Largest number, dot or shape on the printed page."},
    {"name": "palette", "label": "Palette", "kind": "select",
     "options": [{"value": key, "label": palette.label} for key, palette in PALETTES.items()],
     "help": "Match colours to the picture, or to a crayon box or paint set you own."},
    {"name": "marker", "label": "Marks", "kind": "select",
     "options": [{"value": key, "label": text.split(" - ", maxsplit=1)[0]}
                 for key, text in MARKERS.items()],
     "help": "What tells the painter which colour goes where."},
    {"name": "tint", "label": "Pale colour hints", "kind": "checkbox",
     "help": "Wash each area in a pale version of its colour - great for the youngest."},
    {"name": "seed", "label": "Variation", "kind": "range", "min": 0, "max": 20, "step": 1,
     "help": "Try another arrangement of the same colours."},
]  # fmt: skip


def schema() -> dict[str, Any]:
    """Everything the page needs to build its controls, straight from the Python presets."""
    profiles = []
    for key, profile in PROFILES.items():
        settings = Settings.for_profile(key)
        profiles.append(
            {
                "key": key,
                "label": profile.label,
                "ages": profile.ages,
                "description": profile.description,
                "tips": list(profile.tips),
                "settings": settings.to_dict(),
            }
        )
    return {
        "profiles": profiles,
        "default_profile": DEFAULT_PROFILE,
        "styles": [
            {"key": s.key, "label": s.label, "description": s.description} for s in STYLES.values()
        ],
        "markers": [{"key": key, "description": text} for key, text in MARKERS.items()],
        "controls": CONTROLS,
    }


class BrowserApp:
    """Holds the current picture and result between requests from the page."""

    def __init__(self, workdir: str = "/tmp/paint_by_numbers"):
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.picture: Image.Image | None = None
        self.result: Result | None = None
        self.rendered: Rendered | None = None
        self.progress: Callable[[str], None] = lambda _message: None

    def set_progress(self, callback: Callable[[str], None]) -> None:
        """Register a callback (a JavaScript function in the browser) for progress text."""
        self.progress = callback

    def dispatch(self, request_json: str) -> str:
        """Run one allowlisted action and return a JSON reply (errors included)."""
        try:
            request = json.loads(request_json)
            action = request.get("action")
            handlers: dict[str, Callable[..., dict[str, Any]]] = {
                "schema": lambda: schema(),  # pylint: disable=unnecessary-lambda
                "load": self.load,
                "sample": self.sample,
                "generate": self.generate,
                "export": self.export,
            }
            if action not in handlers:
                raise ValueError(f"unknown action {action!r}")
            result = handlers[action](**(request.get("args") or {}))
            return json.dumps({"ok": True, "result": result})
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Errors go back to the page as data; the trace helps when debugging.
            return json.dumps(
                {"ok": False, "error": str(error) or type(error).__name__,
                 "trace": traceback.format_exc(limit=4)}
            )  # fmt: skip

    def _write(self, name: str, data: bytes) -> str:
        path = self.workdir / name
        path.write_bytes(data)
        return str(path)

    def _accept(self, picture: Image.Image) -> dict[str, Any]:
        picture.thumbnail((MAX_INPUT_SIDE, MAX_INPUT_SIDE), Image.Resampling.LANCZOS)
        self.picture = picture
        self.result = self.rendered = None
        return {"width": picture.width, "height": picture.height}

    def load(self, path: str) -> dict[str, Any]:
        """Load an uploaded picture that the page wrote to ``path``."""
        try:
            picture = load_image(path)
        except Exception as error:  # Pillow raises several types for unreadable files
            raise ValueError("That file could not be read as a picture.") from error
        return self._accept(picture)

    def sample(self) -> dict[str, Any]:
        """Load the built-in sample picture."""
        info = self._accept(sample_picture())
        assert self.picture is not None
        info["files"] = {"original": self._write("original.png", png_bytes(self.picture, True))}
        return info

    def generate(
        self, profile: str = DEFAULT_PROFILE, settings: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make the page for the current picture; return its summary and image paths."""
        if self.picture is None:
            raise ValueError("Choose a picture first.")
        known = {item.name for item in fields(Settings)}
        overrides = {k: v for k, v in (settings or {}).items() if k in known}
        overrides["output_size"] = BROWSER_OUTPUT_SIZE
        chosen = Settings.for_profile(profile, **overrides)
        self.result = generate(self.picture, chosen, self.progress)
        self.progress("Drawing the page")
        self.rendered = render(self.result)
        summary = self.result.summary()
        summary["files"] = {
            "page": self._write("page.png", png_bytes(self.rendered.canvas, fast=True)),
            "preview": self._write("preview.png", png_bytes(self.rendered.preview, fast=True)),
            "key": self._write("key.png", png_bytes(self.rendered.legend, fast=True)),
            "styled": self._write(
                "styled.png", png_bytes(Image.fromarray(self.result.styled, "RGB"), fast=True)
            ),
        }
        summary["profile"] = asdict(get_profile(profile))
        return summary

    def export(self, kind: str = "pdf") -> dict[str, Any]:
        """Create a download for the current result (``pdf`` or ``sheets``)."""
        if self.rendered is None:
            raise ValueError("Make a page first.")
        if kind == "pdf":
            self.progress("Preparing the printable PDF")
            return {"files": {"pdf": self._write("paint-by-numbers.pdf", self.rendered.pdf())}}
        if kind == "sheets":
            files = {}
            for number, sheet in enumerate(self.rendered.sheets(), start=1):
                files[f"sheet{number}"] = self._write(f"sheet{number}.png", png_bytes(sheet))
            return {"files": files}
        raise ValueError(f"unknown export {kind!r}")
