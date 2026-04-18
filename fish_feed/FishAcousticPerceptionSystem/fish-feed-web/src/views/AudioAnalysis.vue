<template>
    <div class="audio-analysis-page">
        <div class="page-header">
            <h1>鱼食声识别 · 智能投喂</h1>
        </div>

        <div class="analysis-container">
            <!-- 左侧上传 -->
            <div class="card-left">
                <el-card shadow="hover" class="upload-card">
                    <template #header>
                        <span class="card-title">音频文件上传</span>
                    </template>

                    <el-upload drag :auto-upload="false" @change="handleFileChange"
                        accept="audio/wav,audio/wave,audio/mp3" :show-file-list="false">
                        <i class="el-icon-upload"></i>
                        <div class="el-upload__text">拖入音频文件 / 点击上传</div>
                        <div v-if="file" class="upload-file-info">
                            <span class="file-name">{{ file.name }}</span>
                            <el-button type="danger" size="small" @click.stop="removeFile"
                                style="margin-left:10px">删除</el-button>
                        </div>
                        <div v-if="file">
                            <el-button type="primary" round class="start-btn"
                                :disabled="!file || uploading || uploadSuccess" :loading="uploading"
                                @click.stop="uploadFile" style="margin-top:10px;width:100%">
                                {{ uploading ? '上传中...' : '上传文件' }}
                            </el-button>
                        </div>
                        <div v-if="uploading" class="progress-container">
                            <el-progress :percentage="uploadPercent" status="success" :stroke-width="18" />
                            <p class="progress-text">上传中 {{ uploadPercent }}%（请等待上传完成）</p>
                        </div>
                    </el-upload>


                    <!-- ===================== 分析按钮（上传完才可用） ===================== -->
                    <el-button type="success" round class="start-btn" :disabled="!uploadSuccess || analyzing"
                        :loading="analyzing" @click="startAnalyze"
                        style="margin-top:5px;background:#28c76f;border-color:#28c76f;color:#fff">
                        {{ analyzing ? '识别中...' : '开始智能分析' }}
                    </el-button>
                </el-card>

                <!-- 投喂建议 -->
                <el-card shadow="hover" class="feed-card">
                    <template #header>
                        <span class="card-title">智能投喂决策</span>
                    </template>
                    <div v-if="!result" class="tip-empty">等待分析...</div>
                    <div v-else class="feed-info">
                        <div class="feed-item">
                            <label>建议投喂量</label>
                            <span class="feed-value">{{ feedAmount }} kg</span>
                        </div>
                        <div class="feed-item">
                            <label>进食强度</label>
                            <span class="feed-value">{{ feedLevel }}</span>
                        </div>
                        <div class="feed-suggest">
                            {{ feedMsg }}
                        </div>
                    </div>
                </el-card>
            </div>

            <!-- 右侧结果 -->
            <div class="card-right">
                <el-card shadow="hover" class="result-card">
                    <template #header>
                        <span class="card-title">识别统计结果</span>
                    </template>

                    <div v-if="!result" class="tip-empty">暂无数据</div>
                    <div v-else class="result-info">
                        <p><label>文件名：</label>{{ result.filename }}</p>
                        <p><label>总时长：</label>{{ result.total_duration.toFixed(2) }}s</p>
                        <p><label>总片段数：</label>{{ result.total_segments }}</p>
                        <p><label>鱼进食片段：</label>{{ result.fish_chewing_count }}</p>
                        <p><label>进食总时长：</label>{{ result.fish_chewing_count * 2 }}s</p>
                        <p><label>背景片段：</label>{{ result.total_segments - result.fish_chewing_count }}</p>

                        <el-button type="primary" @click="dialogVisible = true" style="margin-top:12px">
                            查看详细时序
                        </el-button>
                    </div>
                </el-card>
            </div>
        </div>

        <!-- 时序详情弹窗 -->
        <el-dialog title="识别时序详情" v-model="dialogVisible" width="85%">
            <div style="max-height:500px;overflow-y:auto">
                <div v-for="(item, i) in detailList" :key="i" class="detail-item">
                    <span>{{ item.time_start }}s ~ {{ item.time_end }}s</span>
                    <span :class="item.predicted_class === 'fish' ? 'fish-tag' : 'bg-tag'">
                        {{ item.predicted_class === 'fish' ? '鱼吃食' : '背景' }}
                    </span>
                    <span>置信度 {{ (item.confidence * 100).toFixed(1) }}%</span>
                </div>
            </div>
        </el-dialog>
    </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const file = ref(null)
const analyzing = ref(false)
const result = ref(null)
const dialogVisible = ref(false)
const detailList = ref([])

const feedAmount = ref(0)
const feedLevel = ref('-')
const feedMsg = ref('等待分析')

// ===================== 上传状态 =====================
const uploading = ref(false)
const uploadPercent = ref(0)
const uploadSuccess = ref(false)

// 选择文件
function handleFileChange(uploadFile) {
    file.value = Array.isArray(uploadFile) ? uploadFile[0] : uploadFile
    uploadSuccess.value = false
    result.value = null
}

