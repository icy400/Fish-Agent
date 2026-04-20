package com.fishfeed.controller;

import com.fishfeed.entity.MonitorResult;
import com.fishfeed.service.RealtimeMonitorService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/realtime")
public class RealtimeMonitorController {
    
    @Autowired
    private RealtimeMonitorService service;
    
    @GetMapping("/start")
    public Map<String, Object> start() {
        service.start();
        return ok("监测已启动");
    }
    
    @GetMapping("/stop")
    public Map<String, Object> stop() {
        service.stop();
        return ok("监测已停止");
    }
    
    @GetMapping("/reset")
    public Map<String, Object> reset() {
        service.reset();
        return ok("统计已重置");
    }
    
    @GetMapping("/data")
    public MonitorResult data() {
        return service.getResult();
    }
    
    @GetMapping("/config")
    public Map<String, Object> config() {
        return service.getConfigSnapshot();
    }
    
    @PostMapping("/chunk/upload")
    public Map<String, Object> uploadChunk(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "deviceId", required = false) String deviceId,
            @RequestParam(value = "collectedAt", required = false) String collectedAt
    ) {
        return service.ingestChunk(file, deviceId, collectedAt);
    }
    
    /**
     * 前端连接这个接口来接收推送
     * URL: http://localhost:8081/realtime/stream
     */
    @GetMapping("/stream")
    public SseEmitter stream() {
        return service.registerEmitter();
    }
    
    private Map<String, Object> ok(String msg) {
        Map<String, Object> res = new HashMap<>();
        res.put("code", 200);
        res.put("msg", msg);
        res.put("data", service.getResult());
        return res;
    }
    
}
