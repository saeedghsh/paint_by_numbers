// A thin shell around the Python engine: it builds controls from the schema
// Python sends, forwards choices, and shows the images Python draws.
const $ = (id) => document.getElementById(id);
const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
const pending = new Map();
let nextId = 0;

let schema;
let profile;
let style = "photo";
let values = {};
let hasPicture = false;
let running = false;
let rerun = false;
let debounce;
let view = "page";
const urls = {};
const blobs = {};

worker.onmessage = ({ data }) => {
  if (data.progress) {
    $("loading-text").textContent = data.progress;
    $("busy-text").textContent = data.progress;
    return;
  }
  const request = pending.get(data.id);
  if (!request) return;
  pending.delete(data.id);
  clearTimeout(request.timer);
  if (data.error) request.reject(new Error(data.error));
  else request.resolve(data);
};
worker.onerror = (event) => fatal(new Error(event.message || "The Python worker crashed."));

function request(action, args = {}, file = null) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const limit = action === "init" ? 180000 : 120000;
    const timer = setTimeout(() => fatal(new Error("The Python engine stopped responding.")), limit);
    pending.set(id, { resolve, reject, timer });
    worker.postMessage({ id, action, args, file }, file ? [file] : []);
  });
}

function fatal(error) {
  console.error(error);
  $("loading").hidden = true;
  $("app").hidden = true;
  $("fatal").hidden = false;
  $("fatal-text").textContent = `${error.message} Check your connection and try again.`;
}

function setUrl(name, bytes, type = "image/png") {
  if (urls[name]) URL.revokeObjectURL(urls[name]);
  blobs[name] = new Blob([bytes], { type });
  urls[name] = URL.createObjectURL(blobs[name]);
  return urls[name];
}

// ---------- controls built from the Python schema ----------
function formatValue(control, value) {
  if (control.zero && Number(value) === 0) return control.zero;
  return control.unit ? `${value} ${control.unit}` : String(value);
}

function buildControls() {
  const box = $("controls");
  box.replaceChildren();
  for (const control of schema.controls) {
    const row = document.createElement("label");
    row.className = `control ${control.kind}`;
    row.title = control.help;
    const name = document.createElement("span");
    name.className = "control-name";
    name.textContent = control.label;
    let input;
    if (control.kind === "select") {
      input = document.createElement("select");
      for (const option of control.options) input.add(new Option(option.label, option.value));
    } else {
      input = document.createElement("input");
      input.type = control.kind === "checkbox" ? "checkbox" : "range";
      if (control.kind === "range") Object.assign(input, { min: control.min, max: control.max, step: control.step });
    }
    input.name = control.name;
    input.id = `control-${control.name}`;
    const output = document.createElement("output");
    row.append(name, input);
    if (control.kind === "range") row.append(output);
    const hint = document.createElement("small");
    hint.textContent = control.help;
    row.append(hint);
    input.addEventListener("input", () => {
      const value = control.kind === "checkbox" ? input.checked
        : control.kind === "select" ? input.value : Number(input.value);
      values[control.name] = value;
      output.textContent = formatValue(control, value);
      clearTimeout(debounce);
      debounce = setTimeout(update, 450);
    });
    box.append(row);
  }
}

function showValues() {
  for (const control of schema.controls) {
    const input = $(`control-${control.name}`);
    const value = values[control.name];
    if (control.kind === "checkbox") input.checked = Boolean(value);
    else input.value = value;
    const output = input.parentElement.querySelector("output");
    if (output) output.textContent = formatValue(control, value);
  }
}

function choose(group, key) {
  for (const button of $(group).querySelectorAll("[role=radio]")) {
    button.setAttribute("aria-checked", String(button.dataset.key === key));
    button.tabIndex = button.dataset.key === key ? 0 : -1;
  }
}

function radio(group, item, onPick, extra = []) {
  const button = document.createElement("button");
  button.type = "button";
  button.setAttribute("role", "radio");
  button.dataset.key = item.key;
  const title = document.createElement("strong");
  title.textContent = item.label;
  button.append(title, ...extra);
  button.title = item.description;
  button.addEventListener("click", () => onPick(item.key));
  $(group).append(button);
}

function pickProfile(key) {
  profile = schema.profiles.find((item) => item.key === key);
  values = { ...profile.settings };
  choose("profiles", key);
  showValues();
  const tips = profile.tips;
  $("tips-box").hidden = tips.length === 0;
  $("tips").replaceChildren(...tips.map((tip) => Object.assign(document.createElement("li"), { textContent: tip })));
  update();
}

function pickStyle(key) {
  style = key;
  choose("styles", key);
  update();
}

function buildChoices() {
  for (const item of schema.profiles) {
    const ages = Object.assign(document.createElement("span"), { className: "ages", textContent: `Ages ${item.ages}` });
    const text = Object.assign(document.createElement("small"), { textContent: item.description });
    radio("profiles", item, pickProfile, [ages, text]);
  }
  for (const item of schema.styles) radio("styles", item, pickStyle);
}

