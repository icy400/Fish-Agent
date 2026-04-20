package com.fishfeed.utils;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import com.fishfeed.config.RealtimeConfigProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ClassPathResource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@Component
public class PythonChunkInferenceUtil {
    
    private static final Logger log = LoggerFactory.getLogger(PythonChunkInferenceUtil.class);
    
    @Autowired
    private RealtimeConfigProperties realtimeConfig;
    
    public JSONObject detectByFile(String audioPath) {
        try {
            String scriptPath = resolveScriptPath();
            
            ProcessBuilder pb = new ProcessBuilder(
                    realtimeConfig.getPythonCommand(),
                    scriptPath,
                    audioPath
            );
            pb.redirectErrorStream(true);
            
            Process process = pb.start();
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8)
            );
            
            String line;
            String jsonLine = null;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                if (trimmed.startsWith("{")) {
                    jsonLine = trimmed;
                }
            }
            int exitCode = process.waitFor();
            
            if (jsonLine == null || jsonLine.isEmpty()) {
                log.warn(
                        "python inference returned no JSON: command={} scriptPath={} audioPath={} exitCode={}",
                        realtimeConfig.getPythonCommand(),
                        scriptPath,
                        audioPath,
                        exitCode
                );
                return new JSONObject();
            }
            log.debug("python inference done: scriptPath={}, audioPath={}, exitCode={}", scriptPath, audioPath, exitCode);
            return JSON.parseObject(jsonLine);
            
        } catch (Exception e) {
            log.error("python inference failed: audioPath={}", audioPath, e);
            return new JSONObject();
        }
    }
    
    private String resolveScriptPath() throws Exception {
        Path configuredPath = Paths.get(realtimeConfig.getPythonScriptPath());
        if (!configuredPath.isAbsolute()) {
            configuredPath = Paths.get(System.getProperty("user.dir")).resolve(configuredPath).normalize();
        }
        if (Files.exists(configuredPath)) {
            return configuredPath.toString();
        }
        
        log.warn("configured python script path not found, fallback to classpath: {}", configuredPath);
        ClassPathResource resource = new ClassPathResource("python/audio_realtime_infer.py");
        return resource.getFile().getAbsolutePath();
    }
}
