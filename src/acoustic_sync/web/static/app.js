"use strict";
const $ = id => document.getElementById(id);
let token = null, selected = null, busy = false;
const terminal = new Set(["completed", "partial", "failed", "cancelled", "interrupted"]);
const basename = path => path.split(/[\\/]/).pop();
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {"Content-Type": "application/json", "X-Session-Token": token || "", ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check the paths and numeric settings.");
  return data;
}
function error(id, message) { $(id).textContent = message || ""; $(id).hidden = !message; }
function count(value) { return Array.isArray(value) ? value.length : typeof value === "number" ? value : null; }
function metric(report, map, keys) {
  for (const object of [report, report?.summary, report?.stats, map, map?.summary]) {
    for (const key of keys) { const value = count(object?.[key]); if (value !== null) return value; }
  }
  return "—";
}
function render(job) {
  $("empty").hidden = true; $("detail").hidden = false;
  $("status").textContent = job.status.toUpperCase();
  $("job-title").textContent = basename(job.output_xml);
  $("cancel").hidden = terminal.has(job.status);
  $("cancel").disabled = job.status === "cancelling";
  $("cancel").textContent = job.status === "cancelling" ? "Stopping…" : "Cancel job";
  const p = job.progress || {}, total = Number(p.total), completed = Number(p.completed);
  const percent = total > 0 && Number.isFinite(completed) ? Math.min(100, Math.max(0, 100 * completed / total)) : null;
  if (["completed", "partial"].includes(job.status)) $("progress").value = 100;
  else if (percent !== null) $("progress").value = percent;
  else if (job.status === "running" || job.status === "cancelling") $("progress").removeAttribute("value");
  else $("progress").value = 0;
  $("stage").textContent = job.status === "partial" ? "Export ready - some recordings need review" : terminal.has(job.status) ? `Sync ${job.status}` : job.status === "queued" ? "Queued - waiting for the active job" : p.stage || "Starting pipeline";
  $("message").textContent = job.status === "cancelling" ? "Cancellation requested. Waiting for the pipeline to stop safely." : p.message || "";
  $("percent").textContent = ["completed", "partial"].includes(job.status) ? "100%" : percent === null ? "" : `${Math.round(percent)}%`;
  error("job-error", job.error);
  const report = job.report, map = job.sync_map;
  $("matches").textContent = report?.statistics?.accepted_matches ?? (map?.matches ? map.matches.filter(m => m.accepted).length : "-");
  $("groups").textContent = metric(report, map, ["groups", "group_count", "sync_groups"]);
  let warnings = report?.warnings || map?.warnings || [];
  if (!Array.isArray(warnings)) warnings = [warnings];
  const orphans = map?.unmatched_clips || [];
  $("warnings-count").textContent = report || map ? warnings.length + orphans.length : "-";
  if (orphans.length) warnings = [...warnings, `${orphans.length} unmatched recordings are preserved in approximate recording-date order.`];
  $("warnings").replaceChildren(...warnings.map(w => {const li = document.createElement("li"); li.textContent = typeof w === "string" ? w : w.message || JSON.stringify(w); return li;}));
  $("downloads").replaceChildren(...(job.artifacts || []).map(name => {const a = document.createElement("a"); a.href = `/api/jobs/${encodeURIComponent(job.id)}/artifacts/${encodeURIComponent(name)}`; a.textContent = `↓ ${name === "timeline.xml" ? "Timeline XML" : name}`; return a;}));
  $("report-details").hidden = !report && !map;
  $("report").textContent = JSON.stringify({report, sync_map: map}, null, 2);
  $("results").hidden = !map;
  table("aligned-table", "Synchronized recordings", ["Group", "Recording", "Reference", "Offset (s)", "Confidence"],
    (map?.aligned_clips || []).map(m => [m.group_id, basename(m.file_path), basename(m.matched_to), Number(m.offset_seconds).toFixed(4), `${Number(m.confidence).toFixed(1)} / 100`]));
  table("orphan-table", "Unmatched recordings", ["Recording", "Reason", "Confidence"],
    orphans.map(m => [basename(m.file_path), m.reason.replaceAll("_", " "), `${Number(m.confidence).toFixed(1)} / 100`]));
}
function table(id, title, headers, rows) {
  const container = $(id); container.replaceChildren();
  if (!rows.length) return;
  const heading = document.createElement("h3"); heading.textContent = title;
  const element = document.createElement("table"), head = element.createTHead().insertRow(), body = element.createTBody();
  for (const label of headers) { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = label; head.append(cell); }
  for (const values of rows) { const row = body.insertRow(); for (const value of values) row.insertCell().textContent = value; }
  container.append(heading, element);
}
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const jobs = await api("/api/jobs");
    if (!selected && jobs.length) selected = jobs[0].id;
    if (jobs.length) $("jobs").replaceChildren(...jobs.map(job => {
      const button = document.createElement("button"); button.type = "button"; button.className = "job-row" + (selected === job.id ? " selected" : "");
      button.setAttribute("aria-pressed", String(selected === job.id));
      const name = document.createElement("span"); name.textContent = basename(job.output_xml); name.title = job.output_xml;
      const time = document.createElement("time"); time.textContent = new Date(job.created_at * 1000).toLocaleString();
      const badge = document.createElement("span"); badge.className = "badge"; badge.textContent = job.status.toUpperCase();
      button.append(name, time, badge); button.onclick = () => {selected = job.id; refresh();}; return button;
    }));
    if (selected) render(await api(`/api/jobs/${encodeURIComponent(selected)}`));
    $("connection").textContent = "Connected · local server";
  } catch (e) { $("connection").textContent = `Connection issue: ${e.message}`; }
  finally { busy = false; }
}
$("job-form").addEventListener("submit", async event => {
  event.preventDefault(); error("form-error", null); $("submit").disabled = true;
  try {
    token = (await api("/api/session")).token;
    const values = Object.fromEntries(new FormData(event.target));
    for (const key of ["confidence_threshold", "workers"]) values[key] = Number(values[key]);
    values.input_dir = values.input_dir.trim(); values.output_xml = values.output_xml.trim();
    const job = await api("/api/jobs", {method: "POST", body: JSON.stringify(values)});
    selected = job.id; render(job); await refresh();
  } catch (e) { error("form-error", e.message); }
  finally { $("submit").disabled = false; }
});
$("cancel").onclick = async () => {
  $("cancel").disabled = true;
  try { token = (await api("/api/session")).token; render(await api(`/api/jobs/${encodeURIComponent(selected)}/cancel`, {method: "POST"})); }
  catch (e) { error("job-error", e.message); $("cancel").disabled = false; }
};
function saveSettings() {
  try { localStorage.setItem("acoustic-sync.settings", JSON.stringify({
    version: 1, fields: Object.fromEntries(new FormData($("job-form"))), preset: $("fps-preset").value
  })); }
  catch (_) { /* Storage may be disabled; the form remains usable. */ }
}
try {
  const settings = JSON.parse(localStorage.getItem("acoustic-sync.settings"));
  if (settings?.version === 1 && settings.fields && typeof settings.fields === "object") {
    for (const field of $("job-form").elements) {
      const value = settings.fields[field.name];
      if (field.name && typeof value === "string" && ["INPUT", "SELECT", "TEXTAREA"].includes(field.tagName)) field.value = value;
    }
  }
  const saved = settings?.version === 1 ? {preset: settings.preset, value: settings.fields?.fps} : JSON.parse(localStorage.getItem("acoustic-sync.fps"));
  if (saved && typeof saved.value === "string" && Array.from($("fps-preset").options).some(o => o.value === saved.preset)) {
    $("fps-preset").value = saved.preset;
    $("fps").value = saved.preset === "custom" ? saved.value : saved.preset;
    $("fps-custom").hidden = saved.preset !== "custom";
  }
} catch (_) { /* Ignore unavailable storage or an invalid saved preference. */ }
$("job-form").addEventListener("input", saveSettings);
$("job-form").addEventListener("change", saveSettings);
$("fps-preset").onchange = () => {
  const custom = $("fps-preset").value === "custom";
  $("fps-custom").hidden = !custom;
  if (custom) $("fps").focus();
  else $("fps").value = $("fps-preset").value;
  saveSettings();
};

