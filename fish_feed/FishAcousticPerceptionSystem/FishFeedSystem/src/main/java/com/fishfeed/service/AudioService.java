package com.fishfeed.service;

/**
 * @projectName:FishFeedSystem
 * @Author:oldt
 * @DateTime:2026/4/12 22:33
 * @Description:
 **/


import org.springframework.web.multipart.MultipartFile;
import java.util.Map;

public interface AudioService {
    Map<String, Object> uploadAudio(MultipartFile file);
    Map<String, Object> analyzeAudioByName(String filename);
}
