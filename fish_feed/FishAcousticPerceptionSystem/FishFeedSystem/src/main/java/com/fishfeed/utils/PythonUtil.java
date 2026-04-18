package com.fishfeed.utils;

/**
 * @projectName:FishFeedSystem
 * @Author:oldt
 * @DateTime:2026/4/12 22:34
 * @Description:调用Python脚本工具类
 **/

import java.io.BufferedReader;
import java.io.InputStreamReader;

public class PythonUtil {
    public static String runPythonScript(String scriptPath, String audioPath) {
        try {
            String[] cmd = new String[]{"python", scriptPath, audioPath};
            Process process = Runtime.getRuntime().exec(cmd);
            
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            process.waitFor();
            return sb.toString();
            
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }
}