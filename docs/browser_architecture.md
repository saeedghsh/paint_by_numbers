# Browser architecture

The static app follows the approach of
[Distribution Playground](https://github.com/saeedghsh/distribution_playground/)
and [Quiz Games](https://github.com/saeedghsh/quiz_games): ship the Python
engine to the browser and call it through Pyodide. There is no application
server and no JavaScript copy of the image processing.

`scripts/build_pages.py` copies `web/` into `_site/`, zips the
`paint_by_numbers` package into `_site/python/paint_by_numbers.zip`, and exports
the Pyodide, Python, NumPy and Pillow pins from `pyproject.toml` to
`runtime-config.json`.

- `web/worker.js` (module worker) loads Pyodide 0.28.3 from jsDelivr, loads its
  NumPy and Pillow, refuses to start if any version differs from the pins,
  unpacks the archive and creates `paint_by_numbers.browser.BrowserApp`.
- The page sends allowlisted JSON actions (`schema`, `load`, `sample`,
  `generate`, `export`); it never sends Python code. Uploaded pictures are
  written to Pyodide's virtual filesystem and Python reports the paths of the
  PNG/PDF files it wrote; the worker transfers their bytes to the page.
- Python reports progress ("Choosing paint colours", ...) through a callback,
  which the worker forwards while the computation runs.
- `web/app.js` builds the age cards, style chips and fine-tune controls from the
  schema Python sends (profiles, ranges and options live only in Python), and
  re-runs generation when a choice changes (the latest request wins).
- Big phone photos are shrunk to 2400 px on arrival; pages render at 2000 px.

The first visit needs internet access for the Pyodide CDN (several megabytes,
cached by the browser afterwards). Serve `_site` over HTTP, not `file://`.
Relative URLs make the site work below a repository sub-path on GitHub Pages.

## Validation and deployment

```bash
uv sync --locked
make test
make build-pages
make serve-pages
```

The opt-in browser test loads real Pyodide, makes pages for several profiles,
uploads a picture, changes a style and a control, downloads the PDF and checks
for sideways scrolling on a phone-sized screen:

```bash
make test-browser
# Or use an already-installed Chrome/Chromium:
RUN_BROWSER_TESTS=1 BROWSER_EXECUTABLE=/usr/bin/chromium \
  uv run --locked --group browser pytest -m browser --no-cov
```

The GitHub Actions workflow tests and builds on pushes and pull requests. Set
**Settings → Pages → Build and deployment → Source** to **GitHub Actions**.
Pushes to `master` or `main` then deploy the site; pull requests only validate
and build. **Test and build Pages** can also be run manually with **Deploy the
built site** checked. Any static host can serve the contents of `_site/`.
