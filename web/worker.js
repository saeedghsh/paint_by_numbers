// Python owns the paint-by-numbers engine. This worker only starts Pyodide,
// moves bytes in and out of its virtual filesystem, and relays JSON messages.
let pyodide;
let dispatch;
let queue = Promise.resolve();

async function checkedFetch(path) {
  const response = await fetch(new URL(path, self.location.href));
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status}).`);
  return response;
}

function progress(message) {
  self.postMessage({ progress: String(message) });
}

async function initialize() {
  const config = await (await checkedFetch("./runtime-config.json")).json();
  const indexURL = `https://cdn.jsdelivr.net/pyodide/v${config["pyodide-version"]}/full/`;
  progress("Downloading the Python runtime…");
  const { loadPyodide } = await import(`${indexURL}pyodide.mjs`);
  pyodide = await loadPyodide({ indexURL });
  if (pyodide.version !== config["pyodide-version"]) throw new Error("Pyodide version mismatch.");
  progress("Loading NumPy and Pillow…");
  await pyodide.loadPackage(["numpy", "pillow"]);
  const versions = pyodide.runPython(`
import sys, json, numpy, PIL
json.dumps({"python": "%d.%d" % sys.version_info[:2], "numpy": numpy.__version__, "pillow": PIL.__version__})
`);
  const loaded = JSON.parse(versions);
  const expected = { python: config["python-version"], numpy: config["numpy-version"], pillow: config["pillow-version"] };
  for (const [name, version] of Object.entries(expected)) {
    if (loaded[name] !== version) throw new Error(`Expected ${name} ${version}, loaded ${loaded[name]}.`);
  }
  progress("Loading the paint-by-numbers engine…");
  const archive = await (await checkedFetch("./python/paint_by_numbers.zip")).arrayBuffer();
  pyodide.unpackArchive(archive, "zip", { extractDir: "/app" });
  pyodide.runPython("import sys; sys.path.insert(0, '/app')");
  const module = pyodide.pyimport("paint_by_numbers.browser");
  const app = module.BrowserApp();
  app.set_progress(progress);
  dispatch = app.dispatch;
  return { ready: true, versions: loaded };
}

function call(action, args) {
  const reply = JSON.parse(dispatch(JSON.stringify({ action, args })));
  if (!reply.ok) {
    console.error(reply.trace);
    throw new Error(reply.error);
  }
  return reply.result;
}

self.onmessage = ({ data }) => {
  queue = queue.then(async () => {
    try {
      let result;
      if (data.action === "init") {
        result = await initialize();
      } else {
        const args = { ...(data.args || {}) };
        if (data.file) {
          const path = "/tmp/upload";
          pyodide.FS.writeFile(path, new Uint8Array(data.file));
          args.path = path;
        }
        result = call(data.action, args);
      }
      // Read any files Python wrote and hand their bytes to the page.
      const files = {};
      const transfer = [];
      for (const [name, path] of Object.entries(result.files || {})) {
        const bytes = pyodide.FS.readFile(path);
        files[name] = bytes;
        transfer.push(bytes.buffer);
      }
      self.postMessage({ id: data.id, result, files }, transfer);
    } catch (error) {
      self.postMessage({ id: data.id, error: String(error?.message || error) });
    }
  });
};
