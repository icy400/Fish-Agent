<template>
  <div class="real-time-monitor">
    <div class="page-title">鱼群声学实时监测 · 精准投喂策略</div>

    <div class="card-grid">
      <div class="status-card">
        <div class="card-label">运行状态</div>
        <div class="card-value primary">
          {{ monitorData.status === "监测中" ? "实时监测中" : "已暂停" }}
        </div>
      </div>

      <div class="status-card">
        <div class="card-label">当前识别</div>
        <div class="card-value" :class="{ alert: monitorData.currentType === '鱼类摄食声' }">
          {{ monitorData.currentType }}
        </div>
      </div>

      <div class="status-card">
        <div class="card-label">当前置信度</div>
        <div class="card-value">{{ confidencePercent }}</div>
      </div>

      <div class="status-card">
        <div class="card-label">累计鱼声片段</div>
        <div class="card-value alert">{{ monitorData.totalCount }}</div>
      </div>

      <div class="status-card">
        <div class="card-label">当前分片鱼声占比</div>
        <div class="card-value">{{ fishRatioPercent }}</div>
      </div>

      <div class="status-card">
        <div class="card-label">决策窗口鱼声占比</div>
        <div class="card-value">{{ windowRatioPercent }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">实时波形状态</div>
      <div class="wave-box">
        <div
          v-for="(delay, idx) in waveDelays"
          :key="idx"
          class="wave-bar"
          :style="{
            animationPlayState: monitorData.status === '监测中' ? 'running' : 'paused',
            animationDelay: delay
          }"
        />
      </div>
      <div class="meta-line">
        摄食强度：
        <span class="meta-value">{{ monitorData.intensity }}</span>
        <span class="meta-sep">|</span>
        数据来源：
        <span class="meta-value">{{ monitorData.sourceMode }}</span>
      </div>
      <div class="meta-line">
        最近分片：{{ monitorData.lastChunkName }}
        <span class="meta-sep">|</span>
        设备：{{ monitorData.lastDeviceId }}
        <span class="meta-sep">|</span>
        时间：{{ monitorData.lastChunkAt }}
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">投喂策略动作</div>
      <div class="decision-row">
        <span class="decision-label">动作：</span>
        <span class="decision-value">{{ decisionLabel }}</span>
      </div>
      <div class="suggestion-text">{{ monitorData.suggestion }}</div>
    </div>

    <div class="action-row">
      <button
        v-if="monitorData.status !== '监测中'"
        class="btn btn-primary"
        @click="start"
      >
        开始实时监测
      </button>
      <button v-else class="btn btn-danger" @click="stop">暂停监测</button>
      <button class="btn btn-default" @click="reset">重置统计</button>
      <button class="btn btn-default" @click="loadCurrent">刷新状态</button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import request from "../utils/request";

const monitorData = ref({
  status: "已暂停",
  currentType: "背景噪音",
  confidence: 0.5,
  totalCount: 0,
  intensity: "低",
  suggestion: "等待开始监测",
  decisionAction: "WAIT",
  fishRatio: 0,
  windowFishRatio: 0,
  sourceMode: "Windows分片上传",
  lastChunkAt: "-",
  lastChunkName: "-",
  lastDeviceId: "-",
});

const eventSource = ref(null);
const waveDelays = Array.from({ length: 40 }, (_, idx) => `-${(idx * 0.07).toFixed(2)}s`);

const actionLabelMap = {
  WAIT: "待机观察",
  FEED_START: "启动投喂",
  FEED_HOLD: "维持投喂",
  FEED_REDUCE: "减量投喂",
  FEED_STOP: "停止投喂",
};

const apiBase = computed(() => {
  const value = request.defaults.baseURL || window.location.origin;
  return String(value).replace(/\/$/, "");
});

const decisionLabel = computed(
  () => actionLabelMap[monitorData.value.decisionAction] || monitorData.value.decisionAction || "待机观察"
);

const confidencePercent = computed(() => `${((monitorData.value.confidence || 0) * 100).toFixed(1)}%`);
const fishRatioPercent = computed(() => `${((monitorData.value.fishRatio || 0) * 100).toFixed(1)}%`);
const windowRatioPercent = computed(() => `${((monitorData.value.windowFishRatio || 0) * 100).toFixed(1)}%`);

