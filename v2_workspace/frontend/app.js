const cfg = window.APP_CONFIG || {};
const API_BASE = (cfg.apiBaseUrl || "http://127.0.0.1:8081").replace(/\/$/, "");
const REFRESH_MS = Number(cfg.refreshMs || 2000);

const ids = [
  "status",
  "currentType",
  "confidence",
  "totalCount",
  "fishRatio",
  "windowFishRatio",
  "baselineFishRatio",
  "relativeFishDelta",
  "decisionAction",
  "intensity",
  "suggestion",
  "strategyReason",
  "lastChunkName",
  "lastChunkAt",
  "lastDeviceId",
  "agentStatus",
  "collectCommand",
];

const el = {};
ids.forEach((id) => (el[id] = document.getElementById(id)));
const judgmentBody = document.getElementById("judgmentBody");

function ratioText(v) {
  if (v === undefined || v === null) return "-";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function signedRatioText(v) {
  if (v === undefined || v === null) return "-";
  const num = Number(v) * 100;
  return `${num >= 0 ? "+" : ""}${num.toFixed(1)}%`;
}

function confText(v) {
  if (v === undefined || v === null) return "-";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "-")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function applyData(data) {
  el.status.textContent = data.status ?? "-";
  el.currentType.textContent = data.currentType ?? "-";
  el.confidence.textContent = confText(data.confidence);
  el.totalCount.textContent = data.totalCount ?? "-";
  el.fishRatio.textContent = ratioText(data.fishRatio);
  el.windowFishRatio.textContent = ratioText(data.windowFishRatio);
  el.baselineFishRatio.textContent = ratioText(data.baselineFishRatio);
  el.relativeFishDelta.textContent = signedRatioText(data.relativeFishDelta);
  el.decisionAction.textContent = data.decisionAction ?? "-";
  el.intensity.textContent = data.intensity ?? "-";
  el.suggestion.textContent = data.suggestion ?? "-";
  el.strategyReason.textContent = data.strategyReason ?? "-";
  el.lastChunkName.textContent = data.lastChunkName ?? "-";
  el.lastChunkAt.textContent = data.lastChunkAt ?? "-";
  el.lastDeviceId.textContent = data.lastDeviceId ?? "-";
}

function applyAgent(agent) {
  el.agentStatus.textContent = agent?.agentStatus ?? "-";
  el.collectCommand.textContent = agent?.collectEnabled ? "START" : "STOP";
}

function renderJudgments(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    judgmentBody.innerHTML = '<tr><td colspan="7">暂无判断结果</td></tr>';
    return;
  }
  judgmentBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.time)}</td>
          <td>${escapeHtml(item.decisionAction)}</td>
          <td>${ratioText(item.fishRatio)}</td>
          <td>${ratioText(item.windowFishRatio)}</td>
          <td>${ratioText(item.baselineFishRatio)}</td>
          <td>${signedRatioText(item.relativeFishDelta)}</td>
          <td>${escapeHtml(item.strategyReason)}</td>
        </tr>
      `
    )
    .join("");
}

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function loadData() {
  try {
    const [data, agent, judgments] = await Promise.all([
      getJSON("/realtime/data"),
      getJSON("/agent/state"),
      getJSON("/realtime/judgments"),
    ]);
    applyData(data);
    applyAgent(agent);
    renderJudgments(judgments);
  } catch (err) {
    console.error(err);
  }
}

async function callAction(path) {
  try {
    const res = await getJSON(path);
    if (res.data) applyData(res.data);
  } catch (err) {
    alert(`请求失败: ${err.message}`);
  }
}

async function startCollect() {
  try {
    const monitor = await getJSON("/realtime/start");
    if (monitor.data) applyData(monitor.data);
    const control = await getJSON("/agent/collect/start");
    if (control.data) applyAgent(control.data);
    await loadData();
  } catch (err) {
    alert(`开始采集失败: ${err.message}`);
  }
}

async function stopCollect() {
  try {
    const control = await getJSON("/agent/collect/stop");
    if (control.data) applyAgent(control.data);
    const monitor = await getJSON("/realtime/stop");
    if (monitor.data) applyData(monitor.data);
    await loadData();
  } catch (err) {
    alert(`停止采集失败: ${err.message}`);
  }
}

document.getElementById("btnStart").addEventListener("click", startCollect);
document.getElementById("btnStop").addEventListener("click", stopCollect);
document.getElementById("btnReset").addEventListener("click", () => callAction("/realtime/reset"));
document.getElementById("btnRefresh").addEventListener("click", () => loadData());

document.getElementById("uploadForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fileInput = document.getElementById("audioFile");
  const deviceIdInput = document.getElementById("deviceId");
  const resultEl = document.getElementById("uploadResult");
  if (!fileInput.files || !fileInput.files[0]) return;

  const form = new FormData();
  form.append("file", fileInput.files[0]);
  form.append("deviceId", deviceIdInput.value || "web-debug-device");
  form.append("collectedAt", new Date().toISOString().slice(0, 19).replace("T", " "));

  try {
    const res = await fetch(`${API_BASE}/realtime/chunk/upload`, {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    resultEl.textContent = JSON.stringify(data, null, 2);
    if (data.data) applyData(data.data);
    await loadData();
  } catch (err) {
    resultEl.textContent = `upload error: ${err.message}`;
  }
});

loadData();
setInterval(loadData, REFRESH_MS);
