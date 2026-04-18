package com.fishfeed.controller;

/**
 * @projectName:FishFeedSystem
 * @Author:oldt
 * @DateTime:2026/4/12 22:33
 * @Description:
 **/


import com.fishfeed.service.AudioService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;

@RestController
public class AudioController {
    
    @Autowired
    private AudioService audioService;
    
    // 上传文件
    @PostMapping("/upload-audio")
    public Map<String, Object> uploadAudio(@RequestParam("file") MultipartFile file) {
        return audioService.uploadAudio(file);
    }
    
    // 分析文件
    @PostMapping("/analyze-audio")
    public Map<String, Object> analyzeAudio(@RequestBody Map<String, String> params) {
        String filename = params.get("filename");
        return audioService.analyzeAudioByName(filename);
    }
}
