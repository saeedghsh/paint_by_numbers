"""Command-line interface: ``paint-by-numbers convert photo.jpg --age 6-8``."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from paint_by_numbers.palettes import PALETTES
from paint_by_numbers.pipeline import Settings, generate
from paint_by_numbers.profiles import MARKERS, PROFILES, get_profile
from paint_by_numbers.render import png_bytes, render
from paint_by_numbers.samples import sample_picture
from paint_by_numbers.styles import STYLES

OUTPUTS = ("canvas", "preview", "legend", "pdf", "sheets", "styled", "json")
DEFAULT_OUTPUTS = ("canvas", "preview", "legend", "pdf")


def _add_convert(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "convert",
        help="turn a picture into a paint-by-numbers page",
        description="Turn a picture into a paint-by-numbers page. Start from an age "
        "profile and override any setting.",
    )
    parser.add_argument("image", type=Path, help="input picture (JPEG, PNG, WebP, ...)")
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="output folder (default: next to image)"
    )
    parser.add_argument(
        "-a",
        "--age",
        default="kids",
        help="who is painting: a profile (toddler, preschool, early, kids, teen, adult, "
        "expert) or an age such as 3, 5, 6-8 or 18+ (default: kids)",
    )
    parser.add_argument("--style", choices=sorted(STYLES), help="artistic style (default: photo)")
    parser.add_argument("--palette", choices=sorted(PALETTES), help="colour palette")
    parser.add_argument("--colors", type=int, help="number of paint colours")
    parser.add_argument("--marker", choices=sorted(MARKERS), help="what marks each area")
    parser.add_argument("--tint", action=argparse.BooleanOptionalAction, help="pale colour wash")
    parser.add_argument("--detail", type=int, help="working resolution (long side, pixels)")
    parser.add_argument("--smoothing", type=int, choices=range(6), help="simplification 0-5")
    parser.add_argument("--min-size-mm", type=float, help="smallest area on the printed page")
    parser.add_argument("--max-regions", type=int, help="maximum number of areas (0 = no limit)")
    parser.add_argument("--line-mm", type=float, help="outline thickness on the printed page")
    parser.add_argument("--label-mm", type=float, help="largest number / mark size (mm)")
    parser.add_argument("--output-size", type=int, help="long side of rendered images (pixels)")
    parser.add_argument("--seed", type=int, help="random seed for colour clustering")
    parser.add_argument(
        "--outputs",
        default=",".join(DEFAULT_OUTPUTS),
        help=f"comma-separated outputs from: {', '.join(OUTPUTS)} "
        f"(default: {','.join(DEFAULT_OUTPUTS)})",
    )
    parser.add_argument("--quiet", action="store_true", help="print nothing but errors")


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="paint-by-numbers",
        description="Turn pictures into age-appropriate paint-by-numbers pages.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_convert(subparsers)
    listing = subparsers.add_parser("presets", help="list age profiles, styles and palettes")
    listing.add_argument("--json", action="store_true", help="machine-readable output")
    sample = subparsers.add_parser("sample", help="write the built-in sample picture")
    sample.add_argument("output", type=Path, nargs="?", default=Path("sample.png"))
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    """Combine the chosen profile with any explicit overrides."""
    overrides = {
        "style": args.style,
        "palette": args.palette,
        "colors": args.colors,
        "marker": args.marker,
        "tint": args.tint,
        "detail": args.detail,
        "smoothing": args.smoothing,
        "min_size_mm": args.min_size_mm,
        "max_regions": args.max_regions,
        "line_mm": args.line_mm,
        "label_mm": args.label_mm,
        "output_size": args.output_size,
        "seed": args.seed,
    }
    return Settings.for_profile(args.age, **overrides)


def _parse_outputs(text: str) -> list[str]:
    outputs = [item.strip() for item in text.split(",") if item.strip()]
    unknown = sorted(set(outputs) - set(OUTPUTS))
    if unknown:
        raise ValueError(f"unknown output(s): {', '.join(unknown)}")
    return outputs


def convert(args: argparse.Namespace) -> int:
    """Run the ``convert`` command."""
    outputs = _parse_outputs(args.outputs)
    settings = settings_from_args(args)
    folder = args.output or args.image.parent
    folder.mkdir(parents=True, exist_ok=True)
    stem = args.image.stem
    result = generate(str(args.image), settings)
    rendered = render(result)
    written: list[Path] = []

    def write(name: str, data: bytes) -> None:
        path = folder / name
        path.write_bytes(data)
        written.append(path)

    if "canvas" in outputs:
        write(f"{stem}_page.png", png_bytes(rendered.canvas))
    if "preview" in outputs:
        write(f"{stem}_preview.png", png_bytes(rendered.preview))
    if "legend" in outputs:
        write(f"{stem}_key.png", png_bytes(rendered.legend))
    if "styled" in outputs:
        from PIL import Image  # pylint: disable=import-outside-toplevel

        write(f"{stem}_styled.png", png_bytes(Image.fromarray(result.styled, "RGB")))
    if "sheets" in outputs:
        for number, sheet in enumerate(rendered.sheets(), start=1):
            write(f"{stem}_sheet{number}.png", png_bytes(sheet))
    if "pdf" in outputs:
        write(f"{stem}_print.pdf", rendered.pdf())
    if "json" in outputs:
        write(f"{stem}_summary.json", json.dumps(result.summary(), indent=2).encode("utf-8"))

    if not args.quiet:
        print(result.difficulty.summary())
        print(f"{result.region_count} areas, {len(result.palette)} colours:")
        for entry in result.palette:
            print(
                f"  {entry.number:>2}  {entry.hex}  {entry.name:<22} "
                f"{entry.area_fraction * 100:5.1f}%  ({entry.regions} "
                f"{'area' if entry.regions == 1 else 'areas'})"
            )
        for warning in result.warnings:
            print(f"note: {warning}")
        for path in written:
            print(f"wrote {path}")
    return 0


def presets(as_json: bool) -> int:
    """Run the ``presets`` command."""
    if as_json:
        data = {
            "profiles": {key: vars(profile) for key, profile in PROFILES.items()},
            "styles": {key: style.description for key, style in STYLES.items()},
            "palettes": {key: palette.description for key, palette in PALETTES.items()},
            "markers": MARKERS,
        }
        print(json.dumps(data, indent=2, default=list))
        return 0
    print("Who is painting? (--age)")
    for profile in PROFILES.values():
        print(
            f"  {profile.key:<10} ages {profile.ages:<6} {profile.colors:>2} colours, "
            f"areas >= {profile.min_size_mm:g} mm, {profile.marker}: {profile.description}"
        )
    print("\nStyles (--style)")
    for style in STYLES.values():
        print(f"  {style.key:<14} {style.description}")
    print("\nPalettes (--palette)")
    for palette in PALETTES.values():
        print(f"  {palette.key:<11} {palette.description}")
    print("\nMarks (--marker)")
    for key, description in MARKERS.items():
        print(f"  {key:<12} {description}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``paint-by-numbers`` and ``python -m paint_by_numbers``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "convert":
            get_profile(args.age)
            return convert(args)
        if args.command == "presets":
            return presets(args.json)
        sample_picture().save(args.output)
        print(f"wrote {args.output}")
        return 0
    except (OSError, ValueError) as error:
        print(f"paint-by-numbers: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
