package com.fishfeed.controller;

import com.fishfeed.entity.MonitorResult;
import com.fishfeed.service.RealtimeMonitorService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;

@RestController
@RequestMapping("/realtime")
public class RealtimeMonitorController {
    
    @Autowired
    private RealtimeMonitorService service;
    
    @GetMapping("/start")
    public void start() {
        service.start();
    }
    
    @GetMapping("/stop")
    public void stop() {
        service.stop();
    }
    
    @GetMapping("/reset")
    public void reset() {
        service.reset();
    }
    
    @GetMapping("/data")
    public MonitorResult data() {
        return service.getResult();  // 必须返回实时更新的对象
    }
    
    // 保存当前的 emitter，以便随时推送
    private SseEmitter currentEmitter;
    
    /**
     * 前端连接这个接口来接收推送
     * URL: http://localhost:8081/realtime/stream
     */
    @GetMapping("/stream")
    public SseEmitter stream() {
        // 设置超时时间，0表示永不过期
        SseEmitter emitter = new SseEmitter(0L);
        this.currentEmitter = emitter;
        
        // 监听连接关闭事件
        emitter.onCompletion(() -> System.out.println("SSE 连接关闭"));
        emitter.onTimeout(() -> System.out.println("SSE 连接超时"));
        emitter.onError(e -> System.out.println("SSE 连接错误"));
        
        return emitter;
    }
    
    /**
     * 在你的业务逻辑中（比如 Python 识别完成后），调用这个方法推送数据
     */
    public void pushData(Object data) {
        if (currentEmitter != null) {
            try {
                // 发送 JSON 数据
                currentEmitter.send(data);
            } catch (IOException e) {
                e.printStackTrace();
            }
        }
    }
    
}