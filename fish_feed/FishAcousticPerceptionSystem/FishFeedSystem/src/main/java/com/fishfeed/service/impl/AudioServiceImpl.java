package com.fishfeed.service.impl;

import com.fishfeed.service.AudioService;
import com.alibaba.fastjson.JSON;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

@Service
public class AudioServiceImpl implements AudioService {
    
    // 固定上传目录，绝对不会丢失
    private final String BASE_DIR = System.getProperty("user.dir") + "/audio_upload/";
    
    @Override
    public Map<String, Object> uploadAudio(MultipartFile file) {
        Map<String, Object> res = new HashMap<>();
        try {
            File dir = new File(BASE_DIR);
            if (!dir.exists()) dir.mkdirs();
            
            File dest = new File(dir, file.getOriginalFilename());
            file.transferTo(dest);
            
            res.put("code", 200);
            res.put("msg", "上传成功");
            return res;
        } catch (Exception e) {
            e.printStackTrace();
            res.put("code", 500);
            res.put("msg", "上传失败");
            return res;
        }
    }
    
    @Override
    public Map<String, Object> analyzeAudioByName(String filename) {
        try {
            String audioPath = BASE_DIR + filename;
            
            ProcessBuilder pb = new ProcessBuilder(
                    "python",
                    "src/main/resources/python/audio_infer.py",
                    audioPath
            );
            pb.redirectErrorStream(true); // 把错误流也合并到标准输出
            Process process = pb.start();
            
            // 读取 Python 输出
            String pythonOutput = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            process.waitFor();
            
            // ====================== 清理所有非 JSON 脏日志 ======================
            if (pythonOutput.contains("{")) {
                pythonOutput = pythonOutput.substring(pythonOutput.indexOf("{"));
            }
            
            
            System.out.println("清理后最终 JSON：" + pythonOutput);
            return JSON.parseObject(pythonOutput);
            
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }
}