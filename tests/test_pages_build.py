"""The static GitHub Pages build."""

import json
import tomllib
import zipfile
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from scripts.build_pages import ROOT, build_pages


def test_site_contains_the_page_and_the_python_package(tmp_path: Path) -> None:
    output = build_pages(tmp_path / "_site")
    for name in ["index.html", "app.js", "worker.js", "styles.css", "favicon.svg", "LICENSE",
                 ".nojekyll", "runtime-config.json", "python/paint_by_numbers.zip"]:  # fmt: skip
        assert (output / name).is_file(), name
    with zipfile.ZipFile(output / "python" / "paint_by_numbers.zip") as archive:
        names = set(archive.namelist())
    assert {"paint_by_numbers/browser.py", "paint_by_numbers/pipeline.py"} <= names
    assert not any("__pycache__" in name for name in names)


def test_runtime_pins_satisfy_the_package_requirements(tmp_path: Path) -> None:
    config = json.loads((build_pages(tmp_path / "_site") / "runtime-config.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    requirements = {
        Requirement(text).name.lower(): Requirement(text)
        for text in project["project"]["dependencies"]
    }
    assert config["pyodide-version"] == "0.28.3"
    assert config["numpy-version"] in requirements["numpy"].specifier
    assert config["pillow-version"] in requirements["pillow"].specifier


def test_internal_urls_are_relative(tmp_path: Path) -> None:
    output = build_pages(tmp_path / "_site")
    html = (output / "index.html").read_text()
    assert 'href="./styles.css"' in html and 'src="./app.js"' in html
    assert "saeedghsh.github.io" not in html


def test_build_refuses_other_folders(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_pages(tmp_path / "site")