function mergeMonitorData(payload) {
  if (!payload) return;
  monitorData.value = { ...monitorData.value, ...payload };
}

function parseControlResponse(resData) {
  if (resData && typeof resData === "object" && resData.data) {
    mergeMonitorData(resData.data);
  }
}

function connectSSE() {
  if (eventSource.value) {
    eventSource.value.close();
  }

  const streamUrl = `${apiBase.value}/realtime/stream`;
  eventSource.value = new EventSource(streamUrl);

  eventSource.value.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      mergeMonitorData(data);
    } catch (err) {
      console.error("SSE parse failed", err);
    }
  };

  eventSource.value.onerror = () => {
    if (eventSource.value) {
      eventSource.value.close();
      eventSource.value = null;
    }
  };
}

async function loadCurrent() {
  try {
    const res = await request.get("/realtime/data");
    mergeMonitorData(res.data);
  } catch (err) {
    ElMessage.error("获取实时状态失败");
  }
}

async function start() {
  try {
    const res = await request.get("/realtime/start");
    parseControlResponse(res.data);
    connectSSE();
    ElMessage.success("监测已启动");
  } catch (err) {
    ElMessage.error("启动失败");
  }
}

async function stop() {
  try {
    const res = await request.get("/realtime/stop");
    parseControlResponse(res.data);
    ElMessage.success("监测已暂停");
  } catch (err) {
    ElMessage.error("停止失败");
  }
}

async function reset() {
  try {
    const res = await request.get("/realtime/reset");
    parseControlResponse(res.data);
    ElMessage.success("统计已重置");
  } catch (err) {
    ElMessage.error("重置失败");
  }
}

onMounted(async () => {
  await loadCurrent();
  connectSSE();
});

onUnmounted(() => {
  if (eventSource.value) {
    eventSource.value.close();
    eventSource.value = null;
  }
});
</script>

<style scoped>
.real-time-monitor {
  max-width: 1200px;
  margin: 0 auto;
  background: linear-gradient(135deg, #e0f7fa 0%, #f0f9ff 50%, #fef6fb 100%);
  padding: 12px 16px 20px;
}

.page-title {
  text-align: center;
  font-size: 25px;
  color: #0284c7;
  margin-bottom: 16px;
  letter-spacing: 1px;
  font-weight: 700;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.status-card {
  background: #fff;
  border-radius: 12px;
  padding: 14px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.card-label {
  color: #73808c;
  font-size: 13px;
}

.card-value {
  margin-top: 4px;
  font-size: 18px;
  font-weight: 700;
  color: #1f2d3d;
}

.card-value.primary {
  color: #1677ff;
}

.card-value.alert {
  color: #ff4d4f;
}

.panel {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.panel-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 10px;
  color: #2a3a4a;
}

.wave-box {
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
}

.meta-line {
  margin-top: 8px;
  color: #51606f;
  font-size: 14px;
}

.meta-value {
  font-weight: 700;
  color: #1d75cb;
}

.meta-sep {
  margin: 0 8px;
  color: #b4bec8;
}

.decision-row {
  margin-bottom: 10px;
}

.decision-label {
  color: #6d7b88;
}

.decision-value {
  font-size: 20px;
  font-weight: 700;
  color: #ff4d4f;
}

.suggestion-text {
  font-size: 15px;
  line-height: 1.7;
  color: #1f2d3d;
}

.action-row {
  display: flex;
  gap: 10px;
}

.btn {
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  color: #fff;
  cursor: pointer;
  font-size: 14px;
}

.btn-primary {
  background: #1677ff;
}

.btn-danger {
  background: #ff4d4f;
}

.btn-default {
  background: #7f8c99;
}

@keyframes waveMove {
  0% {
    height: 10px;
    opacity: 0.6;
  }

  50% {
    height: 58px;
    opacity: 1;
    background: #40a9ff;
  }

  100% {
    height: 10px;
    opacity: 0.6;
  }
}

.wave-bar {
  width: 4px;
  height: 10px;
  background: #1677ff;
  border-radius: 2px;
  animation: waveMove 1.2s infinite linear;
  animation-play-state: paused;
}
</style>
