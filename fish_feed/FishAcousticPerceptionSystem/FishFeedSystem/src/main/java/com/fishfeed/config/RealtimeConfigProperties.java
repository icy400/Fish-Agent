package com.fishfeed.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "fishfeed.realtime")
public class RealtimeConfigProperties {
    private String mode = "remote-upload";
    private String uploadDir = "realtime_chunk_upload";
    private boolean keepUploadedChunks = false;
    private String pythonCommand = "python";
    private String pythonScriptPath = "src/main/resources/python/audio_realtime_infer.py";

    private int chunkSeconds = 6;
    private int decisionWindowSize = 5;

    private double fishSegmentThreshold = 0.50;
    private double fishTypeThreshold = 0.34;
    private double startThreshold = 0.45;
    private double reduceThreshold = 0.25;
    private double stopThreshold = 0.15;

    private int startConsecutiveWindows = 2;
    private int stopConsecutiveWindows = 3;

    private double defaultConfidence = 0.50;
}
