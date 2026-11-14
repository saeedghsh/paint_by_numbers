"""Build the static GitHub Pages site from ``web/`` and the canonical Python package."""

import argparse
import json
import shutil
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "paint_by_numbers"


def runtime_config() -> dict[str, str]:
    """The Pyodide/Python/package pins declared in ``pyproject.toml``."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return dict(project["tool"]["paint-by-numbers"]["browser"])


def build_pages(output: Path = ROOT / "_site") -> Path:
    """Build into a dedicated folder named ``_site`` (never a source directory)."""
    output = output.absolute()
    if output.name != "_site" or output.is_symlink() or output.resolve() in ROOT.parents:
        raise ValueError("Output must be a dedicated directory named _site.")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(ROOT / "web", output)
    (output / "python").mkdir()
    archive_path = output / "python" / "paint_by_numbers.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(PACKAGE.rglob("*.py")):
            archive.write(source, source.relative_to(PACKAGE.parent).as_posix())
    (output / "runtime-config.json").write_text(
        json.dumps(runtime_config(), indent=2) + "\n", encoding="utf-8"
    )
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    (output / ".nojekyll").touch()
    return output


def main() -> None:
    """Parse ``--output`` and build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    build_pages(parser.parse_args().output)


if __name__ == "__main__":
    main()