function removeFile() {
    file.value = null
    uploadSuccess.value = false
}

// ===================== 带进度条上传 =====================
async function uploadFile() {
    if (!file.value) return

    const formData = new FormData()
    formData.append('file', file.value.raw)

    uploading.value = true
    uploadPercent.value = 0

    try {
        await request.post('/upload-audio', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (e) => {
                uploadPercent.value = Math.floor((e.loaded / e.total) * 100)
            }
        })
        ElMessage.success('✅ 文件上传成功')
        uploadSuccess.value = true
    } catch (err) {
        ElMessage.error('❌ 上传失败')
    } finally {
        uploading.value = false
    }
}

// ===================== 开始分析（仅上传后可用） =====================
async function startAnalyze() {
    if (!uploadSuccess.value) {
        ElMessage.warning('请先上传文件')
        return
    }

    analyzing.value = true
    try {
        const res = await request.post('/analyze-audio', {
            filename: file.value.name
        })

        const data = res.data
        if (!data || !data.results || data.results.length === 0) {
            ElMessage.warning('未返回识别结果')
            return
        }

        result.value = data.results[0]
        detailList.value = result.value.segments || []

        const cnt = result.value.fish_chewing_count
        const total = result.value.total_segments
        const ratio = cnt / total

        if (ratio >= 0.15) {
            feedAmount.value = 0.8
            feedLevel.value = '极高'
            feedMsg.value = '进食活跃，建议足量投喂'
        } else if (ratio >= 0.08) {
            feedAmount.value = 0.5
            feedLevel.value = '高'
            feedMsg.value = '进食正常，建议标准投喂'
        } else if (ratio >= 0.03) {
            feedAmount.value = 0.3
            feedLevel.value = '中等'
            feedMsg.value = '进食一般，建议少量投喂'
        } else {
            feedAmount.value = 0.1
            feedLevel.value = '低'
            feedMsg.value = '进食较弱，建议不投喂或极少量'
        }

        ElMessage.success('分析完成')
    } catch (err) {
        console.error(err)
        ElMessage.error('后端请求失败')
    } finally {
        analyzing.value = false
    }
}
</script>

<style scoped>
.upload-file-info {
    display: flex;
    align-items: center;
    margin-top: 10px;
    font-size: 14px;
    color: #374151;
    justify-content: space-between;
    /* 两端对齐 */
}

.file-name {
    max-width: 80%;
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* 进度条样式 */
.progress-container {
    margin: 15px 0;
}

.progress-text {
    text-align: center;
    margin-top: 8px;
    font-size: 13px;
    color: #6b7280;
}

.audio-analysis-page {
    max-width: 1200px;
    margin: 0 auto;
    font-family: "Microsoft YaHei", sans-serif;
    min-height: 100vh;
    background: linear-gradient(135deg, #e0f7fa 0%, #f0f9ff 50%, #fef6fb 100%);
}

.page-header {
    text-align: center;
    margin-bottom: 30px;
}

.page-header h1 {
    font-size: 25px;
    color: #0284c7;
    margin-bottom: 1px;
    letter-spacing: 2px;
    font-weight: bold;
    text-shadow: 0 2px 8px #b6eaff44;
}


.analysis-container {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
}

.card-left {
    flex: 1;
    min-width: 400px;
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.card-right {
    flex: 1;
    min-width: 400px;
}

.upload-card,
.feed-card,
.result-card {
    border-radius: 16px;
    box-shadow: 0 4px 24px 0 rgba(0, 160, 255, 0.08), 0 1.5px 6px 0 rgba(0, 0, 0, 0.04);
    background: #fff;
}

.card-title {
    font-weight: 700;
    font-size: 18px;
    color: #0284c7;
    letter-spacing: 1px;
}

.start-btn {
    width: 100%;
    margin-top: 18px;
    height: 42px;
    font-size: 16px;
    letter-spacing: 1px;
}

.tip-empty {
    color: #9ca3af;
    text-align: center;
    padding: 20px 0;
    background: #f0f9ff;
    border-radius: 8px;
}
.feed-info {
    padding: 6px 0;
}

.feed-item {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
    font-size: 15px;
}

.feed-item label {
    font-weight: 500;
    color: #374151;
}

.feed-value {
    font-weight: 600;
    color: #0284c7;
}

.feed-suggest {
    margin-top: 10px;
    padding: 10px 12px;
    background: linear-gradient(90deg, #fef2f2 60%, #f0f9ff 100%);
    color: #dc2626;
    border-radius: 6px;
    font-size: 14px;
    text-align: center;
    box-shadow: 0 2px 8px #fca5a522;
}

.result-info {
    line-height: 1.9;
    font-size: 15px;
}

.result-info label {
    font-weight: 500;
    color: #374151;
}

.detail-item {
    display: flex;
    justify-content: space-between;
    padding: 8px 10px;
    border-bottom: 1px solid #eee;
}

.fish-tag {
    color: #059669;
    font-weight: 500;
}

.bg-tag {
    color: #6b7280;
}
</style>