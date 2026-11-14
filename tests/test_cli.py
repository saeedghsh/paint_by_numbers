"""The command-line interface."""

import json
from pathlib import Path

import pytest

from paint_by_numbers.cli import main
from paint_by_numbers.samples import sample_picture


@pytest.fixture()
def picture(tmp_path: Path) -> Path:
    path = tmp_path / "scene.png"
    sample_picture(360, 260).save(path)
    return path


def test_convert_writes_the_default_outputs(picture: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    assert (
        main(["convert", str(picture), "--age", "6-8", "-o", str(out), "--output-size", "600"]) == 0
    )
    names = sorted(path.name for path in out.iterdir())
    assert names == ["scene_key.png", "scene_page.png", "scene_preview.png", "scene_print.pdf"]
    printed = capsys.readouterr().out
    assert "Suggested ages" in printed and "wrote" in printed


def test_convert_with_overrides_and_json(picture: Path, tmp_path: Path) -> None:
    code = main([
        "convert", str(picture), "-o", str(tmp_path), "--age", "toddler", "--style", "cartoon",
        "--colors", "3", "--marker", "shapes", "--no-tint", "--outputs", "json,styled,sheets",
        "--output-size", "500", "--quiet",
    ])  # fmt: skip
    assert code == 0
    summary = json.loads((tmp_path / "scene_summary.json").read_text())
    assert summary["settings"]["marker"] == "shapes"
    assert summary["settings"]["tint"] is False
    assert len(summary["palette"]) <= 3
    assert (tmp_path / "scene_styled.png").exists()
    assert (tmp_path / "scene_sheet2.png").exists()


def test_errors_are_reported_not_raised(picture: Path, tmp_path: Path, capsys) -> None:
    assert main(["convert", str(picture), "--age", "1"]) == 2
    assert main(["convert", str(tmp_path / "missing.jpg")]) == 2
    assert main(["convert", str(picture), "--outputs", "poster"]) == 2
    assert "error" in capsys.readouterr().err


def test_presets_and_sample(tmp_path: Path, capsys) -> None:
    assert main(["presets"]) == 0
    assert "toddler" in capsys.readouterr().out
    assert main(["presets", "--json"]) == 0
    assert "profiles" in json.loads(capsys.readouterr().out)
    assert main(["sample", str(tmp_path / "s.png")]) == 0
    assert (tmp_path / "s.png").stat().st_size > 1000
