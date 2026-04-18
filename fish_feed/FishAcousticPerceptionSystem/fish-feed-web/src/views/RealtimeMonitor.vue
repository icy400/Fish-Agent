<template>
    <div class="real-time-monitor"
        style="max-width: 1200px;margin: 0 auto;background: linear-gradient(135deg, #e0f7fa 0%, #f0f9ff 50%, #fef6fb 100%);">
        <div
            style="text-align: center;font-size: 25px;color: #0284c7;margin-bottom: 1px;letter-spacing: 2px;font-weight: bold;text-shadow: 0 2px 8px #b6eaff44;padding: 15px">
            鱼食声实时监测·智能投喂
        </div>

        <div style="display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap">
            <div class="card"
                style="flex: 1; min-width: 220px; background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 2px 10px rgba(0,0,0,0.05)">
                <div style="color:#999; font-size:13px">运行状态</div>
                <div style="font-size:18px; font-weight:bold; margin-top:4px; color:#1677ff">
                    {{ data.status === "监测中" ? "✅ 实时监测中" : "⏸ 已暂停" }}
                </div>
            </div>
            <div class="card"
                style="flex:1; min-width:220px; background:#fff; border-radius:12px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.05)">
                <div style="color:#999; font-size:13px">当前识别</div>
                <div style="font-size:18px; font-weight:bold; margin-top:4px"
                    :style="{ color: data.currentType === '鱼类摄食声' ? '#ff4d4f' : '#1677ff' }">
                    {{ data.currentType }}
                </div>
            </div>
            <div class="card"
                style="flex:1; min-width:220px; background:#fff; border-radius:12px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.05)">
                <div style="color:#999; font-size:13px">置信度</div>
                <div style="font-size:18px; font-weight:bold; margin-top:4px">
                    {{ data.confidence }}
                </div>
            </div>
            <div class="card"
                style="flex:1; min-width:220px; background:#fff; border-radius:12px; padding:16px; box-shadow:0 2px 10px rgba(0,0,0,0.05)">
                <div style="color:#999; font-size:13px">累计摄食次数</div>
                <div style="font-size:18px; font-weight:bold; margin-top:4px; color:#ff4d4f">
                    {{ data.totalCount }}
                </div>
            </div>
        </div>

        <div
            style="background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 2px 10px rgba(0,0,0,0.05)">
            <div style="font-size:16px; font-weight:bold; margin-bottom:12px; color:#2c50">实时音频波形</div>
            <div style="height:80px; display:flex; align-items:center; justify-content:center; gap:3px">
                <!-- 
                   修改点：
                   1. 给每个波形条添加了 class="wave-bar"
                   2. 利用 CSS 变量 --delay 来设置每个条的动画延迟，形成波浪感
                -->
                <div v-for="index in 40" :key="index" class="wave-bar" :style="{
                    // 监测中时播放动画，暂停时暂停
                    animationPlayState: data.status === '监测中' ? 'running' : 'paused',
                    // 随机延迟，让波形看起来自然
                    animationDelay: `-${Math.random() * 1.5}s`
                }">
                </div>
            </div>
            <div style="margin-top:10px; font-size:14px; color:#666">
                摄食强度：<span style="color:#ff4d4f; font-weight:bold">{{ data.intensity }}</span>
            </div>
        </div>

        <div
            style="background:#fff; border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 2px 10px rgba(0,0,0,0.05)">
            <div style="font-size:16px; font-weight:bold; margin-bottom:12px; color:#2c3e50">智能投喂建议</div>
            <div style="font-size:15px; color:#333; line-height:1.7">{{ data.suggestion }}</div>
        </div>

        <div style="display:flex; gap:12px">
            <button v-if="data.status !== '监测中'" @click="start"
                style="padding:10px 24px; background:#1677ff; color:#fff; border:none; border-radius:8px; cursor:pointer">
                开始实时监测
            </button>
            <button v-else @click="stop"
                style="padding:10px 24px; background:#ff4d4f; color:#fff; border:none; border-radius:8px; cursor:pointer">
                暂停监测
            </button>
            <button @click="reset"
                style="padding:10px 24px; background:#999; color:#fff; border:none; border-radius:8px; cursor:pointer">
                重置统计
            </button>
        </div>
    </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import axios from 'axios'

const data = ref({
    status: "已暂停",
    currentType: "背景噪音",
    confidence: 0.98,
    totalCount: 0,
    intensity: "低",
    suggestion: "等待开始监测"
})

const eventSource = ref(null)
const baseURL = "http://localhost:8081/realtime"

function connectSSE() {
    if (eventSource.value) {
        eventSource.value.close()
    }
    eventSource.value = new EventSource(`${baseURL}/stream`)

    eventSource.value.onmessage = (event) => {
        try {
            const resData = JSON.parse(event.data)
            data.value = resData
        } catch (e) {
            console.error("SSE 数据解析错误", e)
        }
    }
}

async function start() {
    await axios.get(`${baseURL}/start`)
    data.value.status = "监测中"
    connectSSE()
}

async function stop() {
    await axios.get(`${baseURL}/stop`)
    if (eventSource.value) {
        eventSource.value.close()
        eventSource.value = null
    }
    data.value.status = "已暂停"
}

async function reset() {
    await axios.get(`${baseURL}/reset`)
}

onUnmounted(() => {
    if (eventSource.value) {
        eventSource.value.close()
    }
})
</script>

<style scoped>
/* 定义波形上下跳动的动画 */
@keyframes waveMove {
    0% {
        height: 10px;
        opacity: 0.6;
    }

    50% {
        height: 60px;
        /* 跳动最大高度 */
        opacity: 1;
        background: #40a9ff;
        /* 跳动时颜色变浅一点 */
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
    /* 应用动画：时长1.2秒，无限循环，线性变化 */
    animation: waveMove 1.2s infinite linear;
    /* 默认暂停，只有监测中才播放 */
    animation-play-state: paused;
}
</style>