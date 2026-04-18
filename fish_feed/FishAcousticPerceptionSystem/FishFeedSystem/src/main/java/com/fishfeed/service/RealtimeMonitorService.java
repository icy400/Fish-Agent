package com.fishfeed.service;

import com.fishfeed.entity.MonitorResult;
import com.fishfeed.utils.PythonRealtimeUtil;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

@Service
public class RealtimeMonitorService {
    
    @Autowired
    private PythonRealtimeUtil pythonRealtimeUtil;
    
    // 全局实时结果
    private final MonitorResult currentResult = new MonitorResult();
    
    private boolean running = false;
    private final ScheduledExecutorService executor = Executors.newScheduledThreadPool(1);
    
    public RealtimeMonitorService() {
        currentResult.setStatus("已暂停");
        currentResult.setCurrentType("背景噪音");
        currentResult.setConfidence(0.96);
        currentResult.setTotalCount(0);
        currentResult.setIntensity("低");
        currentResult.setSuggestion("等待开始监测");
    }
    
    public void start() {
        if (running) return;
        running = true;
        currentResult.setStatus("监测中");
        
        // 1. 启动持续录音
        pythonRealtimeUtil.startContinuousRecording();
        
        // 2. 定时识别任务
        // 【修复点】初始延迟设为 7 秒：给 FFmpeg 时间写入数据，避免第一次截取时文件为空
        executor.scheduleAtFixedRate(() -> {
            if (!running) return;
            
            try {
                JSONObject result = pythonRealtimeUtil.detect();
                if (result == null || !result.containsKey("results")) return;
                
                JSONArray results = result.getJSONArray("results");
                if (results.isEmpty()) return;
                
                JSONObject segment = results.getJSONObject(0);
                JSONArray allSegments = segment.getJSONArray("segments");
                
                int fishCount = 0;
                double totalConf = 0.0;
                
                for (int i = 0; i < allSegments.size(); i++) {
                    JSONObject seg = allSegments.getJSONObject(i);
                    if ("fish".equals(seg.getString("predicted_class"))) {
                        fishCount++;
                        totalConf += seg.getDoubleValue("confidence");
                    }
                }
                
                // 更新状态
                if (fishCount > 1) {
                    currentResult.setCurrentType("鱼类摄食声");
                } else {
                    currentResult.setCurrentType("背景噪音");
                }
                
                if (fishCount > 0) {
                    currentResult.setConfidence(totalConf / fishCount);
                } else {
                    currentResult.setConfidence(0.96);
                }
                
                if (fishCount == 0) {
                    currentResult.setIntensity("低");
                } else if (fishCount == 1) {
                    currentResult.setIntensity("中");
                } else {
                    currentResult.setIntensity("强");
                }
                
                currentResult.setTotalCount(currentResult.getTotalCount() + fishCount);
                
                if (fishCount >= 2) {
                    currentResult.setSuggestion("6秒内摄食频繁 → 建议立即投喂");
                } else if (fishCount == 1) {
                    currentResult.setSuggestion("6秒内轻微摄食 → 可少量投喂");
                } else {
                    currentResult.setSuggestion("6秒内无摄食 → 暂不投喂");
                }
                
            } catch (Exception e) {
                e.printStackTrace();
            }
        }, 7, 6, TimeUnit.SECONDS); // 初始延迟 7s, 间隔 6s
    }
    
    public void stop() {
        running = false;
        currentResult.setStatus("已暂停");
        pythonRealtimeUtil.stopRecording();
    }
    
    public void reset() {
        currentResult.setCurrentType("背景噪音");
        currentResult.setConfidence(0.96);
        currentResult.setTotalCount(0);
        currentResult.setIntensity("低");
        currentResult.setSuggestion("等待开始监测");
    }
    
    public MonitorResult getResult() {
        return currentResult;
    }
}