// ---------- results ----------
function showView(name) {
  view = name;
  for (const tab of $("tabs").querySelectorAll("[role=tab]")) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  if (urls[name]) $("view").src = urls[name];
  $("view").alt = { page: "The page to paint", preview: "How the finished painting will look",
    styled: "The restyled picture", original: "The original picture" }[name];
}

function showLegend(palette, marker) {
  $("legend").replaceChildren(...palette.map((entry) => {
    const item = document.createElement("li");
    const mark = document.createElement("span");
    mark.className = `mark ${marker}`;
    mark.textContent = marker === "dots" || marker === "none" || marker === "shapes" ? "" : entry.number;
    mark.style.setProperty("--swatch", entry.hex);
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = entry.hex;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = entry.name;
    const detail = document.createElement("small");
    detail.textContent = `${entry.hex} · ${(entry.area_fraction * 100).toFixed(1)}%`;
    item.append(mark, swatch, name, detail);
    return item;
  }));
}

function showResult(reply) {
  const { result, files } = reply;
  for (const name of ["page", "preview", "key", "styled"]) setUrl(name, files[name]);
  $("print-page").src = urls.page;
  $("print-key").src = urls.key;
  $("view").dataset.renders = String(Number($("view").dataset.renders || 0) + 1);
  showView(view);
  const difficulty = result.difficulty;
  const chosen = profile.ages === difficulty.ages ? " — a good match." : ` (you picked ages ${profile.ages}).`;
  $("difficulty").textContent = `${result.regions} areas, ${result.palette.length} colours. `
    + `Suggested for ages ${difficulty.ages}: ${difficulty.reason}${chosen}`;
  $("warnings").hidden = result.warnings.length === 0;
  $("warnings").textContent = result.warnings.join(" ");
  showLegend(result.palette, result.settings.marker);
  $("empty").hidden = true;
  $("output").hidden = false;
  document.body.dataset.state = "ready";
}

function setBusy(value) {
  running = value;
  $("busy").hidden = !value;
  $("output").classList.toggle("stale", value);
}

async function update() {
  if (!hasPicture) return;
  if (running) { rerun = true; return; }
  setBusy(true);
  $("error").hidden = true;
  try {
    do {
      rerun = false;
      const reply = await request("generate", { profile: profile.key, settings: { ...values, style } });
      if (!rerun) showResult(reply);
    } while (rerun);
  } catch (error) {
    $("error").textContent = error.message;
    $("error").hidden = false;
  } finally {
    setBusy(false);
  }
}

async function usePicture(file) {
  if (!file) return;
  if (file.type && !file.type.startsWith("image/")) {
    $("error").textContent = "Please choose a picture file.";
    $("error").hidden = false;
    return;
  }
  setUrl("original", file, file.type);
  showThumb();
  const reply = await request("load", {}, await file.arrayBuffer()).catch((error) => {
    $("error").textContent = error.message;
    $("error").hidden = false;
  });
  if (!reply) return;
  hasPicture = true;
  update();
}

function showThumb() {
  $("original-thumb").src = urls.original;
  $("original-thumb").hidden = false;
  $("drop-text").innerHTML = "<strong>Change picture</strong>";
}

function download(name, filename) {
  const link = document.createElement("a");
  link.href = urls[name];
  link.download = filename;
  link.click();
}

async function pdfUrl() {
  if (urls.pdf && $("output").dataset.pdfFor === $("view").dataset.renders) return urls.pdf;
  setBusy(true);
  try {
    const reply = await request("export", { kind: "pdf" });
    $("output").dataset.pdfFor = $("view").dataset.renders;
    return setUrl("pdf", reply.files.pdf, "application/pdf");
  } finally {
    setBusy(false);
  }
}

function wire() {
  $("file").addEventListener("change", () => usePicture($("file").files[0]));
  const zone = $("dropzone");
  zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("over");
    usePicture(event.dataTransfer.files[0]);
  });
  window.addEventListener("paste", (event) => {
    const item = [...(event.clipboardData?.files || [])].find((file) => file.type.startsWith("image/"));
    if (item) usePicture(item);
  });
  $("sample").addEventListener("click", async () => {
    const reply = await request("sample");
    setUrl("original", reply.files.original);
    showThumb();
    hasPicture = true;
    update();
  });
  $("reset").addEventListener("click", () => pickProfile(profile.key));
  for (const tab of $("tabs").querySelectorAll("[role=tab]")) {
    tab.addEventListener("click", () => showView(tab.dataset.view));
  }
  for (const button of document.querySelectorAll("[data-download]")) {
    button.addEventListener("click", () => download(button.dataset.download, `paint-by-numbers-${button.dataset.download}.png`));
  }
  $("download-pdf").addEventListener("click", async () => {
    try { await pdfUrl(); download("pdf", "paint-by-numbers.pdf"); }
    catch (error) { $("error").textContent = error.message; $("error").hidden = false; }
  });
  $("print").addEventListener("click", () => window.print());
}

async function start() {
  await request("init");
  schema = (await request("schema")).result;
  buildChoices();
  buildControls();
  wire();
  choose("styles", style);
  pickProfile(schema.default_profile);
  $("loading").hidden = true;
  $("app").hidden = false;
  document.body.dataset.runtime = "ready";
}

start().catch(fatal);
