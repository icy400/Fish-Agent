package com.fishfeed.utils;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import java.io.*;

@Component
public class PythonRealtimeUtil {
    
    private Process ffmpegProcess;
    private boolean isRecording = false;
    
    private final String outputFile = "continuous_audio.wav";
    private final String clipFile = "latest_6s.wav";
    
    public void startContinuousRecording() {
        if (isRecording) return;
        
        try {
            ffmpegProcess = new ProcessBuilder(
                    "ffmpeg", "-y",
                    "-hide_banner", "-loglevel", "panic",
                    "-f", "dshow",
                    "-i", "audio=麦克风阵列 (Realtek(R) Audio)",
                    "-ar", "22050",
                    "-ac", "1",
                    "-audio_buffer_size", "32",
                    "-avoid_negative_ts", "make_zero",
                    "-t", "3600",
                    outputFile
            ).start();
            
            isRecording = true;
            System.out.println("【持续监听已启动】麦克风已开启");
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
    
    public JSONObject detect() {
        if (!isRecording) {
            System.out.println("未启动监听");
            return new JSONObject();
        }
        
        try {
            File clipFileObj = new File(clipFile);
            String absoluteClipPath = clipFileObj.getAbsolutePath();
            File sourceFileObj = new File(outputFile);
            String absoluteSourcePath = sourceFileObj.getAbsolutePath();
            
            // 截取音频
            new ProcessBuilder(
                    "ffmpeg", "-y",
                    "-hide_banner", "-loglevel", "panic",
                    "-sseof", "-6",
                    "-i", absoluteSourcePath,
                    "-ar", "22050",
                    "-ac", "1",
                    absoluteClipPath
            ).start().waitFor();
            
            // 获取 Python 脚本路径
            ClassPathResource resource = new ClassPathResource("python/audio_realtime_infer.py");
            String scriptPath = resource.getFile().getAbsolutePath();
            
            System.out.println("正在调用 Python 脚本: " + scriptPath);
            
            ProcessBuilder pb = new ProcessBuilder(
                    "python", scriptPath, absoluteClipPath
            );
            pb.redirectErrorStream(true); // 合并错误流
            Process pythonProcess = pb.start();
            
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(pythonProcess.getInputStream(), "UTF-8")
            );
            
            StringBuilder sb = new StringBuilder();
            String line;
            
            // 【核心修改】只读取并保留 JSON 行
            while ((line = reader.readLine()) != null) {
                // 去除首尾空格
                String trimmedLine = line.trim();
                
                // 只保留以 "{" 开头的行（这是 JSON 的特征）
                if (trimmedLine.startsWith("{")) {
                    sb.setLength(0); // 清空之前可能存在的垃圾数据
                    sb.append(trimmedLine);
                }
            }
            
            pythonProcess.waitFor();
            
            String out = sb.toString();
            
            // 如果没有读到 JSON
            if (out.isEmpty()) {
                System.err.println("错误：Python 未返回有效 JSON");
                return new JSONObject();
            }
            
            // 打印最终结果
            System.out.println("Python 返回结果: " + out);
            
            return JSON.parseObject(out);
            
        } catch (Exception e) {
            e.printStackTrace();
            return new JSONObject();
        }
    }
    
    public void stopRecording() {
        if (!isRecording) return;
        
        try {
            if (ffmpegProcess != null) {
                ffmpegProcess.destroy();
            }
            isRecording = false;
            System.out.println("【持续监听已停止】麦克风已关闭");
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
}