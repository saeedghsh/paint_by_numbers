"""Opt-in integration test: real Pyodide, the bundled Python package, real browser controls.

Run with ``make test-browser`` (needs network access to the Pyodide CDN).
"""

import os
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from paint_by_numbers.samples import sample_picture
from scripts.build_pages import build_pages

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("RUN_BROWSER_TESTS") != "1",
        reason="Set RUN_BROWSER_TESTS=1 to load Pyodide in a browser",
    ),
]


class QuietHandler(SimpleHTTPRequestHandler):
    """Serve the static site without request logs."""

    def log_message(self, *args: object) -> None:  # pylint: disable=arguments-differ
        """Stay quiet."""


def wait_for_new_render(page, previous: str) -> None:  # type: ignore[no-untyped-def]
    """Wait until Python delivered a new page and the busy indicator is gone."""
    page.wait_for_function(
        "([previous]) => document.getElementById('view').dataset.renders !== previous"
        " && document.getElementById('busy').hidden",
        arg=[previous],
        timeout=120000,
    )


def test_real_pyodide_end_to_end(tmp_path: Path) -> None:
    # pylint: disable=import-outside-toplevel
    from playwright.sync_api import expect, sync_playwright

    # Serve below a sub-path, like GitHub Pages does for project sites.
    build_pages(tmp_path / "paint_by_numbers" / "_site")
    upload = tmp_path / "upload.jpg"
    sample_picture(640, 480, seed=3).save(upload, "JPEG")
    handler = partial(QuietHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/paint_by_numbers/_site/"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("BROWSER_EXECUTABLE") or None
            )
            page = browser.new_page(viewport={"width": 1360, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.wait_for_function(
                "document.body.dataset.runtime === 'ready'"
                " || !document.getElementById('fatal').hidden",
                timeout=180000,
            )
            expect(page.locator("#fatal")).to_be_hidden()
            expect(page.locator("#profiles [role=radio]")).to_have_count(7)
            expect(page.locator("#styles [role=radio]")).to_have_count(9)

            # The sample picture with the default (9-12) profile.
            page.locator("#sample").click()
            page.wait_for_function("document.body.dataset.state === 'ready'", timeout=120000)
            wait_for_new_render(page, "0")
            expect(page.locator("#difficulty")).to_contain_text("Suggested for ages")
            assert page.locator("#legend li").count() >= 5

            # Toddler page: colour dots instead of numbers.
            renders = page.locator("#view").get_attribute("data-renders")
            page.locator("#profiles [role=radio]", has_text="Little hands").click()
            wait_for_new_render(page, renders)
            expect(page.locator("#legend .mark.dots").first).to_be_visible()
            assert page.locator("#legend li").count() <= 4

            # Upload a picture, pick a style and fine-tune a control.
            renders = page.locator("#view").get_attribute("data-renders")
            page.locator("#profiles [role=radio]", has_text="Young painter").click()
            page.locator("#file").set_input_files(str(upload))
            page.locator("#styles [role=radio]", has_text="Pixel art").click()
            wait_for_new_render(page, renders)
            renders = page.locator("#view").get_attribute("data-renders")
            page.locator("details.fine-tune summary").click()
            page.locator("#control-colors").fill("4")
            wait_for_new_render(page, renders)
            assert page.locator("#legend li").count() <= 4

            for tab in ["preview", "styled", "original", "page"]:
                page.locator(f"#tabs [data-view={tab}]").click()
                expect(page.locator("#view")).to_have_attribute("src", re.compile(r"^blob:"))

            with page.expect_download(timeout=120000) as download:
                page.locator("#download-pdf").click()
            pdf = tmp_path / "page.pdf"
            download.value.save_as(pdf)
            assert pdf.read_bytes().startswith(b"%PDF")
            page.screenshot(path=str(tmp_path / "desktop.png"), full_page=True)

            # Phones: no sideways scrolling.
            page.set_viewport_size({"width": 390, "height": 844})
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            assert overflow <= 0
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
