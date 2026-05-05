let TOKEN = "";
let lastProbe = null;
let currentJobId = null;
let pollTimer = null;

const $ = (id) => document.getElementById(id);

const audioContainers = ["wav", "mp3", "m4a", "flac", "opus"];
const videoContainers = ["mp4", "webm", "mkv", "avi"];

function toast(message, kind = "info") {
  const box = $("toast");
  box.textContent = message;
  box.classList.remove("hidden");
  box.style.borderColor = kind === "error" ? "#ff9ba1" : "#333846";
  clearTimeout(box._timer);
  box._timer = setTimeout(() => box.classList.add("hidden"), 6200);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (TOKEN) headers.set("X-Local-Agent-Token", TOKEN);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : text;
    throw new Error(detail || `Request failed: ${res.status}`);
  }
  return data;
}

function fmtTime(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "unknown duration";
  const total = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function setBusy(isBusy, text = "Working…") {
  for (const id of ["probe-btn", "download-btn", "save-settings-btn"]) {
    const el = $(id);
    if (!el) continue;
    el.disabled = isBusy;
  }
  if (isBusy) toast(text);
}

function fillContainers() {
  const mode = $("mode").value;
  const container = $("container");
  const keep = container.value;
  container.innerHTML = "";
  const list = mode === "audio" ? audioContainers : videoContainers;
  for (const ext of list) {
    const option = document.createElement("option");
    option.value = ext;
    option.textContent = ext.toUpperCase();
    container.appendChild(option);
  }
  if (list.includes(keep)) container.value = keep;
  else container.value = mode === "audio" ? "wav" : "mp4";
}

function fillFormats() {
  const select = $("format");
  select.innerHTML = "";
  const smart = document.createElement("option");
  smart.value = "smart";
  smart.textContent = "Smart best available";
  select.appendChild(smart);
  if (!lastProbe) return;
  const mode = $("mode").value;
  const items = mode === "audio" ? lastProbe.audio_formats : lastProbe.video_formats;
  for (const item of items || []) {
    const opt = document.createElement("option");
    opt.value = item.format_id;
    opt.textContent = item.label || `${item.format_id} · ${item.ext}`;
    select.appendChild(opt);
  }
}

function displayProbe(data) {
  lastProbe = data;
  $("probe-card").classList.remove("hidden");
  $("media-title").textContent = data.title || "Untitled media";
  if (data.webpage_url) $("url").value = data.webpage_url;
  $("media-meta").textContent = [
    data.extractor ? `Extractor: ${data.extractor}` : "",
    data.duration ? `Duration: ${fmtTime(data.duration)}` : "Duration: unknown",
    data.id ? `ID: ${data.id}` : "",
  ].filter(Boolean).join(" · ");

  const clipBox = $("clip-box");
  if (data.detected_start_seconds !== null && data.detected_start_seconds !== undefined) {
    clipBox.classList.remove("hidden");
    $("use-clip").checked = true;
    $("clip-length").value = 300;
    const end = data.suggested_clip_end_seconds;
    $("clip-hint").textContent = `Detected start ${fmtTime(data.detected_start_seconds)}; suggested end ${fmtTime(end)}.`;
  } else {
    clipBox.classList.add("hidden");
    $("use-clip").checked = false;
    $("clip-hint").textContent = "";
  }

  fillContainers();
  fillFormats();
  if (data.warnings && data.warnings.length) {
    toast(`Probe warning: ${data.warnings.slice(-1)[0]}`, "error");
  }
}

async function probeUrl() {
  const url = $("url").value.trim();
  if (!url) return toast("Paste a URL first.", "error");
  setBusy(true, "Detecting formats…");
  try {
    const data = await api("/api/probe", { method: "POST", body: JSON.stringify({ url }) });
    displayProbe(data);
    toast("Formats detected.");
  } catch (err) {
    toast(String(err.message || err), "error");
  } finally {
    setBusy(false);
  }
}

function inferClipStart() {
  if (!lastProbe || lastProbe.detected_start_seconds === null || lastProbe.detected_start_seconds === undefined) return null;
  return Number(lastProbe.detected_start_seconds);
}

async function startDownload() {
  const url = $("url").value.trim();
  if (!url) return toast("Paste a URL first.", "error");
  const body = {
    url,
    mode: $("mode").value,
    container: $("container").value,
    selected_format_id: $("format").value,
    use_clip: $("use-clip").checked,
    clip_start_seconds: inferClipStart(),
    clip_length_seconds: Number($("clip-length").value || 300),
    title_prefix: $("title-prefix").value.trim(),
  };
  setBusy(true, "Starting download…");
  try {
    const status = await api("/api/download", { method: "POST", body: JSON.stringify(body) });
    $("job-card").classList.remove("hidden");
    currentJobId = status.job_id;
    renderJob(status);
    beginPolling();
  } catch (err) {
    toast(String(err.message || err), "error");
  } finally {
    setBusy(false);
  }
}

function shellQuote(args) {
  return args.map((arg) => {
    if (/^[A-Za-z0-9_@%+=:,./\\-]+$/.test(arg)) return arg;
    return JSON.stringify(arg);
  }).join(" ");
}

function renderJob(status) {
  $("job-state").textContent = status.state.toUpperCase();
  $("job-message").textContent = status.message || "";
  $("progress").value = status.progress_percent || 0;
  $("log").textContent = (status.log_tail || []).join("\n");
  $("command-preview").textContent = status.command && status.command.length ? shellQuote(status.command) : "";
  const save = $("save-link");
  if (status.state === "done" && status.file_url) {
    save.href = status.file_url;
    save.download = status.filename || "media";
    save.classList.remove("hidden");
  } else {
    save.classList.add("hidden");
  }
  if (status.state === "error") toast(status.message || "Download failed", "error");
}

function beginPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!currentJobId) return;
    try {
      const status = await api(`/api/jobs/${currentJobId}`);
      renderJob(status);
      if (["done", "error"].includes(status.state)) {
        clearInterval(pollTimer);
      }
    } catch (err) {
      clearInterval(pollTimer);
      toast(String(err.message || err), "error");
    }
  }, 900);
}