function sourceOutputPath() {
  const source = $("input").value.trim();
  if (!source) return;
  const separator = source.includes("\\") ? "\\" : "/";
  $("output").value = source.replace(/[\\/]+$/, "") + separator + "timeline.xml";
  saveSettings();
}
$("input").addEventListener("change", sourceOutputPath);

let pickerMode = "input", pickerDirectory = null, pickerParent = null, pickerNext = null, pickerRequest = 0;
async function loadFolder(path, initial = false, offset = 0) {
  const requestId = ++pickerRequest;
  error("picker-error", null);
  $("picker-select").disabled = true;
  $("picker-more").hidden = true;
  $("picker-entries").setAttribute("aria-busy", "true");
  if (!offset) $("picker-entries").replaceChildren();
  try {
    const data = await api("/api/filesystem/browse", {method: "POST", body: JSON.stringify({path: path || null, initial, show_xml: pickerMode === "output", offset})});
    if (requestId !== pickerRequest || !$("path-picker").open) return;
    pickerDirectory = data.path; pickerParent = data.parent; pickerNext = data.next_offset;
    $("picker-location").textContent = data.path || "Choose a drive or your home folder";
    $("picker-up").disabled = !data.path;
    for (const entry of data.entries) {
      const button = document.createElement("button"); button.type = "button"; button.className = "picker-entry";
      const kind = document.createElement("span"); kind.className = "entry-kind"; kind.textContent = entry.kind === "directory" ? "Folder" : "XML";
      const label = document.createElement("span"); label.textContent = entry.name;
      button.append(kind, label); button.title = entry.path;
      button.onclick = () => { if (entry.kind === "directory") loadFolder(entry.path); else $("picker-filename").value = entry.name; };
      $("picker-entries").append(button);
    }
    if (!offset && !data.entries.length) { const empty = document.createElement("p"); empty.className = "hint"; empty.textContent = "No subfolders" + (pickerMode === "output" ? " or XML files" : "") + " in this folder."; $("picker-entries").append(empty); }
    $("picker-select").disabled = !data.path;
    $("picker-more").hidden = data.next_offset === null;
  } catch (e) { if (requestId === pickerRequest) { pickerDirectory = null; error("picker-error", e.message); } }
  finally { if (requestId === pickerRequest) $("picker-entries").setAttribute("aria-busy", "false"); }
}
async function openPicker(mode) {
  const openingId = ++pickerRequest;
  pickerMode = mode; pickerDirectory = null;
  $("picker-title").textContent = mode === "input" ? "Choose source folder" : "Choose output XML";
  $("picker-select").textContent = mode === "input" ? "Use this folder" : "Use this output path";
  $("picker-select").disabled = true; $("picker-up").disabled = true;
  $("picker-filename-row").hidden = mode !== "output";
  $("picker-entries").replaceChildren(); error("picker-error", null);
  let seed = $(mode).value.trim();
  if (mode === "output") {
    $("picker-filename").value = seed ? basename(seed) : "timeline.xml";
    const slash = Math.max(seed.lastIndexOf("/"), seed.lastIndexOf("\\"));
    seed = slash >= 0 ? seed.slice(0, slash+1) : "";
  }
  $("path-picker").showModal();
  try {
    token = (await api("/api/session")).token;
    if (openingId !== pickerRequest || !$("path-picker").open) return;
    await loadFolder(seed, true);
  } catch (e) { if (openingId === pickerRequest) error("picker-error", e.message); }
}
$("browse-input").onclick = () => openPicker("input");
$("browse-output").onclick = () => openPicker("output");
$("picker-close").onclick = $("picker-cancel").onclick = () => $("path-picker").close();
$("path-picker").addEventListener("close", () => { ++pickerRequest; });
$("picker-roots").onclick = () => loadFolder(null);
$("picker-up").onclick = () => loadFolder(pickerParent);
$("picker-more").onclick = () => loadFolder(pickerDirectory, false, pickerNext);
$("picker-select").onclick = () => {
  if (!pickerDirectory) return;
  let value = pickerDirectory;
  if (pickerMode === "output") {
    let name = $("picker-filename").value.trim();
    if (!name || /[<>:"/\\|?*\u0000-\u001f]/.test(name) || /[. ]$/.test(name)) { error("picker-error", "Enter a filename, without folder separators or special characters."); return; }
    if (!name.toLowerCase().endsWith(".xml")) name += ".xml";
    const separator = pickerDirectory.includes("\\") ? "\\" : "/";
    value = pickerDirectory.replace(/[\\/]$/, "") + separator + name;
  }
  $(pickerMode).value = value;
  if (pickerMode === "input") sourceOutputPath();
  saveSettings();
  $("path-picker").close(); $(pickerMode).focus();
};
refresh(); setInterval(refresh, 1200);
