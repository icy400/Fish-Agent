package com.fishfeed.service;

import com.fishfeed.entity.MonitorResult;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.fishfeed.config.RealtimeConfigProperties;
import com.fishfeed.utils.PythonChunkInferenceUtil;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class RealtimeMonitorService {
    
    private static final Logger log = LoggerFactory.getLogger(RealtimeMonitorService.class);
    
    @Autowired
    private PythonChunkInferenceUtil pythonChunkInferenceUtil;
    
    @Autowired
    private RealtimeConfigProperties realtimeConfig;
    
    private final MonitorResult currentResult = new MonitorResult();
    private final Deque<Double> fishRatioWindow = new ArrayDeque<>();
    private final List<SseEmitter> emitters = new CopyOnWriteArrayList<>();
    private final AtomicLong chunkCounter = new AtomicLong(0);
    
    private boolean running = false;
    private boolean feedingActive = false;
    private int startHitStreak = 0;
    private int stopHitStreak = 0;
    
    public RealtimeMonitorService() {
        resetResultBase(0.50);
    }
    
    @PostConstruct
    public void initAfterPropertiesLoaded() {
        resetResultBase(realtimeConfig.getDefaultConfidence());
        log.info(
                "Realtime monitor initialized: mode={}, uploadDir={}, keepUploadedChunks={}, windowSize={}",
                realtimeConfig.getMode(),
                resolveUploadDir(),
                realtimeConfig.isKeepUploadedChunks(),
                realtimeConfig.getDecisionWindowSize()
        );
    }
    
    public synchronized void start() {
        if (running) {
            log.info("start ignored: monitor already running");
            return;
        }
        running = true;
        currentResult.setStatus("监测中");
        currentResult.setSourceMode("Windows分片上传");
        currentResult.setSuggestion("监测已启动，等待 Windows 采集端上传音频分片");
        currentResult.setDecisionAction(feedingActive ? "FEED_HOLD" : "WAIT");
        log.info("monitor started: sourceMode={}", currentResult.getSourceMode());
        broadcastCurrentResult();
    }
    
    public synchronized void stop() {
        running = false;
        feedingActive = false;
        startHitStreak = 0;
        stopHitStreak = 0;
        
        currentResult.setStatus("已暂停");
        currentResult.setDecisionAction("WAIT");
        currentResult.setSuggestion("监测已暂停");
        log.info("monitor stopped");
        broadcastCurrentResult();
    }
    
    public synchronized void reset() {
        fishRatioWindow.clear();
        feedingActive = false;
        startHitStreak = 0;
        stopHitStreak = 0;
        resetResultBase(realtimeConfig.getDefaultConfidence());
        currentResult.setStatus(running ? "监测中" : "已暂停");
        currentResult.setSourceMode("Windows分片上传");
        currentResult.setSuggestion(running ? "等待上传新分片" : "等待开始监测");
        log.info("monitor stats reset: running={}", running);
        broadcastCurrentResult();
    }
    
    public synchronized MonitorResult getResult() {
        return currentResult;
    }
    
    public synchronized Map<String, Object> ingestChunk(
            MultipartFile file, String deviceId, String collectedAt
    ) {
        Map<String, Object> response = new HashMap<>();
        Path savedPath = null;
        
        try {
            if (!running) {
                log.warn("chunk rejected: monitor not running, deviceId={}", deviceId);
                response.put("code", 409);
                response.put("msg", "监测未启动，请先调用 /realtime/start");
                response.put("data", currentResult);
                return response;
            }
            
            if (file == null || file.isEmpty()) {
                log.warn("chunk rejected: empty file, deviceId={}", deviceId);
                response.put("code", 400);
                response.put("msg", "上传分片为空");
                return response;
            }
            
            Path uploadDir = resolveUploadDir();
            Files.createDirectories(uploadDir);
            
            String originalName = Optional.ofNullable(file.getOriginalFilename()).orElse("chunk.wav");
            String safeName = originalName.replaceAll("[^a-zA-Z0-9._-]", "_");
            String chunkName = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss_SSS").format(LocalDateTime.now())
                    + "_" + chunkCounter.incrementAndGet() + "_" + safeName;
            savedPath = uploadDir.resolve(chunkName);
            
            file.transferTo(savedPath.toFile());
            log.info(
                    "chunk received: file={}, size={}, deviceId={}, collectedAt={}, savedPath={}",
                    chunkName,
                    file.getSize(),
                    deviceId,
                    collectedAt,
                    savedPath
            );
            
            JSONObject inferResult = pythonChunkInferenceUtil.detectByFile(savedPath.toAbsolutePath().toString());
            ChunkSummary chunkSummary = parseChunkSummary(inferResult);
            applyStrategy(chunkSummary, deviceId, collectedAt, chunkName);
            broadcastCurrentResult();
            
            response.put("code", 200);
            response.put("msg", "分片识别成功");
            response.put("data", currentResult);
            response.put("chunkFishRatio", round(chunkSummary.fishRatio));
            response.put("windowFishRatio", currentResult.getWindowFishRatio());
            response.put("decisionAction", currentResult.getDecisionAction());
            log.info(
                    "chunk processed: file={}, fishRatio={}, windowFishRatio={}, action={}, confidence={}",
                    chunkName,
                    round(chunkSummary.fishRatio),
                    currentResult.getWindowFishRatio(),
                    currentResult.getDecisionAction(),
                    currentResult.getConfidence()
            );
            return response;
            
        } catch (Exception e) {
            log.error("chunk processing failed: deviceId={}, collectedAt={}", deviceId, collectedAt, e);
            response.put("code", 500);
            response.put("msg", "分片识别失败: " + e.getMessage());
            response.put("data", currentResult);
            return response;
        } finally {
            if (!realtimeConfig.isKeepUploadedChunks() && savedPath != null) {
                try {
                    Files.deleteIfExists(savedPath);
                } catch (IOException ex) {
                    log.warn("failed to delete uploaded chunk: path={}", savedPath, ex);
                }
            }
        }
    }
    
    public SseEmitter registerEmitter() {
        SseEmitter emitter = new SseEmitter(0L);
        emitters.add(emitter);
        
        emitter.onCompletion(() -> emitters.remove(emitter));
        emitter.onTimeout(() -> emitters.remove(emitter));
        emitter.onError(ex -> emitters.remove(emitter));
        log.info("sse client connected: activeEmitters={}", emitters.size());
        
        try {
            emitter.send(currentResult);
        } catch (IOException e) {
            emitter.complete();
            emitters.remove(emitter);
            log.warn("sse first push failed", e);
        }
        return emitter;
    }
    
    public Map<String, Object> getConfigSnapshot() {
        Map<String, Object> config = new HashMap<>();
        config.put("mode", realtimeConfig.getMode());
        config.put("chunkSeconds", realtimeConfig.getChunkSeconds());
        config.put("decisionWindowSize", realtimeConfig.getDecisionWindowSize());
        config.put("fishSegmentThreshold", realtimeConfig.getFishSegmentThreshold());
        config.put("fishTypeThreshold", realtimeConfig.getFishTypeThreshold());
        config.put("startThreshold", realtimeConfig.getStartThreshold());
        config.put("reduceThreshold", realtimeConfig.getReduceThreshold());
        config.put("stopThreshold", realtimeConfig.getStopThreshold());
        config.put("startConsecutiveWindows", realtimeConfig.getStartConsecutiveWindows());
        config.put("stopConsecutiveWindows", realtimeConfig.getStopConsecutiveWindows());
        config.put("keepUploadedChunks", realtimeConfig.isKeepUploadedChunks());
        config.put("uploadDir", resolveUploadDir().toString());
        config.put("pythonCommand", realtimeConfig.getPythonCommand());
        config.put("pythonScriptPath", realtimeConfig.getPythonScriptPath());
        return config;
    }
    
    private void resetResultBase(double defaultConfidence) {
        currentResult.setStatus("已暂停");
        currentResult.setCurrentType("背景噪音");
        currentResult.setConfidence(defaultConfidence);
        currentResult.setTotalCount(0);
        currentResult.setIntensity("低");
        currentResult.setSuggestion("等待开始监测");
        currentResult.setDecisionAction("WAIT");
        currentResult.setFishRatio(0.0);
        currentResult.setWindowFishRatio(0.0);
        currentResult.setSourceMode("Windows分片上传");
        currentResult.setLastChunkAt("-");
        currentResult.setLastChunkName("-");
        currentResult.setLastDeviceId("-");
    }
    
    private void applyStrategy(ChunkSummary chunk, String deviceId, String collectedAt, String chunkName) {
        if (chunk.totalSegments > 0) {
            currentResult.setTotalCount(currentResult.getTotalCount() + chunk.fishSegments);
        }
        
        double fishRatio = chunk.fishRatio;
        double windowRatio = updateFishRatioWindow(fishRatio);
        String previousAction = currentResult.getDecisionAction();
        String action = decideAction(windowRatio);
        
        currentResult.setCurrentType(fishRatio >= realtimeConfig.getFishTypeThreshold() ? "鱼类摄食声" : "背景噪音");
        currentResult.setConfidence(chunk.totalSegments > 0 ? round(chunk.avgConfidence) : realtimeConfig.getDefaultConfidence());
        currentResult.setFishRatio(round(fishRatio));
        currentResult.setWindowFishRatio(round(windowRatio));
        currentResult.setDecisionAction(action);
        currentResult.setIntensity(buildIntensity(windowRatio));
        currentResult.setSuggestion(buildSuggestion(action, windowRatio));
        currentResult.setSourceMode("Windows分片上传");
        currentResult.setLastChunkAt((collectedAt == null || collectedAt.isBlank())
                ? LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
                : collectedAt);
        currentResult.setLastChunkName(chunkName);
        currentResult.setLastDeviceId((deviceId == null || deviceId.isBlank()) ? "unknown-device" : deviceId);
        
        if (!action.equals(previousAction)) {
            log.info(
                    "decision action changed: {} -> {}, windowFishRatio={}, fishRatio={}",
                    previousAction,
                    action,
                    round(windowRatio),
                    round(fishRatio)
            );
        }
    }
    
    private ChunkSummary parseChunkSummary(JSONObject result) {
        if (result == null || !result.containsKey("results")) {
            return ChunkSummary.empty();
        }
        
        JSONArray results = result.getJSONArray("results");
        if (results == null || results.isEmpty()) {
            return ChunkSummary.empty();
        }
        
        JSONObject fileResult = results.getJSONObject(0);
        JSONArray segments = fileResult.getJSONArray("segments");
        if (segments == null || segments.isEmpty()) {
            return ChunkSummary.empty();
        }
        
        int fishSegments = 0;
        double fishProbSum = 0.0;
        double confidenceSum = 0.0;
        
        for (int i = 0; i < segments.size(); i++) {
            JSONObject seg = segments.getJSONObject(i);
            String predictedClass = seg.getString("predicted_class");
            double confidence = seg.getDoubleValue("confidence");
            confidenceSum += confidence;
            
            double fishProb = "fish".equalsIgnoreCase(predictedClass) ? confidence : 1.0 - confidence;
            if (seg.containsKey("probabilities")) {
                JSONObject probs = seg.getJSONObject("probabilities");
                if (probs != null && probs.containsKey("fish")) {
                    fishProb = probs.getDoubleValue("fish");
                }
            }
            fishProb = Math.max(0.0, Math.min(1.0, fishProb));
            fishProbSum += fishProb;
            
            if (fishProb >= realtimeConfig.getFishSegmentThreshold()) {
                fishSegments++;
            }
        }
        
        int totalSegments = segments.size();
        double fishRatio = totalSegments == 0 ? 0.0 : (double) fishSegments / totalSegments;
        double avgFishProb = fishProbSum / totalSegments;
        double avgConfidence = confidenceSum / totalSegments;
        
        return new ChunkSummary(totalSegments, fishSegments, fishRatio, avgFishProb, avgConfidence);
    }
    
    private double updateFishRatioWindow(double fishRatio) {
        fishRatioWindow.addLast(fishRatio);
        while (fishRatioWindow.size() > realtimeConfig.getDecisionWindowSize()) {
            fishRatioWindow.pollFirst();
        }
        return fishRatioWindow.stream().mapToDouble(Double::doubleValue).average().orElse(0.0);
    }
    
    private String decideAction(double windowRatio) {
        if (windowRatio >= realtimeConfig.getStartThreshold()) {
            startHitStreak++;
        } else {
            startHitStreak = 0;
        }
        
        if (windowRatio <= realtimeConfig.getStopThreshold()) {
            stopHitStreak++;
        } else {
            stopHitStreak = 0;
        }
        
        if (!feedingActive) {
            if (startHitStreak >= realtimeConfig.getStartConsecutiveWindows()) {
                feedingActive = true;
                stopHitStreak = 0;
                return "FEED_START";
            }
            return "WAIT";
        }
        
        if (stopHitStreak >= realtimeConfig.getStopConsecutiveWindows()) {
            feedingActive = false;
            startHitStreak = 0;
            return "FEED_STOP";
        }
        
        if (windowRatio <= realtimeConfig.getReduceThreshold()) {
            return "FEED_REDUCE";
        }
        
        return "FEED_HOLD";
    }
    
    private String buildIntensity(double windowRatio) {
        if (windowRatio >= realtimeConfig.getStartThreshold()) {
            return "高";
        }
        if (windowRatio >= realtimeConfig.getReduceThreshold()) {
            return "中";
        }
        return "低";
    }
    
    private String buildSuggestion(String action, double windowRatio) {
        switch (action) {
            case "FEED_START":
                return "检测到持续摄食，建议启动投喂";
            case "FEED_HOLD":
                return "摄食稳定，建议维持当前投喂速率";
            case "FEED_REDUCE":
                return "摄食趋势下降，建议减量投喂";
            case "FEED_STOP":
                return "摄食显著减弱，建议停止投喂";
            default:
                return "继续观察，当前窗口鱼声占比 " + round(windowRatio);
        }
    }
    
    private void broadcastCurrentResult() {
        for (SseEmitter emitter : emitters) {
            try {
                emitter.send(currentResult);
            } catch (Exception e) {
                emitter.complete();
                emitters.remove(emitter);
                log.warn("sse push failed; emitter removed", e);
            }
        }
    }
    
    private Path resolveUploadDir() {
        Path configured = Paths.get(realtimeConfig.getUploadDir());
        if (configured.isAbsolute()) {
            return configured;
        }
        return Paths.get(System.getProperty("user.dir")).resolve(configured).normalize();
    }
    
    private double round(double value) {
        return Math.round(value * 10000.0) / 10000.0;
    }
    
    private static class ChunkSummary {
        private final int totalSegments;
        private final int fishSegments;
        private final double fishRatio;
        private final double avgFishProb;
        private final double avgConfidence;
        
        private ChunkSummary(
                int totalSegments,
                int fishSegments,
                double fishRatio,
                double avgFishProb,
                double avgConfidence
        ) {
            this.totalSegments = totalSegments;
            this.fishSegments = fishSegments;
            this.fishRatio = fishRatio;
            this.avgFishProb = avgFishProb;
            this.avgConfidence = avgConfidence;
        }
        
        private static ChunkSummary empty() {
            return new ChunkSummary(0, 0, 0.0, 0.0, 0.0);
        }
    }
}