async function loadSystem() {
  const card = $("system-card");
  try {
    const info = await api("/api/system");
    const warnings = info.warnings || [];
    const rt = Object.keys(info.js_runtimes_found || {});
    card.innerHTML = `
      <span class="pill ok">RAM free: ${info.available_memory_gb} GB</span>
      <span class="pill">yt-dlp: ${info.yt_dlp_version}</span>
      <span class="pill">ffmpeg: ready</span>
      <span class="pill ${rt.length ? "ok" : "warn"}">JS runtime: ${rt.length ? rt.join(", ") : "none"}</span>
      ${warnings.map((w) => `<span class="pill warn">${escapeHtml(w)}</span>`).join("")}
    `;
  } catch (err) {
    card.innerHTML = `<span class="pill warn">system check failed</span>`;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}

async function loadSettings() {
  const settings = await api("/api/settings");
  $("cookies-file").value = settings.cookies_file || "";
  $("allow-remote-ejs").checked = Boolean(settings.allow_remote_ejs_github);
  $("js-runtime").value = settings.js_runtime || "auto";
}

async function saveSettings() {
  const settings = {
    cookies_file: $("cookies-file").value.trim(),
    allow_remote_ejs_github: $("allow-remote-ejs").checked,
    js_runtime: $("js-runtime").value,
    max_clip_seconds: 300,
    cleanup_ttl_hours: 6,
  };
  setBusy(true, "Saving settings…");
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(settings) });
    toast("Settings saved.");
    await loadSystem();
  } catch (err) {
    toast(String(err.message || err), "error");
  } finally {
    setBusy(false);
  }
}

async function boot() {
  try {
    const bootInfo = await api("/api/bootstrap");
    TOKEN = bootInfo.token;
    await Promise.all([loadSystem(), loadSettings()]);
  } catch (err) {
    toast(`Could not talk to local agent: ${String(err.message || err)}`, "error");
  }
  fillContainers();
  fillFormats();

  $("probe-btn").addEventListener("click", probeUrl);
  $("download-btn").addEventListener("click", startDownload);
  $("save-settings-btn").addEventListener("click", saveSettings);
  $("mode").addEventListener("change", () => { fillContainers(); fillFormats(); });
  $("url").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") probeUrl();
  });
}

boot();
