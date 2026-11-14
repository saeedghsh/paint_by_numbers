"""The JSON adapter used by the web page (run here without a browser)."""

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from paint_by_numbers.browser import BrowserApp, schema


def call(app: BrowserApp, action: str, **args: Any) -> dict[str, Any]:
    reply = json.loads(app.dispatch(json.dumps({"action": action, "args": args})))
    return reply


def test_schema_comes_from_the_python_presets() -> None:
    data = schema()
    assert [profile["key"] for profile in data["profiles"]][0] == "toddler"
    assert data["default_profile"] in {profile["key"] for profile in data["profiles"]}
    names = {control["name"] for control in data["controls"]}
    assert {"colors", "min_size_mm", "palette", "marker", "tint"} <= names
    assert {"photo", "cartoon", "pixel"} <= {style["key"] for style in data["styles"]}
    json.dumps(data)


def test_full_session(tmp_path: Path) -> None:
    app = BrowserApp(str(tmp_path))
    messages: list[str] = []
    app.set_progress(messages.append)
    assert call(app, "generate")["error"] == "Choose a picture first."
    assert call(app, "export")["error"] == "Make a page first."

    sample = call(app, "sample")
    assert sample["ok"] and Path(sample["result"]["files"]["original"]).exists()
    reply = call(app, "generate", profile="preschool", settings={"style": "cartoon", "colors": 5,
                                                              "bogus": 1})  # fmt: skip
    assert reply["ok"], reply.get("trace")
    result = reply["result"]
    assert result["settings"]["style"] == "cartoon"
    assert result["profile"]["key"] == "preschool"
    for path in result["files"].values():
        assert Path(path).read_bytes().startswith(b"\x89PNG")
    assert messages

    pdf = call(app, "export", kind="pdf")["result"]["files"]["pdf"]
    assert Path(pdf).read_bytes().startswith(b"%PDF")
    sheets = call(app, "export", kind="sheets")["result"]["files"]
    assert len(sheets) == 2


def test_uploads_are_loaded_and_shrunk(tmp_path: Path) -> None:
    app = BrowserApp(str(tmp_path))
    upload = tmp_path / "upload"
    Image.new("RGB", (5000, 1000), "orange").save(upload, "JPEG")
    reply = call(app, "load", path=str(upload))
    assert reply["result"] == {"width": 2400, "height": 480}
    upload.write_bytes(b"not a picture")
    assert "could not be read" in call(app, "load", path=str(upload))["error"]


def test_unknown_actions_and_bad_json_are_errors(tmp_path: Path) -> None:
    app = BrowserApp(str(tmp_path))
    assert not call(app, "exec")["ok"]
    assert not json.loads(app.dispatch("{not json"))["ok"]
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, "PNG")
